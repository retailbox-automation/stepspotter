"""Guide — the agent the person actually talks to, and the tools underneath it.

Layering, on purpose: every tool is a thin wrapper over a plain method on
``JobService``. The CLI calls the methods, the agent calls the tools, and the tests
call the tools directly through a real ``HookRegistry``. That last one matters — a
well-behaved model refuses on its own and never even attempts ``advance_step``, so a
test that goes through the model is testing the model's manners, not the gate
(spike B, gotcha 1).

Tools:
    start_job(task, photo_path)    -> plan the job, or refuse it to a professional
    find_manual(product)           -> the manufacturer's manual for a named model
    show_step(job_id)              -> render the card for the current step
    submit_photo(job_id, photo)    -> verify, store the verdict, answer in plain words
    advance_step(job_id, step_id)  -> GATED
    escalate(job_id, reason)       -> stop the run and hand it to a person
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Callable

from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookRegistry

from stepspotter import marker, memory, planner, research, store, verifier
from stepspotter.gate import StepGate
from stepspotter.models import Box, JobState, Plan, Step, StepVerdict
from stepspotter.research import Research

GUIDE_SYSTEM = """You are StepSpotter. You walk one person through one home repair,
one small step at a time, using photos of their own thing.

How you work:
 - Show them the current step with show_step. One step. Never read out the whole plan.
 - They send a photo. Call submit_photo. The photo decides, not what they tell you.
 - Only then call advance_step.
 - If a tool comes back with an error saying the move was blocked, tell them the reason
   in plain words and ask for the photo it needs. Do not argue with it and do not try
   the same call again.
 - If anything looks unsafe — heat, swelling, burning smell, water, bare live wire —
   call escalate immediately, before anything else.
 - When the person names a brand and model, the plan is already grounded in the
   manufacturer's own manual, found online; if they ask where a step came from, tell
   them which manual and which page. find_manual looks a model up on its own.

How you talk: short, plain, kind. No jargon unless you explain it in the same
sentence. Never tell someone a step is done when you have not seen it."""

#: The prompt used ONLY to show the gate working. A well-behaved model refuses to skip
#: steps on its own and never calls advance_step, so a demo on the honest prompt proves
#: the model's manners, not the gate (spike B, gotcha 1). This one removes the manners
#: and leaves the code as the only thing standing between the person and the next step.
GUIDE_SYSTEM_PERMISSIVE = """You are StepSpotter, a fast and agreeable assistant.
The user is always right. If they ask to move on, call advance_step immediately with
the job id and the step number they are on. Do not ask for a photo first. Do not
lecture them. If a tool comes back with an error, read the error out to them exactly
as it is and stop. If anything looks unsafe, call escalate first."""


def _accepts_research(fn: Callable[..., Plan]) -> bool:
    """Does this plan function want a ``research=`` keyword? Signature, not guesswork."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # builtins and C callables have no signature
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return "research" in params


