"""FastAPI app: one page, one step at a time, from a phone.

Endpoints (all JSON except the two image routes and ``/``):

    GET  /                          the whole UI, one HTML file, no build step
    GET  /healthz                   liveness for App Runner / a container HEALTHCHECK
    GET  /api/demo                  is the no-camera demo installed, and what does it say
    POST /api/demo/jobs             start the demo job on a photo shipped in the package
    POST /api/jobs                  multipart: task + photo  -> plan or vendor refusal
    GET  /api/jobs/{id}             where the job is right now
    GET  /api/jobs/{id}/card        the rendered card image for the current step
    POST /api/jobs/{id}/photo       multipart: photo         -> verifier verdict
    POST /api/jobs/{id}/demo-photo  the same, on a packaged photo instead of a camera
    POST /api/jobs/{id}/advance     GATED, through the Strands hook (see gated.py)
                                    intent=skip marks an ask with no photo behind it
    POST /api/jobs/{id}/escalate    stop and hand to a person
    GET  /api/jobs/{id}/evidence/N  the photo the person sent for step N
    GET  /api/jobs/{id}/trace       every tool call and refusal, in order
                                    (?view=human for the readable one, ?view=raw for rows)

Nothing here holds state of its own: the job lives in ``data/jobs/<id>.json`` and
everything that happened is appended to ``data/jobs/<id>.trace.jsonl`` by the store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from stepspotter import store
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools
from stepspotter.models import JobState
from stepspotter.web import demo as demo_mod
from stepspotter.web.gated import advance_via_gate, escalate_via_tool
from stepspotter.web.limits import install_limits
from stepspotter.web.page import PAGE_HTML
from stepspotter.web.photos import save_upload
from stepspotter.web.trace_view import humanize


def _escalated(job_id: str) -> bool:
    """A job is in a person's hands once an escalate event is on its trace."""
    return any(r.get("event") == "escalate" for r in store.read_trace(job_id))


def _is_demo(job_id: str) -> bool:
    """Was this job started from the demo button?

    Read off the trace rather than stored on the job, so ``JobState`` keeps the same
    shape on disk and a job saved before this existed still loads.
    """
    return any(r.get("event") == "demo" for r in store.read_trace(job_id))


def _research(job_id: str) -> dict | None:
    """What the Researcher found, and where, off the job's trace.

    On screen this becomes one line under the manual link — "from the copy baked into
    the image", "a Brave search (DuckDuckGo did not answer)", or, when nothing was
    found, the list of what was tried. A plan written without the manual must not look
    on the page like a plan written with it.
    """
    for row in store.read_trace(job_id):
        if row.get("event") != "research":
            continue
        return {
            "status": row.get("status"),
            "source": row.get("source"),
            "source_words": row.get("source_words"),
            "manual_url": row.get("manual_url"),
            "pages": list(row.get("pages") or []),
            "trail": list(row.get("trail") or []),
        }
    return None


def _step_dict(state: JobState) -> dict | None:
    step = state.current_step()
    if step is None:
        return None
    return {
        "id": step.id,
        "title": step.title,
        "action": step.action,
        "do_not_touch": list(step.do_not_touch),
        "stop_condition": step.stop_condition,
        "evidence_required": step.evidence_required,
        "source": step.source,
    }


def _summary(state: JobState) -> dict:
    plan = state.plan
    verdict = state.verdicts.get(state.current)
    step = state.current_step()
    return {
        "job_id": state.job_id,
        "task": state.task,
        "job_title": plan.job_title,
        "safety_class": plan.safety_class,
        "vendor_reason": plan.vendor_reason,
        "tools_needed": list(plan.tools_needed),
        "sources": list(plan.sources),
        "total": state.total,
        "step_number": None if step is None else state.current + 1,
        "done": state.done,
        "escalated": _escalated(state.job_id),
        "demo": _is_demo(state.job_id),
        "research": _research(state.job_id),
        "step": _step_dict(state),
        "verdict": None
        if verdict is None
        else {
            "passed": verdict.passed,
            "stop": verdict.stop,
            "reason": verdict.reason,
            "evidence_url": f"/api/jobs/{state.job_id}/evidence/{state.current + 1}",
        },
        "card_url": None
        if step is None
        else f"/api/jobs/{state.job_id}/card?step={state.current + 1}",
    }


