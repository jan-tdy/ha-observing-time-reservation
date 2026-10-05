"""The Observing Time Reservation integration."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CAPABILITY,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ENABLED,
    ATTR_END,
    ATTR_RESERVATION_ID,
    ATTR_START,
    ATTR_STEPS,
    ATTR_VALUE,
    ATTR_WINDOWS,
    DOMAIN,
    SERVICE_CANCEL,
    SERVICE_CANCEL_SEQUENCE,
    SERVICE_PAUSE_SEQUENCE,
    SERVICE_RESERVE,
    SERVICE_RESUME_SEQUENCE,
    SERVICE_SAVE_FRAME,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_AVAILABILITY,
    SERVICE_SET_RECORDING,
    SERVICE_START_SEQUENCE,
)
from .coordinator import TelescopeCoordinator
from .reservation import ReservationError
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["calendar", "binary_sensor", "sensor"]

# Everything is configured through config entries (the config_flow) - there is
# no YAML configuration for this integration.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILENAME = "observing-time-reservation-card.js"
PANEL_FILENAME = "observing-time-reservation-panel.js"
CATALOG_FILENAME = "catalog.json"
PANEL_WEBCOMPONENT_NAME = "observing-time-reservation-panel"
PANEL_URL_PATH = "observing-time-reservation"

CARD_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"
PANEL_JS_URL_PATH = f"/{DOMAIN}/{PANEL_FILENAME}"
CATALOG_URL_PATH = f"/{DOMAIN}/{CATALOG_FILENAME}"
FRONTEND_DIR = Path(__file__).parent / "frontend"


def _coordinator_for(hass: HomeAssistant, config_entry_id: str) -> TelescopeCoordinator:
    coordinator = hass.data.get(DOMAIN, {}).get(config_entry_id)
    if coordinator is None:
        raise HomeAssistantError(f"unknown observing_time_reservation config entry {config_entry_id}")
    return coordinator


def _user_name(hass: HomeAssistant, user_id: str | None) -> str:
    if user_id is None:
        return "system"
    user = hass.auth.async_get_user(user_id)
    return user.name if user and user.name else (user_id if user else "unknown")


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register the frontend assets, the panel, the websocket API and the
    domain-wide services once."""
    hass.data.setdefault(DOMAIN, {})

    if FRONTEND_DIR.exists():
        card_path = str(FRONTEND_DIR / CARD_FILENAME)
        panel_path = str(FRONTEND_DIR / PANEL_FILENAME)
        catalog_path = str(FRONTEND_DIR / CATALOG_FILENAME)
        static_configs = [
            (CARD_URL_PATH, card_path),
            (PANEL_JS_URL_PATH, panel_path),
            (CATALOG_URL_PATH, catalog_path),
        ]
        if hasattr(hass.http, "async_register_static_paths"):
            # HA >= 2024.7
            from homeassistant.components.http import StaticPathConfig

            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(url_path, path, cache_headers=False)
                    for url_path, path in static_configs
                ]
            )
        else:
            for url_path, path in static_configs:
                hass.http.register_static_path(url_path, path, cache_headers=False)

        from homeassistant.components.frontend import add_extra_js_url

        # The small Lovelace card: still useful for a compact dashboard tile.
        add_extra_js_url(hass, CARD_URL_PATH)

        # The full-page sidebar panel: the primary, CCDciel-style interface,
        # covering every telescope (it discovers them itself over websocket,
        # see websocket_api.py) rather than needing one card per telescope.
        from homeassistant.components import frontend, panel_custom

        if not frontend.async_panel_exists(hass, PANEL_URL_PATH):
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=PANEL_URL_PATH,
                webcomponent_name=PANEL_WEBCOMPONENT_NAME,
                sidebar_title="Observing Time",
                sidebar_icon="mdi:telescope",
                module_url=PANEL_JS_URL_PATH,
                embed_iframe=False,
                require_admin=False,
            )

    async_setup_websocket_api(hass)

    async def _handle_reserve(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        user_id = call.context.user_id
        # cv.datetime leaves a naive datetime when the caller sends one with no
        # offset (e.g. the Developer Tools datetime selector); as_utc treats
        # that as local time and makes it comparable with our aware internals.
        start = dt_util.as_utc(call.data[ATTR_START])
        end = dt_util.as_utc(call.data[ATTR_END])
        try:
            await coordinator.async_reserve(
                user_id=user_id,
                user_name=_user_name(hass, user_id),
                start=start,
                end=end,
            )
        except ReservationError as err:
            raise HomeAssistantError(str(err)) from err

    async def _handle_cancel(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_cancel(
            reservation_id=call.data[ATTR_RESERVATION_ID], user_id=call.context.user_id
        )

    async def _handle_set_availability(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_set_availability(
            user_id=call.context.user_id, windows=call.data[ATTR_WINDOWS]
        )

    async def _handle_send_command(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_send_command(
            user_id=call.context.user_id,
            capability=call.data[ATTR_CAPABILITY],
            value=call.data.get(ATTR_VALUE),
        )

    async def _handle_set_recording(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_set_recording(
            user_id=call.context.user_id, enabled=call.data[ATTR_ENABLED]
        )

    async def _handle_save_frame(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_save_frame(user_id=call.context.user_id)

    async def _handle_start_sequence(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_start_sequence(
            user_id=call.context.user_id, steps=call.data[ATTR_STEPS]
        )

    async def _handle_pause_sequence(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_pause_sequence(user_id=call.context.user_id)

    async def _handle_resume_sequence(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_resume_sequence(user_id=call.context.user_id)

    async def _handle_cancel_sequence(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_cancel_sequence(user_id=call.context.user_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESERVE,
        _handle_reserve,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): str,
                vol.Required(ATTR_START): cv.datetime,
                vol.Required(ATTR_END): cv.datetime,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL,
        _handle_cancel,
        schema=vol.Schema(
            {vol.Required(ATTR_CONFIG_ENTRY_ID): str, vol.Required(ATTR_RESERVATION_ID): str}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AVAILABILITY,
        _handle_set_availability,
        schema=vol.Schema(
            {vol.Required(ATTR_CONFIG_ENTRY_ID): str, vol.Required(ATTR_WINDOWS): list}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        _handle_send_command,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): str,
                vol.Required(ATTR_CAPABILITY): str,
                vol.Optional(ATTR_VALUE): object,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_RECORDING,
        _handle_set_recording,
        schema=vol.Schema(
            {vol.Required(ATTR_CONFIG_ENTRY_ID): str, vol.Required(ATTR_ENABLED): bool}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_FRAME,
        _handle_save_frame,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_SEQUENCE,
        _handle_start_sequence,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): str, vol.Required(ATTR_STEPS): list}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE_SEQUENCE,
        _handle_pause_sequence,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_SEQUENCE,
        _handle_resume_sequence,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_SEQUENCE,
        _handle_cancel_sequence,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): str}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TelescopeCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TelescopeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_unload()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
