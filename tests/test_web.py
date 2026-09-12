"""The web face, end to end, offline.

No model is called: the JobService gets fake plan/verify/locate functions, so this
test is about the wiring — that the browser's "Next step" really does travel through
the Strands gate hook, and is refused there when the photo did not pass.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from stepspotter.guide import JobService
from stepspotter.models import Box, Plan, Step, StepVerdict
from stepspotter.web.app import create_app


def _photo_bytes(size=(900, 600), color=(90, 110, 140)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _plan(task: str, photo: str, model_id=None) -> Plan:
    return Plan(
        job_title="Two jacks and a test",
        safety_class="diy_ok",
        tools_needed=["punch-down tool", "cable tester"],
        steps=[
            Step(
                id=1,
                title="Punch down the first cable",
                action="Press the blue cable's wires into the jack with the punch-down tool.",
                do_not_touch=["the grey coax splitter"],
                stop_condition="if anything is hot or smells burnt, stop and get a person",
                evidence_required="all eight wires seated in the jack, no loose ends",
                highlight_targets=["blue cable", "keystone jack"],
                source="manual p.11 FIG.7",
            ),
            Step(
                id=2,
                title="Test the link",
                action="Plug the tester into both ends and read the lights.",
                evidence_required="the tester showing all pairs lit",
            ),
        ],
        sources=["https://example.test/manual.pdf", "https://www.youtube.com/watch?v=abc"],
    )


class _Verifier:
    """Fails the first photo of each step, passes the next. Deterministic, offline."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    def __call__(self, step: Step, photo_path: str, model_id=None) -> StepVerdict:
        first = step.id not in self.seen
        self.seen.append(step.id)
        if first:
            return StepVerdict(step_id=step.id, passed=False, reason="I cannot see the jack in this photo.")
        return StepVerdict(step_id=step.id, passed=True, reason="The wires are seated in the jack.")


@pytest.fixture
def client(isolated_data):
    service = JobService(
        plan_fn=_plan,
        verify_fn=_Verifier(),
        locate_fn=lambda step, photo, model_id=None: [
            Box(label="keystone jack", x0=0.3, y0=0.3, x1=0.6, y1=0.6, kind="act")
        ],
    )
    return TestClient(create_app(service))


