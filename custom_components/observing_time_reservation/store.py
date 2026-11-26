"""Persistence for one telescope's availability windows and reservations."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .reservation import Reservation, Window

_LOGGER = logging.getLogger(__name__)


def _load_records(values: object, record_type: type, label: str) -> list:
    if not isinstance(values, list):
        _LOGGER.warning("Ignoring invalid stored %s collection", label)
        return []

    records = []
    for index, value in enumerate(values):
        try:
            if not isinstance(value, dict):
                raise TypeError("record must be an object")
            record = record_type.from_dict(value)
            if record.end <= record.start:
                raise ValueError("record end must be after its start")
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Skipping invalid stored %s record at index %d: %s", label, index, err)
            continue
        records.append(record)
    return records


class ReservationStore:
    """Thin wrapper around a HA Store holding one telescope's state."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}")
        self.windows: list[Window] = []
        self.reservations: list[Reservation] = []
        # {"reservation_id": ..., "sequence": Sequence.to_dict()} for the
        # exposure sequence belonging to the reservation it was started
        # under (if any) - survives a HA restart so progress isn't lost,
        # though the coordinator never auto-resumes capturing on its own.
        self.sequence_data: dict | None = None

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        if not isinstance(data, dict):
            _LOGGER.warning("Ignoring invalid reservation storage data")
            return
        self.windows = _load_records(data.get("windows", []), Window, "window")
        self.reservations = _load_records(data.get("reservations", []), Reservation, "reservation")
        self.sequence_data = data.get("sequence_data")

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "windows": [w.to_dict() for w in self.windows],
                "reservations": [r.to_dict() for r in self.reservations],
                "sequence_data": self.sequence_data,
            }
        )
