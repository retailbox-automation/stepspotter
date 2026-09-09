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


# -- research reaching the planner -------------------------------------------------


def a_research() -> "Research":
    from stepspotter.research import Research, VideoHit

    return Research(
        product="Westinghouse ePX3030",
        status="found",
        manual_url="https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf",
        manual_path="/tmp-not-used/epx3030.pdf",
        manual_pages=[10, 11, 12],
        excerpt="[p.11]\nASSEMBLY\nFit the handle with two screws.",
        videos=[VideoHit(title="ePX3030 unboxing", url="https://www.youtube.com/watch?v=abc")],
    )


def test_the_manual_lookup_reaches_a_planner_that_asked_for_it():
    """A plan_fn with a research= parameter gets the manual; the trace records it."""
    seen = {}

    def capture(task, photo, model_id=None, research=None):
        seen["research"] = research
        return a_plan()

    service = JobService(
        plan_fn=capture,
        locate_fn=lambda *a, **k: [],
        research_fn=lambda task: a_research(),
        use_house_memory=False,
    )
    state = service.start("assemble my Westinghouse ePX3030 pressure washer", "start.jpg")

    assert seen["research"].manual_pages == [10, 11, 12]

    from stepspotter import store

    row = next(r for r in store.read_trace(state.job_id) if r["event"] == "research")
    assert row["status"] == "found"
    assert row["product"] == "Westinghouse ePX3030"
    assert row["pages"] == [10, 11, 12]


def test_a_planner_from_before_research_existed_is_still_called_correctly():
    """The old three-positional-argument plan_fn must not start blowing up."""
    calls = []

    def old_style(task, photo, model_id=None):
        calls.append((task, photo, model_id))
        return a_plan()

    service = JobService(
        plan_fn=old_style,
        locate_fn=lambda *a, **k: [],
        research_fn=lambda task: a_research(),
        use_house_memory=False,
    )
    service.start("assemble my Westinghouse ePX3030 pressure washer", "start.jpg")
    assert calls == [("assemble my Westinghouse ePX3030 pressure washer", "start.jpg", None)]


def test_research_can_be_switched_off_per_service():
    called = []
    service = JobService(
        plan_fn=lambda task, photo, model_id=None: a_plan(),
        locate_fn=lambda *a, **k: [],
        research_fn=lambda task: called.append(task) or a_research(),
        use_research=False,
    )
    service.start("assemble my Westinghouse ePX3030 pressure washer", "start.jpg")
    assert called == []


def test_a_broken_lookup_never_stops_the_repair():
    def boom(task):
        raise RuntimeError("the search engine fell over")

    service = JobService(
        plan_fn=lambda task, photo, model_id=None, research=None: a_plan(),
        locate_fn=lambda *a, **k: [],
        research_fn=boom,
    )
    state = service.start("assemble my Westinghouse ePX3030 pressure washer", "start.jpg")
    assert state.total == 2  # the plan still happened

    from stepspotter import store

    row = next(r for r in store.read_trace(state.job_id) if r["event"] == "research")
    assert row["status"] == "failed"


def test_the_find_manual_tool_answers_in_plain_words(job):
    _service, _state, _gate, _tools = job
    service = JobService(
        plan_fn=lambda task, photo, model_id=None: a_plan(),
        locate_fn=lambda *a, **k: [],
        research_fn=lambda product: a_research(),
    )
    tools = build_tools(service)
    gate = StepGate(state_for=service.get)
    res = run_tool_through_gate(gate, tools, "find_manual", {"product": "Westinghouse ePX3030"})

    assert res["status"] == "success"
    assert "ePX3030_manual_web.pdf" in res["content"]
    assert "10, 11, 12" in res["content"]
    assert "youtube.com" in res["content"]


def test_a_step_source_survives_being_saved_and_loaded():
    """Step.source and Plan.sources are part of the job on disk, not just the prompt."""
    from stepspotter import store
    from stepspotter.models import JobState

    plan = a_plan()
    plan.sources = ["https://example.test/manual.pdf"]
    plan.steps[0].source = "manual p.11 FIG.7"
    state = JobState(job_id="job-20260909-090000-aaaa", task="t", start_photo="p.jpg", plan=plan)
    store.save(state)

    back = store.load(state.job_id)
    assert back.plan.steps[0].source == "manual p.11 FIG.7"
    assert back.plan.steps[1].source is None
    assert back.plan.sources == ["https://example.test/manual.pdf"]
