"""One live check that the Planner really talks to Bedrock and really forks on safety.

Skipped without AWS credentials. Run it with:
    pytest -q -m integration
"""

import pytest

from conftest import PHOTOS, needs_aws

pytestmark = [pytest.mark.integration, needs_aws]


@needs_aws
def test_planner_writes_usable_steps_for_a_real_photo():
    from stepspotter.planner import plan_job

    photo = PHOTOS / "03-telecom-module.jpg"
    if not photo.is_file():
        pytest.skip("reference photos not available")

    plan = plan_job(
        "Connect the two blue Cat5e network cables from the old phone block to new "
        "keystone jacks and join them with a patch cord, then test the link",
        str(photo),
    )
    assert plan.safety_class in ("diy_ok", "vendor_required")
    if plan.safety_class == "vendor_required":
        assert plan.vendor_reason and plan.steps == []
        return

    assert 3 <= len(plan.steps) <= 12
    assert [s.id for s in plan.steps] == list(range(1, len(plan.steps) + 1))
    assert all(s.evidence_required.strip() for s in plan.steps)
    # the last step must be a check, not another action
    last = plan.steps[-1]
    assert any(w in (last.title + " " + last.action).lower()
               for w in ("test", "check", "verify", "confirm", "tester", "light"))
