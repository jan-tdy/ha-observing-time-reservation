"""Pure-Python reservation/availability logic.

No Home Assistant imports here on purpose (mirrors the indi/ protocol-core
pattern in ha-indi-client) so this module can be unit tested in isolation
and reused by both the integration and its test suite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4


class ReservationError(Exception):
    """Raised when a reservation request cannot be satisfied."""


@dataclass
class Window:
    """An admin-defined period during which a telescope can be booked."""

    start: datetime
    end: datetime

    def contains(self, start: datetime, end: datetime) -> bool:
        return self.start <= start and end <= self.end

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_dict(cls, data: dict) -> "Window":
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
        )


@dataclass
class Reservation:
    """A single confirmed booking."""

    client_user_id: str
    client_name: str
    start: datetime
    end: datetime
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=datetime.utcnow)
    recording: bool = False
    cancelled: bool = False

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end

    def is_active(self, now: datetime) -> bool:
        return not self.cancelled and self.start <= now < self.end

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "client_user_id": self.client_user_id,
            "client_name": self.client_name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "created_at": self.created_at.isoformat(),
            "recording": self.recording,
            "cancelled": self.cancelled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Reservation":
        return cls(
            id=data["id"],
            client_user_id=data["client_user_id"],
            client_name=data["client_name"],
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            recording=data.get("recording", False),
            cancelled=data.get("cancelled", False),
        )


def is_within_any_window(windows: list[Window], start: datetime, end: datetime) -> bool:
    """A reservation must fit entirely inside a single admin-opened window."""
    return any(window.contains(start, end) for window in windows)


def find_overlap(
    reservations: list[Reservation], start: datetime, end: datetime, ignore_id: str | None = None
) -> Reservation | None:
    for res in reservations:
        if res.cancelled or res.id == ignore_id:
            continue
        if res.overlaps(start, end):
            return res
    return None


def validate_new_reservation(
    *,
    windows: list[Window],
    reservations: list[Reservation],
    start: datetime,
    end: datetime,
    min_duration: timedelta,
    max_duration: timedelta,
    slot_step: timedelta,
    now: datetime,
) -> None:
    """Raise ReservationError if the requested slot cannot be booked."""
    if end <= start:
        raise ReservationError("end must be after start")
    if start < now:
        raise ReservationError("cannot reserve a slot in the past")

    duration = end - start
    if duration < min_duration:
        raise ReservationError(
            f"minimum reservation length is {int(min_duration.total_seconds() // 60)} minutes"
        )
    if duration > max_duration:
        raise ReservationError(
            f"maximum reservation length is {int(max_duration.total_seconds() // 60)} minutes"
        )

    if slot_step.total_seconds() > 0:
        offset = (start.hour * 60 + start.minute) % (slot_step.total_seconds() / 60)
        if offset != 0:
            raise ReservationError(
                f"start time must align to {int(slot_step.total_seconds() // 60)}-minute slots"
            )

    if not is_within_any_window(windows, start, end):
        raise ReservationError(
            "requested time is outside the availability window opened by the admin"
        )

    conflict = find_overlap(reservations, start, end)
    if conflict is not None:
        raise ReservationError("requested time overlaps an existing reservation")


def active_reservation(reservations: list[Reservation], now: datetime) -> Reservation | None:
    for res in reservations:
        if res.is_active(now):
            return res
    return None


def upcoming_reservations(
    reservations: list[Reservation], now: datetime, limit: int | None = None
) -> list[Reservation]:
    future = sorted(
        (r for r in reservations if not r.cancelled and r.end > now),
        key=lambda r: r.start,
    )
    return future[:limit] if limit else future


def usage_summary(reservations: list[Reservation]) -> dict[str, dict]:
    """Per-client totals, for the admin to invoice manually, outside this system."""
    summary: dict[str, dict] = {}
    for res in reservations:
        if res.cancelled:
            continue
        entry = summary.setdefault(
            res.client_user_id,
            {"client_name": res.client_name, "total_minutes": 0, "sessions": 0},
        )
        entry["total_minutes"] += int((res.end - res.start).total_seconds() // 60)
        entry["sessions"] += 1
    return summary
