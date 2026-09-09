"""Where a job lives between commands, and the trace that proves what happened.

Two files per job under ``data/jobs/``:

* ``<job_id>.json``       — the JobState, rewritten on every change;
* ``<job_id>.trace.jsonl`` — append-only, one JSON object per line: every tool call,
  every verdict, every gate refusal. Nothing that happened is only in a chat scroll.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

from stepspotter.models import JobState


def data_root() -> Path:
    """Runtime output root. ``STEPSPOTTER_DATA`` overrides it (demos write elsewhere)."""
    env = os.environ.get("STEPSPOTTER_DATA")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "data"


def jobs_dir() -> Path:
    d = data_root() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_job_id() -> str:
    return f"job-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def job_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def trace_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.trace.jsonl"


def cards_dir(job_id: str) -> Path:
    d = jobs_dir() / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(state: JobState) -> Path:
    state.touch()
    p = job_path(state.job_id)
    p.write_text(state.model_dump_json(indent=2))
    return p


def load(job_id: str) -> JobState:
    p = job_path(job_id)
    if not p.is_file():
        raise FileNotFoundError(f"No job {job_id} at {p}")
    return JobState.model_validate_json(p.read_text())


def trace(job_id: str, event: str, **fields: Any) -> None:
    """Append one trace line. Best-effort: a broken trace must never break the repair."""
    line = {
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "job_id": job_id,
        "event": event,
        **fields,
    }
    try:
        with trace_path(job_id).open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
    except Exception:  # noqa: BLE001 - never let logging take down the run
        pass


def read_trace(job_id: str) -> list[dict]:
    p = trace_path(job_id)
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