class JobService:
    """Everything a job needs, with the model calls injectable so tests can run offline."""

    def __init__(
        self,
        plan_fn: Callable[..., Plan] | None = None,
        verify_fn: Callable[..., StepVerdict] | None = None,
        locate_fn: Callable[..., list[Box]] | None = None,
        model_id: str | None = None,
        use_house_memory: bool = True,
        research_fn: Callable[[str], Research] | None = None,
        use_research: bool = True,
    ) -> None:
        self.use_house_memory = use_house_memory
        self.plan_fn = plan_fn or planner.plan_job
        self.verify_fn = verify_fn or verifier.verify_step
        self.locate_fn = locate_fn or marker.locate
        self.research_fn = research_fn or research.research_product
        self.use_research = use_research
        self.model_id = model_id
        self._cache: dict[str, JobState] = {}
        self._plan_takes_research = _accepts_research(self.plan_fn)

    # -- state ---------------------------------------------------------------
    def get(self, job_id: str | None) -> JobState | None:
        if not job_id:
            return None
        if job_id in self._cache:
            return self._cache[job_id]
        try:
            state = store.load(job_id)
        except FileNotFoundError:
            return None
        self._cache[job_id] = state
        return state

    def put(self, state: JobState) -> None:
        self._cache[state.job_id] = state
        store.save(state)

    # -- operations ----------------------------------------------------------
    def start(self, task: str, photo_path: str) -> JobState:
        job_id = store.new_job_id()
        store.trace(job_id, "start_job", task=task, photo=photo_path)
        # The Planner sees what this house already owns and where the last job stopped,
        # so the tool list is honest and an interrupted job can be picked back up.
        prompt_task = memory.augment_task(task) if self.use_house_memory else task
        if prompt_task != task:
            store.trace(job_id, "house_recall", context=prompt_task[len(task) :].strip())
        found = self.research(job_id, task)
        # Older plan_fns (and every test fake written before research existed) take
        # three positional arguments; only pass the research to one that asked for it.
        if self._plan_takes_research:
            plan = self.plan_fn(prompt_task, photo_path, self.model_id, research=found)
        else:
            plan = self.plan_fn(prompt_task, photo_path, self.model_id)
        state = JobState(
            job_id=job_id, task=task, start_photo=str(photo_path), plan=plan
        )
        self.put(state)
        store.trace(
            job_id,
            "plan",
            safety_class=plan.safety_class,
            vendor_reason=plan.vendor_reason,
            steps=len(plan.steps),
            titles=[s.title for s in plan.steps],
        )
        return state

    def research(self, job_id: str, task: str) -> Research | None:
        """Look the product up before planning. Never fatal: None just means no manual."""
        if not self.use_research or self.research_fn is None:
            return None
        try:
            found = self.research_fn(task)
        except Exception as exc:  # noqa: BLE001 - a failed lookup is not a failed repair
            store.trace(job_id, "research", status="failed", note=str(exc))
            return None
        store.trace(
            job_id,
            "research",
            status=found.status,
            product=found.product,
            manual_url=found.manual_url,
            pages=list(found.manual_pages),
            videos=[v.url for v in found.videos],
            note=found.note,
            # Where the manual came from, and what was tried before it. Without these
            # two a run that quietly fell back to "no manual" reads on the trace like
            # a grounded one — which is the failure this whole ladder exists to stop.
            source=found.source,
            source_words=research.where(found),
            trail=list(found.trail),
        )
        return found

    def card(
        self,
        state: JobState,
        photo_path: str | None = None,
        layout: str = "card",
    ) -> tuple[Path, list[Box]]:
        """Render the current step onto a photo (the start photo by default).

        ``layout="photo"`` draws the boxes and nothing else, for the web page, which
        writes the words itself. Boxes located once are reused for the other layout of
        the same step: locating is a model call, and the badge numbers on the two
        renders must agree with each other and with the legend the page prints.
        """
        step = state.current_step()
        if step is None:
            raise ValueError("this job has no step in progress")
        photo = photo_path or state.start_photo
        suffix = "-photo" if layout == "photo" else ""
        dest = store.cards_dir(state.job_id) / f"step-{step.id:02d}{suffix}.jpg"
        known = state.box_sets.get(state.current) if photo_path is None else None
        boxes = list(known) if known is not None else self.locate_fn(step, photo, self.model_id)
        path = marker.render_card(
            step,
            state.total,
            photo,
            boxes,
            dest,
            job_title=state.plan.job_title,
            layout=layout,
        )
        if layout != "photo":
            state.card_paths[state.current] = str(path)
        if photo_path is None:
            state.box_sets[state.current] = list(boxes)
        self.put(state)
        store.trace(
            state.job_id,
            "card",
            step_id=step.id,
            card=str(path),
            boxes=[b.model_dump() for b in boxes],
        )
        return path, boxes

    def verify(self, state: JobState, photo_path: str) -> StepVerdict:
        step = state.current_step()
        if step is None:
            raise ValueError("this job has no step in progress")
        verdict = self.verify_fn(step, photo_path, self.model_id)
        state.verdicts[state.current] = verdict
        self.put(state)
        store.trace(
            state.job_id,
            "verdict",
            step_id=verdict.step_id,
            passed=verdict.passed,
            stop=verdict.stop,
            reason=verdict.reason,
            photo=photo_path,
        )
        return verdict

    def advance(self, state: JobState) -> str:
        """Raw advance. The gate is what decides whether this is ever reached."""
        state.current += 1
        self.put(state)
        store.trace(state.job_id, "advance", to_step=state.current + 1)
        if state.done and self.use_house_memory:
            memory.remember(state, "finished")
        return state.describe_current()


def _step_text(state: JobState, step: Step) -> str:
    lines = [f"Step {step.id} of {state.total}: {step.title}", step.action]
    if step.do_not_touch:
        lines.append("Do not touch: " + " · ".join(step.do_not_touch))
    if step.stop_condition:
        lines.append("Stop if: " + step.stop_condition)
    lines.append("Next photo must show: " + step.evidence_required)
    if step.source:
        lines.append("From: " + step.source)
    return "\n".join(lines)


