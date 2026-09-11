"""FastAPI app: one page, one step at a time, from a phone.

Endpoints (all JSON except the two image routes and ``/``):

    GET  /                          form B: the screen-stack UI, one HTML file
    GET  /chat                      form A: the chat master (prototype, same server logic)
    GET  /healthz                   liveness for App Runner / a container HEALTHCHECK
    POST /api/jobs                  multipart: task + photo  -> plan or vendor refusal
    GET  /api/jobs/{id}             where the job is right now
    GET  /api/jobs/{id}/card        the rendered card image for the current step
    POST /api/jobs/{id}/photo       multipart: photo         -> verifier verdict
    POST /api/jobs/{id}/advance     GATED, through the Strands hook (see gated.py)
    POST /api/jobs/{id}/escalate    stop and hand to a person
    GET  /api/jobs/{id}/evidence/N  the photo the person sent for step N
    GET  /api/jobs/{id}/start-photo the photo the job was opened with
    GET  /api/jobs/{id}/card/N      the card for step N (cached; the current step renders)
    GET  /api/jobs/{id}/feed        the chat transcript, rebuilt from the trace
    POST /api/jobs/{id}/ask         a typed question -> the Guide, with no tools at all
    GET  /api/jobs/{id}/trace       every tool call and refusal, in order

Nothing here holds state of its own: the job lives in ``data/jobs/<id>.json`` and
everything that happened is appended to ``data/jobs/<id>.trace.jsonl`` by the store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from stepspotter import store
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools
from stepspotter.models import JobState
from stepspotter.web.ask import answer as answer_question
from stepspotter.web.chat_page import CHAT_HTML
from stepspotter.web.feed import build_feed, composer_state
from stepspotter.web.gated import advance_via_gate, escalate_via_tool
from stepspotter.web.page import PAGE_HTML
from stepspotter.web.photos import save_upload


def _escalated(job_id: str) -> bool:
    """A job is in a person's hands once an escalate event is on its trace."""
    return any(r.get("event") == "escalate" for r in store.read_trace(job_id))


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


