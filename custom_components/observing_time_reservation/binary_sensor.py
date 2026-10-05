"""Binary sensor: is this telescope currently in use by a client's reservation."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import TelescopeCoordinator
from .entity import ObservingTimeReservationEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TelescopeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([InUseBinarySensor(coordinator)])


class InUseBinarySensor(ObservingTimeReservationEntity, BinarySensorEntity):
    _attr_translation_key = "in_use"
    _attr_name = "In use"
    _attr_device_class = "occupancy"

    def __init__(self, coordinator: TelescopeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_in_use"

    @property
    def is_on(self) -> bool:
        return self.coordinator.current_holder() is not None

    @property
    def extra_state_attributes(self) -> dict:
        holder = self.coordinator.current_holder()
        if holder is None:
            return {}
        return {
            "client_name": holder.client_name,
            "client_user_id": holder.client_user_id,
            "start": holder.start.isoformat(),
            "end": holder.end.isoformat(),
            "recording": holder.recording,
        }
