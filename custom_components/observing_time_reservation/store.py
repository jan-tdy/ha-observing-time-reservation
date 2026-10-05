"""Persistence for one telescope's availability windows and reservations."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .reservation import Reservation, Window


class ReservationStore:
    """Thin wrapper around a HA Store holding one telescope's state."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}")
        self.windows: list[Window] = []
        self.reservations: list[Reservation] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        self.windows = [Window.from_dict(w) for w in data.get("windows", [])]
        self.reservations = [Reservation.from_dict(r) for r in data.get("reservations", [])]

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "windows": [w.to_dict() for w in self.windows],
                "reservations": [r.to_dict() for r in self.reservations],
            }
        )
