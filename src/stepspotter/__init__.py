"""StepSpotter — one repair step at a time, on your own photo.

The next step does not unlock until a photo proves the last one was done safely.
That block lives in code (``gate.StepGate``, a Strands ``BeforeToolCall`` hook),
not in a prompt, so no amount of user or model pressure gets past it.
"""

from stepspotter.models import Box, JobState, Plan, Step, StepVerdict

__all__ = ["Box", "JobState", "Plan", "Step", "StepVerdict"]
__version__ = "0.1.0"
