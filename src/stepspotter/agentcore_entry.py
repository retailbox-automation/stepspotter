"""The Guide agent behind the Amazon Bedrock AgentCore Runtime contract.

AgentCore Runtime hosts a container that is ARM64, listens on 8080, and exposes
exactly ``POST /invocations`` and ``GET /ping``. ``BedrockAgentCoreApp`` is a
Starlette app that already declares both routes (verified by introspection on
bedrock-agentcore 1.22.0: ``app.routes`` -> ``/invocations`` POST, ``/ping``
GET+HEAD), so this module only has to say what one invocation means.

One invocation = one turn with the Guide::

    {"prompt": "...",          # what the person said
     "job_id": "job-...",      # optional: carry on an existing repair
     "task":   "...",          # optional: what they want to do (starts a job)
     "photo_b64": "..."}       # optional: base64 JPEG/PNG straight off a phone

    -> {"text": "...",              # the Guide's answer, in plain words
        "job_id": "job-...",        # resolved even when the caller did not know it
        "current_step": {...},      # where the repair stands after this turn
        "trace_tail": [...]}        # the last few trace rows: tool calls, verdicts,
                                    # and every gate refusal, in order

Nothing new is decided here. The five tools, the ``StepGate`` hook that cancels
``advance_step`` in code, and the file-backed store are the same objects the CLI and
the web UI use — this is a second front door onto ``guide.build_agent()``, not a
second implementation of the rules.

Photos travel as base64 because a JSON prompt cannot carry a multipart upload. They
are written through ``web.photos.save_upload``, which is where EXIF rotation and the
downscale live, and the *path* is what the agent's tools see.

State lives under ``$STEPSPOTTER_DATA`` (``/tmp/stepspotter`` in the container — set
in ``Dockerfile.agentcore``, not here, so local runs and tests keep their own
defaults). AgentCore gives each ``runtimeSessionId`` its own microVM, so that
directory is already private to one repair; it is not durable across sessions, which
is the same trade the web UI makes on App Runner (see docs/DEPLOY.md).

Local run::

    PYTHONPATH=src PORT=8140 python -m stepspotter.agentcore_entry
    curl localhost:8140/ping
    curl -sX POST localhost:8140/invocations -H 'Content-Type: application/json' \
         -d '{"prompt": "what can you do?"}'
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path
from typing import Any, Callable

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from stepspotter import store
from stepspotter.guide import JobService, build_agent
from stepspotter.web.photos import save_upload

app = BedrockAgentCoreApp()

#: How many trace rows come back with an answer. Enough to show a refusal and what
#: led to it; not so many that a long repair returns its whole history every turn.
TRACE_TAIL = 8


def _decode_photo(photo_b64: str, job_id: str | None) -> Path:
    """Write an inbound base64 photo to disk, upright and downscaled.

    Raises ``ValueError`` on anything that is not decodable image bytes, so a bad
    upload becomes a sentence to the person rather than a 500 from the runtime.
    """
    try:
        raw = base64.b64decode(photo_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"that photo was not valid base64 ({exc})") from exc
    if not raw:
        raise ValueError("that photo arrived empty")
    stem = hashlib.sha256(raw).hexdigest()[:12]
    folder = store.cards_dir(job_id) if job_id else store.jobs_dir() / "_uploads"
    return save_upload(raw, folder / f"in-{stem}.jpg")


def _compose(prompt: str, job_id: str | None, task: str, photo: Path | None) -> str:
    """One message for the model: what they said, then the facts of this turn.

    The tools take a ``photo_path``, so the path has to reach the model as text. It
    is stated as a fact rather than as an instruction — which tool to call is the
    Guide's decision, and the gate is what keeps that decision honest.
    """
    parts: list[str] = []
    if prompt:
        parts.append(prompt)
    if job_id:
        parts.append(f"(job_id: {job_id})")
    if task:
        parts.append(f"(what they want to do: {task})")
    if photo is not None:
        parts.append(f"(their photo is saved at: {photo})")
    return "\n".join(parts)


def _answer_text(result: Any) -> str:
    """The assistant's words out of an AgentResult, without trusting one shape."""
    message = getattr(result, "message", None)
    if isinstance(message, dict):
        blocks = message.get("content") or []
        said = [
            b["text"]
            for b in blocks
            if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()
        ]
        if said:
            return "\n".join(said).strip()
    return str(result).strip()


