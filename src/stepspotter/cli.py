"""stepspotter — the command line.

    stepspotter plan "<what you want to do>" <photo.jpg>
    stepspotter step <job_id>                 # draw the current step on your photo
    stepspotter verify <job_id> <photo.jpg>   # does this photo prove the step?
    stepspotter next <job_id>                 # gated: only after a passing photo
    stepspotter trace <job_id>                # everything that happened, in order
    stepspotter chat <job_id>                 # talk to the Guide agent
    stepspotter serve [--host H] [--port 8080] # the phone-first web UI

Every command needs AWS credentials for Bedrock except ``trace``.
"""

from __future__ import annotations

import argparse
import sys

from stepspotter import store
from stepspotter.guide import JobService, build_agent, build_tools, run_tool_through_gate
from stepspotter.gate import StepGate


def _service_and_gate() -> tuple[JobService, StepGate, list]:
    service = JobService()
    gate = StepGate(
        state_for=service.get,
        on_block=lambda reason, ti: store.trace(
            ti.get("job_id") or "unknown", "gate_block", reason=reason, tool_input=ti
        ),
    )
    return service, gate, build_tools(service)


def cmd_plan(args: argparse.Namespace) -> int:
    service, _gate, _tools = _service_and_gate()
    state = service.start(args.task, args.photo)
    plan = state.plan
    print(f"job_id: {state.job_id}")
    print(f"job:    {plan.job_title}  [{plan.safety_class}]")
    if not plan.is_diy:
        print(f"\nNot a do-it-yourself job. {plan.vendor_reason}")
        print("Get a licensed professional. No steps were written.")
        return 0
    if plan.tools_needed:
        print("tools:  " + ", ".join(plan.tools_needed))
    print()
    for s in plan.steps:
        print(f"  {s.id}. {s.title}")
        print(f"     {s.action}")
        if s.do_not_touch:
            print(f"     do not touch: {' · '.join(s.do_not_touch)}")
        if s.stop_condition:
            print(f"     stop if: {s.stop_condition}")
        print(f"     photo must show: {s.evidence_required}")
    print(f"\nNext: stepspotter step {state.job_id}")
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    service, _gate, _tools = _service_and_gate()
    state = service.get(args.job_id)
    if state is None:
        print(f"No job {args.job_id}", file=sys.stderr)
        return 2
    if state.done:
        print(f"All {state.total} steps are finished.")
        return 0
    path, boxes = service.card(state, args.photo)
    print(state.describe_current())
    print(f"card: {path}  ({len(boxes)} marks)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    service, _gate, _tools = _service_and_gate()
    state = service.get(args.job_id)
    if state is None:
        print(f"No job {args.job_id}", file=sys.stderr)
        return 2
    verdict = service.verify(state, args.photo)
    mark = "STOP" if verdict.stop else ("pass" if verdict.passed else "not yet")
    print(f"[{mark}] step {verdict.step_id}: {verdict.reason}")
    return 0 if verdict.passed and not verdict.stop else 1


def cmd_next(args: argparse.Namespace) -> int:
    service, gate, tools = _service_and_gate()
    state = service.get(args.job_id)
    if state is None:
        print(f"No job {args.job_id}", file=sys.stderr)
        return 2
    res = run_tool_through_gate(
        gate, tools, "advance_step", {"job_id": args.job_id, "step_id": state.current + 1}
    )
    if res["cancelled"]:
        print(res["content"])
        return 1
    print(res["content"])
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    rows = store.read_trace(args.job_id)
    if not rows:
        print(f"No trace for {args.job_id}")
        return 2
    for r in rows:
        extra = {k: v for k, v in r.items() if k not in ("at", "job_id", "event")}
        print(f"{r['at']}  {r['event']:<12} {extra}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    agent, service, _gate = build_agent(session_id=args.job_id)
    state = service.get(args.job_id)
    if state is not None:
        print(state.describe_current())
    print("Talk to the Guide. Empty line or Ctrl-D to leave.\n")
    while True:
        try:
            line = input("you> ").strip()
        except EOFError:
            break
        if not line:
            break
        print(f"\n{agent(line)}\n")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the web UI. Same JobService, same gate; the browser is not a back door."""
    import uvicorn

    from stepspotter.web.app import create_app

    print(f"StepSpotter on http://{args.host}:{args.port}  (open it on your phone)")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Run the fixtures/ eval harness (docs/EVAL-PLAN.md). Needs AWS creds for Bedrock."""
    from stepspotter.evalharness import main as eval_main

    eval_argv = [args.fixtures, "--repeat", str(args.repeat)]
    if args.out:
        eval_argv += ["--out", args.out]
    if args.model:
        eval_argv += ["--model", args.model]
    return eval_main(eval_argv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stepspotter", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="plan a job from a task and a photo")
    p.add_argument("task")
    p.add_argument("photo")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("step", help="draw the current step on your photo")
    p.add_argument("job_id")
    p.add_argument("photo", nargs="?", default=None, help="photo to draw on (default: the start photo)")
    p.set_defaults(fn=cmd_step)

    p = sub.add_parser("verify", help="check a photo against the current step")
    p.add_argument("job_id")
    p.add_argument("photo")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("next", help="move on (gated)")
    p.add_argument("job_id")
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("trace", help="print everything that happened on a job")
    p.add_argument("job_id")
    p.set_defaults(fn=cmd_trace)

    p = sub.add_parser("serve", help="run the phone-first web UI")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("chat", help="talk to the Guide agent")
    p.add_argument("job_id")
    p.set_defaults(fn=cmd_chat)

    p = sub.add_parser("eval", help="run the fixtures/ eval harness (see docs/EVAL-PLAN.md)")
    p.add_argument("fixtures", help="path to a fixtures/ directory")
    p.add_argument("--repeat", type=int, default=1, help="run each case N times, report agreement")
    p.add_argument("--out", default=None, help="output dir for <date>.md / <date>.json")
    p.add_argument("--model", default=None, help="override STEPSPOTTER_MODEL for this run")
    p.set_defaults(fn=cmd_eval)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
