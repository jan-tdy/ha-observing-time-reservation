"""Sensors: next availability window and admin usage/billing summary."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import TelescopeCoordinator
from .entity import ObservingTimeReservationEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TelescopeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [AvailabilitySensor(coordinator), UsageSensor(coordinator), SequenceSensor(coordinator)]
    )


class AvailabilitySensor(ObservingTimeReservationEntity, SensorEntity):
    _attr_translation_key = "availability"
    _attr_name = "Next availability window"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: TelescopeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_availability"

    @property
    def native_value(self):
        now = dt_util.utcnow()
        future_windows = [w for w in self.coordinator.store.windows if w.end > now]
        if not future_windows:
            return None
        return min(future_windows, key=lambda w: w.start).start

    @property
    def extra_state_attributes(self) -> dict:
        return {"windows": [w.to_dict() for w in self.coordinator.store.windows]}


class UsageSensor(ObservingTimeReservationEntity, SensorEntity):
    """For the admin: who booked how much, so it can be invoiced manually elsewhere."""

    _attr_translation_key = "usage"
    _attr_name = "Usage"
    _attr_native_unit_of_measurement = "min"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: TelescopeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_usage"

    @property
    def native_value(self) -> int:
        return sum(entry["total_minutes"] for entry in self.coordinator.usage().values())

    @property
    def extra_state_attributes(self) -> dict:
        return {"per_client": self.coordinator.usage()}


class SequenceSensor(ObservingTimeReservationEntity, SensorEntity):
    """Live progress of the current/last multi-exposure sequence, if any
    (see sequence.py) - idle/running/paused/done/cancelled, with per-step
    filter/exposure/count/done_count so the panel can render real progress."""

    _attr_translation_key = "sequence"
    _attr_name = "Sequence"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: TelescopeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_sequence"

    @property
    def native_value(self) -> str:
        snapshot = self.coordinator.sequence_snapshot()
        return snapshot["state"] if snapshot else "idle"

    @property
    def extra_state_attributes(self) -> dict:
        snapshot = self.coordinator.sequence_snapshot()
        return {"steps": snapshot["steps"], "current_step": snapshot["current_step"]} if snapshot else {}
