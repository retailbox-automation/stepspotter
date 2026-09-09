"""The AgentCore front door, offline.

No model and no AWS call: ``handle()`` takes the agent builder as an argument, so
these tests stand a scripted agent in its place and check the only things this module
is responsible for — the payload it accepts, the answer shape it returns, the job id
it resolves for a caller who could not know one, and the fact that a photo arrives as
a real file on disk. The rules themselves (the gate, the verifier) are tested where
they live; one test here walks a refusal through the same ``HookRegistry`` the agent
loop uses, to prove this door does not route around it.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from stepspotter import store
from stepspotter.agentcore_entry import app, handle, invoke
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, run_tool_through_gate
from stepspotter.models import Box, Plan, Step, StepVerdict


def _photo_b64(size=(800, 600), color=(80, 120, 160)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def _plan(task: str, photo: str, model_id=None) -> Plan:
    return Plan(
        job_title="Two jacks and a test",
        safety_class="diy_ok",
        tools_needed=["punch-down tool"],
        steps=[
            Step(
                id=1,
                title="Punch down the first cable",
                action="Press the blue cable's wires into the jack.",
                evidence_required="all eight wires seated in the jack",
            ),
            Step(
                id=2,
                title="Test the link",
                action="Plug the tester in and read the lights.",
                evidence_required="the tester showing all pairs lit",
            ),
        ],
    )


class _Result:
    """The bits of an AgentResult this module reads."""

    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.message = {"role": "assistant", "content": [{"text": text}]}
        self.stop_reason = stop_reason

    def __str__(self) -> str:  # pragma: no cover - only the fallback path uses it
        return self.message["content"][0]["text"]


@pytest.fixture
def service() -> JobService:
    return JobService(
        plan_fn=_plan,
        verify_fn=lambda step, photo, model_id=None: StepVerdict(
            step_id=step.id, passed=False, reason="I cannot see the jack in this photo."
        ),
        locate_fn=lambda step, photo, model_id=None: [
            Box(label="jack", x0=0.3, y0=0.3, x1=0.6, y1=0.6, kind="act")
        ],
    )


def _builder(service: JobService, script, stop_reason: str = "end_turn"):
    """A stand-in for ``guide.build_agent`` that runs ``script(message, service, gate)``."""
    seen: list[str] = []

    def build(session_id=None, model_id=None, **kwargs):
        gate = StepGate(
            state_for=service.get,
            on_block=lambda reason, ti: store.trace(
                ti.get("job_id") or "unknown", "gate_block", reason=reason, tool_input=ti
            ),
        )

        def agent(message: str):
            seen.append(message)
            return _Result(script(message, service, gate), stop_reason)

        return agent, service, gate

    build.seen = seen  # type: ignore[attr-defined]
    build.sessions = []  # type: ignore[attr-defined]
    return build


def _boom(**kwargs):
    raise AssertionError("the agent must not be built for this payload")


# -- the payload -----------------------------------------------------------------


def test_empty_payload_never_reaches_the_model():
    out = handle({}, build=_boom)
    assert out["error"] == "empty_payload"
    assert out["job_id"] is None and out["trace_tail"] == []
    assert "photo" in out["text"]


def test_none_payload_is_the_same_as_an_empty_one():
    assert handle(None, build=_boom)["error"] == "empty_payload"


def test_a_broken_photo_is_a_sentence_not_a_crash():
    out = handle({"prompt": "here you go", "photo_b64": "this is not base64!!"}, build=_boom)
    assert out["error"] == "bad_photo"
    assert "send it again" in out["text"].lower()


# -- the turn --------------------------------------------------------------------


def test_start_resolves_the_job_id_the_caller_could_not_know(service):
    """``start_job`` mints the id inside the tool, so the answer has to carry it back."""

    def script(message, svc, gate):
        assert "their photo is saved at:" in message
        state = svc.start("connect two cables", message.split("saved at: ")[1].strip(" )"))
        return f"job_id={state.job_id}\nStep 1 of 2: Punch down the first cable"

    build = _builder(service, script)
    out = handle(
        {"task": "connect two cables and test", "photo_b64": _photo_b64()}, build=build
    )

    assert out["job_id"] and out["job_id"].startswith("job-")
    assert out["current_step"]["number"] == 1
    assert out["current_step"]["total"] == 2
    assert out["current_step"]["title"] == "Punch down the first cable"
    assert out["current_step"]["done"] is False
    events = [row["event"] for row in out["trace_tail"]]
    assert "start_job" in events and "plan" in events
    # no prompt in the payload, so the module supplied the one that starts a repair
    assert "step 1" in build.seen[0].lower()


def test_a_photo_arrives_as_a_real_upright_file(service):
    def script(message, svc, gate):
        return message  # echo, so the test can read the path the model was given

    out = handle({"prompt": "here it is", "photo_b64": _photo_b64((1200, 400))}, build=_builder(service, script))
    path = out["text"].split("saved at: ")[1].strip(" )")
    assert path.endswith(".jpg")
    with Image.open(path) as img:
        assert img.format == "JPEG" and max(img.size) <= 1600


def test_an_existing_job_is_carried_through_and_kept(service):
    state = service.start("connect two cables", "x.jpg")

    def script(message, svc, gate):
        assert f"(job_id: {state.job_id})" in message
        return "Not yet. Send me a photo of the seated wires."

    out = handle({"prompt": "done", "job_id": state.job_id}, build=_builder(service, script))
    assert out["job_id"] == state.job_id
    assert out["current_step"]["number"] == 1


def test_the_gate_refusal_comes_back_on_the_trace(service):
    """This door reaches the tools through the same hook registry the agent loop uses."""
    state = service.start("connect two cables", "x.jpg")

    def script(message, svc, gate):
        res = run_tool_through_gate(
            gate, build_tools(svc), "advance_step", {"job_id": state.job_id, "step_id": 1}
        )
        assert res["cancelled"] is True
        return str(res["content"])

    out = handle({"prompt": "next step please", "job_id": state.job_id}, build=_builder(service, script))
    assert "have not checked step 1" in out["text"]
    assert "gate_block" in [row["event"] for row in out["trace_tail"]]
    assert out["current_step"]["number"] == 1  # nobody moved


def test_a_hazard_stop_reason_is_surfaced(service):
    state = service.start("connect two cables", "x.jpg")
    build = _builder(service, lambda m, s, g: "", stop_reason="interrupt")
    out = handle({"prompt": "next", "job_id": state.job_id}, build=build)
    assert out["stop_reason"] == "interrupt"


def test_an_end_turn_carries_no_stop_reason(service):
    state = service.start("connect two cables", "x.jpg")
    out = handle({"prompt": "hi", "job_id": state.job_id}, build=_builder(service, lambda m, s, g: "hello"))
    assert "stop_reason" not in out


def test_a_model_failure_is_answered_not_raised(service):
    def script(message, svc, gate):
        raise RuntimeError("Bedrock said no")

    out = handle({"prompt": "hello"}, build=_builder(service, script))
    assert out["error"] == "agent_failed"
    assert "Bedrock said no" in out["text"]


def test_a_vendor_job_reports_itself_as_not_diy(service):
    service.plan_fn = lambda task, photo, model_id=None: Plan(
        job_title="Replace the main breaker",
        safety_class="vendor_required",
        vendor_reason="This is live service wiring.",
        steps=[],
    )

    def script(message, svc, gate):
        svc.start("replace the main breaker", "x.jpg")
        return "This one needs a licensed electrician."

    out = handle({"prompt": "replace my main breaker", "photo_b64": _photo_b64()}, build=_builder(service, script))
    assert out["current_step"]["diy"] is False
    assert out["current_step"]["vendor_reason"]


# -- the contract ----------------------------------------------------------------


def test_the_runtime_contract_routes_exist():
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/invocations" in paths and "/ping" in paths


def test_the_entrypoint_delegates_to_handle():
    assert invoke({}) == handle({}, build=_boom)
