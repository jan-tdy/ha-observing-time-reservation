"""Config and options flow for Observing Time Reservation.

Every field uses a native HA selector (voluptuous `selector.selector(...)`)
so the generated form renders with the exact same dropdowns/entity pickers
the built-in HA settings pages use - no bespoke UI widgets here.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    ALL_CAPABILITIES,
    BACKEND_INDI,
    BACKEND_MANUAL,
    BACKEND_SEESTAR,
    CONF_ADMIN_USER_IDS,
    CONF_BACKEND,
    CONF_CAPABILITY_MAP,
    CONF_CAPTURE_INTERVAL,
    CONF_IMAGE_BASE_PATH,
    CONF_MAX_DURATION,
    CONF_MIN_DURATION,
    CONF_SLOT_STEP,
    CONF_SOURCE_DEVICE_IDS,
    DEFAULT_CAPTURE_INTERVAL,
    DEFAULT_IMAGE_BASE_PATH,
    DEFAULT_MAX_DURATION,
    DEFAULT_MIN_DURATION,
    DEFAULT_SLOT_STEP,
    DOMAIN,
)

BACKEND_LABELS = {
    BACKEND_INDI: "INDI (ha-indi-client)",
    BACKEND_SEESTAR: "ZWO Seestar (ha-seestar)",
    BACKEND_MANUAL: "Manual entity mapping",
}

CAPABILITY_LABELS = {
    "set_goto_ra": "Goto target - Right Ascension field",
    "set_goto_dec": "Goto target - Declination field",
    "goto": "Goto / slew (execute)",
    "stop_goto": "Stop goto",
    "park": "Park",
    "unpark": "Unpark",
    "set_tracking": "Tracking on/off",
    "start_capture": "Start capture / stacking",
    "stop_capture": "Stop capture / stacking",
    "set_exposure": "Exposure length",
    "set_filter": "Filter wheel",
    "set_focus": "Focuser",
    "set_ccd_temperature": "CCD temperature",
    "live_camera_entity": "Live view camera",
    "preview_camera_entity": "Preview / capture camera (used for saved frames)",
    "status_sensor_entity": "Status / last message sensor",
}


class ObservingTimeReservationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One config entry = one telescope."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_device()

        schema = vol.Schema(
            {
                vol.Required("name"): selector.selector({"text": {}}),
                vol.Required(CONF_BACKEND, default=BACKEND_MANUAL): selector.selector(
                    {
                        "select": {
                            "options": [
                                {"value": key, "label": label}
                                for key, label in BACKEND_LABELS.items()
                            ],
                            "mode": "dropdown",
                        }
                    }
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_device(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data["name"], data=self._data)

        backend = self._data.get(CONF_BACKEND, BACKEND_MANUAL)
        integration_filter = {
            BACKEND_INDI: "indi_client",
            BACKEND_SEESTAR: None,  # ha-seestar publishes via MQTT discovery, no fixed domain
        }.get(backend)

        device_selector_config: dict[str, Any] = {"multiple": True}
        if integration_filter:
            device_selector_config["integration"] = integration_filter

        # A telescope is rarely a single HA device - INDI gives the mount,
        # CCD/camera, focuser and filter wheel each their own device. Pick
        # every one that belongs to this telescope; the capability-mapping
        # step below then only offers entities from these devices.
        schema = vol.Schema(
            {
                vol.Optional(CONF_SOURCE_DEVICE_IDS, default=[]): selector.selector(
                    {"device": device_selector_config}
                ),
            }
        )
        return self.async_show_form(step_id="device", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return ObservingTimeReservationOptionsFlow(config_entry)


class ObservingTimeReservationOptionsFlow(config_entries.OptionsFlow):
    """Reconfigurable afterwards: durations, image path, admins, capability map."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_capabilities()

        current = self._entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_DURATION, default=current.get(CONF_MIN_DURATION, DEFAULT_MIN_DURATION)
                ): selector.selector({"number": {"min": 5, "max": 1440, "unit_of_measurement": "min"}}),
                vol.Required(
                    CONF_MAX_DURATION, default=current.get(CONF_MAX_DURATION, DEFAULT_MAX_DURATION)
                ): selector.selector({"number": {"min": 5, "max": 1440, "unit_of_measurement": "min"}}),
                vol.Required(
                    CONF_SLOT_STEP, default=current.get(CONF_SLOT_STEP, DEFAULT_SLOT_STEP)
                ): selector.selector({"number": {"min": 1, "max": 120, "unit_of_measurement": "min"}}),
                vol.Required(
                    CONF_IMAGE_BASE_PATH,
                    default=current.get(CONF_IMAGE_BASE_PATH, DEFAULT_IMAGE_BASE_PATH),
                ): selector.selector({"text": {}}),
                vol.Required(
                    CONF_CAPTURE_INTERVAL,
                    default=current.get(CONF_CAPTURE_INTERVAL, DEFAULT_CAPTURE_INTERVAL),
                ): selector.selector({"number": {"min": 5, "max": 3600, "unit_of_measurement": "s"}}),
                vol.Optional(
                    CONF_ADMIN_USER_IDS, default=current.get(CONF_ADMIN_USER_IDS, [])
                ): selector.selector({"text": {"multiple": True}}),
                vol.Optional(
                    CONF_SOURCE_DEVICE_IDS,
                    default=current.get(
                        CONF_SOURCE_DEVICE_IDS, self._entry.data.get(CONF_SOURCE_DEVICE_IDS, [])
                    ),
                ): selector.selector({"device": {"multiple": True}}),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_capabilities(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            capability_map = {k: v for k, v in user_input.items() if v}
            self._options[CONF_CAPABILITY_MAP] = capability_map
            return self.async_create_entry(title="", data=self._options)

        current_map = self._entry.options.get(CONF_CAPABILITY_MAP, {})
        device_ids = self._options.get(
            CONF_SOURCE_DEVICE_IDS, self._entry.data.get(CONF_SOURCE_DEVICE_IDS, [])
        )
        entity_selector_config: dict[str, Any] = {}
        if device_ids:
            # Scope every entity picker to this telescope's own devices
            # (mount, CCD/camera, focuser, filter wheel, ...) instead of
            # listing every entity in the house.
            registry = er.async_get(self.hass)
            include_entities = [
                entity.entity_id
                for device_id in device_ids
                for entity in er.async_entries_for_device(
                    registry, device_id, include_disabled_entities=False
                )
            ]
            if include_entities:
                entity_selector_config["include_entities"] = include_entities

        fields = {}
        for capability in ALL_CAPABILITIES:
            # HA's entity selector rejects "" as a default, so only mapped
            # capabilities get a suggested_value - the rest stay unset.
            existing = current_map.get(capability)
            key = (
                vol.Optional(capability, description={"suggested_value": existing})
                if existing
                else vol.Optional(capability)
            )
            fields[key] = selector.selector({"entity": entity_selector_config})
        return self.async_show_form(
            step_id="capabilities",
            data_schema=vol.Schema(fields),
            description_placeholders={"labels": ", ".join(CAPABILITY_LABELS.values())},
        )
