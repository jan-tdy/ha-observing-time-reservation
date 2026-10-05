"""Calendar platform: one calendar entity per telescope, listing reservations."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
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
    async_add_entities([ReservationCalendar(coordinator)])


class ReservationCalendar(ObservingTimeReservationEntity, CalendarEntity):
    _attr_translation_key = "reservations"
    _attr_name = "Reservations"

    def __init__(self, coordinator: TelescopeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_reservations"

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        upcoming = self.coordinator.upcoming(limit=1)
        reservation = self.coordinator.current_holder(now) or (upcoming[0] if upcoming else None)
        if reservation is None:
            return None
        return CalendarEvent(
            start=reservation.start,
            end=reservation.end,
            summary=reservation.client_name,
            uid=reservation.id,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        events = []
        for reservation in self.coordinator.store.reservations:
            if reservation.cancelled:
                continue
            if reservation.end < start_date or reservation.start > end_date:
                continue
            events.append(
                CalendarEvent(
                    start=reservation.start,
                    end=reservation.end,
                    summary=reservation.client_name,
                    uid=reservation.id,
                )
            )
        return events
