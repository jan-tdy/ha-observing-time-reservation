"""Pure-Python multi-exposure sequence stepping logic.

Modeled on CCDciel's own plan/step engine (cu_plan.pas's T_Plan and
u_global.pas's TStep - studied from https://github.com/pchev/ccdciel): a
sequence is an ordered list of capture steps, each run for its configured
sub-exposure count before moving to the next, and a step already fully
done is skipped on resume (CCDciel's own `donecount >= count` check in
T_Plan.StartStep). Deliberately narrower than CCDciel's own step type,
matching only what this integration's generic capability dispatch already
supports: exposure, filter, CCD temperature and autofocus-every-N.
Dithering/guiding, frame type (light/dark/flat/bias) and CCDciel's script/
switch step types have no equivalent capability here, so they're left out
rather than faked.

No Home Assistant imports here on purpose, same as reservation.py, so this
module is fully unit tested without a running HA instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class SequenceError(Exception):
    """Raised when a sequence (or one of its steps) is invalid."""


STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"


@dataclass
class SequenceStep:
    """One capture step: take `count` subs at `exposure` length."""

    exposure: float
    count: int
    filter: str | None = None
    ccd_temperature: float | None = None
    # Trigger the auto_focus capability (if mapped) before every Nth sub of
    # THIS step, sub 0 included - i.e. 1 means every sub, 4 means every 4th.
    autofocus_every: int | None = None
    done_count: int = 0

    def __post_init__(self) -> None:
        if self.exposure <= 0:
            raise SequenceError("exposure must be greater than 0")
        if self.count <= 0:
            raise SequenceError("count must be greater than 0")
        if self.autofocus_every is not None and self.autofocus_every <= 0:
            raise SequenceError("autofocus_every must be greater than 0")
        if self.done_count < 0:
            raise SequenceError("done_count cannot be negative")

    @property
    def is_complete(self) -> bool:
        return self.done_count >= self.count

    def needs_autofocus(self) -> bool:
        """Whether the next sub (at done_count) should be preceded by an
        autofocus run."""
        return bool(self.autofocus_every) and self.done_count % self.autofocus_every == 0

    @classmethod
    def from_dict(cls, data: dict) -> "SequenceStep":
        return cls(
            exposure=float(data["exposure"]),
            count=int(data["count"]),
            filter=data.get("filter"),
            ccd_temperature=data.get("ccd_temperature"),
            autofocus_every=data.get("autofocus_every"),
            done_count=int(data.get("done_count", 0)),
        )

    def to_dict(self) -> dict:
        return {
            "exposure": self.exposure,
            "count": self.count,
            "filter": self.filter,
            "ccd_temperature": self.ccd_temperature,
            "autofocus_every": self.autofocus_every,
            "done_count": self.done_count,
        }


@dataclass
class Sequence:
    """An ordered plan of steps for one reservation's session."""

    steps: list[SequenceStep] = field(default_factory=list)
    current_step: int = 0
    state: str = STATE_IDLE

    @classmethod
    def from_steps(cls, steps: list[dict]) -> "Sequence":
        if not steps:
            raise SequenceError("a sequence needs at least one step")
        return cls(steps=[SequenceStep.from_dict(s) for s in steps])

    def current(self) -> SequenceStep | None:
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def skip_completed_steps(self) -> bool:
        """Advance past any step already fully done (e.g. on resume after a
        restart), CCDciel-style. Returns False once every step is done."""
        while self.current_step < len(self.steps) and self.steps[self.current_step].is_complete:
            self.current_step += 1
        return self.current_step < len(self.steps)

    def record_sub_done(self) -> None:
        step = self.current()
        if step is None:
            raise SequenceError("no current step to record progress against")
        step.done_count += 1

    def total_subs(self) -> int:
        return sum(s.count for s in self.steps)

    def done_subs(self) -> int:
        return sum(s.done_count for s in self.steps)

    def progress(self) -> dict:
        return {
            "state": self.state,
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "done_subs": self.done_subs(),
            "total_subs": self.total_subs(),
        }

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "current_step": self.current_step,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Sequence":
        return cls(
            steps=[SequenceStep.from_dict(s) for s in data.get("steps", [])],
            current_step=int(data.get("current_step", 0)),
            state=data.get("state", STATE_IDLE),
        )
