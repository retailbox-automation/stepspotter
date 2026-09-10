"""The `stepspotter plan` printout, offline.

One thing is under test here: which URL the CLI calls the manual. The Researcher
writes the URL it actually downloaded onto the job's trace, and that is what the
printout must use. The older rule — "the first source ending in .pdf" — files a
manual served from a redirector under `video:` and shows the job as having no manual
at all, which is the opposite of what this feature is for.
"""

from __future__ import annotations

import argparse
import contextlib
import io

from stepspotter import cli, store
from stepspotter.models import JobState, Plan, Step

REDIRECTOR = "https://manuals.example.test/download?doc=epx3030&fmt=pdf"
VIDEO = "https://www.youtube.com/watch?v=abc123"


def _state(job_id: str, sources: list[str]) -> JobState:
    return JobState(
        job_id=job_id,
        task="assemble my Westinghouse ePX3030",
        start_photo="photo.jpg",
        plan=Plan(
            job_title="Assemble the pressure washer",
            safety_class="diy_ok",
            tools_needed=["Phillips-head screwdriver"],
            steps=[
                Step(
                    id=1,
                    title="Unpack the box",
                    action="Lay the parts out on the floor.",
                    evidence_required="every part out of the box",
                    source="manual p.10",
                )
            ],
            sources=sources,
        ),
    )


def _run_plan(monkeypatch, state: JobState) -> str:
    """Run cmd_plan against a service that plans nothing and calls no model."""

    class _Service:
        def start(self, task: str, photo: str) -> JobState:
            return state

    monkeypatch.setattr(cli, "_service_and_gate", lambda: (_Service(), None, []))
    args = argparse.Namespace(task=state.task, photo=state.start_photo)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli.cmd_plan(args) == 0
    return buf.getvalue()


def test_a_manual_without_a_pdf_extension_is_still_printed_as_the_manual(monkeypatch):
    """A redirector URL: no `.pdf` in the path, but the trace says it is the manual."""
    state = _state("job-redirect", [REDIRECTOR, VIDEO])
    store.trace(
        state.job_id,
        "research",
        status="found",
        product="Westinghouse ePX3030",
        manual_url=REDIRECTOR,
        pages=[10, 11],
        videos=[VIDEO],
    )

    out = _run_plan(monkeypatch, state)

    assert f"manual: {REDIRECTOR} (pages 10, 11)" in out
    assert f"video:  {VIDEO}" in out
    assert f"video:  {REDIRECTOR}" not in out  # it is not a video, whatever its suffix


def test_without_a_research_trace_the_pdf_suffix_still_names_the_manual(monkeypatch):
    """Older jobs (and runs with research switched off) keep the previous behaviour."""
    pdf = "https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf"
    out = _run_plan(monkeypatch, _state("job-no-trace", [pdf, VIDEO]))

    assert f"manual: {pdf}" in out
    assert "(pages" not in out  # no trace means no page numbers to claim
    assert f"video:  {VIDEO}" in out