def create_app(
    service: JobService | None = None,
    answer_fn: Callable[[JobState, str], str] | None = None,
) -> FastAPI:
    """Build the app. Pass a ``JobService`` with fake model functions to run offline.

    ``answer_fn(state, question) -> str`` overrides who answers a question typed into
    the chat feed; the default is the Guide on Bedrock (``web.ask.guide_answer``).
    """
    app = FastAPI(title="StepSpotter", docs_url=None, redoc_url=None)
    svc = service or JobService()
    tools = build_tools(svc)
    gate = StepGate(
        state_for=svc.get,
        on_block=lambda reason, ti: store.trace(
            ti.get("job_id") or "unknown", "gate_block", reason=reason, tool_input=ti
        ),
    )
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

    @app.get("/chat", response_class=HTMLResponse)
    def chat_page() -> str:
        """Form A. Same endpoints, same gate, same trace — a feed instead of screens."""
        return CHAT_HTML

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "service": "stepspotter"}

    # ---------------------------------------------------------------- jobs
    @app.post("/api/jobs")
    async def create_job(task: str = Form(...), photo: UploadFile = File(...)) -> dict:
        raw = await photo.read()
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
        return _summary(state)

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
            path, _boxes = svc.card(state)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Could not draw the card: {exc}")
        return FileResponse(str(path), media_type="image/jpeg")

    @app.post("/api/jobs/{job_id}/photo")
    async def submit_photo(job_id: str, photo: UploadFile = File(...)) -> dict:
        state = _job(job_id)
        if state.done:
            raise HTTPException(status_code=409, detail="This job is already finished.")
        raw = await photo.read()
        if not raw:
            raise HTTPException(status_code=400, detail="That photo did not arrive. Try again.")
        step_no = state.current + 1
        dest = save_upload(raw, store.cards_dir(job_id) / f"evidence-{step_no:02d}.jpg")
        try:
            verdict = svc.verify(state, str(dest))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"The checker could not answer: {exc}")
        return {"verdict": _summary(state)["verdict"], "job": _summary(state), "raw_passed": verdict.passed}

    @app.post("/api/jobs/{job_id}/advance")
    def advance(job_id: str) -> JSONResponse:
        """Ask to move on. The gate hook decides, exactly as it does for the agent."""
        state = _job(job_id)
        res = advance_via_gate(gate, tools, job_id, state.current + 1)
        content = res.get("content")
        if res.get("cancelled"):
            if res.get("status") == "interrupt":
                message = (
                    content.get("message")
                    if isinstance(content, dict)
                    else str(content)
                )
                # The cancel path traces itself through the gate's on_block. The hazard
                # path raises an interrupt instead and traced nothing, so a reloaded
                # feed lost the one refusal that matters most. Record it here.
                store.trace(job_id, "gate_stop", reason=message)
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

    @app.get("/api/jobs/{job_id}/start-photo")
    def start_photo(job_id: str) -> Any:
        """The photo the job was opened with — the first thing in the chat feed."""
        state = _job(job_id)
        p = Path(state.start_photo)
        if not p.is_file():
            raise HTTPException(status_code=404, detail="That photo is no longer on disk.")
        return FileResponse(str(p), media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/card/{step_no}")
    def card_for_step(job_id: str, step_no: int) -> Any:
        """The person's photo with this step's boxes on it, and nothing else.

        ``layout="photo"`` on purpose: the chat writes the title, the action, the
        do-not-touch list and the legend as real HTML, so baking the same sentences
        into the JPEG would print every step twice (see marker.render_marked_photo).
        A past step is served from the file drawn when it was live — re-rendering it
        would be a fresh model call for a picture the person already acted on.
        """
        state = _job(job_id)
        idx = step_no - 1
        marked = store.cards_dir(job_id) / f"step-{step_no:02d}-photo.jpg"
        if marked.is_file():
            return FileResponse(str(marked), media_type="image/jpeg")
        if idx != state.current or state.current_step() is None:
            raise HTTPException(status_code=404, detail="No card drawn for that step.")
        try:
            path, _boxes = svc.card(state, layout="photo")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Could not draw the card: {exc}")
        return FileResponse(str(path), media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/feed")
    def feed(job_id: str) -> dict:
        """The chat transcript. Derived from the trace every time — see web/feed.py."""
        state = _job(job_id)
        # Locate this step's boxes now, if nobody has yet: the legend under the photo
        # is written from them, and the feed is fetched at exactly the moment a new
        # step appears. Failing to draw is not failing to help — the words still go.
        if state.current_step() is not None and state.current not in state.box_sets:
            try:
                svc.card(state, layout="photo")
            except Exception as exc:  # noqa: BLE001
                store.trace(job_id, "card_failed", step=state.current + 1, error=str(exc))
            state = _job(job_id)
        rows = store.read_trace(job_id)
        escalated = _escalated(job_id)
        return {
            "job": _summary(state),
            "messages": build_feed(state, rows),
            "composer": composer_state(state, escalated),
        }

    @app.post("/api/jobs/{job_id}/ask")
    def ask(job_id: str, question: str = Form(...)) -> dict:
        """A question typed into the feed. Cannot move the job: the lane has no tools."""
        state = _job(job_id)
        q = question.strip()
        if not q:
            raise HTTPException(status_code=400, detail="Type the question first.")
        store.trace(job_id, "ask", question=q)
        text, reached = answer_question(state, q, answer_fn)
        store.trace(job_id, "answer", text=text, model=reached)
        return {"question": q, "answer": text, "reached_model": reached}

    @app.get("/api/jobs/{job_id}/trace")
    def trace(job_id: str) -> dict:
        rows = store.read_trace(job_id)
        if not rows:
            raise HTTPException(status_code=404, detail=f"No trace for {job_id}.")
        return {"job_id": job_id, "rows": rows}

    return app


app = create_app()
