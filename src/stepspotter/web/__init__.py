"""The phone-first web face of StepSpotter.

One page, one step at a time. The browser only ever calls the same JobService and
the same gated tool path the CLI and the Guide agent use — see ``gated.py`` for why
the advance endpoint goes the long way round instead of just doing ``current += 1``.
"""

from stepspotter.web.app import create_app

__all__ = ["create_app"]