def _resolve_job_id(service: JobService, known: str | None) -> str | None:
    """The job this turn touched.

    ``start_job`` mints the id inside the tool, so a caller who is starting a repair
    cannot pass one in. ``JobService`` caches every state it writes, so the newest
    key is the job that was just created. Reading a private attribute is deliberate:
    the alternative is scraping the id out of the model's prose.
    """
    if known:
        return known
    cache: dict[str, Any] = getattr(service, "_cache", {}) or {}
    for job_id in reversed(list(cache)):
        return job_id
    return None


def _current_step(service: JobService, job_id: str | None) -> dict | None:
    """Where the repair stands, straight off the stored state."""
    if not job_id:
        return None
    state = service.get(job_id)
    if state is None:
        return None
    plan = state.plan
    if not plan.is_diy:
        return {
            "job_title": plan.job_title,
            "diy": False,
            "vendor_reason": plan.vendor_reason,
        }
    step = state.current_step()
    if step is None:
        return {"job_title": plan.job_title, "diy": True, "done": True, "total": state.total}
    verdict = state.verdicts.get(state.current)
    return {
        "job_title": plan.job_title,
        "diy": True,
        "done": False,
        "number": state.current + 1,
        "total": state.total,
        "title": step.title,
        "action": step.action,
        "evidence_required": step.evidence_required,
        "verdict": None
        if verdict is None
        else {"passed": verdict.passed, "stop": verdict.stop, "reason": verdict.reason},
    }


def handle(payload: dict | None, build: Callable[..., Any] = build_agent) -> dict:
    """One invocation, end to end. ``build`` is injected so tests can stay offline."""
    payload = payload or {}
    prompt = str(payload.get("prompt") or "").strip()
    job_id = str(payload.get("job_id") or "").strip() or None
    task = str(payload.get("task") or "").strip()
    photo_b64 = payload.get("photo_b64")

    photo: Path | None = None
    if photo_b64:
        try:
            photo = _decode_photo(str(photo_b64), job_id)
        except ValueError as exc:
            return {
                "text": f"I could not open that photo — {exc}. Send it again.",
                "job_id": job_id,
                "current_step": None,
                "trace_tail": [],
                "error": "bad_photo",
            }

    if not prompt and not task and photo is None:
        return {
            "text": "Tell me what you are trying to do, and send a photo of it.",
            "job_id": None,
            "current_step": None,
            "trace_tail": [],
            "error": "empty_payload",
        }
    if not prompt:
        prompt = (
            "Here is my photo for this step." if job_id else "Start this job and show me step 1."
        )

    # A fresh agent per turn, with the job id as the session key: FileSessionManager
    # then keeps the conversation for one repair on disk, and a turn that has no job
    # yet simply has no history to keep.
    agent, service, _gate = build(
        session_id=job_id,
        model_id=os.environ.get("STEPSPOTTER_MODEL"),
    )

    try:
        result = agent(_compose(prompt, job_id, task, photo))
    except Exception as exc:  # noqa: BLE001 - a model failure is a sentence, not a 500
        resolved = _resolve_job_id(service, job_id)
        return {
            "text": f"Something went wrong on my side and I did not get an answer: {exc}",
            "job_id": resolved,
            "current_step": _current_step(service, resolved),
            "trace_tail": store.read_trace(resolved)[-TRACE_TAIL:] if resolved else [],
            "error": "agent_failed",
        }

    resolved = _resolve_job_id(service, job_id)
    out: dict[str, Any] = {
        "text": _answer_text(result),
        "job_id": resolved,
        "current_step": _current_step(service, resolved),
        "trace_tail": store.read_trace(resolved)[-TRACE_TAIL:] if resolved else [],
    }
    stop_reason = getattr(result, "stop_reason", None)
    if stop_reason and stop_reason != "end_turn":
        # 'interrupt' is the gate stopping the whole run on a hazard. The caller has
        # to see that; it is not an ordinary end of turn.
        out["stop_reason"] = str(stop_reason)
    return out


@app.entrypoint
def invoke(payload: dict) -> dict:
    """POST /invocations — one turn with the Guide."""
    return handle(payload)


if __name__ == "__main__":  # pragma: no cover - the container's entry
    app.run(port=int(os.environ.get("PORT", "8080")))
