"""House memory — the small part of a repair that is worth carrying to the next one.

Two different kinds of remembering live in StepSpotter, and they are not the same
thing:

* **Session memory** is the SDK's job. ``FileSessionManager(session_id, storage_dir)``
  persists the Guide's conversation, so closing the terminal in the middle of a repair
  and coming back an hour later continues the same chat about the same job
  (``guide.build_agent(session_id=...)``). On a deployed box the same wiring takes
  ``S3SessionManager(session_id, bucket, prefix)`` instead — same interface.
* **House memory** is this file: a handful of durable facts about the *house and the
  person*, not about one conversation. Three lines per finished or escalated job:
  what the job was, which tools they now own, what actually got done, and what got
  handed to a person. It survives the session being deleted, and it is what stops the
  next job from asking "do you own a punch-down tool?" for the fourth time.

Kept deliberately small: one JSON file, no model call, no embedding, nothing to go
stale in a way a person cannot read and correct by opening it.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from pydantic import BaseModel, Field

from stepspotter import store
from stepspotter.models import JobState

#: How many past jobs the Planner is told about. Two is enough to be useful and short
#: enough that the prompt does not turn into a diary.
RECALL_JOBS = 2


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class JobRecord(BaseModel):
    """What is worth keeping about one job after it ends."""

    job_id: str
    title: str
    task: str
    outcome: str = Field(description="finished | escalated")
    tools: list[str] = Field(default_factory=list)
    completed: list[str] = Field(
        default_factory=list, description="titles of steps that passed their photo check"
    )
    escalated: str | None = Field(
        default=None, description="why a person was called in, in plain words"
    )
    stopped_at: str | None = Field(
        default=None, description="the step title the job stopped on, if it did"
    )
    at: str = Field(default_factory=_now)


class HouseMemory(BaseModel):
    """Everything remembered about this house. Newest job last."""

    jobs: list[JobRecord] = Field(default_factory=list)

    @property
    def tools_owned(self) -> list[str]:
        """Tools seen on any past job, de-duplicated, first-seen order kept."""
        seen: list[str] = []
        for job in self.jobs:
            for tool_name in job.tools:
                name = tool_name.strip()
                if name and name.lower() not in {s.lower() for s in seen}:
                    seen.append(name)
        return seen

    @property
    def last_stop(self) -> JobRecord | None:
        """The most recent job that did NOT finish — the one worth mentioning."""
        for job in reversed(self.jobs):
            if job.outcome != "finished":
                return job
        return None


def path() -> Path:
    """``data/house-memory.json`` — under STEPSPOTTER_DATA when set, so tests isolate."""
    return store.data_root() / "house-memory.json"


def load() -> HouseMemory:
    """Read the file. A corrupt or missing file is an empty memory, never an error —
    the point of this module is to help, and it must never stop a repair."""
    p = path()
    if not p.is_file():
        return HouseMemory()
    try:
        return HouseMemory.model_validate_json(p.read_text())
    except Exception:  # noqa: BLE001 - a bad memory file is not worth a crash
        return HouseMemory()


def save(mem: HouseMemory) -> Path:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mem.model_dump(), indent=2))
    return p


def _completed_titles(state: JobState) -> list[str]:
    """Step titles with a passing verdict on file. The photo decided these, not talk."""
    out = []
    for idx, verdict in sorted(state.verdicts.items()):
        step = state.plan.step(idx)
        if step is not None and verdict.passed and not verdict.stop:
            out.append(step.title)
    return out


def remember(
    state: JobState, outcome: str, escalated: str | None = None
) -> JobRecord:
    """Write one job into house memory. Called when a job finishes or escalates."""
    step = state.current_step()
    record = JobRecord(
        job_id=state.job_id,
        title=state.plan.job_title,
        task=state.task,
        outcome=outcome,
        tools=list(state.plan.tools_needed),
        completed=_completed_titles(state),
        escalated=escalated,
        stopped_at=step.title if (step is not None and outcome != "finished") else None,
    )
    mem = load()
    mem.jobs = [j for j in mem.jobs if j.job_id != state.job_id]  # one row per job
    mem.jobs.append(record)
    save(mem)
    store.trace(
        state.job_id,
        "house_memory",
        outcome=outcome,
        tools=record.tools,
        completed=record.completed,
        escalated=escalated,
    )
    return record


def planner_context(mem: HouseMemory | None = None) -> str:
    """The two lines the Planner gets about this house, or "" when nothing is known.

    Kept to two facts on purpose: what they already own (so the tool list is honest
    about what they still need to buy) and where they stopped last time (so the plan
    can pick the job back up instead of restarting it).
    """
    mem = load() if mem is None else mem
    lines: list[str] = []
    tools = mem.tools_owned
    if tools:
        lines.append("You already have: " + ", ".join(tools) + ".")
    stop = mem.last_stop
    if stop is not None:
        where = f" at the step '{stop.stopped_at}'" if stop.stopped_at else ""
        why = f" — {stop.escalated}" if stop.escalated else ""
        lines.append(f"Last time you stopped at: {stop.title}{where}{why}")
    return "\n".join(lines)


def augment_task(task: str, mem: HouseMemory | None = None) -> str:
    """The Planner's prompt builder: the person's own words plus what we know already.

    The house lines are clearly labelled so the Planner cannot mistake them for part
    of what the person just asked for.
    """
    context = planner_context(mem)
    if not context:
        return task
    return f"{task}\n\nWhat I already know about this house:\n{context}"