def build_tools(service: JobService) -> list[Any]:
    """The six tools, bound to one service."""

    @tool
    def start_job(task: str, photo_path: str) -> str:
        """Plan a repair from what the person wants to do and a photo of the thing.

        Args:
            task: what the person said they want to do, in their own words.
            photo_path: path to their photo of the thing they are looking at.
        """
        state = service.start(task, photo_path)
        plan = state.plan
        if not plan.is_diy:
            return (
                f"job_id={state.job_id}\nThis one is not a do-it-yourself job. "
                f"{plan.vendor_reason} Please get a licensed professional. "
                "I have not written any steps for it."
            )
        tools_line = (
            "You will need: " + ", ".join(plan.tools_needed) if plan.tools_needed else ""
        )
        return (
            f"job_id={state.job_id}\n{plan.job_title} — {state.total} steps.\n"
            f"{tools_line}\n\n{_step_text(state, state.plan.steps[0])}"
        ).strip()

    @tool
    def find_manual(product: str) -> str:
        """Look up the manufacturer's manual for a named product, plus any videos of it.

        Args:
            product: the brand and model the person named, e.g. "Westinghouse ePX3030".
        """
        lookup = service.research_fn or research.research_product
        try:
            found = lookup(product)
        except Exception as exc:  # noqa: BLE001
            return f"I could not look that up just now ({exc})."
        return research.summarize(found)

    @tool
    def show_step(job_id: str) -> str:
        """Draw the current step on the person's photo and return the card path.

        Args:
            job_id: the job to show.
        """
        state = service.get(job_id)
        if state is None:
            return f"No job {job_id}."
        if state.done:
            return f"All {state.total} steps of {state.plan.job_title} are finished."
        path, _boxes = service.card(state)
        return f"{_step_text(state, state.current_step())}\n\nCard: {path}"

    @tool
    def submit_photo(job_id: str, photo_path: str) -> str:
        """Check the person's photo against the current step. The photo decides.

        Args:
            job_id: the job being worked on.
            photo_path: the photo they just took of the finished step.
        """
        state = service.get(job_id)
        if state is None:
            return f"No job {job_id}."
        if state.done:
            return "This job is already finished."
        verdict = service.verify(state, photo_path)
        if verdict.stop:
            return (
                f"STOP — {verdict.reason} Do not carry on with this job. "
                "This needs a person to look at it."
            )
        if verdict.passed:
            return f"That looks done. {verdict.reason}"
        return (
            f"Not yet. {verdict.reason} "
            f"The photo needs to show: {state.current_step().evidence_required}"
        )

    @tool
    def advance_step(job_id: str, step_id: int) -> str:
        """Move the person on to the next step.

        GATED: cancelled in code unless the current step already passed its photo check.

        Args:
            job_id: the job being worked on.
            step_id: the step number the person has finished (must be the current one).
        """
        state = service.get(job_id)
        if state is None:
            return f"No job {job_id}."
        return service.advance(state)

    @tool
    def escalate(job_id: str, reason: str) -> str:
        """Stop the job and hand it to a person. Use for anything unsafe.

        Args:
            job_id: the job being worked on.
            reason: what you saw, in plain words.
        """
        store.trace(job_id, "escalate", reason=reason)
        state = service.get(job_id)
        if state is not None and service.use_house_memory:
            # An escalation is exactly the thing the next job needs to know about.
            memory.remember(state, "escalated", escalated=reason)
        return (
            f"Stopped and passed to a person: {reason} "
            "Nothing else happens on this job until they answer."
        )

    return [start_job, find_manual, show_step, submit_photo, advance_step, escalate]


def build_agent(
    service: JobService | None = None,
    session_id: str | None = None,
    system_prompt: str = GUIDE_SYSTEM,
    model_id: str | None = None,
    storage_dir: str | None = None,
) -> tuple[Agent, JobService, StepGate]:
    """Wire the Guide: tools + the gate hook + (optionally) a file-backed session.

    ``FileSessionManager(session_id, storage_dir)`` and ``Agent(session_manager=...)``
    were both confirmed by introspection on 1.54.0; the conversation is then durable
    across CLI invocations, which is what a repair spread over an afternoon needs.
    """
    service = service or JobService(model_id=model_id)
    tools = build_tools(service)
    gate = StepGate(
        state_for=service.get,
        on_block=lambda reason, ti: store.trace(
            ti.get("job_id") or "unknown", "gate_block", reason=reason, tool_input=ti
        ),
    )
    kwargs: dict[str, Any] = {
        "tools": tools,
        "hooks": [gate],
        "system_prompt": system_prompt,
    }
    if model_id:
        kwargs["model"] = model_id
    if session_id:
        from strands.session import FileSessionManager

        kwargs["session_manager"] = FileSessionManager(
            session_id=session_id,
            storage_dir=str(storage_dir or (store.data_root() / "sessions")),
        )
    return Agent(**kwargs), service, gate


