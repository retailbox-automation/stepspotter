"""The readable trace — and the one thing it must never do.

A trace row is an operator's record: container paths, job ids, box coordinates, raw
tool inputs. "See what it did" is read by the person holding the phone, so the rule
these tests enforce is blunt — **nothing that looks like a filesystem path or an
internal id reaches the human view**, whichever event it came in on, including one
this renderer has never seen.
"""

from __future__ import annotations

import io
import json
import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from stepspotter.guide import JobService
from stepspotter.models import Plan, Step, StepVerdict
from stepspotter.web.app import create_app
from stepspotter.web.trace_view import humanize, humanize_row, scrub

#: What must not appear on screen. Kept here so the web test and the unit tests agree.
FORBIDDEN = (
    re.compile(r"/(?:Users|home|tmp|private|var|data|app)/"),
    re.compile(r"\.jpe?g\b"),
    re.compile(r"\.jsonl?\b"),
    re.compile(r"\bjob-\d{8}-\d{6}-[0-9a-f]{4}\b"),
)


def assert_clean(text: str) -> None:
    for pattern in FORBIDDEN:
        assert not pattern.search(text), f"{pattern.pattern} leaked into: {text[:300]}"


def _text_of(rows: list[dict]) -> str:
    return " ".join(f"{r['actor']} {r['what']} {r['result']} {r['why']}" for r in rows)


# ------------------------------------------------------------------ scrubbing
@pytest.mark.parametrize(
    "dirty",
    [
        "/Users/someone/Projects/Retailbox - Agents for Humans Hackathon/data/jobs/x/start.jpg",
        "/tmp/stepspotter/jobs/_uploads/start-7792889889.jpg",
        "/data/jobs/job-20260911-101010-ab12/evidence-01.jpg",
        "wrote the card to /app/data/jobs/abc/step-01.jpg for you",
        "job-20260911-101010-ab12 did not pass",
    ],
)
def test_scrub_takes_out_paths_and_job_ids(dirty):
    assert_clean(scrub(dirty))


def test_scrub_leaves_ordinary_prose_alone():
    said = "The punch-down block is visible but too far away to read the T568A/T568B label."
    assert scrub(said) == said


# ------------------------------------------------------------------ per event
def test_the_whole_vocabulary_renders_readably_and_cleanly():
    rows = [
        {
            "at": "2026-09-11T14:42:42+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "start_job",
            "task": "Confirm the panel is safe to work on",
            "photo": "/data/jobs/_uploads/start-1.jpg",
        },
        {
            "at": "2026-09-11T14:42:43+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "research",
            "status": "not_found",
            "trail": ["DuckDuckGo: no answer", "/app/data/manuals/cache.json: miss"],
        },
        {
            "at": "2026-09-11T14:43:20+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "plan",
            "safety_class": "diy_ok",
            "steps": 6,
            "titles": ["Open the panel", "Find the runs", "Punch down", "Test", "Tidy"],
        },
        {
            "at": "2026-09-11T14:43:39+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "card",
            "step_id": 1,
            "card": "/data/jobs/job-20260911-144242-b179/step-01.jpg",
            "boxes": [{"kind": "act"}, {"kind": "act"}, {"kind": "avoid"}],
        },
        {
            "at": "2026-09-11T14:43:47+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "verdict",
            "step_id": 1,
            "passed": False,
            "stop": False,
            "reason": "This is a close-up of a jack, not the panel.",
            "photo": "/data/jobs/job-20260911-144242-b179/evidence-01.jpg",
        },
        {
            "at": "2026-09-11T14:43:48+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "gate_block",
            "reason": "Blocked: step 1 did not pass the check.",
            "tool_input": {"job_id": "job-20260911-144242-b179", "step_id": 1},
        },
        {
            "at": "2026-09-11T14:44:10+00:00",
            "job_id": "job-20260911-144242-b179",
            "event": "advance",
            "to_step": 2,
        },
    ]
    human = humanize(rows)
    assert [r["actor"] for r in human] == [
        "You", "Researcher", "Planner", "Marker", "Checker", "Gate (code, not the model)", "Guide",
    ]
    assert human[0]["at"] == "14:42:42"
    assert human[2]["result"] == "6 steps, safe to do yourself"
    assert human[3]["result"] == "2 box(es) to work in, 1 to keep away from"
    assert human[4]["result"] == "Not yet" and human[4]["tone"] == "bad"
    assert human[5]["result"] == "Blocked" and "did not pass" in human[5]["why"]
    assert human[6]["result"].startswith("Allowed")
    assert_clean(_text_of(human))


def test_a_hazard_and_an_escalation_read_as_stops():
    stop = humanize_row(
        {"at": "2026-09-11T14:00:00+00:00", "event": "verdict", "step_id": 2,
         "passed": True, "stop": True, "reason": "The plastic is scorched."}
    )
    assert stop["tone"] == "stop" and "not safe" in stop["result"]
    esc = humanize_row({"at": "2026-09-11T14:00:01+00:00", "event": "escalate", "reason": "smells hot"})
    assert esc["actor"] == "Guide" and esc["tone"] == "stop"


