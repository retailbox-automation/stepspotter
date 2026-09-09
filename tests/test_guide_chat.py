"""The Guide as a conversation: does it survive the process dying, and does the house
remember anything between jobs?

All offline. The model is a stub that raises if anything tries to call it, so a test
that accidentally reaches Bedrock fails loudly instead of passing slowly.
"""

import pytest
from strands import Agent
from strands.models import Model
from strands.session import FileSessionManager

from stepspotter import memory
from stepspotter.gate import StepGate
from stepspotter.guide import JobService, build_tools, job_id_in_session, run_tool_through_gate
from stepspotter.models import Plan, Step, StepVerdict

JOB_A = "job-20260909-111810-8501"
JOB_B = "job-20260909-120000-abcd"


class StubModel(Model):
    """A model that exists so an Agent can be built, and screams if it is used."""

    def get_config(self) -> dict:
        return {}

    def update_config(self, **kwargs) -> None:
        pass

    async def structured_output(self, *a, **k):
        raise AssertionError("this test must not call a model")

    async def stream(self, *a, **k):
        raise AssertionError("this test must not call a model")


def a_plan() -> Plan:
    return Plan(
        job_title="Connect two network cables",
        safety_class="diy_ok",
        tools_needed=["punch-down tool", "cable tester"],
        steps=[
            Step(id=1, title="Open the panel", action="Take the cover off.",
                 evidence_required="the open panel"),
            Step(id=2, title="Test the link", action="Plug in the tester.",
                 evidence_required="the tester showing 1 to 8"),
        ],
    )


@pytest.fixture
def job():
    """A started job with a fake planner and a photo-name-driven verifier."""
    service = JobService(
        plan_fn=lambda task, photo, model_id=None: a_plan(),
        verify_fn=lambda step, photo, model_id=None: StepVerdict(
            step_id=step.id, passed=photo == "pass.jpg", reason="the cover is off"
        ),
        locate_fn=lambda step, photo, model_id=None: [],
    )
    state = service.start("connect two cables", "start.jpg")
    return service, state, StepGate(state_for=service.get), build_tools(service)


def call(job, name, **tool_input):
    _service, _state, gate, tools = job
    return run_tool_through_gate(gate, tools, name, tool_input)


# -- session memory --------------------------------------------------------------


def test_a_new_process_resumes_the_same_conversation_and_the_same_job(tmp_path):
    """Kill the process mid-repair, come back later: same chat, same job.

    This is the Strands ``FileSessionManager`` doing the work — building a second
    Agent with the same session_id restores the message history, and the job id is
    read back out of it, so the resumed run knows which repair it is in the middle of.
    """
    storage = str(tmp_path / "sessions")
    first = Agent(
        model=StubModel(),
        session_manager=FileSessionManager(session_id="afternoon", storage_dir=storage),
    )
    message = {"role": "assistant", "content": [{"text": f"job_id={JOB_A}\nStep 1 of 8"}]}
    first.messages.append(message)
    first._session_manager.append_message(message, first)
    del first  # the terminal is closed, the process is gone

    later = Agent(
        model=StubModel(),
        session_manager=FileSessionManager(session_id="afternoon", storage_dir=storage),
    )
    assert len(later.messages) == 1
    assert job_id_in_session(later) == JOB_A

    other = Agent(
        model=StubModel(),
        session_manager=FileSessionManager(session_id="someone-else", storage_dir=storage),
    )
    assert other.messages == []  # sessions do not bleed into each other
    assert job_id_in_session(other) is None


def test_the_resumed_job_is_the_newest_one_in_the_conversation():
    """A session can outlive one repair; the current job is the last one started."""

    class Fake:
        messages = [
            {"role": "assistant", "content": [{"text": f"job_id={JOB_A} done"}]},
            {"role": "user", "content": [{"text": "next job please"}]},
            {
                "role": "user",
                "content": [
                    {"toolResult": {"content": [{"text": f"job_id={JOB_B}\nStep 1 of 3"}]}}
                ],
            },
        ]

    assert job_id_in_session(Fake()) == JOB_B


# -- house memory ----------------------------------------------------------------


def test_escalating_writes_the_job_into_house_memory(job):
    _service, state, _gate, _tools = job
    call(job, "submit_photo", job_id=state.job_id, photo_path="pass.jpg")
    call(job, "escalate", job_id=state.job_id, reason="the connector is warm and smells burnt")

    mem = memory.load()
    assert len(mem.jobs) == 1
    record = mem.jobs[0]
    assert record.job_id == state.job_id
    assert record.outcome == "escalated"
    assert record.escalated == "the connector is warm and smells burnt"
    assert record.completed == ["Open the panel"]  # only what a photo proved
    assert record.stopped_at == "Open the panel"
    assert mem.tools_owned == ["punch-down tool", "cable tester"]


def test_finishing_the_last_step_is_remembered_as_finished(job):
    _service, state, _gate, _tools = job
    for _ in range(state.total):
        call(job, "submit_photo", job_id=state.job_id, photo_path="pass.jpg")
        call(job, "advance_step", job_id=state.job_id, step_id=state.current + 1)

    assert state.done
    mem = memory.load()
    assert [j.outcome for j in mem.jobs] == ["finished"]
    assert mem.last_stop is None  # a finished job is not "where we stopped"


def test_the_planner_prompt_carries_what_the_house_already_has(job):
    """The prompt builder, which is the whole point of house memory."""
    _service, state, _gate, _tools = job
    call(job, "escalate", job_id=state.job_id, reason="the connector is warm and smells burnt")

    context = memory.planner_context()
    assert "You already have: punch-down tool, cable tester." in context
    assert "Last time you stopped at: Connect two network cables" in context
    assert "warm and smells burnt" in context

    prompt = memory.augment_task("hang a shelf")
    assert prompt.startswith("hang a shelf")
    assert "What I already know about this house:" in prompt
    assert "punch-down tool" in prompt

    # and the next job actually plans against that prompt, not the bare task
    seen = {}

    def capture(task, photo, model_id=None):
        seen["task"] = task
        return a_plan()

    later = JobService(plan_fn=capture, locate_fn=lambda *a, **k: [])
    later.start("hang a shelf", "shelf.jpg")
    assert "punch-down tool" in seen["task"]
    assert seen["task"].startswith("hang a shelf")


def test_an_empty_or_broken_memory_file_never_stops_a_repair():
    assert memory.load().jobs == []
    assert memory.planner_context() == ""
    assert memory.augment_task("hang a shelf") == "hang a shelf"

    memory.path().parent.mkdir(parents=True, exist_ok=True)
    memory.path().write_text("{not json at all")
    assert memory.load().jobs == []  # unreadable memory is no memory, not a crash


def test_house_memory_can_be_switched_off_for_a_run():
    """A demo or an eval must be able to plan from a clean slate."""
    memory.remember(
        JobService(plan_fn=lambda *a, **k: a_plan(), locate_fn=lambda *a, **k: []).start(
            "connect two cables", "start.jpg"
        ),
        "escalated",
        escalated="something scary",
    )
    seen = {}

    def capture(task, photo, model_id=None):
        seen["task"] = task
        return a_plan()

    JobService(plan_fn=capture, locate_fn=lambda *a, **k: [], use_house_memory=False).start(
        "hang a shelf", "shelf.jpg"
    )
    assert seen["task"] == "hang a shelf"
