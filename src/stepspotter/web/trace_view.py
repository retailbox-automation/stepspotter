"""The trace, rendered for a person instead of for the process that wrote it.

``data/jobs/<id>.trace.jsonl`` is an operator's log: every row carries absolute
filesystem paths, job ids, box coordinates and raw tool inputs. Putting that on
screen under a button called "See what it did" answers a question nobody asked —
the person wants to know *who did what, what came back, and why*, not where the
JPEG landed on a container's disk.

So this module turns each row into four plain fields:

    actor   who acted — You, the Planner, the Checker, the Gate…
    what    what they did, in words a person uses
    result  how it came out
    why     the reason, when there is one worth reading

Two rules hold the whole file together:

1. **Allow-list, never deny-list.** Each event names the handful of fields it is
   allowed to show. A new field added to a trace row upstream cannot leak here by
   accident, because nothing copies a row wholesale.
2. **Scrub anyway.** Model-written prose (a verdict reason, a refusal) can quote a
   path it was handed, so every free-text field still goes through ``scrub``. Belt
   and braces, because the cost of being wrong is a judge reading ``/tmp/...`` on a
   demo screen.

The raw rows are still available — the page asks for them explicitly, behind a
"raw" link, for whoever wants the operator's view.
"""

from __future__ import annotations

import re

#: A job id. Correct in a log, meaningless to a person looking at their own job.
_JOB_ID = re.compile(r"\bjob-\d{8}-\d{6}-[0-9a-f]{4}\b")

#: A filesystem path ending in a file we write. Directory names in this project
#: contain spaces ("Retailbox - Agents for Humans Hackathon"), so the segment class
#: has to allow them — which is exactly why this is a backstop and not the defence.
_PATH = re.compile(r"(?:/|[A-Za-z]:\\)[^\s\"']*(?:[^\s\"']|\s(?=\S))*?\.(?:jpg|jpeg|png|json|jsonl)\b")

#: Any remaining absolute path, even without a known extension.
_BARE_PATH = re.compile(r"(?<![\w.])(?:/[\w.\- ]+){2,}/?")


