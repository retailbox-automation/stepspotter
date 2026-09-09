"""The typed boundary: what must be rejected, and what must survive a round trip."""

import pytest
from pydantic import ValidationError

from stepspotter.models import Box, JobState, Plan, Step, StepVerdict


def a_step(**kw):
    base = dict(id=1, title="Open the panel", action="Take the cover off.", evidence_required="the open panel")
    base.update(kw)
    return Step(**base)


def test_box_coordinates_are_constrained_to_the_frame():
    with pytest.raises(ValidationError):
        Box(label="x", x0=-0.1, y0=0, x1=0.5, y1=0.5)
    with pytest.raises(ValidationError):
        Box(label="x", x0=0, y0=0, x1=1.4, y1=0.5)


def test_box_normalized_orders_the_corners():
    b = Box(label="x", x0=0.8, y0=0.9, x1=0.2, y1=0.1).normalized()
    assert (b.x0, b.y0, b.x1, b.y1) == (0.2, 0.1, 0.8, 0.9)
    assert b.area == pytest.approx(0.6 * 0.8)


def test_a_step_needs_an_action_and_a_way_to_prove_it():
    with pytest.raises(ValidationError):
        a_step(action="   ")
    with pytest.raises(ValidationError):
        Step(id=1, title="t", action="do it")  # no evidence_required


def test_vendor_required_plan_carries_no_steps_to_walk_someone_through():
    plan = Plan(
        job_title="Move a breaker",
        safety_class="vendor_required",
        vendor_reason="Live mains inside a breaker panel needs a licensed electrician.",
    )
    assert plan.is_diy is False
    assert plan.steps == []


def test_jobstate_survives_a_json_round_trip_with_int_keys():
    plan = Plan(job_title="Two jacks", safety_class="diy_ok", steps=[a_step(), a_step(id=2, title="Punch down")])
    state = JobState(job_id="j1", task="t", start_photo="p.jpg", plan=plan)
    state.verdicts[0] = StepVerdict(step_id=1, passed=True, reason="the panel is open")
    state.card_paths[0] = "/tmp/step-01.jpg"

    back = JobState.model_validate_json(state.model_dump_json())
    # JSON turns int keys into strings; if that leaked, the gate would look up 0 and find nothing.
    assert back.verdicts[0].passed is True
    assert back.card_paths[0].endswith("step-01.jpg")
    assert back.total == 2
    assert "Step 1 of 2" in back.describe_current()


def test_done_is_true_only_past_the_last_step():
    plan = Plan(job_title="One", safety_class="diy_ok", steps=[a_step()])
    state = JobState(job_id="j", task="t", start_photo="p", plan=plan)
    assert state.done is False and state.current_step() is not None
    state.current = 1
    assert state.done is True and state.current_step() is None
    assert "finished" in state.describe_current()
