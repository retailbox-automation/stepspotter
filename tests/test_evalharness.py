"""Offline tests for the eval harness. No model calls, no network.

Every ``verify_fn`` here is a stub keyed by photo filename, exactly like
``test_guide_gate.py::fake_verify`` — the harness must be gradeable without a single
Bedrock call. These tests prove two things: the summary math, and that a red-team
case which SHOULD have been rejected but the (stub) verifier passed anyway is
reported as a harness FAILURE, non-zero exit included — a red-team miss must never
be silently averaged into a green report.
"""

from __future__ import annotations

import json

import pytest

from stepspotter.evalharness import run_eval
from stepspotter.models import Plan, Step, StepVerdict


def a_plan() -> Plan:
    return Plan(
        job_title="Terminate two jacks",
        safety_class="diy_ok",
        tools_needed=["punch-down tool"],
        steps=[
            Step(id=1, title="Open the panel", action="Take the cover off.",
                 evidence_required="the open panel, no breakers in frame"),
            Step(id=2, title="Seat the pairs", action="Lay the wire pairs into the jack.",
                 evidence_required="the jack open with pairs laid in, faceplate off"),
        ],
    )


def stub_plan_fn(task, photo_path, model_id=None):
    return a_plan()


def make_verify_fn(table: dict[str, StepVerdict]):
    def verify_fn(step: Step, photo_path: str, model_id=None) -> StepVerdict:
        key = photo_path.rsplit("/", 1)[-1]
        if key not in table:
            raise AssertionError(f"unexpected photo in stub: {key}")
        v = table[key]
        return v.model_copy(update={"step_id": step.id})
    return verify_fn


def _write_all_pass_fixture(root):
    job_dir = root / "smoke-job"
    (job_dir / "steps").mkdir(parents=True)
    (job_dir / "redteam").mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({
        "task": "terminate two jacks",
        "start_photo": "steps/01-open.jpg",
        "plan_override": a_plan().model_dump(),
    }))
    (job_dir / "steps" / "01-open.jpg").write_bytes(b"fake-jpeg-1")
    (job_dir / "steps" / "02-seat.jpg").write_bytes(b"fake-jpeg-2")
    (job_dir / "redteam" / "R1-wrong-photo.jpg").write_bytes(b"fake-jpeg-wrong")
    (job_dir / "redteam" / "redteam.json").write_text(json.dumps([
        {"id": "R1", "target_step": 2, "photo": "R1-wrong-photo.jpg", "expected": "reject",
         "note": "closed faceplate submitted for the open-jack step"},
        {"id": "R4", "target_step": 1, "photo": None, "expected": "reject-no-photo",
         "note": "advance_step called with no verdict on file at all"},
    ]))
    return job_dir


def test_all_pass_and_all_redteam_rejected_is_a_clean_report(tmp_path):
    root = tmp_path / "fixtures"
    _write_all_pass_fixture(root)

    verify_fn = make_verify_fn({
        "01-open.jpg": StepVerdict(step_id=1, passed=True, reason="panel is open, no breakers"),
        "02-seat.jpg": StepVerdict(step_id=2, passed=True, reason="pairs are laid into the jack"),
        "R1-wrong-photo.jpg": StepVerdict(step_id=2, passed=False, reason="faceplate is still closed"),
    })

    report = run_eval(root, repeat=1, plan_fn=stub_plan_fn, verify_fn=verify_fn)

    assert len(report.steps) == 2
    assert all(r.ok for r in report.steps)
    assert report.to_dict()["summary"]["steps_confirmed"] == "2/2"

    redteam = {r.case_id: r for r in report.redteam}
    assert redteam["R1"].ok and redteam["R1"].outcomes == ["reject"]
    # R4 has no photo at all — the gate must block it WITHOUT the verifier being asked.
    assert redteam["R4"].ok and redteam["R4"].outcomes == ["reject-no-photo"]

    assert report.all_ok is True


