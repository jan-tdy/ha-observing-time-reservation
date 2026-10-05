"""Runtime coordinator for a single telescope config entry.

Owns the persisted availability windows and reservations, enforces access
control (only the client who currently holds the slot - or an admin - may
send commands), dispatches abstract "capabilities" (goto, park, start
capture, ...) onto the concrete entities the admin mapped in the options
flow, and runs the periodic frame-saving loop while a session is recording.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CAP_AUTO_FOCUS,
    CAP_CONTROLS_ENABLED,
    CAP_SET_CCD_TEMPERATURE,
    CAP_SET_EXPOSURE,
    CAP_SET_FILTER,
    CAP_START_CAPTURE,
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
from .sequence import STATE_CANCELLED, STATE_DONE, STATE_PAUSED, STATE_RUNNING, Sequence, SequenceError
from .store import ReservationStore

_LOGGER = logging.getLogger(__name__)

# How long to wait after triggering a sub-exposure before considering it
# done: the configured exposure length plus a fixed readout/download
# margin. No backend here exposes a generic, reliable "capture finished"
# signal to poll instead (CCDciel itself polls its own capture controller's
# `Running` flag, which is backend-internal state this integration's
# generic entity-mapping model has no equivalent of), so progress advances
# by elapsed time rather than by an event.
SEQUENCE_READOUT_BUFFER = timedelta(seconds=5)
# Approximate settle time after triggering an autofocus run before resuming
# capture - likewise a fixed guess, since there is no generic "autofocus
# finished" signal to wait on either.
SEQUENCE_AUTOFOCUS_SETTLE = timedelta(seconds=20)


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
        self._armed_reservation_id: str | None = None
        self._sequence: Sequence | None = None
        self._sequence_reservation_id: str | None = None
        self._sequence_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return self.entry.title

    @property
    def slug(self) -> str:
        return _slug(self.entry.title)

    # -- setup / teardown -------------------------------------------------

    async def async_setup(self) -> None:
        await self.store.async_load()
        if self.store.sequence_data:
            try:
                self._sequence = Sequence.from_dict(self.store.sequence_data["sequence"])
                self._sequence_reservation_id = self.store.sequence_data.get("reservation_id")
            except (KeyError, SequenceError) as err:
                _LOGGER.warning("Discarding unreadable stored sequence for %s: %s", self.name, err)
                self._sequence = None
                self._sequence_reservation_id = None
            else:
                if self._sequence.state == STATE_RUNNING:
                    # Never resume issuing capture commands on our own after
                    # a restart - land in a safe, explicit-resume-required
                    # state instead.
                    self._sequence.state = STATE_PAUSED
        self._unsub_timer = async_track_time_interval(
            self.hass, self._async_tick, timedelta(seconds=15)
        )

    async def async_unload(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._sequence_task is not None:
            self._sequence_task.cancel()
            self._sequence_task = None

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

    async def _is_admin(self, user_id: str | None) -> bool:
        if user_id is None:
            return True  # internal/automation call
        if user_id in self.admin_user_ids:
            return True
        if not hasattr(self.hass, "auth"):
            return False
        user = await self.hass.auth.async_get_user(user_id)
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
                if res.client_user_id != user_id and not await self._is_admin(user_id):
                    raise HomeAssistantError("only the owning client or an admin can cancel this reservation")
                res.cancelled = True
                await self.store.async_save()
                self._notify()
                return
        raise HomeAssistantError(f"unknown reservation_id {reservation_id}")

    async def async_set_availability(self, *, user_id: str | None, windows: list[dict]) -> None:
        if not await self._is_admin(user_id):
            raise HomeAssistantError("only an admin can set the availability window")
        parsed = [Window(start=dt_util.parse_datetime(w["start"]), end=dt_util.parse_datetime(w["end"])) for w in windows]
        for window in parsed:
            if window.start is None or window.end is None or window.end <= window.start:
                raise HomeAssistantError(f"invalid window: {window}")
        self.store.windows = parsed
        await self.store.async_save()
        self._notify()

    # -- access control ---------------------------------------------------

    async def _assert_holds_slot(self, user_id: str | None) -> Reservation:
        if await self._is_admin(user_id):
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

    def _has_capability(self, capability: str) -> bool:
        return bool(self.capability_map.get(capability))

    async def _async_dispatch_capability(self, capability: str, value=None) -> None:
        """Fire-and-forget version of async_send_command for internal
        callers (the sequence engine) that already know a capability may
        legitimately be unmapped - silently skips rather than raising."""
        entity_id = self.capability_map.get(capability)
        if not entity_id:
            return
        domain = entity_id.split(".", 1)[0]
        service, data = _infer_service_call(domain, entity_id, value)
        await self.hass.services.async_call(domain, service, data, blocking=True)

    async def async_send_command(
        self, *, user_id: str | None, capability: str, value=None
    ) -> None:
        """Dispatch an abstract capability onto the entity the admin mapped to it.

        The admin only ever picks a target *entity* (a native entity selector,
        same widget HA itself uses) - the domain.service call is inferred from
        that entity's domain, so there is nothing for the admin to get wrong.
        """
        await self._assert_holds_slot(user_id)
        if not self._has_capability(capability):
            raise HomeAssistantError(f"capability '{capability}' is not configured for this telescope")
        await self._async_dispatch_capability(capability, value)

    def reference_entity(self, key: str) -> str | None:
        return self.capability_map.get(key)

    # -- exposure sequences ---------------------------------------------------
    #
    # An ordered plan of capture steps (filter/exposure/count/CCD temp,
    # optional autofocus every N subs), modeled on CCDciel's own plan/step
    # engine (cu_plan.pas) but narrowed to what the generic capability map
    # above already supports - no dithering/guiding, frame type or scripts.
    # Progress advances by elapsed time (exposure + a fixed readout
    # margin), since no backend here exposes a generic "capture finished"
    # signal to poll instead.

    def sequence_snapshot(self) -> dict | None:
        if self._sequence is None:
            return None
        return self._sequence.to_dict()

    def _exposure_wait_seconds(self, step_exposure: float) -> float:
        """A sequence step's exposure is in whatever unit the mapped
        set_exposure entity itself uses - seconds for a typical INDI
        CCD_EXPOSURE, milliseconds for ha-seestar's stacking exposure (see
        the "exposure units differ by backend" note in the README). Timing
        the wait needs real seconds regardless of what unit was actually
        sent to the camera."""
        entity_id = self.capability_map.get(CAP_SET_EXPOSURE)
        state = self.hass.states.get(entity_id) if entity_id else None
        unit = ((state.attributes.get("unit_of_measurement") if state else None) or "").strip().lower()
        if unit in ("ms", "millisecond", "milliseconds"):
            return step_exposure / 1000
        return step_exposure

    async def _async_save_sequence(self) -> None:
        if self._sequence is None:
            self.store.sequence_data = None
        else:
            self.store.sequence_data = {
                "reservation_id": self._sequence_reservation_id,
                "sequence": self._sequence.to_dict(),
            }
        await self.store.async_save()

    async def async_start_sequence(self, *, user_id: str | None, steps: list[dict]) -> None:
        holder = await self._assert_holds_slot(user_id)
        if self._sequence_task is not None and not self._sequence_task.done():
            raise HomeAssistantError("a sequence is already running on this telescope")
        if not self._has_capability(CAP_SET_EXPOSURE):
            raise HomeAssistantError("set_exposure capability is not configured for this telescope")
        try:
            sequence = Sequence.from_steps(steps)
        except SequenceError as err:
            raise HomeAssistantError(str(err)) from err

        sequence.state = STATE_RUNNING
        self._sequence = sequence
        self._sequence_reservation_id = holder.id
        await self._async_save_sequence()
        self._notify()
        self._sequence_task = self.hass.async_create_task(self._async_run_sequence(holder.id))

    async def async_pause_sequence(self, *, user_id: str | None) -> None:
        await self._assert_holds_slot(user_id)
        if self._sequence is None or self._sequence.state != STATE_RUNNING:
            raise HomeAssistantError("no running sequence on this telescope")
        self._sequence.state = STATE_PAUSED
        await self._async_save_sequence()
        self._notify()

    async def async_resume_sequence(self, *, user_id: str | None) -> None:
        holder = await self._assert_holds_slot(user_id)
        if self._sequence is None or self._sequence_reservation_id != holder.id:
            raise HomeAssistantError("no paused sequence for this reservation")
        if self._sequence.state != STATE_PAUSED:
            raise HomeAssistantError("sequence is not paused")
        self._sequence.state = STATE_RUNNING
        await self._async_save_sequence()
        self._notify()
        if self._sequence_task is None or self._sequence_task.done():
            self._sequence_task = self.hass.async_create_task(self._async_run_sequence(holder.id))

    async def async_cancel_sequence(self, *, user_id: str | None) -> None:
        await self._assert_holds_slot(user_id)
        if self._sequence is None:
            raise HomeAssistantError("no sequence on this telescope")
        self._sequence.state = STATE_CANCELLED
        await self._async_save_sequence()
        self._notify()

    def _async_check_sequence_still_valid(self, holder: Reservation | None) -> None:
        """A reservation ending mid-sequence cancels it - checked every 15s
        tick so it doesn't have to wait for the current sub's sleep to end."""
        if self._sequence is None or self._sequence.state not in (STATE_RUNNING, STATE_PAUSED):
            return
        if holder is None or holder.id != self._sequence_reservation_id:
            self._sequence.state = STATE_CANCELLED

    async def _async_run_sequence(self, reservation_id: str) -> None:
        sequence = self._sequence
        if sequence is None:
            return
        try:
            while sequence.state == STATE_RUNNING:
                if not sequence.skip_completed_steps():
                    sequence.state = STATE_DONE
                    break
                holder = self.current_holder()
                if holder is None or holder.id != reservation_id:
                    sequence.state = STATE_CANCELLED
                    break

                step = sequence.current()
                if step.needs_autofocus() and self._has_capability(CAP_AUTO_FOCUS):
                    await self._async_dispatch_capability(CAP_AUTO_FOCUS)
                    await asyncio.sleep(SEQUENCE_AUTOFOCUS_SETTLE.total_seconds())
                    if sequence.state != STATE_RUNNING:
                        break

                if step.filter is not None:
                    await self._async_dispatch_capability(CAP_SET_FILTER, step.filter)
                if step.ccd_temperature is not None:
                    await self._async_dispatch_capability(CAP_SET_CCD_TEMPERATURE, step.ccd_temperature)
                await self._async_dispatch_capability(CAP_SET_EXPOSURE, step.exposure)
                await self._async_dispatch_capability(CAP_START_CAPTURE)

                wait_seconds = self._exposure_wait_seconds(step.exposure) + SEQUENCE_READOUT_BUFFER.total_seconds()
                await asyncio.sleep(wait_seconds)

                # The exposure already happened even if paused/cancelled
                # partway through the wait above, so it still counts.
                sequence.record_sub_done()
                await self._async_save_sequence()
                self._notify()
        except asyncio.CancelledError:
            raise
        except HomeAssistantError as err:
            _LOGGER.warning("Sequence for %s stopped: %s", self.name, err)
            sequence.state = STATE_CANCELLED
        finally:
            await self._async_save_sequence()
            self._notify()

    # -- recording / frame capture ------------------------------------------

    async def async_set_recording(self, *, user_id: str | None, enabled: bool) -> None:
        holder = await self._assert_holds_slot(user_id)
        holder.recording = enabled
        await self.store.async_save()
        self._notify()

    async def async_save_frame(self, *, user_id: str | None) -> str:
        holder = await self._assert_holds_slot(user_id)
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
        await self.hass.async_add_executor_job(
            functools.partial(os.makedirs, session_dir, exist_ok=True)
        )
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
        await self._async_sync_controls_enabled(holder)
        self._async_check_sequence_still_valid(holder)
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

    async def _async_sync_controls_enabled(self, holder: Reservation | None) -> None:
        """Arm/disarm a backend's session-lifecycle gate (e.g. ha-seestar's
        "Controls enabled" switch, without which it refuses every command)
        to track whether a reservation is currently active - "arm before
        commanding, disarm after", automatically, per the upstream backend's
        own safety guidance. No-ops when the capability isn't mapped (e.g.
        ha-indi-client, which has no such gate)."""
        entity_id = self.capability_map.get(CAP_CONTROLS_ENABLED)
        if not entity_id or not entity_id.startswith("switch."):
            return
        holder_id = holder.id if holder is not None else None
        if holder_id == self._armed_reservation_id:
            return
        service = "turn_on" if holder_id is not None else "turn_off"
        try:
            await self.hass.services.async_call(
                "switch", service, {"entity_id": entity_id}, blocking=True
            )
            self._armed_reservation_id = holder_id
        except HomeAssistantError as err:
            _LOGGER.warning("Could not %s controls-enabled gate for %s: %s", service, self.name, err)
