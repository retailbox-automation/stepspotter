"""Form A — the chat master, end to end, offline.

No model is called. What these tests are about is the thing a prototype is easiest to
fake: that the feed is really a projection of the job's trace, and that the chat is a
face on the SAME gate — not a second, looser path to the next step.

The two that matter most:
  * test_refusal_stays_in_the_feed_after_a_reload — a rebuilt feed still carries the
    refusal. If the block only ever lived in the browser, the demo would lose its
    point on any reload.
  * test_a_question_cannot_move_the_job — asking is not advancing.
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
                source="manual p.11",
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
            return StepVerdict(
                step_id=step.id, passed=False, reason="I cannot see the jack in this photo."
            )
        return StepVerdict(step_id=step.id, passed=True, reason="The wires are seated in the jack.")


def _client(plan_fn=_plan, verify_fn=None, answer_fn=None) -> TestClient:
    service = JobService(
        plan_fn=plan_fn,
        verify_fn=verify_fn or _Verifier(),
        locate_fn=lambda step, photo, model_id=None: [
            Box(label="keystone jack", x0=0.3, y0=0.3, x1=0.6, y1=0.6, kind="act")
        ],
    )
    return TestClient(create_app(service, answer_fn=answer_fn))


@pytest.fixture
def client(isolated_data):
    return _client()


def _new_job(client) -> str:
    r = client.post(
        "/api/jobs",
        data={"task": "connect two cables and test"},
        files={"photo": ("panel.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def _send(client, jid: str):
    return client.post(
        f"/api/jobs/{jid}/photo", files={"photo": ("try.jpg", _photo_bytes(), "image/jpeg")}
    )


def _feed(client, jid: str) -> dict:
    r = client.get(f"/api/jobs/{jid}/feed")
    assert r.status_code == 200, r.text
    return r.json()


def _kinds(payload: dict) -> list[str]:
    return [m["kind"] for m in payload["messages"]]


# --------------------------------------------------------------------------- page
def test_chat_page_is_its_own_form_and_keeps_the_camera(client):
    body = client.get("/chat").text
    assert 'capture="environment"' in body  # the rear camera, not a file picker
    assert "Ask a question about this step" in body  # form A's whole point
    assert "screen-step" not in body  # form B's screen stack is not in here
    assert client.get("/steps").status_code == 200  # and form B still serves


# The decision this branch exists to offer: what does a phone land on. Form A answers
# "/" now, and form B is not retired — it keeps a path of its own so the two can be
# opened side by side before anything is thrown away.
def test_the_chat_master_is_what_a_phone_lands_on(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.text == client.get("/chat").text  # one page, two ways in
    assert "Ask a question about this step" in root.text


def test_form_b_is_still_whole_at_its_own_path(client):
    steps = client.get("/steps")
    assert steps.status_code == 200
    assert steps.text == client.get("/jobs").text
    assert "I did it — take photo" in steps.text  # the screen stack, intact
    assert steps.text != client.get("/").text  # and it is not the chat


# --------------------------------------------------------------------------- demo
# A judge has ten minutes and no low-voltage panel in front of them. Without this the
# chat's first screen is a dead end for everyone who cannot photograph a panel.
def test_the_chat_offers_the_demo_and_takes_its_words_from_the_server(client):
    body = client.get("/chat").text
    assert 'id="demoBtn"' in body and "Try a demo job" in body
    # the labels/captions of the two photos are fetched, never written into the page
    assert "DEMO.buttons.wrong.label" in body and "DEMO.buttons.right.caption" in body
    assert "/api/demo" in body and "/demo-photo" in body
    # and the offer is hidden unless the install actually has the photos
    assert 'classList.toggle("hide", !on)' in body


def test_the_demo_runs_the_whole_refuse_then_pass_through_the_chat_feed(client):
    """The same walk a judge makes: demo job, wrong photo refused, right photo passes.

    Every call here is the one the page makes. Nothing about the verdicts is faked by
    the page: they arrive as feed messages built from the job's trace.
    """
    jid = client.post("/api/demo/jobs").json()["job_id"]

    opened = _feed(client, jid)
    assert opened["job"]["demo"] is True  # this is what swaps the camera for two buttons
    assert _kinds(opened) [:2] == ["task", "photo"]  # the packaged photo opens the feed
    assert opened["composer"]["action"] == "photo"

    wrong = client.post(f"/api/jobs/{jid}/demo-photo", data={"which": "wrong"})
    assert wrong.status_code == 200
    refused = [m for m in _feed(client, jid)["messages"] if m["kind"] == "verdict"][-1]
    assert refused["passed"] is False

    right = client.post(f"/api/jobs/{jid}/demo-photo", data={"which": "right"})
    assert right.status_code == 200
    feed = _feed(client, jid)
    assert [m for m in feed["messages"] if m["kind"] == "verdict"][-1]["passed"] is True
    assert feed["composer"]["action"] == "advance"

    # the refusal is still above the pass, which is the whole reason to show a judge this
    verdicts = [m["passed"] for m in feed["messages"] if m["kind"] == "verdict"]
    assert verdicts == [False, True]

    client.post(f"/api/jobs/{jid}/advance")
    steps = [m for m in _feed(client, jid)["messages"] if m["kind"] == "step"]
    assert [m["step_number"] for m in steps] == [1, 2]


def test_a_demo_photo_the_server_does_not_ship_is_refused_not_guessed(client):
    jid = client.post("/api/demo/jobs").json()["job_id"]
    assert client.post(f"/api/jobs/{jid}/demo-photo", data={"which": "sideways"}).status_code == 400


def test_the_page_lets_someone_try_to_skip_so_the_code_can_refuse(client):
    """If the UI hid this, the browser would be the gate and the refusal unseen."""
    body = client.get("/chat").text
    assert "It is fine — move on anyway" in body
    assert 'data-act="advance"' in body and 'data-act="escalate"' in body


# --------------------------------------------------------------------------- feed
def test_feed_opens_with_the_task_the_photo_the_plan_and_one_step(client):
    jid = _new_job(client)
    payload = _feed(client, jid)
    assert _kinds(payload)[:4] == ["task", "photo", "plan", "step"]

    step = payload["messages"][3]
    assert step["step_number"] == 1 and step["total"] == 2
    # the reference card format: one action, what not to touch, the stop, the evidence
    assert step["do_not_touch"] == ["the grey coax splitter"]
    assert step["stop_condition"].startswith("if anything is hot")
    assert step["evidence_required"] == "all eight wires seated in the jack, no loose ends"
    assert step["source"] == "manual p.11"
    assert step["card_url"] == f"/api/jobs/{jid}/card/1"
    assert payload["composer"] == {
        "action": "photo",
        "label": "I did it — take photo",
        "can_ask": True,
    }


def test_refusal_stays_in_the_feed_after_a_reload(client):
    """A fresh GET /feed — what a reloaded phone does — still carries the refusal."""
    jid = _new_job(client)
    assert client.post(f"/api/jobs/{jid}/advance").json()["blocked"] is True  # no photo yet
    _send(client, jid)  # first photo of step 1 fails
    assert client.post(f"/api/jobs/{jid}/advance").json()["blocked"] is True

    kinds = _kinds(_feed(client, jid))
    assert kinds.count("block") == 2
    blocks = [m for m in _feed(client, jid)["messages"] if m["kind"] == "block"]
    assert "have not checked" in blocks[0]["reason"]
    assert "did not pass" in blocks[1]["reason"]
    assert all(b["hazard"] is False for b in blocks)
    # and the refusal sits ABOVE the verdict that caused the retry, not instead of it
    assert kinds.index("block") < kinds.index("verdict")


def test_a_pass_opens_the_next_step_and_the_feed_shows_both(client):
    jid = _new_job(client)
    _send(client, jid)  # fail
    _send(client, jid)  # pass
    assert client.post(f"/api/jobs/{jid}/advance").json()["blocked"] is False

    payload = _feed(client, jid)
    steps = [m for m in payload["messages"] if m["kind"] == "step"]
    assert [s["step_number"] for s in steps] == [1, 2]
    verdicts = [m for m in payload["messages"] if m["kind"] == "verdict"]
    assert [v["passed"] for v in verdicts] == [False, True]
    assert payload["composer"]["action"] == "photo"  # step 2 needs its own photo


def test_composer_names_the_one_next_action_at_every_state(client):
    jid = _new_job(client)
    assert _feed(client, jid)["composer"]["label"] == "I did it — take photo"
    _send(client, jid)
    assert _feed(client, jid)["composer"]["label"] == "Try again — take photo"
    _send(client, jid)
    assert _feed(client, jid)["composer"] == {
        "action": "advance",
        "label": "Next step",
        "can_ask": True,
    }
    client.post(f"/api/jobs/{jid}/advance")
    _send(client, jid)
    _send(client, jid)
    client.post(f"/api/jobs/{jid}/advance")
    done = _feed(client, jid)
    assert done["job"]["done"] is True
    assert done["composer"]["action"] == "restart"
    assert _kinds(done)[-1] == "done"


def test_a_hazard_photo_shows_as_a_stop_in_the_feed(isolated_data):
    def hazard(step: Step, photo_path: str, model_id=None) -> StepVerdict:
        return StepVerdict(
            step_id=step.id,
            passed=True,
            stop=True,
            reason="The plastic around the jack is scorched.",
        )

    client = _client(verify_fn=hazard)
    jid = _new_job(client)
    _send(client, jid)
    assert _feed(client, jid)["composer"]["action"] == "escalate"

    res = client.post(f"/api/jobs/{jid}/advance").json()
    assert res["blocked"] is True and res["hazard"] is True
    payload = _feed(client, jid)  # the interrupt is on the record, so it survives a reload
    stops = [m for m in payload["messages"] if m["kind"] == "block" and m["hazard"]]
    assert len(stops) == 1 and "unsafe" in stops[0]["reason"]
    assert payload["job"]["step_number"] == 1  # nothing moved


def test_a_question_cannot_move_the_job(isolated_data):
    asked: list[str] = []

    def answer(state, question: str) -> str:
        asked.append(question)
        return "A keystone is the little snap-in socket the cable ends in."

    client = _client(answer_fn=answer)
    jid = _new_job(client)
    r = client.post(f"/api/jobs/{jid}/ask", data={"question": "what is a keystone?"})
    assert r.status_code == 200 and r.json()["reached_model"] is True
    assert asked == ["what is a keystone?"]

    payload = _feed(client, jid)
    texts = [m for m in payload["messages"] if m["kind"] == "text"]
    assert [t["from"] for t in texts] == ["you", "agent"]
    assert "snap-in socket" in texts[1]["text"]
    assert payload["job"]["step_number"] == 1  # asking is not advancing
    assert payload["composer"]["action"] == "photo"
    # and the gate is untouched by the question
    assert client.post(f"/api/jobs/{jid}/advance").json()["blocked"] is True


def test_an_unreachable_model_is_a_message_not_a_crash(isolated_data):
    def boom(state, question: str) -> str:
        raise RuntimeError("no AWS credentials found")

    client = _client(answer_fn=boom)
    jid = _new_job(client)
    r = client.post(f"/api/jobs/{jid}/ask", data={"question": "is this the right cable?"})
    assert r.status_code == 200
    assert r.json()["reached_model"] is False
    assert "could not reach" in r.json()["answer"]
    events = [row["event"] for row in client.get(f"/api/jobs/{jid}/trace").json()["rows"]]
    assert "ask_failed" in events  # the failure is on the record, not swallowed


def test_each_step_message_keeps_its_own_card_picture(client):
    jid = _new_job(client)
    assert client.get(f"/api/jobs/{jid}/card/1").status_code == 200  # drawn on demand
    assert client.get(f"/api/jobs/{jid}/card/2").status_code == 404  # not reached yet
    _send(client, jid)
    _send(client, jid)
    client.post(f"/api/jobs/{jid}/advance")
    old = client.get(f"/api/jobs/{jid}/card/1")  # still served, from the cache
    assert old.status_code == 200 and old.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/jobs/{jid}/card/2").status_code == 200
    assert client.get(f"/api/jobs/{jid}/start-photo").status_code == 200


def test_a_vendor_job_gets_a_refusal_and_no_steps(isolated_data):
    def vendor(task: str, photo: str, model_id=None) -> Plan:
        return Plan(
            job_title="Breaker panel rewire",
            safety_class="vendor_required",
            vendor_reason="This is mains wiring inside a breaker panel.",
        )

    client = _client(plan_fn=vendor, verify_fn=lambda *a, **k: None)
    jid = _new_job(client)
    payload = _feed(client, jid)
    assert _kinds(payload) == ["task", "photo", "vendor"]
    assert "mains wiring" in payload["messages"][2]["reason"]
    assert payload["composer"] == {
        "action": "restart",
        "label": "Start something else",
        "can_ask": False,
    }


def test_the_card_is_the_marked_photo_and_the_words_are_html(client):
    """The chat writes the step as text, so the picture must not repeat it.

    ``render_marked_photo`` (1200px wide, boxes only) vs ``render_card`` (the 1100px
    printed sheet with every sentence baked in): the widths tell them apart, and the
    legend arriving as data is what lets the page write the badge labels itself.
    """
    from PIL import Image as _Image

    from stepspotter import store

    jid = _new_job(client)
    payload = _feed(client, jid)
    step = payload["messages"][3]
    assert step["legend"] == [{"n": 1, "label": "keystone jack", "kind": "act"}]

    r = client.get(f"/api/jobs/{jid}/card/1")
    assert r.status_code == 200
    assert _Image.open(io.BytesIO(r.content)).width == 1200  # the photo, not the sheet
    assert (store.cards_dir(jid) / "step-01-photo.jpg").is_file()


def test_the_way_out_is_always_on_the_card(client):
    """A step whose planner wrote no stop condition must still offer a way to stop.

    Asserted against the page source because the row is drawn in the browser: the
    guard must not exist at all, and a fallback wording must ship with the page.
    """
    body = client.get("/chat").text
    assert "if(m.stop_condition)" not in body  # the stop row is unconditional
    assert "or you are not sure what " in body  # the fallback wording ships
    assert body.count('data-act="escalate"') == 1

    # and the plan this client serves has a step with no stop condition of its own
    jid = _new_job(client)
    _send(client, jid)
    _send(client, jid)
    client.post(f"/api/jobs/{jid}/advance")
    step2 = [m for m in _feed(client, jid)["messages"] if m["kind"] == "step"][-1]
    assert step2["step_number"] == 2 and step2["stop_condition"] is None
