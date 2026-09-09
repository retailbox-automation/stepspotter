"""The planner prompt with a manual behind it — offline, no Bedrock.

The model is replaced by a capture: what matters here is what the planner PUTS IN
FRONT of it (the excerpt, with its page markers, and the instruction to trust the
photo over the manual) and what the planner does with the answer afterwards (fills
the source URLs itself, so a hallucinated link cannot get in).
"""

from __future__ import annotations

import pytest

from stepspotter import planner
from stepspotter.models import Plan, Step
from stepspotter.research import Research, VideoHit

MANUAL = "https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf"
VIDEO = "https://www.youtube.com/watch?v=abc"


def a_research(**over) -> Research:
    base = dict(
        product="Westinghouse ePX3030",
        status="found",
        manual_url=MANUAL,
        manual_pages=[10, 11],
        excerpt="[p.10]\nINCLUDED LIST\n2 x Screw\n\n[p.11]\nASSEMBLY\nFit the handle.",
        videos=[VideoHit(title="ePX3030 unboxing", url=VIDEO)],
    )
    base.update(over)
    return Research(**base)


def a_plan() -> Plan:
    return Plan(
        job_title="Assemble the pressure washer",
        safety_class="diy_ok",
        steps=[
            Step(id=1, title="Fit the handle", action="Slide it on.",
                 evidence_required="the handle seated", source="manual p.11"),
            Step(id=2, title="Run the water", action="Open the tap.",
                 evidence_required="water running clear"),
        ],
    )


@pytest.fixture
def captured(monkeypatch):
    """Swap the photo loader and the model call; keep everything else real."""
    seen: dict = {}

    monkeypatch.setattr(planner, "load_photo", lambda path: (b"jpeg", None))

    def fake_ask(system, prompt, schema, jpeg=None, model_id=None):
        seen["system"] = system
        seen["prompt"] = prompt
        return a_plan()

    monkeypatch.setattr(planner, "ask_typed", fake_ask)
    return seen


def test_the_manual_excerpt_and_its_rules_are_in_the_prompt(captured):
    plan = planner.plan_job("assemble it", "photo.jpg", research=a_research())

    prompt = captured["prompt"]
    assert "The manufacturer's manual for Westinghouse ePX3030 says" in prompt
    assert "[p.11]" in prompt and "Fit the handle." in prompt
    assert "Follow the manual's ORDER and PART NAMES" in prompt
    # the photo still wins — this sentence is the whole reason the fork is safe
    assert "if the photo contradicts the manual, trust the photo" in prompt
    # and the system prompt tells the model what source is for
    assert "source:" in captured["system"] and "manual p.11" in captured["system"]
    assert plan.steps[0].source == "manual p.11"


def test_the_urls_come_from_the_research_object_not_the_model(captured):
    plan = planner.plan_job("assemble it", "photo.jpg", research=a_research())
    assert plan.sources == [MANUAL, VIDEO]


def test_no_manual_means_no_block_and_no_sources(captured):
    plan = planner.plan_job("hang a shelf", "photo.jpg", research=None)

    assert "manufacturer's manual" not in captured["prompt"]
    assert plan.sources == []

    # A real "not_found" has no manual and no excerpt: nothing to ground on, but a
    # video someone made of this model is still worth keeping on the job.
    nothing = a_research(status="not_found", manual_url=None, manual_pages=[], excerpt="")
    plan = planner.plan_job("hang a shelf", "photo.jpg", research=nothing)
    assert "manufacturer's manual" not in captured["prompt"]
    assert plan.sources == [VIDEO]


def test_a_vendor_refusal_still_carries_the_manual_it_was_read_from(monkeypatch):
    """Even a "call a professional" answer says where the reading came from."""
    monkeypatch.setattr(planner, "load_photo", lambda path: (b"jpeg", None))
    monkeypatch.setattr(
        planner,
        "ask_typed",
        lambda *a, **k: Plan(
            job_title="Gas line work",
            safety_class="vendor_required",
            vendor_reason="This is a gas line.",
            steps=[Step(id=1, title="x", action="y", evidence_required="z")],
        ),
    )
    plan = planner.plan_job("connect the gas", "photo.jpg", research=a_research())

    assert plan.steps == [] and plan.vendor_reason
    assert plan.sources == [MANUAL, VIDEO]
