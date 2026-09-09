"""Unit tests for the step gate. No model calls, no network.

How the agent loop is simulated: instead of a stub model we build a real
``strands.hooks.HookRegistry``, register the real ``StepGate`` provider, construct a
real ``BeforeToolCallEvent`` and call ``registry.invoke_callbacks(event)`` — the same
call the SDK's tool executor makes. If ``event.cancel_tool`` is truthy the harness
never invokes the tool and returns an error-status tool result, which is exactly what
Strands does with a cancelled tool call.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spikes"))

from spike_gate import JobState, StepGate, Verdict, build_tools, run_tool_through_gate  # noqa: E402

FIXTURES = {
    "fixtures/step1_pass.jpg": (True, "Both terminals are disconnected and taped."),
    "fixtures/step1_fail.jpg": (False, "The negative terminal is still bolted to the battery."),
}


@pytest.fixture
def job():
    state = JobState(steps=["Disconnect the battery terminals", "Take off the access panel", "Swap the pump"])
    tools = build_tools(state, FIXTURES)
    gate = StepGate(state)
    return state, tools, gate


def advance(job, step_id=0):
    state, tools, gate = job
    return run_tool_through_gate(state, gate, tools, "advance_step", {"step_id": step_id})


def verify(job, step_id, photo):
    state, tools, gate = job
    return run_tool_through_gate(state, gate, tools, "verify_step", {"step_id": step_id, "photo_path": photo})


def test_advance_without_verdict_is_cancelled(job):
    state, _tools, gate = job
    res = advance(job)
    assert res["cancelled"] is True
    assert res["status"] == "error"
    assert "not checked" in res["content"].lower()
    assert state.current == 0
    assert gate.blocks  # refusal recorded for the audit trail


def test_advance_after_failed_verdict_is_cancelled_with_the_failure_reason(job):
    state, _tools, _gate = job
    v = verify(job, 0, "fixtures/step1_fail.jpg")
    assert v["content"]["passed"] is False
    res = advance(job)
    assert res["cancelled"] is True
    assert "did not pass" in res["content"]
    assert "negative terminal is still bolted" in res["content"]
    assert state.current == 0


def test_advance_after_passing_verdict_moves_exactly_one_step(job):
    state, _tools, _gate = job
    v = verify(job, 0, "fixtures/step1_pass.jpg")
    assert v["content"]["passed"] is True
    res = advance(job)
    assert res["cancelled"] is False
    assert state.current == 1
    # and the next step is gated again — one verdict buys exactly one step
    again = advance(job, step_id=1)
    assert again["cancelled"] is True
    assert state.current == 1


def test_pass_on_step_0_does_not_unlock_step_2(job):
    state, _tools, _gate = job
    state.verdicts[0] = Verdict(passed=True, reason="step 1 is genuinely done")
    # the user (or a hallucinating model) asks to close step 3 while sitting on step 1
    res = advance(job, step_id=2)
    assert res["cancelled"] is True
    assert "does not unlock" in res["content"]
    assert state.current == 0
    # jumping ahead in state does not help either: step 2 has no verdict of its own
    state.current = 2
    res2 = advance(job, step_id=2)
    assert res2["cancelled"] is True
    assert state.current == 2


def test_cancel_tool_is_a_settable_field_and_others_are_not():
    """Guards the SDK contract this spike depends on (rule 54: resolve values, not names)."""
    from strands.hooks import BeforeToolCallEvent

    ev = BeforeToolCallEvent(agent=None, selected_tool=None, tool_use={"name": "x", "toolUseId": "1", "input": {}}, invocation_state={})
    ev.cancel_tool = "nope"
    assert ev.cancel_tool == "nope"
    with pytest.raises(AttributeError):
        ev.invocation_state = {}


def test_stop_condition_escalates_to_a_human_via_interrupt():
    """A hazard must PAUSE the loop for a person, not just cancel one tool call."""
    from strands.hooks import BeforeToolCallEvent
    from strands.interrupt import InterruptException, _InterruptState

    from spike_gate import escalate_stop_condition

    class FakeAgent:
        def __init__(self):
            self._interrupt_state = _InterruptState()

    tu = {"name": "advance_step", "toolUseId": "t1", "input": {}}
    ev = BeforeToolCallEvent(agent=FakeAgent(), selected_tool=None, tool_use=tu, invocation_state={})
    with pytest.raises(InterruptException) as exc:
        escalate_stop_condition(ev, "STOP: the battery is hot and swollen — do not touch it.")
    assert exc.value.interrupt.name == "stop_condition"
    assert "hot and swollen" in exc.value.interrupt.reason["message"]

    # resume path: once the human's answer is supplied, the same call returns it
    ev2 = BeforeToolCallEvent(agent=FakeAgent(), selected_tool=None, tool_use=tu, invocation_state={})
    assert ev2.interrupt("stop_condition", reason="r", response="human: stop, call a pro") == "human: stop, call a pro"
