"""evalharness — the reproducible number described in ``docs/EVAL-PLAN.md``.

Walks a ``fixtures/<job-name>/`` tree. For each job: build the Plan (a hand-written
override in ``job.json``, or the real Planner when none is given), then push every
declared evidence photo and every red-team case through the SAME real path every
StepSpotter run uses — ``JobService.verify`` -> ``run_tool_through_gate`` -> the real
``StepGate``. Nothing here re-implements the Verifier or the Gate; a prompt change or
a gate change is graded by the exact code that ships, never a private copy of it.

Outcome vocabulary (what actually happened on one ``advance_step`` attempt):
    "pass"            advance_step succeeded — the step is unlocked
    "reject"          advance_step was cancelled and a verdict existed (it failed)
    "reject-no-photo" advance_step was cancelled and NO verdict existed yet
    "escalate"        the gate raised an interrupt (a hazard stop)

A red-team case's ``expected`` field is one of "reject", "escalate" or
"reject-no-photo" (never "pass" — a red-team case that passes is a miss, and a miss
is what this harness exists to catch, not average away).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from stepspotter import planner as _planner
from stepspotter import store
from stepspotter import verifier as _verifier
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, run_tool_through_gate
from stepspotter.models import JobState, Plan, StepVerdict

PHOTO_EXTS = (".jpg", ".jpeg", ".png")


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """One case (one step, or one red-team row), possibly run several times."""

    kind: str  # "step" | "redteam"
    case_id: str  # "step-2", "R1", ...
    job: str
    target_step: int
    expected: str  # "pass" | "reject" | "escalate" | "reject-no-photo"
    photo: str | None
    outcomes: list[str] = field(default_factory=list)  # one entry per repeat run
    reasons: list[str] = field(default_factory=list)
    latencies_s: list[float] = field(default_factory=list)
    error: str | None = None

    @property
    def agreement_pct(self) -> float:
        """Boolean agreement across repeats: did every run land on the same outcome?"""
        if not self.outcomes:
            return 0.0
        top = Counter(self.outcomes).most_common(1)[0][1]
        return round(100.0 * top / len(self.outcomes), 1)

    @property
    def ok(self) -> bool:
        """True only if EVERY run matched the expected outcome. One bad run fails it."""
        if self.error:
            return False
        return bool(self.outcomes) and all(o == self.expected for o in self.outcomes)

    def to_dict(self) -> dict:
        d = {
            "kind": self.kind,
            "case_id": self.case_id,
            "job": self.job,
            "target_step": self.target_step,
            "expected": self.expected,
            "photo": self.photo,
            "outcomes": self.outcomes,
            "reasons": self.reasons,
            "latencies_s": [round(t, 2) for t in self.latencies_s],
            "agreement_pct": self.agreement_pct,
            "ok": self.ok,
        }
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class EvalReport:
    generated_at: str
    fixtures_root: str
    repeat: int
    results: list[CaseResult] = field(default_factory=list)

    @property
    def steps(self) -> list[CaseResult]:
        return [r for r in self.results if r.kind == "step"]

    @property
    def redteam(self) -> list[CaseResult]:
        return [r for r in self.results if r.kind == "redteam"]

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "fixtures_root": self.fixtures_root,
            "repeat": self.repeat,
            "summary": {
                "steps_confirmed": f"{sum(1 for r in self.steps if r.ok)}/{len(self.steps)}",
                "redteam_rejected": f"{sum(1 for r in self.redteam if r.ok)}/{len(self.redteam)}",
                "all_ok": self.all_ok,
            },
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# fixture loading
# ---------------------------------------------------------------------------


def _load_job_spec(job_dir: Path) -> dict:
    spec_path = job_dir / "job.json"
    if not spec_path.is_file():
        raise FileNotFoundError(f"no job.json in {job_dir}")
    return json.loads(spec_path.read_text())


def _build_plan(spec: dict, job_dir: Path, plan_fn: Callable, model_id: str | None) -> Plan:
    if "plan_override" in spec:
        return Plan.model_validate(spec["plan_override"])
    start_photo = str(job_dir / spec["start_photo"])
    return plan_fn(spec["task"], start_photo, model_id)


def _find_one(dir_: Path, prefix: str) -> Path | None:
    if not dir_.is_dir():
        return None
    for ext in PHOTO_EXTS:
        matches = sorted(dir_.glob(f"{prefix}*{ext}"))
        if matches:
            return matches[0]
    return None


def discover_step_photos(job_dir: Path, plan: Plan) -> dict[int, Path]:
    """``steps/NN-*.jpg`` for each step id NN, if it exists. Missing = not run.

    Convention only, no code change needed to add a fixture: drop
    ``steps/03-whatever-you-call-it.jpg`` and step 3 picks it up.
    """
    out: dict[int, Path] = {}
    steps_dir = job_dir / "steps"
    for step in plan.steps:
        found = _find_one(steps_dir, f"{step.id:02d}-")
        if found is not None:
            out[step.id] = found
    return out


def discover_redteam(job_dir: Path) -> list[dict]:
    """``redteam/redteam.json`` lists cases; ``photo`` may be null (no-photo case)."""
    meta_path = job_dir / "redteam" / "redteam.json"
    if not meta_path.is_file():
        return []
    cases = json.loads(meta_path.read_text())
    for c in cases:
        c["photo_path"] = str(job_dir / "redteam" / c["photo"]) if c.get("photo") else None
    return cases


# ---------------------------------------------------------------------------
# mechanics shared by step and red-team runs
# ---------------------------------------------------------------------------


def _new_state(job_id: str, spec: dict, job_dir: Path, plan: Plan) -> JobState:
    start_photo = str(job_dir / spec.get("start_photo", "steps/01.jpg"))
    return JobState(job_id=job_id, task=spec.get("task", ""), start_photo=start_photo, plan=plan)


def _classify(advance_result: dict, verdict: StepVerdict | None) -> tuple[str, str]:
    """Turn one ``advance_step`` attempt into (outcome, reason-for-the-record).

    Reads the actual gate/interrupt result rather than sniffing message text, so a
    reworded refusal message can never silently change what a case is graded as.
    """
    if advance_result["status"] == "interrupt":
        content = advance_result["content"]
        # ``.get("message")`` can be missing even on a dict, so coerce to str either
        # way — the reason is always a string, never None.
        reason = content.get("message", content) if isinstance(content, dict) else content
        return "escalate", str(reason)
    if advance_result["cancelled"]:
        if verdict is None:
            return "reject-no-photo", str(advance_result["content"])
        return "reject", str(advance_result["content"])
    return "pass", str(advance_result["content"])


def _require_state(service: JobService, job_id: str) -> JobState:
    """``JobService.get`` returns ``None`` when a job is missing; here it never
    legitimately should be (we just ``put`` it ourselves), so a miss is a bug in
    the harness or the store, not something to chase as an AttributeError three
    calls downstream. Fail loudly, at the point where the job went missing.
    """
    state = service.get(job_id)
    if state is None:
        raise RuntimeError(f"job {job_id!r} disappeared from JobService mid-eval-run")
    return state


# ---------------------------------------------------------------------------
# one run of one job (fresh JobService + fresh job_id every call — no state leakage
# between repeats, and no leakage between a job's own steps and its red-team rows)
# ---------------------------------------------------------------------------


def _run_step_walk(
    job_dir: Path,
    spec: dict,
    plan: Plan,
    plan_fn: Callable,
    verify_fn: Callable,
    model_id: str | None,
    step_results: dict[int, CaseResult],
) -> None:
    """Walk the job once, in order, appending one outcome onto each step's CaseResult.

    Stops at the first step whose evidence photo does not pass — later steps in this
    run simply get no new outcome appended (a missing repeat entry, not a fabricated
    one; the Markdown/JSON report shows exactly how many runs each step actually saw).
    """
    service = JobService(plan_fn=plan_fn, verify_fn=verify_fn, model_id=model_id)
    job_id = store.new_job_id()
    state = _new_state(job_id, spec, job_dir, plan)
    service.put(state)
    tools = build_tools(service)
    gate = StepGate(state_for=service.get)

    photos = discover_step_photos(job_dir, plan)
    for step in plan.steps:
        if step.id not in step_results:
            continue  # no fixture photo for this step; not part of this eval
        r = step_results[step.id]
        if step.id not in photos:
            continue
        photo_path = str(photos[step.id])
        t0 = time.perf_counter()
        verdict = service.verify(state, photo_path)
        dt = time.perf_counter() - t0
        state = _require_state(service, job_id)
        adv = run_tool_through_gate(
            gate, tools, "advance_step", {"job_id": job_id, "step_id": state.current + 1}
        )
        outcome, reason = _classify(adv, verdict)
        r.outcomes.append(outcome)
        r.reasons.append(f"{verdict.reason} | {reason}")
        r.latencies_s.append(dt)
        state = _require_state(service, job_id)
        if outcome != "pass":
            break  # stuck here this run; do not fabricate outcomes for later steps


def _run_redteam_case(
    job_dir: Path,
    spec: dict,
    plan: Plan,
    plan_fn: Callable,
    verify_fn: Callable,
    model_id: str | None,
    case_result: CaseResult,
    case_spec: dict,
) -> None:
    """Drop straight onto the case's target step (no need to walk earlier steps —
    the gate reads only ``state.current``'s own verdict) and attempt one advance."""
    service = JobService(plan_fn=plan_fn, verify_fn=verify_fn, model_id=model_id)
    job_id = store.new_job_id()
    target_step = int(case_spec["target_step"])
    state = _new_state(job_id, spec, job_dir, plan)
    state.current = target_step - 1
    service.put(state)
    tools = build_tools(service)
    gate = StepGate(state_for=service.get)

    verdict: StepVerdict | None = None
    t0 = time.perf_counter()
    photo_path = case_spec.get("photo_path")
    if photo_path:
        verdict = service.verify(state, photo_path)
    dt = time.perf_counter() - t0
    state = _require_state(service, job_id)
    adv = run_tool_through_gate(
        gate, tools, "advance_step", {"job_id": job_id, "step_id": state.current + 1}
    )
    outcome, reason = _classify(adv, verdict)
    case_result.outcomes.append(outcome)
    case_result.reasons.append(f"{verdict.reason} | {reason}" if verdict is not None else reason)
    case_result.latencies_s.append(dt)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def run_eval(
    fixtures_root: str | Path,
    repeat: int = 1,
    model_id: str | None = None,
    plan_fn: Callable | None = None,
    verify_fn: Callable | None = None,
) -> EvalReport:
    """Run every job under ``fixtures_root`` and return the full report.

    ``plan_fn``/``verify_fn`` default to the real Planner/Verifier (live Bedrock
    calls); tests inject stubs, exactly like ``JobService`` does everywhere else.
    """
    root = Path(fixtures_root)
    plan_fn = plan_fn or _planner.plan_job
    verify_fn = verify_fn or _verifier.verify_step
    repeat = max(1, repeat)

    report = EvalReport(
        generated_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        fixtures_root=str(root),
        repeat=repeat,
    )
    if not root.is_dir():
        raise FileNotFoundError(f"no fixtures directory at {root}")

    job_dirs = sorted(d for d in root.iterdir() if d.is_dir() and (d / "job.json").is_file())
    if not job_dirs:
        raise FileNotFoundError(f"no job.json found under any subdirectory of {root}")

    for job_dir in job_dirs:
        job_name = job_dir.name
        spec = _load_job_spec(job_dir)
        try:
            plan = _build_plan(spec, job_dir, plan_fn, model_id)
        except Exception as exc:  # noqa: BLE001 - a broken fixture is a result, not a crash
            report.results.append(
                CaseResult(
                    kind="step", case_id="plan", job=job_name, target_step=0,
                    expected="pass", photo=None, error=f"could not build plan: {exc}",
                )
            )
            continue

        photos = discover_step_photos(job_dir, plan)
        step_results: dict[int, CaseResult] = {
            step.id: CaseResult(
                kind="step", case_id=f"step-{step.id}", job=job_name, target_step=step.id,
                expected="pass", photo=str(photos[step.id]),
            )
            for step in plan.steps
            if step.id in photos
        }
        for _i in range(repeat):
            try:
                _run_step_walk(job_dir, spec, plan, plan_fn, verify_fn, model_id, step_results)
            except Exception as exc:  # noqa: BLE001 - publish the failure, never hide it
                for r in step_results.values():
                    r.error = r.error or f"run crashed: {exc}"
                break
        report.results.extend(step_results.values())

        for case_spec in discover_redteam(job_dir):
            cr = CaseResult(
                kind="redteam",
                case_id=str(case_spec.get("id")),
                job=job_name,
                target_step=int(case_spec.get("target_step", 0)),
                expected=str(case_spec.get("expected")),
                photo=case_spec.get("photo"),
            )
            for _i in range(repeat):
                try:
                    _run_redteam_case(job_dir, spec, plan, plan_fn, verify_fn, model_id, cr, case_spec)
                except Exception as exc:  # noqa: BLE001
                    cr.error = f"run crashed: {exc}"
                    break
            report.results.append(cr)

    return report


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def render_markdown(report: EvalReport) -> str:
    steps, redteam = report.steps, report.redteam
    steps_ok = sum(1 for r in steps if r.ok)
    rt_ok = sum(1 for r in redteam if r.ok)
    lines = [
        f"# StepSpotter eval — {report.generated_at}",
        "",
        f"Fixtures: `{report.fixtures_root}`  ·  repeat: {report.repeat}",
        "",
        f"**{steps_ok}/{len(steps)} steps confirmed**  ·  "
        f"**{rt_ok}/{len(redteam)} wrong photos rejected**  ·  "
        f"overall: {'PASS' if report.all_ok else 'FAIL'}",
        "",
        "## Steps",
        "",
        "| job | step | expected | outcomes (one per run) | agreement | last reason |",
        "|---|---|---|---|---|---|",
    ]
    for r in steps:
        mark = "OK" if r.ok else "MISS"
        lines.append(
            f"| {r.job} | {r.case_id} | {r.expected} | {', '.join(r.outcomes) or '(no run)'} "
            f"| {r.agreement_pct}% | **{mark}** — {(r.reasons[-1] if r.reasons else r.error) or ''} |"
        )
    lines += [
        "",
        "## Red-team",
        "",
        "| job | case | target step | expected | outcomes (one per run) | agreement | last reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in redteam:
        mark = "OK" if r.ok else "MISS — release blocker"
        lines.append(
            f"| {r.job} | {r.case_id} | {r.target_step} | {r.expected} | "
            f"{', '.join(r.outcomes) or '(no run)'} | {r.agreement_pct}% "
            f"| **{mark}** — {(r.reasons[-1] if r.reasons else r.error) or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: EvalReport, out_md: Path, out_json: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(report))
    out_json.write_text(json.dumps(report.to_dict(), indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the StepSpotter fixture eval.")
    ap.add_argument("fixtures", help="path to a fixtures/ directory (one subdir per job)")
    ap.add_argument("--repeat", type=int, default=1, help="run each case N times, report agreement")
    ap.add_argument("--out", default=None, help="output dir for <date>.md / <date>.json")
    ap.add_argument("--model", default=None, help="override STEPSPOTTER_MODEL for this run")
    args = ap.parse_args(argv)

    fixtures_path = Path(args.fixtures).resolve()
    out_dir = Path(args.out) if args.out else fixtures_path.parent / "docs" / "eval-results"
    report = run_eval(fixtures_path, repeat=args.repeat, model_id=args.model)
    date = _dt.date.today().isoformat()
    write_report(report, out_dir / f"{date}.md", out_dir / f"{date}.json")
    print(render_markdown(report))
    print(f"\nwritten: {out_dir / f'{date}.md'}")
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