def _new_job(client) -> dict:
    r = client.post(
        "/api/jobs",
        data={"task": "connect two cables and test"},
        files={"photo": ("panel.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True


def test_page_serves_and_mentions_the_gate_words(client):
    body = client.get("/").text
    assert "StepSpotter" in body and "I did it — take photo" in body


def test_full_run_photo_gate_advance_escalate(client):
    job = _new_job(client)
    jid = job["job_id"]
    assert job["total"] == 2 and job["step_number"] == 1
    assert job["step"]["do_not_touch"] == ["the grey coax splitter"]

    # the card renders on demand from the person's own photo
    card = client.get(f"/api/jobs/{jid}/card")
    assert card.status_code == 200 and card.headers["content-type"] == "image/jpeg"
    assert len(card.content) > 2000

    # advancing before any photo is refused BY THE GATE, not by the UI
    blocked = client.post(f"/api/jobs/{jid}/advance").json()
    assert blocked["blocked"] is True
    assert "have not checked" in blocked["reason"]
    assert blocked["job"]["step_number"] == 1  # nothing moved

    # a photo that does not prove it -> fail, and advancing is still refused
    r = client.post(f"/api/jobs/{jid}/photo", files={"photo": ("try.jpg", _photo_bytes(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["verdict"]["passed"] is False
    blocked2 = client.post(f"/api/jobs/{jid}/advance").json()
    assert blocked2["blocked"] is True and "did not pass" in blocked2["reason"]
    assert blocked2["job"]["step_number"] == 1

    # the evidence photo is served back for the verdict panel
    assert client.get(f"/api/jobs/{jid}/evidence/1").status_code == 200

    # a passing photo -> advance goes through
    r = client.post(f"/api/jobs/{jid}/photo", files={"photo": ("done.jpg", _photo_bytes(), "image/jpeg")})
    assert r.json()["verdict"]["passed"] is True
    ok = client.post(f"/api/jobs/{jid}/advance").json()
    assert ok["blocked"] is False and ok["job"]["step_number"] == 2

    # last step, and the job reports itself finished
    client.post(f"/api/jobs/{jid}/photo", files={"photo": ("a.jpg", _photo_bytes(), "image/jpeg")})
    client.post(f"/api/jobs/{jid}/photo", files={"photo": ("b.jpg", _photo_bytes(), "image/jpeg")})
    end = client.post(f"/api/jobs/{jid}/advance").json()
    assert end["blocked"] is False and end["job"]["done"] is True

    # the trace holds the whole story, refusals included
    rows = client.get(f"/api/jobs/{jid}/trace").json()["rows"]
    events = [r_["event"] for r_ in rows]
    assert "plan" in events and "verdict" in events and "gate_block" in events and "advance" in events

    # stop hands it to a person
    esc = client.post(f"/api/jobs/{jid}/escalate", data={"reason": "smells hot"}).json()
    assert esc["escalated"] is True and esc["job"]["escalated"] is True


def test_hazard_photo_stops_the_run_as_an_interrupt(isolated_data):
    def hazard(step: Step, photo_path: str, model_id=None) -> StepVerdict:
        return StepVerdict(
            step_id=step.id, passed=True, stop=True, reason="The plastic around the jack is scorched."
        )

    service = JobService(plan_fn=_plan, verify_fn=hazard, locate_fn=lambda *a, **k: [])
    client = TestClient(create_app(service))
    jid = _new_job(client)["job_id"]
    client.post(f"/api/jobs/{jid}/photo", files={"photo": ("hot.jpg", _photo_bytes(), "image/jpeg")})
    res = client.post(f"/api/jobs/{jid}/advance").json()
    assert res["blocked"] is True and res["hazard"] is True
    assert "unsafe" in res["reason"] or "STOP" in res["reason"]
    assert res["job"]["step_number"] == 1


def test_vendor_required_returns_no_steps(isolated_data):
    def vendor(task: str, photo: str, model_id=None) -> Plan:
        return Plan(
            job_title="Breaker panel rewire",
            safety_class="vendor_required",
            vendor_reason="This is mains wiring inside a breaker panel.",
        )

    client = TestClient(create_app(JobService(plan_fn=vendor, verify_fn=lambda *a, **k: None, locate_fn=lambda *a, **k: [])))
    job = _new_job(client)
    assert job["safety_class"] == "vendor_required" and job["total"] == 0
    assert job["step"] is None and job["card_url"] is None


def test_upload_is_rotated_upright_and_downscaled(isolated_data, tmp_path):
    from stepspotter.web.photos import save_upload

    big = Image.new("RGB", (4032, 3024), (200, 30, 30))
    buf = io.BytesIO()
    big.save(buf, format="JPEG", exif=Image.Exif())
    out = save_upload(buf.getvalue(), tmp_path / "u.jpg")
    assert max(Image.open(out).size) == 1600


def test_the_page_is_told_where_the_step_came_from(client):
    """The manual link and the step's page live in the JSON the page renders from."""
    job = _new_job(client)

    assert job["step"]["source"] == "manual p.11 FIG.7"
    assert job["sources"] == [
        "https://example.test/manual.pdf",
        "https://www.youtube.com/watch?v=abc",
    ]
    # and the page has somewhere to put both
    body = client.get("/").text
    assert 'id="stepSource"' in body and 'id="manualLine"' in body


# ------------------------------------------------------- the first screen
# A judge opens "/" with ten minutes, no panel in front of them and no idea what this
# is. Before this, that screen was a heading and two file inputs — no explanation, no
# link to the code, no way in without a photo of a low-voltage panel.
def test_the_first_screen_says_what_this_is(client):
    body = client.get("/").text
    assert "one step at a time" in body
    assert "The next step stays locked" in body
    assert "a photo proves the last" in body


def test_the_first_screen_links_to_the_repository(client):
    from stepspotter.web.page import REPO_URL

    assert REPO_URL == "https://github.com/retailbox-automation/stepspotter"
    body = client.get("/").text
    assert f'href="{REPO_URL}"' in body and "Source code on GitHub" in body


def test_the_video_link_renders_only_once_there_is_a_video():
    """An empty constant must leave no dead link behind — a broken promise is worse."""
    from stepspotter.web.page import render_page

    assert "Watch the 3-minute demo" not in render_page(video_url="")
    with_video = render_page(video_url="https://youtu.be/abc123")
    assert 'href="https://youtu.be/abc123"' in with_video
    assert "Watch the 3-minute demo" in with_video


def test_the_first_screen_offers_the_demo_and_the_waiting_stages(client):
    body = client.get("/").text
    assert "Try a demo job" in body
    assert "Send the wrong photo" in body and "Send the right photo" in body
    # the stage lines that replace 35 seconds of the word "Working…"
    for stage in ("Looking at your photo…", "Writing the steps…", "Checking your photo…"):
        assert stage in body
    assert "Usually 20–40 seconds" in body


def test_a_long_manual_url_cannot_push_the_page_sideways(client):
    """Overflow fix for a 390px phone: the URL breaks, it does not set the width."""
    body = client.get("/").text
    assert "overflow-wrap:anywhere" in body
    assert "#manualLine a{display:inline-block;max-width:100%" in body


# ------------------------------------------------- the refusal, from a browser
# The gate is the point of this project, and until now a browser could not reach it:
# "Next step" is hidden while no photo has passed, so the only way to see a refusal was
# to read the tests. These cover the button that asks anyway — and the promise that the
# same ask, once a photo HAS passed, still moves the step exactly as it always did.
def test_the_step_card_offers_a_visible_way_to_ask_without_a_photo(client):
    body = client.get("/").text
    assert 'id="skipBtn"' in body and "Skip the photo and move on" in body
    # and it says what will happen, rather than looking like a shortcut that works
    assert "cancels the call in code" in body
    assert 'id="skipCap"' in body


def test_asking_to_skip_the_photo_is_refused_and_names_the_photo_it_wants(client):
    job = _new_job(client)
    jid = job["job_id"]

    res = client.post(f"/api/jobs/{jid}/advance", data={"intent": "skip"})
    assert res.status_code == 200
    body = res.json()

    assert body["blocked"] is True and body["hazard"] is False
    assert "have not checked" in body["reason"]          # the refusal, in words
    assert body["job"]["step_number"] == 1               # and nothing moved
    # the page draws "the photo it is waiting for" from this field
    assert body["job"]["step"]["evidence_required"] == "all eight wires seated in the jack, no loose ends"

    # both halves of the story are on the record: the ask, then the code that refused it
    events = [r["event"] for r in client.get(f"/api/jobs/{jid}/trace").json()["rows"]]
    assert events.index("skip_attempt") < events.index("gate_block")

    # and the readable trace says so without leaking a path or a job id
    human = client.get(f"/api/jobs/{jid}/trace?view=human").json()["human"]
    asked = [r for r in human if r["what"] == "Asked to move on without sending a photo"]
    assert len(asked) == 1 and asked[0]["actor"] == "You"
    assert any(r["actor"].startswith("Gate") for r in human)
    text = " ".join(f"{r['actor']} {r['what']} {r['result']} {r['why']}" for r in human)
    assert "/" not in text.replace("and/or", "") and ".jpg" not in text


def test_the_same_ask_after_a_passing_photo_still_moves_the_step(client):
    """intent only labels the ask. The gate never sees it, so a pass still advances."""
    jid = _new_job(client)["job_id"]
    client.post(f"/api/jobs/{jid}/photo", files={"photo": ("a.jpg", _photo_bytes(), "image/jpeg")})
    passed = client.post(f"/api/jobs/{jid}/photo", files={"photo": ("b.jpg", _photo_bytes(), "image/jpeg")})
    assert passed.json()["verdict"]["passed"] is True

    ok = client.post(f"/api/jobs/{jid}/advance", data={"intent": "skip"}).json()
    assert ok["blocked"] is False and ok["job"]["step_number"] == 2


def test_the_skip_ask_works_on_the_demo_job_too(isolated_data):
    """A judge with no camera must be able to reach the refusal from the demo flow."""
    from stepspotter.web import demo as demo_mod

    service = JobService(plan_fn=_plan, verify_fn=_Verifier(), locate_fn=lambda *a, **k: [])
    client = TestClient(create_app(service))
    if not demo_mod.available():
        pytest.skip("demo photos are not installed in this checkout")

    jid = client.post("/api/demo/jobs").json()["job_id"]
    blocked = client.post(f"/api/jobs/{jid}/advance", data={"intent": "skip"}).json()
    assert blocked["blocked"] is True and blocked["job"]["step_number"] == 1