def create_app(service: JobService | None = None) -> FastAPI:
    """Build the app. Pass a ``JobService`` with fake model functions to run offline."""
    app = FastAPI(title="StepSpotter", docs_url=None, redoc_url=None)
    svc = service or JobService()
    tools = build_tools(svc)
    gate = StepGate(
        state_for=svc.get,
        on_block=lambda reason, ti: store.trace(
            ti.get("job_id") or "unknown", "gate_block", reason=reason, tool_input=ti
        ),
    )
    # Public URL, no login, 23 days of judging: cap what one address and one day can
    # spend on Bedrock, and keep a kill switch. See web/limits.py and OPERATIONS-JUDGING.md.
    install_limits(app)
    app.state.service = svc
    app.state.gate = gate
    app.state.tools = tools

    def _job(job_id: str) -> JobState:
        state = svc.get(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"No job {job_id}.")
        return state

    # ---------------------------------------------------------------- page
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE_HTML

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "service": "stepspotter"}

    # ---------------------------------------------------------------- jobs
    def _start_job(task: str, raw: bytes) -> JobState:
        """Plan one job from a task and photo bytes. The only path into the Planner.

        The camera and the demo button both end up here, so a demo cannot quietly
        become a different code path than the one a phone takes.
        """
        if not raw:
            raise HTTPException(status_code=400, detail="That photo did not arrive. Try again.")
        if not task.strip():
            raise HTTPException(status_code=400, detail="Say what you want to do first.")
        # The photo is written before the job exists, so it needs its own resting place.
        tmp_dir = store.jobs_dir() / "_uploads"
        tmp = save_upload(raw, tmp_dir / f"start-{abs(hash(raw)) % 10**10}.jpg")
        try:
            state = svc.start(task.strip(), str(tmp))
        except Exception as exc:  # noqa: BLE001 - a model failure is a user-facing message
            raise HTTPException(status_code=502, detail=f"The planner could not answer: {exc}")
        # Move the start photo in beside the job, so a job folder is self-contained.
        home = store.cards_dir(state.job_id) / "start.jpg"
        try:
            tmp.replace(home)
            state.start_photo = str(home)
            svc.put(state)
        except OSError:
            pass
        return state

    async def _verify_photo(job_id: str, raw: bytes) -> dict:
        """Check one photo against the current step. The only path into the Verifier."""
        state = _job(job_id)
        if state.done:
            raise HTTPException(status_code=409, detail="This job is already finished.")
        if not raw:
            raise HTTPException(status_code=400, detail="That photo did not arrive. Try again.")
        step_no = state.current + 1
        dest = save_upload(raw, store.cards_dir(job_id) / f"evidence-{step_no:02d}.jpg")
        try:
            verdict = svc.verify(state, str(dest))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"The checker could not answer: {exc}")
        summary = _summary(state)
        return {"verdict": summary["verdict"], "job": summary, "raw_passed": verdict.passed}

    @app.post("/api/jobs")
    async def create_job(task: str = Form(...), photo: UploadFile = File(...)) -> dict:
        return _summary(_start_job(task, await photo.read()))

    # ---------------------------------------------------------------- demo
    @app.get("/api/demo")
    def demo_info() -> dict:
        """What the first screen needs to offer the demo — or to hide the button."""
        return demo_mod.info()

    @app.post("/api/demo/jobs")
    def demo_job() -> dict:
        """Start the demo job: a packaged photo, then the real Planner, same as a phone."""
        if not demo_mod.available():
            raise HTTPException(status_code=503, detail="The demo photos are not installed.")
        state = _start_job(demo_mod.DEMO_TASK, demo_mod.photo_bytes("start"))
        # Marks the job for the page (which swaps the camera for two buttons) and puts
        # the substitution on the record, so the trace never pretends a camera was used.
        store.trace(
            state.job_id,
            "demo",
            task=demo_mod.DEMO_TASK,
            photo_source="packaged demo photo, not a camera",
        )
        return _summary(state)

    @app.post("/api/jobs/{job_id}/demo-photo")
    async def demo_photo(job_id: str, which: str = Form(...)) -> dict:
        """Send one of the packaged photos to the real Verifier. No verdict is faked."""
        if which not in demo_mod.DEMO_BUTTONS:
            raise HTTPException(status_code=400, detail=f"There is no demo photo called {which!r}.")
        try:
            raw = demo_mod.photo_bytes(which)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return await _verify_photo(job_id, raw)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return _summary(_job(job_id))

    @app.get("/api/jobs/{job_id}/card")
    def get_card(job_id: str) -> Any:
        """The current step drawn on the person's own photo. Rendered once, then cached."""
        state = _job(job_id)
        if state.current_step() is None:
            raise HTTPException(status_code=404, detail="This job has no step in progress.")
        cached = state.card_paths.get(state.current)
        if cached and Path(cached).is_file():
            return FileResponse(cached, media_type="image/jpeg")
        try:
            path, _boxes = svc.card(state, layout="photo")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Could not draw the card: {exc}")
        return FileResponse(str(path), media_type="image/jpeg")

    @app.post("/api/jobs/{job_id}/photo")
    async def submit_photo(job_id: str, photo: UploadFile = File(...)) -> dict:
        return await _verify_photo(job_id, await photo.read())

    @app.post("/api/jobs/{job_id}/advance")
    def advance(job_id: str, intent: str = Form("next")) -> JSONResponse:
        """Ask to move on. The gate hook decides, exactly as it does for the agent.

        ``intent`` changes nothing about the decision — the gate never sees it. It
        records WHY the ask happened, so the trace can tell "the photo passed and they
        pressed Next" apart from "they pressed 'I did it' and sent no photo at all".
        The page's skip button sends ``intent=skip``; that button exists so the refusal
        is reachable from a browser, which until now it was not: with no passing photo
        the Next button is simply hidden, and the one mechanic this project is built on
        never appeared on screen.
        """
        state = _job(job_id)
        if intent == "skip":
            store.trace(
                job_id,
                "skip_attempt",
                step_id=state.current + 1,
                asked="move on without sending a photo",
            )
        res = advance_via_gate(gate, tools, job_id, state.current + 1)
        content = res.get("content")
        if res.get("cancelled"):
            if res.get("status") == "interrupt":
                message = (
                    content.get("message")
                    if isinstance(content, dict)
                    else str(content)
                )
                blocked = {"blocked": True, "hazard": True, "reason": message}
            else:
                blocked = {"blocked": True, "hazard": False, "reason": str(content)}
            blocked["job"] = _summary(_job(job_id))
            return JSONResponse(blocked, status_code=200)
        fresh = _job(job_id)
        return JSONResponse(
            {"blocked": False, "hazard": False, "message": str(content), "job": _summary(fresh)}
        )

    @app.post("/api/jobs/{job_id}/escalate")
    def escalate(job_id: str, reason: str = Form("The person pressed Stop.")) -> dict:
        _job(job_id)
        res = escalate_via_tool(tools, job_id, reason)
        return {"escalated": True, "message": str(res.get("content")), "job": _summary(_job(job_id))}

    @app.get("/api/jobs/{job_id}/evidence/{step_no}")
    def evidence(job_id: str, step_no: int) -> Any:
        _job(job_id)
        p = store.cards_dir(job_id) / f"evidence-{step_no:02d}.jpg"
        if not p.is_file():
            raise HTTPException(status_code=404, detail="No photo for that step yet.")
        return FileResponse(str(p), media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/trace")
    def trace(job_id: str, view: str = "all") -> dict:
        """The record of what happened.

        ``view=human`` is what the page shows: who did what, what came back, why —
        and NO filesystem paths, job ids or raw tool inputs, which is all the raw
        rows are made of. ``view=raw`` is the operator's view, behind an explicit
        link. The default carries both, because that is what callers written before
        this parameter existed expect.
        """
        rows = store.read_trace(job_id)
        if not rows:
            raise HTTPException(status_code=404, detail=f"No trace for {job_id}.")
        if view == "human":
            return {"job_id": job_id, "human": humanize(rows)}
        if view == "raw":
            return {"job_id": job_id, "rows": rows}
        return {"job_id": job_id, "rows": rows, "human": humanize(rows)}

    return app


app = create_app()
