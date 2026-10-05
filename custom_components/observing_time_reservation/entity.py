"""Shared base entity for the Observing Time Reservation platforms."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .coordinator import TelescopeCoordinator


class ObservingTimeReservationEntity(Entity):
    """Groups every entity for one telescope under a single HA device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TelescopeCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.name,
            manufacturer="DevControl2 / Bombol.Space",
            model="Observing time reservation",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
