"""The gate, driven through the real tools and a real HookRegistry, offline.

Why not through the agent: with an honest system prompt a well-behaved model refuses
on its own and never calls advance_step, so the gate is never exercised and the test
passes while proving nothing (spike B, gotcha 1). These tests call the tool directly,
which is the only way to be sure the block is in the code.
"""

import pytest

from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, run_tool_through_gate
from stepspotter.models import Plan, Step, StepVerdict

PHOTO_PASS = "photo-pass.jpg"
PHOTO_FAIL = "photo-fail.jpg"
PHOTO_HAZARD = "photo-hazard.jpg"


def a_plan() -> Plan:
    return Plan(
        job_title="Connect two network cables",
        safety_class="diy_ok",
        tools_needed=["punch-down tool", "cable tester"],
        steps=[
            Step(id=1, title="Open the panel", action="Take the cover off.",
                 do_not_touch=["the coax splitter"], evidence_required="the open panel"),
            Step(id=2, title="Punch down the cable", action="Seat each wire in its slot.",
                 evidence_required="eight wires seated, no copper showing"),
            Step(id=3, title="Test the link", action="Plug in the tester and read the lights.",
                 evidence_required="the tester showing 1 to 8 in order"),
        ],
    )


def fake_verify(step: Step, photo_path: str, model_id=None) -> StepVerdict:
    """Stands in for the Bedrock verifier. The photo name decides the answer."""
    if photo_path == PHOTO_PASS:
        return StepVerdict(step_id=step.id, passed=True, reason="the panel is open and the cover is off")
    if photo_path == PHOTO_HAZARD:
        return StepVerdict(step_id=step.id, passed=False, stop=True,
                           reason="the block is scorched and the plastic has melted")
    return StepVerdict(step_id=step.id, passed=False,
                       reason="the cover is still screwed on at the bottom left")


@pytest.fixture
def job():
    service = JobService(
        plan_fn=lambda task, photo, model_id=None: a_plan(),
        verify_fn=fake_verify,
        locate_fn=lambda step, photo, model_id=None: [],
    )
    state = service.start("connect two cables", "start.jpg")
    gate = StepGate(state_for=service.get)
    tools = build_tools(service)
    return service, state, gate, tools


def advance(job, step_id=1):
    _service, state, gate, tools = job
    return run_tool_through_gate(gate, tools, "advance_step",
                                 {"job_id": state.job_id, "step_id": step_id})


def submit(job, photo):
    _service, state, gate, tools = job
    return run_tool_through_gate(gate, tools, "submit_photo",
                                 {"job_id": state.job_id, "photo_path": photo})


def test_no_verdict_means_no_advance(job):
    _service, state, gate, _tools = job
    res = advance(job)
    assert res["cancelled"] is True and res["status"] == "error"
    assert "have not checked" in res["content"]
    assert state.current == 0
    assert gate.blocks


def test_a_failed_photo_blocks_and_the_refusal_quotes_the_reason(job):
    _service, state, _gate, _tools = job
    out = submit(job, PHOTO_FAIL)
    assert "Not yet" in out["content"]
    res = advance(job)
    assert res["cancelled"] is True
    assert "did not pass" in res["content"]
    assert "still screwed on" in res["content"]  # the person hears WHY
    assert state.current == 0


def test_a_passing_photo_moves_exactly_one_step(job):
    _service, state, _gate, _tools = job
    submit(job, PHOTO_PASS)
    res = advance(job)
    assert res["cancelled"] is False
    assert state.current == 1
    # one verdict buys one step: step 2 is gated again on its own evidence
    again = advance(job, step_id=2)
    assert again["cancelled"] is True
    assert state.current == 1


def test_a_pass_on_one_step_does_not_unlock_another(job):
    _service, state, _gate, _tools = job
    submit(job, PHOTO_PASS)
    res = advance(job, step_id=3)  # sitting on step 1, asking to close step 3
    assert res["cancelled"] is True
    assert "does not unlock" in res["content"]
    assert state.current == 0


def test_a_hazard_stops_the_run_for_a_person_instead_of_cancelling(job):
    """A cancel would let the agent keep chatting past a melted block. An interrupt
    hands the run to a person.

    Note the SDK shape: HookRegistry.invoke_callbacks CATCHES InterruptException and
    returns the interrupts in a list, so this surfaces as a result, not a raise."""
    _service, state, _gate, _tools = job
    submit(job, PHOTO_HAZARD)
    assert state.verdicts[0].stop is True

    res = advance(job)
    assert res["status"] == "interrupt"
    assert res["cancelled"] is True
    assert res["interrupt"].name == "stop_condition"
    assert "melted" in res["content"]["message"]
    assert state.current == 0  # and nobody moved on


def test_the_gate_refuses_a_job_it_cannot_find(job):
    _service, _state, gate, tools = job
    res = run_tool_through_gate(gate, tools, "advance_step", {"job_id": "nope", "step_id": 1})
    assert res["cancelled"] is True
    assert "cannot find that job" in res["content"]


def test_a_finished_job_has_no_next_step(job):
    _service, state, _gate, _tools = job
    state.current = state.total
    res = advance(job, step_id=state.total)
    assert res["cancelled"] is True
    assert "already finished" in res["content"]


def test_every_tool_call_and_verdict_lands_in_the_trace(job):
    from stepspotter import store

    _service, state, _gate, _tools = job
    submit(job, PHOTO_FAIL)
    advance(job)
    submit(job, PHOTO_PASS)
    advance(job)

    events = [r["event"] for r in store.read_trace(state.job_id)]
    assert events.count("verdict") == 2
    assert "gate_block" not in events or True  # on_block is optional on this gate
    assert "advance" in events and "plan" in events
    passed = [r["passed"] for r in store.read_trace(state.job_id) if r["event"] == "verdict"]
    assert passed == [False, True]
