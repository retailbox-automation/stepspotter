"""The typed shapes every StepSpotter agent speaks in.

Everything the model produces is a pydantic model, so a bad answer fails at the
boundary instead of halfway down the pipeline. Field descriptions are part of the
JSON schema the model sees — they are prompt text, not comments; edit them with care.
"""

from __future__ import annotations

import datetime as _dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SafetyClass = Literal["diy_ok", "vendor_required"]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class Box(BaseModel):
    """A normalized rectangle on a photo. Origin (0,0) is the TOP-LEFT corner.

    Spike A: these coordinates drift down and run oversized, and small parts in
    clutter are missed outright. Treat a box as a soft "look around here"
    highlight. Never crop a photo with one, never point at one as proof.
    """

    label: str = Field(description="short name of the object, as a person would say it")
    x0: float = Field(ge=0.0, le=1.0, description="left edge, fraction of image width")
    y0: float = Field(ge=0.0, le=1.0, description="top edge, fraction of image height")
    x1: float = Field(ge=0.0, le=1.0, description="right edge, fraction of image width")
    y1: float = Field(ge=0.0, le=1.0, description="bottom edge, fraction of image height")
    kind: Literal["act", "avoid", "stop"] = Field(
        default="act",
        description="act = do the step here; avoid = do not touch this; stop = hazard to watch",
    )

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def normalized(self) -> "Box":
        """Return a copy with the corners ordered, so x0<x1 and y0<y1 always hold."""
        x0, x1 = sorted((self.x0, self.x1))
        y0, y1 = sorted((self.y0, self.y1))
        return self.model_copy(update={"x0": x0, "y0": y0, "x1": x1, "y1": y1})


class Step(BaseModel):
    """One small physical action, and the proof needed before the next one opens."""

    id: int = Field(ge=1, description="step number, starting at 1")
    title: str = Field(description="four to seven plain words naming the step")
    action: str = Field(
        description="at most two plain sentences describing ONE physical action; "
        "define every technical word in the same sentence"
    )
    do_not_touch: list[str] = Field(
        default_factory=list,
        description="things in reach that must be left alone during this step",
    )
    stop_condition: str | None = Field(
        default=None,
        description="what the person must stop and get a human for, e.g. "
        "'if the unit is hot, swollen or smells, stop and contact a human'",
    )
    evidence_required: str = Field(
        description="exactly what the next photo must show for this step to count as done"
    )
    highlight_targets: list[str] = Field(
        default_factory=list,
        description="objects to mark on the person's photo for this step",
    )
    source: str | None = Field(
        default=None,
        description="where this step comes from, e.g. 'manual p.11 FIG.7'; "
        "null when it comes from the photo alone",
    )

    @field_validator("action")
    @classmethod
    def _action_is_short(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("action must not be empty")
        return v.strip()


class Plan(BaseModel):
    """The whole job. Either a run of steps, or a refusal with a reason."""

    job_title: str = Field(description="the job in plain words, six words or fewer")
    safety_class: SafetyClass = Field(
        description="vendor_required when a licensed trade is needed; otherwise diy_ok"
    )
    vendor_reason: str | None = Field(
        default=None,
        description="when vendor_required: one plain sentence on why a professional is needed",
    )
    tools_needed: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    sources: list[str] = Field(
        default_factory=list,
        description="filled in by the system after planning (manual and video URLs); "
        "leave this empty",
    )

    @property
    def is_diy(self) -> bool:
        return self.safety_class == "diy_ok"

    def step(self, index: int) -> Step | None:
        """Step by zero-based position."""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None


class StepVerdict(BaseModel):
    """The verifier's answer about one photo, for one step.

    ``passed`` is the only field the gate reads. Spike A: the boolean was stable
    across repeated runs but the model's own confidence swung 0.82 -> 0.20 on an
    identical call, so no confidence field exists here and none should be added
    without an eval sweep behind it.
    """

    step_id: int = Field(ge=1, description="the step this photo is supposed to prove")
    passed: bool = Field(
        description="true only when the photo itself clearly shows the step was done"
    )
    reason: str = Field(
        description="one short sentence naming what is, or is not, visible in the photo"
    )
    stop: bool = Field(
        default=False,
        description="true when the photo shows a hazard: heat, swelling, scorching, water, "
        "smoke, or exposed live wiring. Raises the job to a human.",
    )
    evidence_boxes: list[Box] = Field(default_factory=list)


class JobState(BaseModel):
    """Everything about one job on disk: the plan, where we are, and the proof so far."""

    job_id: str
    task: str
    start_photo: str
    plan: Plan
    current: int = Field(default=0, description="zero-based index of the step in progress")
    verdicts: dict[int, StepVerdict] = Field(
        default_factory=dict, description="keyed by zero-based step index"
    )
    card_paths: dict[int, str] = Field(default_factory=dict)
    box_sets: dict[int, list[Box]] = Field(
        default_factory=dict,
        description="the boxes drawn for each step, keyed by zero-based step index, in "
        "badge order — so the legend under the photo can be written as real text",
    )
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    @field_validator("verdicts", "card_paths", "box_sets", mode="before")
    @classmethod
    def _int_keys(cls, v: object) -> object:
        """JSON turns int keys into strings; turn them back on load."""
        if isinstance(v, dict):
            return {int(k): val for k, val in v.items()}
        return v

    @property
    def total(self) -> int:
        return len(self.plan.steps)

    @property
    def done(self) -> bool:
        return self.current >= self.total

    def current_step(self) -> Step | None:
        return self.plan.step(self.current)

    def describe_current(self) -> str:
        step = self.current_step()
        if step is None:
            return f"{self.plan.job_title}: all {self.total} steps are finished."
        return f"Step {self.current + 1} of {self.total}: {step.title} — {step.action}"

    def touch(self) -> None:
        self.updated_at = _now()
