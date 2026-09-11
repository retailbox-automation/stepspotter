"""Answering a question typed into the feed — the one thing in the chat that talks back.

The person is standing in front of the thing and types "what is a keystone?". That is
not a command, it is a question, and it must not move the job: this lane builds the
Guide with **no tools at all**, so a question physically cannot call ``advance_step``.
The gate is what stops a model that tries; this is the layer below that — it never gets
the chance to try.

Durable on purpose: ``FileSessionManager(session_id="web-<job_id>")`` keeps the
questions and answers across a phone reload and across a process restart, the same
mechanism ``stepspotter chat`` uses. The id is prefixed so the web lane and the CLI
lane cannot overwrite each other's message history.

Failure is a message, never a 500. No AWS credentials on the box, a throttle, a bad
region — the person still has a step card on screen and is entitled to be told plainly
that the question could not be answered right now.
"""

from __future__ import annotations

from typing import Callable

from stepspotter import store
from stepspotter.models import JobState

ASK_SYSTEM = """You are StepSpotter, helping one person through one home repair.

They are standing in front of the thing right now and have asked you a question.
Answer it and nothing else:
 - two or three short sentences, plain words, no lists
 - define every technical word in the same sentence you use it in
 - if the answer depends on what you cannot see, say so and say what photo would settle it
 - never tell them a step is done, and never tell them to move on: you cannot see
   their work from here, and only a photo opens the next step
 - if their question describes heat, smoke, a burning smell, water or a bare live wire,
   tell them to stop and get a person, first sentence."""


def _context(state: JobState) -> str:
    """What the answer has to be consistent with: the job and the step in hand."""
    lines = [f"The job: {state.plan.job_title} ({state.total} steps)."]
    step = state.current_step()
    if step is None:
        lines.append("All steps are finished.")
    else:
        lines.append(
            f"They are on step {state.current + 1} of {state.total}: {step.title} — {step.action}"
        )
        if step.do_not_touch:
            lines.append("Must be left alone: " + " · ".join(step.do_not_touch))
        if step.stop_condition:
            lines.append("Stop condition: " + step.stop_condition)
        lines.append("Their next photo must show: " + step.evidence_required)
    verdict = state.verdicts.get(state.current)
    if verdict is not None:
        lines.append(
            f"Their last photo {'passed' if verdict.passed else 'did not pass'}: {verdict.reason}"
        )
    return "\n".join(lines)


def guide_answer(state: JobState, question: str, model_id: str | None = None) -> str:
    """Ask the Guide, with the current step in context. Raises on a model failure."""
    from strands import Agent
    from strands.session import FileSessionManager

    kwargs: dict = {
        "tools": [],  # a question may not move anything. See the module docstring.
        "system_prompt": ASK_SYSTEM,
        "session_manager": FileSessionManager(
            session_id=f"web-{state.job_id}",
            storage_dir=str(store.data_root() / "sessions"),
        ),
    }
    if model_id:
        kwargs["model"] = model_id
    agent = Agent(**kwargs)
    return str(agent(f"{_context(state)}\n\nTheir question: {question}")).strip()


def answer(
    state: JobState,
    question: str,
    answer_fn: Callable[[JobState, str], str] | None = None,
) -> tuple[str, bool]:
    """Answer a question from the feed. Returns (text, reached_the_model).

    Never raises: the caller is a web route serving someone mid-repair.
    """
    fn = answer_fn or (lambda s, q: guide_answer(s, q))
    try:
        text = fn(state, question)
    except Exception as exc:  # noqa: BLE001 - an unanswered question is not a failed repair
        store.trace(state.job_id, "ask_failed", question=question, error=str(exc))
        return (
            "I could not reach my model just now, so I will not guess at an answer. "
            "The step above still stands — nothing moved.",
            False,
        )
    text = (text or "").strip() or "I do not have an answer to that one."
    return text, True
