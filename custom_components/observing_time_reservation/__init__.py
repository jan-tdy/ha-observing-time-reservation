"""The Observing Time Reservation integration."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CAPABILITY,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ENABLED,
    ATTR_END,
    ATTR_RESERVATION_ID,
    ATTR_START,
    ATTR_VALUE,
    ATTR_WINDOWS,
    DOMAIN,
    SERVICE_CANCEL,
    SERVICE_RESERVE,
    SERVICE_SAVE_FRAME,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_AVAILABILITY,
    SERVICE_SET_RECORDING,
)
from .coordinator import TelescopeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["calendar", "binary_sensor", "sensor"]

CARD_URL_PATH = f"/{DOMAIN}/observing-time-reservation-card.js"
CARD_DIR = Path(__file__).parent / "frontend"


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
    """Register the frontend card and the domain-wide services once."""
    hass.data.setdefault(DOMAIN, {})

    if CARD_DIR.exists():
        card_path = str(CARD_DIR / "observing-time-reservation-card.js")
        if hasattr(hass.http, "async_register_static_paths"):
            # HA >= 2024.7
            from homeassistant.components.http import StaticPathConfig

            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL_PATH, card_path, cache_headers=False)]
            )
        else:
            hass.http.register_static_path(CARD_URL_PATH, card_path, cache_headers=False)

        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, CARD_URL_PATH)

    async def _handle_reserve(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        user_id = call.context.user_id
        await coordinator.async_reserve(
            user_id=user_id,
            user_name=_user_name(hass, user_id),
            start=call.data[ATTR_START],
            end=call.data[ATTR_END],
        )

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