def scrub(value: object) -> str:
    """Free text with paths and job ids taken out, safe to render on screen."""
    text = "" if value is None else str(value)
    text = _PATH.sub("a photo", text)
    text = _BARE_PATH.sub(" a file ", text)
    text = _JOB_ID.sub("this job", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _clock(at: object) -> str:
    """``2026-09-11T14:42:42+00:00`` -> ``14:42:42``. The date is the job's, not the row's."""
    text = str(at or "")
    if "T" in text:
        text = text.split("T", 1)[1]
    return text.split("+")[0].split(".")[0]


def _row(actor: str, what: str, result: str = "", why: str = "", tone: str = "") -> dict:
    return {"actor": actor, "what": what, "result": result, "why": why, "tone": tone}


def _research(r: dict) -> dict:
    status = r.get("status")
    if status == "found":
        where = r.get("source_words") or r.get("source") or "a lookup"
        pages = r.get("pages") or []
        return _row(
            "Researcher",
            "Looked for the manufacturer's manual",
            "Found it via " + scrub(where) + (f" — pages {', '.join(str(p) for p in pages)}" if pages else ""),
            tone="ok",
        )
    if status == "not_found":
        trail = "; ".join(scrub(t) for t in (r.get("trail") or []))
        return _row(
            "Researcher",
            "Looked for the manufacturer's manual",
            "Nothing found — the steps come from the photo alone",
            why=("Tried: " + trail) if trail else "",
        )
    # Neither found nor not_found: the lookup never ran. Usually because the person
    # named no brand or model — which is ordinary, not a fault, and must not read on
    # screen like something broke.
    return _row(
        "Researcher",
        "Looked for the manufacturer's manual",
        "No lookup was possible",
        why=scrub(r.get("note")),
    )


def _verdict(r: dict) -> dict:
    step = r.get("step_id")
    if r.get("stop"):
        result, tone = "Stop — this is not safe to carry on", "stop"
    elif r.get("passed"):
        result, tone = "Passed", "ok"
    else:
        result, tone = "Not yet", "bad"
    return _row(
        "Checker",
        f"Looked at the photo for step {step}",
        result,
        why=scrub(r.get("reason")),
        tone=tone,
    )


def _fallback(r: dict) -> dict:
    """An event this file has not been taught yet: name it, show nothing risky."""
    shown = []
    for key, value in r.items():
        if key in ("at", "job_id", "event"):
            continue
        if isinstance(value, (dict, list)):
            shown.append(f"{key}: {len(value)} item(s)")
        elif isinstance(value, str) and ("/" in value or "\\" in value):
            shown.append(f"{key}: (hidden)")
        elif value is not None:
            shown.append(f"{key}: {scrub(value)}")
    return _row("System", scrub(r.get("event")).replace("_", " "), "; ".join(shown)[:300])


def humanize_row(r: dict) -> dict:
    """One trace row -> one screen row. Never copies unknown fields through."""
    event = r.get("event")
    if event == "start_job":
        out = _row("You", "Described the job and sent a photo of it", scrub(r.get("task")))
    elif event == "demo":
        out = _row(
            "You",
            "Started the built-in demo job",
            scrub(r.get("task")),
            why="Photos come from the repo instead of a camera; everything after this is live.",
        )
    elif event == "house_recall":
        out = _row("Memory", "Recalled what this house already has", scrub(r.get("context")))
    elif event == "research":
        out = _research(r)
    elif event == "plan":
        if r.get("safety_class") == "vendor_required":
            out = _row(
                "Planner",
                "Read the photo and the job",
                "Refused to write steps — this one needs a professional",
                why=scrub(r.get("vendor_reason")),
                tone="stop",
            )
        else:
            titles = r.get("titles") or []
            out = _row(
                "Planner",
                "Wrote the plan from the photo",
                f"{r.get('steps')} steps, safe to do yourself",
                why=" · ".join(scrub(t) for t in titles[:4]) + (" …" if len(titles) > 4 else ""),
                tone="ok",
            )
    elif event == "card":
        boxes = r.get("boxes") or []
        act = sum(1 for b in boxes if isinstance(b, dict) and b.get("kind") == "act")
        avoid = len(boxes) - act
        out = _row(
            "Marker",
            f"Drew step {r.get('step_id')} onto your photo",
            f"{act} box(es) to work in, {avoid} to keep away from",
        )
    elif event == "verdict":
        out = _verdict(r)
    elif event == "skip_attempt":
        # The person pressed "I did it" and sent nothing. On its own this row proves
        # only that they asked; the Gate row right under it is what actually happened.
        out = _row(
            "You",
            "Asked to move on without sending a photo",
            f"Wanted step {r.get('step_id')} closed on your word alone",
            tone="bad",
        )
    elif event == "gate_block":
        out = _row(
            "Gate (code, not the model)",
            "Refused to move to the next step",
            "Blocked",
            why=scrub(r.get("reason")),
            tone="bad",
        )
    elif event == "advance":
        out = _row("Guide", f"Moved on to step {r.get('to_step')}", "Allowed — the photo had passed", tone="ok")
    elif event == "escalate":
        out = _row(
            "Guide",
            "Stopped the job and handed it to a person",
            scrub(r.get("reason")),
            tone="stop",
        )
    else:
        out = _fallback(r)
    out["at"] = _clock(r.get("at"))
    return out


def humanize(rows: list[dict]) -> list[dict]:
    """The whole trace, in order, with nothing in it a person cannot read.

    One cross-row fix-up: the ``demo`` marker can only be written *after* the job
    exists, so on the raw trace it lands below the plan it started. Reading "you
    started the demo" after "here is your plan" is simply wrong about what happened,
    so the note is folded into the opening row and the stray one is dropped.
    """
    demo = next((r for r in rows if r.get("event") == "demo"), None)
    out: list[dict] = []
    for r in rows:
        if r is demo:
            continue
        row = humanize_row(r)
        if demo is not None and r.get("event") == "start_job":
            row["what"] = "Started the built-in demo job"
            row["why"] = (
                "Photos come from the repo instead of a camera; "
                "the plan, the checks and the gate after this are live."
            )
        out.append(row)
    return out
