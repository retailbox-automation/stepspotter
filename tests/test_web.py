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
            ),
            Step(
                id=2,
                title="Test the link",
                action="Plug the tester into both ends and read the lights.",
                evidence_required="the tester showing all pairs lit",
            ),
        ],
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