def test_a_vendor_refusal_says_so_rather_than_counting_steps():
    row = humanize_row(
        {"at": "2026-09-11T14:00:00+00:00", "event": "plan", "safety_class": "vendor_required",
         "vendor_reason": "This is mains wiring inside a breaker panel.", "steps": 0, "titles": []}
    )
    assert "Refused" in row["result"] and "mains wiring" in row["why"]


def test_an_event_this_renderer_has_never_seen_still_cannot_leak_a_path():
    """The allow-list has to hold for tomorrow's trace events too, not just today's."""
    row = humanize_row(
        {
            "at": "2026-09-11T14:00:00+00:00",
            "job_id": "job-20260911-140000-ffff",
            "event": "some_new_thing",
            "file": "/Users/someone/secret/place/photo.jpg",
            "payload": {"a": 1, "b": 2},
            "count": 3,
        }
    )
    assert row["actor"] == "System" and "some new thing" in row["what"]
    assert "(hidden)" in row["result"] and "count: 3" in row["result"]
    assert_clean(row["result"])


# ------------------------------------------------------------------ over HTTP
def _plan(task: str, photo: str, model_id=None) -> Plan:
    return Plan(
        job_title="Two jacks and a test",
        safety_class="diy_ok",
        steps=[
            Step(id=1, title="Punch down", action="Seat the wires.",
                 evidence_required="eight wires seated"),
            Step(id=2, title="Test", action="Read the lights.", evidence_required="all pairs lit"),
        ],
    )


@pytest.fixture
def client(isolated_data):
    service = JobService(
        plan_fn=_plan,
        verify_fn=lambda step, photo, model_id=None: StepVerdict(
            step_id=step.id, passed=False, reason="I cannot see the jack."
        ),
        locate_fn=lambda *a, **k: [],
    )
    return TestClient(create_app(service))


def _job(client) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (60, 80, 110)).save(buf, format="JPEG")
    r = client.post(
        "/api/jobs",
        data={"task": "connect two cables"},
        files={"photo": ("panel.jpg", buf.getvalue(), "image/jpeg")},
    )
    return r.json()["job_id"]


def test_the_human_view_carries_no_paths_no_ids_and_no_raw_rows(client):
    jid = _job(client)
    client.post(f"/api/jobs/{jid}/photo", files={"photo": ("a.jpg", b"", "image/jpeg")})
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (10, 200, 10)).save(buf, format="JPEG")
    client.post(f"/api/jobs/{jid}/photo", files={"photo": ("a.jpg", buf.getvalue(), "image/jpeg")})
    client.post(f"/api/jobs/{jid}/advance")

    body = client.get(f"/api/jobs/{jid}/trace?view=human")
    assert body.status_code == 200
    payload = body.json()
    assert "rows" not in payload  # the raw log is a separate, deliberate request
    # Everything the page renders. The envelope's own job_id is the address of the
    # thing being asked for — it is already in the request URL and the browser's
    # address bar — so it is excluded here and never drawn on screen.
    assert_clean(json.dumps(payload["human"]))
    assert len(payload["human"]) >= 4


def test_the_raw_view_is_still_there_for_an_engineer(client):
    jid = _job(client)
    raw = client.get(f"/api/jobs/{jid}/trace?view=raw").json()
    assert "human" not in raw
    assert raw["rows"][0]["event"] == "start_job"
    # the default keeps both, for anything written before ?view existed
    both = client.get(f"/api/jobs/{jid}/trace").json()
    assert "rows" in both and "human" in both


def test_the_demo_marker_is_folded_into_the_opening_row():
    """The marker can only be written after the job exists, so the raw trace has it
    below the plan it started. On screen that would be a lie about the order."""
    rows = [
        {"at": "2026-09-11T14:00:00+00:00", "event": "start_job", "task": "Confirm the panel"},
        {"at": "2026-09-11T14:00:40+00:00", "event": "plan", "safety_class": "diy_ok",
         "steps": 9, "titles": ["Inspect the panel"]},
        {"at": "2026-09-11T14:00:40+00:00", "event": "demo", "task": "Confirm the panel",
         "photo_source": "packaged demo photo, not a camera"},
    ]
    human = humanize(rows)
    assert len(human) == 2  # the stray marker is gone, not duplicated
    assert human[0]["what"] == "Started the built-in demo job"
    assert "instead of a camera" in human[0]["why"]
    assert human[1]["actor"] == "Planner"


def test_a_real_job_keeps_its_own_opening_words():
    human = humanize([{"at": "2026-09-11T14:00:00+00:00", "event": "start_job", "task": "Swap a switch"}])
    assert human[0]["what"] == "Described the job and sent a photo of it"
    assert human[0]["why"] == ""


def test_a_lookup_with_nothing_to_look_up_does_not_read_as_a_fault():
    row = humanize_row(
        {"at": "2026-09-11T14:00:00+00:00", "event": "research", "status": "failed",
         "note": "no brand and model number in the task"}
    )
    assert row["result"] == "No lookup was possible"
    assert "no brand and model" in row["why"]
