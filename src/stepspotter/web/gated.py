"""The web's way into the gate — deliberately the long way round.

The browser must not be a back door. ``POST /api/jobs/{id}/advance`` does NOT call
``JobService.advance``; it calls the ``advance_step`` TOOL through a real Strands
``HookRegistry`` with the ``StepGate`` hook attached, which is the same dispatch the
Guide agent's tool loop performs (``guide.run_tool_through_gate``, already used by
``stepspotter next``). So the refusal a phone user sees is produced by the same
``event.cancel_tool`` line that stops the model, not by a second copy of the policy.

A hazard comes back as ``status == "interrupt"``: the SDK's HookRegistry catches the
InterruptException and returns the interrupts in a list, so it never reaches us as an
exception. Both shapes carry ``cancelled=True`` and the step does not move.
"""

from __future__ import annotations

from typing import Any

from stepspotter.gate import StepGate
from stepspotter.guide import run_tool_through_gate


def advance_via_gate(gate: StepGate, tools: list[Any], job_id: str, step_id: int) -> dict:
    """Ask to move on. Returns the tool-result dict: status / content / cancelled."""
    return run_tool_through_gate(
        gate, tools, "advance_step", {"job_id": job_id, "step_id": step_id}
    )


def escalate_via_tool(tools: list[Any], job_id: str, reason: str) -> dict:
    """Hand the job to a person, through the same tool the agent would call."""
    return run_tool_through_gate(None_gate(), tools, "escalate", {"job_id": job_id, "reason": reason})


def None_gate() -> StepGate:
    """A gate that governs nothing — ``escalate`` is not a gated tool.

    Wiring one anyway keeps every web tool call on the identical code path, so there
    is exactly one way a tool runs in this app.
    """
    return StepGate(state_for=lambda _job_id: None)
