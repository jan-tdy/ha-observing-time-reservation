from datetime import datetime, timedelta, timezone

import pytest

from reservation import (
    Reservation,
    ReservationError,
    Window,
    active_reservation,
    find_overlap,
    is_within_any_window,
    upcoming_reservations,
    usage_summary,
    validate_new_reservation,
)

TZ = timezone.utc


def dt(*args, **kwargs):
    return datetime(*args, tzinfo=TZ, **kwargs)


def make_window(start_hour, end_hour, day=10):
    return Window(start=dt(2026, 10, day, start_hour), end=dt(2026, 10, day, end_hour))


def test_is_within_any_window():
    windows = [make_window(20, 23)]
    assert is_within_any_window(windows, dt(2026, 10, 10, 20, 30), dt(2026, 10, 10, 21, 30))
    assert not is_within_any_window(windows, dt(2026, 10, 10, 19, 0), dt(2026, 10, 10, 21, 0))
    assert not is_within_any_window(windows, dt(2026, 10, 10, 22, 0), dt(2026, 10, 11, 1, 0))


def test_find_overlap():
    existing = Reservation(
        client_user_id="u1", client_name="Alice", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 21, 0)
    )
    assert find_overlap([existing], dt(2026, 10, 10, 20, 30), dt(2026, 10, 10, 21, 30)) is existing
    assert find_overlap([existing], dt(2026, 10, 10, 21, 0), dt(2026, 10, 10, 22, 0)) is None
    assert find_overlap([existing], dt(2026, 10, 10, 19, 0), dt(2026, 10, 10, 20, 0)) is None
    assert find_overlap([existing], dt(2026, 10, 10, 20, 0), dt(2026, 10, 10, 20, 30), ignore_id=existing.id) is None


def test_validate_new_reservation_happy_path():
    windows = [make_window(20, 23)]
    validate_new_reservation(
        windows=windows,
        reservations=[],
        start=dt(2026, 10, 10, 20, 0),
        end=dt(2026, 10, 10, 21, 0),
        min_duration=timedelta(minutes=30),
        max_duration=timedelta(minutes=240),
        slot_step=timedelta(minutes=15),
        now=dt(2026, 10, 9, 0, 0),
    )


@pytest.mark.parametrize(
    "start,end,message_part",
    [
        (dt(2026, 10, 10, 21, 0), dt(2026, 10, 10, 20, 0), "end must be after start"),
        (dt(2026, 10, 8, 0, 0), dt(2026, 10, 8, 1, 0), "in the past"),
        (dt(2026, 10, 10, 20, 0), dt(2026, 10, 10, 20, 10), "minimum"),
        (dt(2026, 10, 10, 20, 0), dt(2026, 10, 11, 1, 0), "maximum"),
        (dt(2026, 10, 10, 19, 0), dt(2026, 10, 10, 20, 0), "availability window"),
        (dt(2026, 10, 10, 20, 7), dt(2026, 10, 10, 21, 0), "slots"),
    ],
)
def test_validate_new_reservation_rejects(start, end, message_part):
    windows = [make_window(20, 23)]
    with pytest.raises(ReservationError, match=message_part):
        validate_new_reservation(
            windows=windows,
            reservations=[],
            start=start,
            end=end,
            min_duration=timedelta(minutes=30),
            max_duration=timedelta(minutes=240),
            slot_step=timedelta(minutes=15),
            now=dt(2026, 10, 9, 0, 0),
        )


def test_validate_new_reservation_rejects_overlap():
    windows = [make_window(20, 23)]
    existing = Reservation(
        client_user_id="u1", client_name="Alice", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 21, 0)
    )
    with pytest.raises(ReservationError, match="overlaps"):
        validate_new_reservation(
            windows=windows,
            reservations=[existing],
            start=dt(2026, 10, 10, 20, 30),
            end=dt(2026, 10, 10, 21, 30),
            min_duration=timedelta(minutes=30),
            max_duration=timedelta(minutes=240),
            slot_step=timedelta(minutes=15),
            now=dt(2026, 10, 9, 0, 0),
        )


def test_active_reservation():
    res = Reservation(
        client_user_id="u1", client_name="Alice", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 21, 0)
    )
    assert active_reservation([res], dt(2026, 10, 10, 20, 30)) is res
    assert active_reservation([res], dt(2026, 10, 10, 21, 30)) is None

    cancelled = Reservation(
        client_user_id="u2",
        client_name="Bob",
        start=dt(2026, 10, 10, 20, 0),
        end=dt(2026, 10, 10, 21, 0),
        cancelled=True,
    )
    assert active_reservation([cancelled], dt(2026, 10, 10, 20, 30)) is None


def test_upcoming_reservations_sorted_and_limited():
    now = dt(2026, 10, 9, 0, 0)
    r1 = Reservation(client_user_id="u1", client_name="A", start=dt(2026, 10, 11, 20, 0), end=dt(2026, 10, 11, 21, 0))
    r2 = Reservation(client_user_id="u2", client_name="B", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 21, 0))
    past = Reservation(client_user_id="u3", client_name="C", start=dt(2026, 10, 1, 20, 0), end=dt(2026, 10, 1, 21, 0))

    result = upcoming_reservations([r1, r2, past], now)
    assert result == [r2, r1]
    assert upcoming_reservations([r1, r2, past], now, limit=1) == [r2]


def test_usage_summary():
    r1 = Reservation(client_user_id="u1", client_name="Alice", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 21, 30))
    r2 = Reservation(client_user_id="u1", client_name="Alice", start=dt(2026, 10, 11, 20, 0), end=dt(2026, 10, 11, 20, 30))
    cancelled = Reservation(
        client_user_id="u2", client_name="Bob", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 22, 0), cancelled=True
    )

    summary = usage_summary([r1, r2, cancelled])
    assert summary == {
        "u1": {"client_name": "Alice", "total_minutes": 120, "sessions": 2},
    }


def test_reservation_to_from_dict_roundtrip():
    res = Reservation(
        client_user_id="u1", client_name="Alice", start=dt(2026, 10, 10, 20, 0), end=dt(2026, 10, 10, 21, 0)
    )
    restored = Reservation.from_dict(res.to_dict())
    assert restored == res
