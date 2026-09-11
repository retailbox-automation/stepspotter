"""The "Try a demo job" route, offline.

The model is faked, but *which photo was actually sent* is not: the fake checker
identifies the JPEG it was handed by comparing it with the three packaged photos, so
these tests fail if the wrong-photo button ever starts sending the right photo (or
either button stops sending anything at all). That is the one thing a canned demo
would get away with and this one must not.

What is deliberately NOT faked anywhere in here: the gate. "Next step" travels the
same Strands hook path a phone's does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from stepspotter.guide import JobService
from stepspotter.models import Plan, Step, StepVerdict
from stepspotter.web import demo
from stepspotter.web.app import create_app


def _signature(path: str | Path) -> tuple[int, ...]:
    """A tiny greyscale thumbprint — enough to tell three photos apart after re-encoding."""
    with Image.open(path) as im:
        return tuple(im.convert("L").resize((8, 8)).getdata())


def _which_photo(path: str) -> str:
    """Which of the packaged demo photos is this? Nearest thumbprint wins."""
    mine = _signature(path)
    return min(
        demo.DEMO_PHOTOS,
        key=lambda key: sum((a - b) ** 2 for a, b in zip(mine, _signature(demo.photo_path(key)))),
    )


class _Planner:
    """Records which photo it planned from.

    It records the identification, not the path: the app moves the start photo into
    the job's own folder straight after planning, so the path it was handed is gone
    by the time the test looks.
    """

    def __init__(self) -> None:
        self.photos: list[str] = []
        self.tasks: list[str] = []

    def __call__(self, task: str, photo: str, model_id=None) -> Plan:
        self.tasks.append(task)
        self.photos.append(_which_photo(photo))
        return Plan(
            job_title="Check the panel is safe to work in",
            safety_class="diy_ok",
            tools_needed=["a torch"],
            steps=[
                Step(
                    id=1,
                    title="Confirm the panel is low-voltage",
                    action="Open the panel door and look for mains wiring.",
                    do_not_touch=["the coax splitter"],
                    stop_condition="if you see a breaker or an orange mains wire, stop",
                    evidence_required="the open panel in one wide frame, no breakers in it",
                ),
                Step(
                    id=2,
                    title="Lay out the two runs",
                    action="Find the two Cat5e runs and free their ends.",
                    evidence_required="both cable ends free of the bundle",
                ),
            ],
        )


class _PhotoAwareVerifier:
    """Passes only the photo the demo calls "right". Decided from pixels, not order."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, step: Step, photo_path: str, model_id=None) -> StepVerdict:
        which = _which_photo(photo_path)
        self.seen.append(which)
        if which == "right":
            return StepVerdict(
                step_id=step.id, passed=True, reason="The whole panel is in frame and I see no breakers."
            )
        return StepVerdict(
            step_id=step.id,
            passed=False,
            reason="This is a close-up of a wall jack, not the panel the step asked for.",
        )


@pytest.fixture
def planner() -> _Planner:
    return _Planner()


@pytest.fixture
def verifier() -> _PhotoAwareVerifier:
    return _PhotoAwareVerifier()


@pytest.fixture
def client(isolated_data, planner, verifier):
    service = JobService(plan_fn=planner, verify_fn=verifier, locate_fn=lambda *a, **k: [])
    return TestClient(create_app(service))


# ---------------------------------------------------------------- the assets
def test_all_three_demo_photos_ship_inside_the_package():
    """They must be in the package: the container copies src/, not the repo root."""
    assert demo.available()
    for key in ("start", "wrong", "right"):
        path = demo.photo_path(key)
        assert path.is_file() and path.stat().st_size > 10_000
        assert "stepspotter/web/demo_photos" in path.as_posix()


def test_demo_info_tells_the_page_what_to_draw(client):
    info = client.get("/api/demo").json()
    assert info["available"] is True
    assert info["task"] == demo.DEMO_TASK
    assert info["buttons"]["wrong"]["label"] == "Send the wrong photo"
    assert info["buttons"]["right"]["label"] == "Send the right photo"


# ---------------------------------------------------------------- the run
def test_demo_job_plans_from_the_packaged_start_photo(client, planner):
    job = client.post("/api/demo/jobs").json()
    assert job["demo"] is True
    assert job["task"] == demo.DEMO_TASK
    assert planner.tasks == [demo.DEMO_TASK]
    assert planner.photos == ["start"]
    # and the substitution is on the record, not hidden
    rows = client.get(f"/api/jobs/{job['job_id']}/trace?view=raw").json()["rows"]
    assert any(r["event"] == "demo" for r in rows)


def test_wrong_photo_is_refused_then_right_photo_passes_the_gate(client, verifier):
    """The whole demo in one test: refuse, stay put, pass, move on."""
    job = client.post("/api/demo/jobs").json()
    jid = job["job_id"]

    # advancing before any photo: refused by the gate
    assert client.post(f"/api/jobs/{jid}/advance").json()["blocked"] is True

    wrong = client.post(f"/api/jobs/{jid}/demo-photo", data={"which": "wrong"}).json()
    assert wrong["verdict"]["passed"] is False
    assert verifier.seen == ["wrong"]
    blocked = client.post(f"/api/jobs/{jid}/advance").json()
    assert blocked["blocked"] is True and "did not pass" in blocked["reason"]
    assert blocked["job"]["step_number"] == 1  # nothing moved

    right = client.post(f"/api/jobs/{jid}/demo-photo", data={"which": "right"}).json()
    assert right["verdict"]["passed"] is True
    assert verifier.seen == ["wrong", "right"]
    moved = client.post(f"/api/jobs/{jid}/advance").json()
    assert moved["blocked"] is False and moved["job"]["step_number"] == 2

    # the demo flag survives a reload of the job, so the buttons come back
    assert client.get(f"/api/jobs/{jid}").json()["demo"] is True


def test_demo_photo_rejects_an_unknown_name(client):
    jid = client.post("/api/demo/jobs").json()["job_id"]
    r = client.post(f"/api/jobs/{jid}/demo-photo", data={"which": "sideways"})
    assert r.status_code == 400 and "sideways" in r.json()["detail"]


def test_a_normal_job_is_not_marked_as_a_demo(client):
    import io

    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (40, 60, 90)).save(buf, format="JPEG")
    job = client.post(
        "/api/jobs",
        data={"task": "swap a light switch"},
        files={"photo": ("mine.jpg", buf.getvalue(), "image/jpeg")},
    ).json()
    assert job["demo"] is False


def test_demo_button_hides_when_the_photos_are_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(demo, "PHOTOS_DIR", tmp_path / "gone")
    assert demo.available() is False
    assert client.get("/api/demo").json()["available"] is False
    assert client.post("/api/demo/jobs").status_code == 503
