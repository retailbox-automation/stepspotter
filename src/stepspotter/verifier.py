"""Verifier — does this photo actually prove the step was done?

This is the half of the system that earned its keep in spike A: 8/8 correct, and
critically 4/4 on claims about things that were not in the frame at all. It refused
and named the absence ("no circuit breaker is visible in this photo") instead of
inventing one. The system prompt line that produces that behaviour is the one about
returning passed=false when the subject is not visible — do not soften it.

No confidence score is returned or used. Spike A ran the same call twice and got
0.82 then 0.20 while the boolean stayed put; a threshold on that number would flip
a person's route between two identical runs.
"""

from __future__ import annotations

from stepspotter.models import Step, StepVerdict
from stepspotter.vision import ask_typed, load_photo

VERIFIER_SYSTEM = """You check whether a photo proves that one repair step was done.
You are strict, and you are on the side of the person's safety, not their impatience.

passed=true ONLY when the photo itself clearly shows what was asked for.
passed=false, saying the evidence is not visible, when:
 - the thing being checked is not in the frame
 - it is out of focus, too dark, or hidden behind something
 - the photo shows a different object or a different place
 - you are unsure
Never assume anything outside the frame. Never accept the person's word that it is
done: the photo is the only thing you are allowed to believe. If they said they did
it and the photo does not show it, that is passed=false.

Set stop=true, on top of your pass/fail answer, if the photo shows a hazard: heat
damage, scorching, melted plastic, a swollen battery, water on wiring, smoke, or
bare live conductors. A hazard stops the whole job for a person to look at.

reason is ONE short sentence in plain words, naming what you can or cannot see. The
person reads it directly, so write it to them.

Boxes are normalized [0,1] with (0,0) at the TOP-LEFT. Box only what you can see."""


def verify_step(step: Step, photo_path: str, model_id: str | None = None) -> StepVerdict:
    """Judge one photo against one step's evidence requirement."""
    jpeg, _img = load_photo(photo_path)
    prompt = (
        f"The person was asked to do step {step.id}: {step.title}\n"
        f"  What they had to do: {step.action}\n"
        f"  What this photo must show: {step.evidence_required}\n\n"
        "Does this photo prove that step is done? Answer passed=true only if the photo "
        "clearly shows it. If the subject is not visible in this photo, answer "
        "passed=false and say so."
    )
    verdict = ask_typed(VERIFIER_SYSTEM, prompt, StepVerdict, jpeg, model_id)
    verdict.step_id = step.id  # the model does not get to renumber the step it judged
    return verdict
