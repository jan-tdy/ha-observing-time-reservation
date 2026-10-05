"""Websocket API: lets the panel discover every telescope's entities by
itself, instead of making the admin type entity ids into a card config.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, REF_LIVE_CAMERA, REF_PREVIEW_CAMERA, REF_STATUS_SENSOR
from .coordinator import TelescopeCoordinator


def async_setup_websocket_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_list_telescopes)


def _telescope_info(registry: er.EntityRegistry, coordinator: TelescopeCoordinator) -> dict[str, Any]:
    entry_id = coordinator.entry.entry_id

    def _entity_id(entity_domain: str, suffix: str) -> str | None:
        return registry.async_get_entity_id(entity_domain, DOMAIN, f"{entry_id}_{suffix}")

    return {
        "entry_id": entry_id,
        "name": coordinator.name,
        "in_use_entity": _entity_id("binary_sensor", "in_use"),
        "availability_entity": _entity_id("sensor", "availability"),
        "usage_entity": _entity_id("sensor", "usage"),
        "sequence_entity": _entity_id("sensor", "sequence"),
        "calendar_entity": _entity_id("calendar", "reservations"),
        "live_camera_entity": coordinator.reference_entity(REF_LIVE_CAMERA),
        "preview_camera_entity": coordinator.reference_entity(REF_PREVIEW_CAMERA),
        "status_sensor_entity": coordinator.reference_entity(REF_STATUS_SENSOR),
        # Every mapped action capability -> its target entity_id. Exposed so
        # the UI can inspect the *actual* target entity at click time
        # (domain, current .attributes.options, unit_of_measurement, ...)
        # instead of guessing option labels or units that differ by backend
        # (e.g. ha-indi-client's Park is a `select` with driver-defined
        # option text; ha-seestar's is a `button` with none at all), and so
        # it can hide controls for capabilities nobody mapped.
        "capability_map": dict(coordinator.capability_map),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_telescopes"})
@websocket_api.async_response
async def websocket_list_telescopes(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return every telescope (config entry) with its entities, pre-resolved."""
    registry = er.async_get(hass)
    coordinators: dict[str, TelescopeCoordinator] = hass.data.get(DOMAIN, {})
    telescopes = [_telescope_info(registry, coordinator) for coordinator in coordinators.values()]
    connection.send_result(
        msg["id"],
        {
            "telescopes": telescopes,
            "is_admin": connection.user.is_admin,
            "user_id": connection.user.id,
        },
    )
