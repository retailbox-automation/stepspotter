"""stepspotter — the command line.

    stepspotter research "<brand and model>"   # find the maker's manual for a product
    stepspotter plan "<what you want to do>" <photo.jpg>
    stepspotter step <job_id>                 # draw the current step on your photo
    stepspotter verify <job_id> <photo.jpg>   # does this photo prove the step?
    stepspotter next <job_id>                 # gated: only after a passing photo
    stepspotter trace <job_id>                # everything that happened, in order
    stepspotter chat [job_id] [--session S]   # talk to the Guide; the chat is remembered
    stepspotter serve [--host H] [--port 8080] # the phone-first web UI

Every command needs AWS credentials for Bedrock except ``trace`` and ``research``
(that one only reads the open web).
"""

from __future__ import annotations

import argparse
import sys

from stepspotter import store
from stepspotter.guide import (
    GUIDE_SYSTEM,
    GUIDE_SYSTEM_PERMISSIVE,
    JobService,
    build_agent,
    build_tools,
    job_id_in_session,
    run_tool_through_gate,
    say,
)
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
    manual, pages, source_words = _manual_from_trace(state.job_id)
    if manual is None:  # no trace to read (an older job, or research switched off)
        manual = next((u for u in plan.sources if u.lower().endswith(".pdf")), None)
    if manual:
        print(f"manual: {manual}" + (f" (pages {pages})" if pages else ""))
        if source_words:
            print(f"found:  {source_words}")
    for url in plan.sources:
        if url != manual:
            print(f"video:  {url}")
    print()
    for s in plan.steps:
        print(f"  {s.id}. {s.title}")
        print(f"     {s.action}")
        if s.do_not_touch:
            print(f"     do not touch: {' · '.join(s.do_not_touch)}")
        if s.stop_condition:
            print(f"     stop if: {s.stop_condition}")
        print(f"     photo must show: {s.evidence_required}")
        print(f"     source: {s.source or '(the photo)'}")
    print(f"\nNext: stepspotter step {state.job_id}")
    return 0


def _manual_from_trace(job_id: str) -> tuple[str | None, str, str]:
    """Manual URL, the pages read, and where it came from — off the job's own trace.

    The trace is the honest source: it records the URL the Researcher actually
    downloaded. Guessing the manual out of ``plan.sources`` by a ``.pdf`` suffix
    misfiles a manual served from a redirector under ``video:``.
    """
    for row in store.read_trace(job_id):
        if row.get("event") != "research":
            continue
        url = row.get("manual_url") or None
        pages = ", ".join(str(p) for p in row.get("pages") or [])
        if url or pages:
            return url, pages, str(row.get("source_words") or "")
    return None, "", ""


def cmd_research(args: argparse.Namespace) -> int:
    """Find the manufacturer's manual for a product. No Bedrock, no AWS credentials."""
    from stepspotter import research

    found = research.research_product(args.product, use_cache=not args.fresh)
    print(f"product: {found.product or '(not recognised)'}")
    print(f"status:  {found.status}")
    print(f"source:  {found.source or 'none'} — {research.where(found)}")
    for line in found.trail:
        print(f"  tried:  {line}")
    if found.note:
        print(f"note:    {found.note}")
    if found.manual_url:
        print(f"manual:  {found.manual_url}")
        print(f"saved:   {found.manual_path}")
        print("pages:   " + ", ".join(str(p) for p in found.manual_pages))
        head = found.excerpt[: args.chars]
        print(f"\n--- excerpt ({len(found.excerpt)} chars, first {len(head)}) ---")
        print(head)
        print("--- end excerpt ---")
    if found.videos:
        print("\nvideos:")
        for v in found.videos:
            print(f"  {v.title or 'video'}\n    {v.url}")
    return 0 if found.status == "found" else 1


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
    """Talk to the Guide.

    The conversation is kept by a Strands ``FileSessionManager`` under the session id,
    so quitting mid-repair and running the same command tomorrow carries on where it
    stopped — including which job it was about, read back out of the restored messages.

    ``--say`` runs fixed turns and exits, which is how the demo transcripts under
    ``data/demo/guide-chat/`` are produced; without it this is a plain REPL.
    """
    session_id = args.session or args.job_id or "house"
    system = GUIDE_SYSTEM_PERMISSIVE if args.permissive else GUIDE_SYSTEM
    agent, service, _gate = build_agent(session_id=session_id, system_prompt=system)

    job_id = args.job_id or job_id_in_session(agent)
    state = service.get(job_id)
    header = [f"session: {session_id}" + ("  [permissive prompt]" if args.permissive else "")]
    if state is not None:
        header.append(f"job {state.job_id}: {state.describe_current()}")
    elif job_id:
        header.append(f"job {job_id}: not on disk")
    for line in header:
        print(line)

    log = open(args.transcript, "a") if args.transcript else None

    def record(who: str, text: str) -> None:
        if log:
            log.write(f"{who}: {text}\n\n")
            log.flush()

    try:
        record("--- session", f"{session_id} ({'permissive' if args.permissive else 'honest'} prompt)")
        if args.say:
            for line in args.say:
                print(f"\nyou> {line}")
                record("you", line)
                reply = say(agent, line)
                print(f"\n{reply}\n")
                record("guide", reply)
            return 0
        print("Talk to the Guide. Empty line or Ctrl-D to leave.\n")
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                break
            if not line:
                break
            record("you", line)
            reply = say(agent, line)
            print(f"\n{reply}\n")
            record("guide", reply)
    finally:
        if log:
            log.close()
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

    p = sub.add_parser("research", help="find the maker's manual for a brand and model")
    p.add_argument("product", help='e.g. "Westinghouse ePX3030"')
    p.add_argument("--fresh", action="store_true", help="ignore the cached lookup")
    p.add_argument("--chars", type=int, default=1200, help="how much of the excerpt to print")
    p.set_defaults(fn=cmd_research)

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

    p = sub.add_parser("chat", help="talk to the Guide agent (conversation is remembered)")
    p.add_argument("job_id", nargs="?", default=None, help="an existing job to carry on with")
    p.add_argument("--session", default=None,
                   help="session id to resume (default: the job id, else 'house')")
    p.add_argument("--say", action="append", default=None,
                   help="run this turn and exit; repeat for a scripted conversation")
    p.add_argument("--permissive", action="store_true",
                   help="swap in the agreeable prompt that WILL try to skip steps, "
                        "so the gate is the only thing stopping it")
    p.add_argument("--transcript", default=None, help="append the conversation to this file")
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