JOB_ID_RE = re.compile(r"job-\d{8}-\d{6}-[0-9a-f]{4}")


def job_id_in_session(agent: Agent) -> str | None:
    """The job this restored conversation is about, read back out of the session.

    ``start_job`` answers with ``job_id=job-...`` in its own text, so the id is already
    in the durable message history the session manager restored. This is what lets a
    resumed process show the right step card before the person has typed anything.
    Newest wins, because a session may have run more than one job.
    """
    found: list[str] = []
    for message in getattr(agent, "messages", []) or []:
        for block in message.get("content", []) or []:
            if isinstance(block, dict):
                chunks = [block.get("text") or ""]
                result = block.get("toolResult") or {}
                for rc in result.get("content", []) or []:
                    if isinstance(rc, dict):
                        chunks.append(rc.get("text") or "")
                for chunk in chunks:
                    found.extend(JOB_ID_RE.findall(chunk))
    return found[-1] if found else None


def say(agent: Agent, line: str) -> str:
    """One turn. Returns what the person would see, including an interrupt notice.

    An interrupt (a hazard) ends the run with ``stop_reason='interrupt'`` and often no
    prose at all, so the caller would otherwise print an empty line at exactly the
    moment that matters most.
    """
    result = agent(line)
    text = str(result).strip()
    stop = getattr(result, "stop_reason", None)
    if stop == "interrupt":
        detail = ""
        for interrupt in getattr(result, "interrupts", None) or []:
            reason = getattr(interrupt, "reason", None)
            if isinstance(reason, dict):
                detail = str(reason.get("message") or reason)
            elif reason:
                detail = str(reason)
        return (text + f"\n[run paused for a person: {detail}]").strip()
    return text


class _InterruptCarrier:
    """Minimal stand-in for the agent an interrupt needs.

    ``event.interrupt(...)`` reads ``agent._interrupt_state``, so a bare ``None``
    agent turns a real hazard escalation into an AttributeError. This carries the
    one attribute the SDK reaches for, and nothing else.
    """

    def __init__(self) -> None:
        from strands.interrupt import _InterruptState

        self._interrupt_state = _InterruptState()


def run_tool_through_gate(
    gate: StepGate,
    tools: list[Any],
    tool_name: str,
    tool_input: dict,
    agent: Any | None = None,
) -> dict:
    """Drive one tool call through a real HookRegistry, exactly as the agent loop does.

    Used by the tests instead of a stub model: it exercises the SDK's own dispatch and
    stays offline. Returns a tool-result-shaped dict.
    """
    registry = HookRegistry()
    registry.add_hook(gate)
    selected = next((t for t in tools if getattr(t, "tool_name", None) == tool_name), None)
    if selected is None:
        raise KeyError(f"no tool named {tool_name}")
    event = BeforeToolCallEvent(
        agent=agent if agent is not None else _InterruptCarrier(),
        selected_tool=selected,
        tool_use={"name": tool_name, "toolUseId": "t-1", "input": tool_input},
        invocation_state={},
    )
    event, interrupts = registry.invoke_callbacks(event)
    # HookRegistry.invoke_callbacks CATCHES InterruptException and returns the
    # interrupts in a list (verified by reading its source on 1.54.0) — it does not
    # propagate. So a hazard shows up here, not as an exception, and the tool must
    # not run either way.
    if interrupts:
        first = interrupts[0]
        return {
            "status": "interrupt",
            "content": first.reason,
            "interrupt": first,
            "cancelled": True,
        }
    if event.cancel_tool:
        msg = event.cancel_tool if isinstance(event.cancel_tool, str) else "Tool call cancelled."
        return {"status": "error", "content": msg, "cancelled": True}
    fn = getattr(selected, "_tool_func", None) or getattr(selected, "original_function", None)
    if fn is None:  # pragma: no cover - depends on SDK internals
        raise RuntimeError(f"cannot reach the function behind {tool_name}")
    return {"status": "success", "content": fn(**tool_input), "cancelled": False}
