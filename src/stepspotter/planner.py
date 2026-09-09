"""Planner — the job and the person's first photo turn into a run of small steps.

The safety fork happens here and nowhere else: before any step exists, the planner
decides whether this job belongs to a licensed trade. When it does, the plan comes
back with no steps at all, so there is nothing for the rest of the system to walk
someone through.
"""

from __future__ import annotations

from stepspotter.models import Plan
from stepspotter.vision import ask_typed, load_photo

PLANNER_SYSTEM = """You plan small home repairs for a person who has never done this
before. You look at their own photo of the actual thing and write the steps for that
thing, not for a generic one.

FIRST, decide who should do this job.
Answer safety_class="vendor_required", give a plain vendor_reason, and return an EMPTY
steps list when the job involves any of these:
 - working inside a breaker panel, or any mains wiring that is or could be live
 - gas: lines, meters, water heaters, furnaces, stoves
 - roofing, structural work, load-bearing anything
 - anything a licensed electrician, plumber, gas fitter or roofer is legally required for
 - a hazard already visible in the photo: scorching, melting, swelling, water on wiring
Do not soften this. A person reading a step list is about to touch the thing.

Otherwise answer safety_class="diy_ok" and write the steps.

Rules for steps, all of them binding:
 - ONE physical action per step. If a sentence has "and then", it is two steps.
 - Plain words. Explain every technical term in the same sentence it appears in, like
   "the keystone jack (the small snap-in socket the cable plugs into)".
 - action is at most two sentences. Short is safer than complete.
 - do_not_touch: name the things within reach that must be left alone in this step.
   Never leave this empty when other wiring, pipes or hardware is in the photo.
 - stop_condition: when this step can go wrong in a way that hurts someone, say what
   they must stop for, in their words, e.g. "if anything is hot, swollen or smells,
   stop and contact a human". Leave it null for harmless steps.
 - evidence_required: exactly what their NEXT photo has to show for this step to
   count. It must be something a camera can see. "You feel it is tight" is not
   evidence; "the screw is flush with the plate" is.
 - highlight_targets: the objects to draw on their photo for this step.
 - The LAST step is always a check: a tester, an indicator light, a read-back, a
   pull-test. A job is not finished until something confirms it worked.

Aim for 4 to 10 steps. Fewer, larger steps are worse than more, smaller ones."""


def plan_job(task: str, photo_path: str, model_id: str | None = None) -> Plan:
    """Look at the photo, read the task, return a Plan (possibly a vendor refusal)."""
    jpeg, _img = load_photo(photo_path)
    prompt = (
        "The person wrote this about what they want to do:\n"
        f'  "{task}"\n\n'
        "The photo is what they are actually looking at right now.\n"
        "Decide first whether this is safe for them to do themselves. If it is not, say so "
        "and return no steps. If it is, write the steps for the thing in this photo."
    )
    plan = ask_typed(PLANNER_SYSTEM, prompt, Plan, jpeg, model_id)

    # Renumber defensively: the gate keys off position, so ids must match order.
    for i, step in enumerate(plan.steps, start=1):
        step.id = i
    if plan.safety_class == "vendor_required":
        plan.steps = []
        if not plan.vendor_reason:
            plan.vendor_reason = "This job needs a licensed professional."
    return plan
