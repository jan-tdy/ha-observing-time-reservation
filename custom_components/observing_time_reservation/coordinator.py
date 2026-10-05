"""Runtime coordinator for a single telescope config entry.

Owns the persisted availability windows and reservations, enforces access
control (only the client who currently holds the slot - or an admin - may
send commands), dispatches abstract "capabilities" (goto, park, start
capture, ...) onto the concrete entities the admin mapped in the options
flow, and runs the periodic frame-saving loop while a session is recording.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADMIN_USER_IDS,
    CONF_CAPABILITY_MAP,
    CONF_CAPTURE_INTERVAL,
    CONF_IMAGE_BASE_PATH,
    CONF_MAX_DURATION,
    CONF_MIN_DURATION,
    CONF_SLOT_STEP,
    DEFAULT_CAPTURE_INTERVAL,
    DEFAULT_IMAGE_BASE_PATH,
    DEFAULT_MAX_DURATION,
    DEFAULT_MIN_DURATION,
    DEFAULT_SLOT_STEP,
    REF_PREVIEW_CAMERA,
)
from .reservation import (
    Reservation,
    ReservationError,
    Window,
    active_reservation,
    find_overlap,
    upcoming_reservations,
    usage_summary,
    validate_new_reservation,
)
from .store import ReservationStore

_LOGGER = logging.getLogger(__name__)


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _infer_service_call(domain: str, entity_id: str, value) -> tuple[str, dict]:
    """Map a bare entity + optional value onto the right domain service call."""
    data: dict = {"entity_id": entity_id}
    if domain == "button":
        return "press", data
    if domain == "number":
        data["value"] = value
        return "set_value", data
    if domain == "select":
        data["option"] = value
        return "select_option", data
    if domain == "text":
        data["value"] = value
        return "set_value", data
    if domain == "switch":
        return ("turn_on" if value else "turn_off"), data
    if domain == "climate" and value is not None:
        data["temperature"] = value
        return "set_temperature", data
    raise HomeAssistantError(f"entity domain '{domain}' is not supported as a capability target")


class TelescopeCoordinator:
    """One instance per config entry (= one telescope)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = ReservationStore(hass, entry.entry_id)
        self._listeners: list[callback] = []
        self._unsub_timer = None
        self._last_capture: dict[str, datetime] = {}

    @property
    def name(self) -> str:
        return self.entry.title

    @property
    def slug(self) -> str:
        return _slug(self.entry.title)

    # -- setup / teardown -------------------------------------------------

    async def async_setup(self) -> None:
        await self.store.async_load()
        self._unsub_timer = async_track_time_interval(
            self.hass, self._async_tick, timedelta(seconds=15)
        )

    async def async_unload(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    def async_add_listener(self, update_callback: callback) -> callback:
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    def _notify(self) -> None:
        for update_callback in self._listeners:
            update_callback()

    # -- config helpers -----------------------------------------------------

    def _opt(self, key: str, default):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def min_duration(self) -> timedelta:
        return timedelta(minutes=self._opt(CONF_MIN_DURATION, DEFAULT_MIN_DURATION))

    @property
    def max_duration(self) -> timedelta:
        return timedelta(minutes=self._opt(CONF_MAX_DURATION, DEFAULT_MAX_DURATION))

    @property
    def slot_step(self) -> timedelta:
        return timedelta(minutes=self._opt(CONF_SLOT_STEP, DEFAULT_SLOT_STEP))

    @property
    def image_base_path(self) -> str:
        return self._opt(CONF_IMAGE_BASE_PATH, DEFAULT_IMAGE_BASE_PATH)

    @property
    def capture_interval(self) -> timedelta:
        return timedelta(seconds=self._opt(CONF_CAPTURE_INTERVAL, DEFAULT_CAPTURE_INTERVAL))

    @property
    def admin_user_ids(self) -> set[str]:
        return set(self.entry.options.get(CONF_ADMIN_USER_IDS, []))

    @property
    def capability_map(self) -> dict:
        return self.entry.options.get(CONF_CAPABILITY_MAP, {})

    def _is_admin(self, user_id: str | None) -> bool:
        if user_id is None:
            return True  # internal/automation call
        if user_id in self.admin_user_ids:
            return True
        user = self.hass.auth.async_get_user(user_id) if hasattr(self.hass, "auth") else None
        return bool(user and user.is_admin)

    # -- reservations ---------------------------------------------------------

    def current_holder(self, now: datetime | None = None) -> Reservation | None:
        now = now or dt_util.utcnow()
        return active_reservation(self.store.reservations, now)

    def upcoming(self, limit: int | None = None) -> list[Reservation]:
        return upcoming_reservations(self.store.reservations, dt_util.utcnow(), limit)

    def usage(self) -> dict:
        return usage_summary(self.store.reservations)

    async def async_reserve(
        self, *, user_id: str, user_name: str, start: datetime, end: datetime
    ) -> Reservation:
        now = dt_util.utcnow()
        validate_new_reservation(
            windows=self.store.windows,
            reservations=self.store.reservations,
            start=start,
            end=end,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            slot_step=self.slot_step,
            now=now,
        )
        reservation = Reservation(client_user_id=user_id, client_name=user_name, start=start, end=end)
        self.store.reservations.append(reservation)
        await self.store.async_save()
        self._notify()
        return reservation

    async def async_cancel(self, *, reservation_id: str, user_id: str | None) -> None:
        for res in self.store.reservations:
            if res.id == reservation_id:
                if res.client_user_id != user_id and not self._is_admin(user_id):
                    raise HomeAssistantError("only the owning client or an admin can cancel this reservation")
                res.cancelled = True
                await self.store.async_save()
                self._notify()
                return
        raise HomeAssistantError(f"unknown reservation_id {reservation_id}")

    async def async_set_availability(self, *, user_id: str | None, windows: list[dict]) -> None:
        if not self._is_admin(user_id):
            raise HomeAssistantError("only an admin can set the availability window")
        parsed = [Window(start=dt_util.parse_datetime(w["start"]), end=dt_util.parse_datetime(w["end"])) for w in windows]
        for window in parsed:
            if window.start is None or window.end is None or window.end <= window.start:
                raise HomeAssistantError(f"invalid window: {window}")
        self.store.windows = parsed
        await self.store.async_save()
        self._notify()

    # -- access control ---------------------------------------------------

    def _assert_holds_slot(self, user_id: str | None) -> Reservation:
        if self._is_admin(user_id):
            holder = self.current_holder()
            if holder is None:
                raise HomeAssistantError("no active reservation on this telescope right now")
            return holder
        holder = self.current_holder()
        if holder is None or holder.client_user_id != user_id:
            raise HomeAssistantError(
                "you do not currently hold a reservation for this telescope - control is locked"
            )
        return holder

    # -- capability dispatch -----------------------------------------------

    async def async_send_command(
        self, *, user_id: str | None, capability: str, value=None
    ) -> None:
        """Dispatch an abstract capability onto the entity the admin mapped to it.

        The admin only ever picks a target *entity* (a native entity selector,
        same widget HA itself uses) - the domain.service call is inferred from
        that entity's domain, so there is nothing for the admin to get wrong.
        """
        self._assert_holds_slot(user_id)
        entity_id = self.capability_map.get(capability)
        if not entity_id:
            raise HomeAssistantError(f"capability '{capability}' is not configured for this telescope")

        domain = entity_id.split(".", 1)[0]
        service, data = _infer_service_call(domain, entity_id, value)
        await self.hass.services.async_call(domain, service, data, blocking=True)

    def reference_entity(self, key: str) -> str | None:
        return self.capability_map.get(key)

    # -- recording / frame capture ------------------------------------------

    async def async_set_recording(self, *, user_id: str | None, enabled: bool) -> None:
        holder = self._assert_holds_slot(user_id)
        holder.recording = enabled
        await self.store.async_save()
        self._notify()

    async def async_save_frame(self, *, user_id: str | None) -> str:
        holder = self._assert_holds_slot(user_id)
        return await self._async_capture_frame(holder)

    async def _async_capture_frame(self, reservation: Reservation) -> str:
        camera_entity = self.reference_entity(REF_PREVIEW_CAMERA)
        if not camera_entity:
            raise HomeAssistantError("no preview/capture camera configured for this telescope")

        session_dir = os.path.join(
            self.image_base_path,
            self.slug,
            _slug(reservation.client_name or reservation.client_user_id),
            reservation.start.strftime("%Y%m%dT%H%M%S"),
        )
        await self.hass.async_add_executor_job(os.makedirs, session_dir, True)
        filename = os.path.join(session_dir, f"frame_{dt_util.utcnow().strftime('%Y%m%dT%H%M%S')}.jpg")
        await self.hass.services.async_call(
            "camera",
            "snapshot",
            {"entity_id": camera_entity, "filename": filename},
            blocking=True,
        )
        return filename

    @callback
    def _async_tick(self, now: datetime) -> None:
        self.hass.async_create_task(self._async_tick_async(now))

    async def _async_tick_async(self, now: datetime) -> None:
        holder = self.current_holder(now)
        if holder is not None and holder.recording:
            last = self._last_capture.get(holder.id)
            if last is None or now - last >= self.capture_interval:
                try:
                    await self._async_capture_frame(holder)
                    self._last_capture[holder.id] = now
                except HomeAssistantError as err:
                    _LOGGER.warning("Frame capture failed for %s: %s", self.name, err)
        else:
            self._last_capture.clear()
        self._notify()