def test_a_redteam_case_that_should_reject_but_passes_is_reported_as_a_failure(tmp_path):
    """The core safety property of this harness: a fooled Verifier must surface as a
    FAILED case (and a non-zero exit), never get averaged into a green summary."""
    root = tmp_path / "fixtures"
    _write_all_pass_fixture(root)

    # The stub verifier is fooled: it PASSES the wrong photo. This must not vanish.
    verify_fn = make_verify_fn({
        "01-open.jpg": StepVerdict(step_id=1, passed=True, reason="panel is open, no breakers"),
        "02-seat.jpg": StepVerdict(step_id=2, passed=True, reason="pairs are laid into the jack"),
        "R1-wrong-photo.jpg": StepVerdict(step_id=2, passed=True, reason="looks fine (WRONG — fooled)"),
    })

    report = run_eval(root, repeat=1, plan_fn=stub_plan_fn, verify_fn=verify_fn)

    redteam = {r.case_id: r for r in report.redteam}
    assert redteam["R1"].outcomes == ["pass"]  # what actually happened
    assert redteam["R1"].expected == "reject"  # what should have happened
    assert redteam["R1"].ok is False  # the mismatch is caught, not hidden

    # A single red-team miss must sink the whole run's verdict — this is the line
    # that makes "exit non-zero on any red-team miss" true end to end.
    assert report.all_ok is False


def test_a_hazard_photo_is_reported_as_escalate_not_reject(tmp_path):
    root = tmp_path / "fixtures"
    job_dir = _write_all_pass_fixture(root)
    (job_dir / "redteam" / "redteam.json").write_text(json.dumps([
        {"id": "R5", "target_step": 2, "photo": "R1-wrong-photo.jpg", "expected": "escalate",
         "note": "hazard visible in frame"},
    ]))

    verify_fn = make_verify_fn({
        "01-open.jpg": StepVerdict(step_id=1, passed=True, reason="panel is open"),
        "02-seat.jpg": StepVerdict(step_id=2, passed=True, reason="pairs are laid in"),
        "R1-wrong-photo.jpg": StepVerdict(
            step_id=2, passed=False, stop=True, reason="bare copper touching the metal chassis"
        ),
    })

    report = run_eval(root, repeat=1, plan_fn=stub_plan_fn, verify_fn=verify_fn)
    r5 = next(r for r in report.redteam if r.case_id == "R5")
    assert r5.outcomes == ["escalate"]
    assert r5.ok is True


def test_repeat_reports_agreement_across_runs(tmp_path):
    """An unstable verifier (flips its answer run to run) must show up as <100%
    agreement, not get silently rounded to a single confident-looking number."""
    root = tmp_path / "fixtures"
    _write_all_pass_fixture(root)

    seat_calls = {"n": 0}

    def flaky_verify_fn(step: Step, photo_path: str, model_id=None) -> StepVerdict:
        key = photo_path.rsplit("/", 1)[-1]
        if key == "02-seat.jpg":
            seat_calls["n"] += 1
            # alternate pass/fail across repeats to prove agreement < 100%
            passed = seat_calls["n"] % 2 == 0
            return StepVerdict(step_id=step.id, passed=passed, reason="flaky")
        if key == "01-open.jpg":
            return StepVerdict(step_id=step.id, passed=True, reason="panel is open")
        return StepVerdict(step_id=step.id, passed=False, reason="wrong photo")

    report = run_eval(root, repeat=4, plan_fn=stub_plan_fn, verify_fn=flaky_verify_fn)
    step2 = next(r for r in report.steps if r.case_id == "step-2")
    assert step2.agreement_pct < 100.0
    assert step2.ok is False  # not every run matched "pass"


def test_missing_job_json_raises_a_clear_error(tmp_path):
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "empty-dir").mkdir()
    with pytest.raises(FileNotFoundError):
        run_eval(root)


def test_main_exits_nonzero_on_a_redteam_miss(tmp_path, capsys):
    from stepspotter.evalharness import main

    root = tmp_path / "fixtures"
    _write_all_pass_fixture(root)
    out_dir = tmp_path / "eval-results"

    import stepspotter.evalharness as eh

    real_run_eval = eh.run_eval

    def patched_run_eval(fixtures_root, repeat=1, model_id=None, plan_fn=None, verify_fn=None):
        vf = make_verify_fn({
            "01-open.jpg": StepVerdict(step_id=1, passed=True, reason="ok"),
            "02-seat.jpg": StepVerdict(step_id=2, passed=True, reason="ok"),
            "R1-wrong-photo.jpg": StepVerdict(step_id=2, passed=True, reason="fooled"),
        })
        return real_run_eval(fixtures_root, repeat=repeat, plan_fn=stub_plan_fn, verify_fn=vf)

    eh.run_eval = patched_run_eval
    try:
        code = main([str(root), "--out", str(out_dir)])
    finally:
        eh.run_eval = real_run_eval

    assert code == 1
    written = list(out_dir.glob("*.md"))
    assert written, "main() must still write a report even when the run fails"
    assert "MISS" in written[0].read_text()
