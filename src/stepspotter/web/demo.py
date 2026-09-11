"""The demo job — a judge with no panel in front of them, and no photo on their phone.

The point of this app is a photo gate, so a first screen that can only be crossed by
taking a photo of your own low-voltage panel is a dead end for anyone reviewing it in
ten minutes. This module supplies three photos of a real panel, shipped inside the
package, so the demo can walk the identical server path a phone walks:

    POST /api/demo/jobs            start photo -> the REAL Planner
    POST /api/jobs/{id}/demo-photo the wrong photo -> the REAL Verifier -> refused
                                   the right photo -> the REAL Verifier -> passed
    POST /api/jobs/{id}/advance    the REAL gate hook

Nothing here fakes a plan, a verdict or a gate decision. The only difference from a
phone is where the JPEG bytes come from: this directory instead of a camera. If the
model answers differently today than it did when this combination was chosen, the
page shows whatever it actually said — an honest surprise is a better demo than a
canned one.

Why this exact task text and these exact three photos: they are the one combination
confirmed live, end to end, on 2026-09-11 (five independent Planner calls were tried;
see docs/video-prep-2026-09-11/NOTES.md section 3). The plans this model writes are
not deterministic, so a different task or a different start photo usually produces a
step-1 evidence line that none of the archive photos can satisfy — which would make
the "right photo" fail too, and turn the demo into a confusing dead end rather than a
clean refuse-then-pass.
"""

from __future__ import annotations

from pathlib import Path

#: The three JPEGs, inside the package so `pip install .` and the container both get
#: them (see [tool.setuptools.package-data] in pyproject.toml).
PHOTOS_DIR = Path(__file__).resolve().parent / "demo_photos"

#: Verbatim the task text that produced a live refuse-then-pass on 2026-09-11.
DEMO_TASK = (
    "Confirm the structured wiring panel is safe to work on before terminating "
    "two Cat5e cable runs into keystone jacks and testing the links"
)

DEMO_PHOTOS: dict[str, str] = {
    "start": "02-panel-inside.jpg",
    "wrong": "04-office-jack-front.jpg",
    "right": "01-panel-overview.jpg",
}

#: What each button says, and what the person should expect from it. The wrong photo
#: is honestly labelled as wrong: the demo is the refusal, not a magic trick.
DEMO_BUTTONS: dict[str, dict[str, str]] = {
    "wrong": {
        "label": "Send the wrong photo",
        "caption": "A close-up of a wall jack — not what the step asked for.",
    },
    "right": {
        "label": "Send the right photo",
        "caption": "The open panel, wide, which is what the step asked for.",
    },
}


def photo_path(which: str) -> Path:
    """Absolute path to one of the three demo photos. Raises on an unknown name."""
    try:
        name = DEMO_PHOTOS[which]
    except KeyError:
        raise KeyError(f"no demo photo called {which!r}") from None
    return PHOTOS_DIR / name


def photo_bytes(which: str) -> bytes:
    """The JPEG bytes, read fresh each time — three small files, no cache worth its bugs."""
    path = photo_path(which)
    if not path.is_file():
        raise FileNotFoundError(f"demo photo missing: {path.name}")
    return path.read_bytes()


def available() -> bool:
    """Are all three photos actually in the install? The button hides if they are not."""
    return all(photo_path(k).is_file() for k in DEMO_PHOTOS)


def info() -> dict:
    """What the page needs to draw the demo buttons, without hard-coding any of it in JS."""
    return {
        "available": available(),
        "task": DEMO_TASK,
        "buttons": {k: dict(v) for k, v in DEMO_BUTTONS.items()},
    }
