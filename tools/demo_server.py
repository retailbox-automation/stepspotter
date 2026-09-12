"""Run the UI with no AWS account, on the photos checked into this repo.

    python tools/demo_server.py --port 8140      # then open http://127.0.0.1:8140/chat

Why this exists: the form of the interface is a decision someone has to make by
clicking, and waiting on Bedrock credentials to look at a layout is a bad trade. Every
line of server logic is the real one — the real JobService, the real StepGate, the real
trace, the real card renderer drawing on real photos of a real panel. Three things are
scripted, and they are exactly the three that need a model:

    plan     the checked-in plan from fixtures/onq-keystone-smoke/job.json, verbatim
    verify   first photo of each step fails, the second passes (so the refusal is
             reachable in one click without needing a genuinely wrong photo)
    locate   fixed boxes, so the card has something to draw

Nothing else is faked. "Next step" still travels through the Strands BeforeToolCall
hook and is still refused there, which is the only claim this prototype makes.

--live drops all three fakes and uses Bedrock (export credentials in the same command).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "onq-keystone-smoke" / "job.json"

# Roughly where the things named in the plan sit in 01-confirm-panel.jpg. Hand-placed
# so the demo card looks like a located card; a live run gets these from the model.
DEMO_BOXES = {
    1: [("the panel box", 0.08, 0.10, 0.72, 0.62, "act"), ("coax splitter", 0.30, 0.34, 0.52, 0.48, "avoid")],
    2: [("keystone jack", 0.33, 0.30, 0.63, 0.66, "act")],
    3: [("telecom module", 0.10, 0.36, 0.46, 0.70, "act"), ("punched-down ports", 0.12, 0.40, 0.40, 0.60, "avoid")],
}


def _demo_plan():
    from stepspotter.models import Plan

    data = json.loads(FIXTURE.read_text())
    # No step.source is set here on purpose: this fixture plan was written by hand
    # from the photos, not from a manual, and the card's "Source:" line must not
    # claim otherwise. A --live run on the research branch fills it in for real.
    return Plan.model_validate(data["plan_override"])


def build_service(live: bool):
    from stepspotter.guide import JobService
    from stepspotter.models import Box, Step, StepVerdict

    if live:
        return JobService()

    plan = _demo_plan()

    def plan_fn(task: str, photo: str, model_id=None):
        return plan.model_copy(deep=True)

    seen: list[int] = []

    def verify_fn(step: Step, photo_path: str, model_id=None) -> StepVerdict:
        first = step.id not in seen
        seen.append(step.id)
        if first:
            return StepVerdict(
                step_id=step.id,
                passed=False,
                reason=(
                    "I cannot see what this step needs in that photo — "
                    f"it has to show {step.evidence_required.split(',')[0]}."
                ),
            )
        return StepVerdict(
            step_id=step.id, passed=True, reason=f"That photo shows {step.evidence_required.split(',')[0]}."
        )

    def locate_fn(step: Step, photo: str, model_id=None) -> list[Box]:
        return [
            Box(label=lbl, x0=a, y0=b, x1=c, y1=d, kind=k)
            for (lbl, a, b, c, d, k) in DEMO_BOXES.get(step.id, DEMO_BOXES[1])
        ]

    return JobService(plan_fn=plan_fn, verify_fn=verify_fn, locate_fn=locate_fn)


def demo_answer(state, question: str) -> str:
    """A scripted answer, so the ask lane is clickable without a model.

    Deliberately not a canned-phrase lookup pretending to be clever: it says what it
    is. A live run answers through web/ask.py with the Guide and no tools.
    """
    step = state.current_step()
    where = f"step {state.current + 1}, {step.title}" if step else "this job"
    return (
        f"(scripted demo answer — run with --live for the real Guide) "
        f"You asked: {question} On {where}, the short version is: do the one action on "
        "the card, leave the red things alone, and photograph what the green line asks for."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8140)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--live", action="store_true", help="use Bedrock instead of the scripted parts")
    ap.add_argument("--data", default=str(ROOT / "data" / "demo-chat"))
    args = ap.parse_args()

    import os

    os.environ.setdefault("STEPSPOTTER_DATA", args.data)
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from stepspotter.web.app import create_app

    app = create_app(build_service(args.live), answer_fn=None if args.live else demo_answer)
    print(f"form A (chat)  http://{args.host}:{args.port}/chat")
    print(f"form B (steps) http://{args.host}:{args.port}/")
    print(f"photos to drag in: {ROOT / 'fixtures' / 'onq-keystone-smoke'}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
