"""Marker — draws the step card: the person's own photo, marked, with a legend.

Two jobs. First, ask the vision model where the step's highlight_targets are.
Second, render a card in the format that already works on a real person (see
docs/design-reference-2026-09-09): title, their photo with numbered coloured
boxes, then the step written under it in the same colours.

Colour code, kept identical everywhere:
    green  = do the step here
    red    = do not touch this
    orange = stop and get a human if you see this

What the boxes are NOT. Spike A judged 14 model boxes by eye: 3 tight, 10 loose,
1 landed on blank wall a full band below a coax splitter. The failure is in the
model's spatial estimate, and asking for grid cells reproduced the same error, so
neither format is trustworthy for small hardware in clutter. So:

* boxes are drawn translucent and captioned "roughly here", never as a crisp
  assertion of "it is exactly there";
* any box under 8% of the frame is snapped out to whole 4x4 grid cells — the wrong
  answer then reads as "look in this area" instead of pointing at the wrong screw;
* nothing is ever cropped to a box.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from stepspotter.models import Box, Step
from stepspotter.vision import ask_typed, load_photo

# --------------------------------------------------------------------- locating


class LocateResult(BaseModel):
    boxes: list[Box] = Field(
        default_factory=list,
        description="one box per object that is actually visible; omit anything you cannot see",
    )


LOCATE_SYSTEM = (
    "You mark objects on a photo of home hardware so a beginner can find them. "
    "You return normalized boxes in [0,1] where (0,0) is the TOP-LEFT of the image and "
    "(1,1) is the BOTTOM-RIGHT, with x0<x1 and y0<y1. "
    "Box only what you can actually see. If an object you were asked about is not "
    "visible, omit it entirely rather than guessing where it might be. "
    "Set kind='act' for the thing the person must work on, kind='avoid' for anything "
    "they must leave alone, kind='stop' for something hazardous."
)

GRID_N = 4
SMALL_BOX_AREA = 0.08  # below this fraction of the frame, snap out to grid cells


def locate(step: Step, photo_path: str, model_id: str | None = None) -> list[Box]:
    """Ask where this step's targets are. Returns [] rather than guessing."""
    targets = list(step.highlight_targets)
    avoid = list(step.do_not_touch)
    if not targets and not avoid:
        return []
    want = "; ".join(f'"{t}"' for t in targets) or "(nothing specific)"
    dont = "; ".join(f'"{t}"' for t in avoid)
    prompt = (
        "This is the person's own photo of what they are working on.\n"
        f"Mark these, if visible, with kind='act': {want}.\n"
        + (f"Mark these, if visible, with kind='avoid': {dont}.\n" if dont else "")
        + "Use the object's own name as the label. Omit anything that is not visible."
    )
    jpeg, _img = load_photo(photo_path)
    result = ask_typed(LOCATE_SYSTEM, prompt, LocateResult, jpeg, model_id)
    return [b.normalized() for b in result.boxes]


def snap_to_grid(box: Box, n: int = GRID_N) -> Box:
    """Expand a box out to the whole 4x4 cells it touches.

    Used only on small boxes. A highlighted cell block says "look in this area";
    a tight rectangle in the wrong place says "it is exactly there", which is the
    lie spike A caught.
    """
    b = box.normalized()
    c0 = max(0, min(n - 1, int(b.x0 * n)))
    c1 = max(0, min(n - 1, int(min(b.x1, 0.9999) * n)))
    r0 = max(0, min(n - 1, int(b.y0 * n)))
    r1 = max(0, min(n - 1, int(min(b.y1, 0.9999) * n)))
    return b.model_copy(
        update={"x0": c0 / n, "x1": (c1 + 1) / n, "y0": r0 / n, "y1": (r1 + 1) / n}
    )


def prepare_boxes(boxes: list[Box], n: int = GRID_N) -> list[Box]:
    """Normalize, then widen the small ones to grid cells."""
    out: list[Box] = []
    for b in boxes:
        nb = b.normalized()
        out.append(snap_to_grid(nb, n) if nb.area < SMALL_BOX_AREA else nb)
    return out


# ---------------------------------------------------------------------- drawing

GREEN = (0, 160, 60)
RED = (200, 30, 30)
ORANGE = (225, 125, 0)
INK = (20, 20, 20)
GREY = (110, 110, 110)
PAPER = (255, 255, 255)

KIND_COLOR = {"act": GREEN, "avoid": RED, "stop": ORANGE}

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
CARD_W = 1100
PAD = 28


@dataclass
class _Fonts:
    title: ImageFont.ImageFont
    body: ImageFont.ImageFont
    small: ImageFont.ImageFont
    badge: ImageFont.ImageFont


def _fonts() -> _Fonts:
    def f(size: int):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:  # noqa: BLE001 - any box without that font
            return ImageFont.load_default()

    return _Fonts(title=f(40), body=f(25), small=f(20), badge=f(30))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    """Wrap to pixel width, measuring the real font rather than guessing characters."""
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines or [""]


def _line_h(font) -> int:
    return int(getattr(font, "size", 20) * 1.45)


def _draw_boxes_on_photo(img: Image.Image, boxes: list[Box]) -> Image.Image:
    """Translucent fill + outline + numbered badge. Nothing is cropped."""
    canvas = img.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    W, H = canvas.size
    for i, b in enumerate(boxes, start=1):
        r, g, bl = KIND_COLOR.get(b.kind, GREEN)
        x0, y0, x1, y1 = b.x0 * W, b.y0 * H, b.x1 * W, b.y1 * H
        # A big box tinting half the photo hides the thing it points at, so the
        # fill fades as the box grows; the outline carries the meaning either way.
        alpha = 48 if b.area < 0.25 else 22
        d.rectangle([x0, y0, x1, y1], fill=(r, g, bl, alpha), outline=(r, g, bl, 255), width=6)
    canvas = Image.alpha_composite(canvas, overlay).convert("RGB")

    d2 = ImageDraw.Draw(canvas)
    fonts = _fonts()
    for i, b in enumerate(boxes, start=1):
        color = KIND_COLOR.get(b.kind, GREEN)
        x0, y0 = b.x0 * W, b.y0 * H
        rad = 22
        cx, cy = min(W - rad - 4, x0 + rad + 6), min(H - rad - 4, y0 + rad + 6)
        d2.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=color, outline=PAPER, width=3)
        txt = str(i)
        tb = d2.textbbox((0, 0), txt, font=fonts.badge)
        d2.text(
            (cx - (tb[2] - tb[0]) / 2, cy - (tb[3] - tb[1]) / 2 - tb[1]),
            txt,
            fill=PAPER,
            font=fonts.badge,
        )
    return canvas


def render_card(
    step: Step,
    total: int,
    photo_path: str,
    boxes: list[Box],
    dest: str | Path,
    job_title: str = "",
) -> Path:
    """Render one step card to ``dest``. No model calls — pure PIL, so tests can run it."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    _bytes, photo = load_photo(photo_path)
    boxes = prepare_boxes(boxes)
    marked = _draw_boxes_on_photo(photo, boxes)

    inner = CARD_W - 2 * PAD
    ph = int(marked.height * (inner / marked.width))
    marked = marked.resize((inner, ph), Image.LANCZOS)

    fonts = _fonts()
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    # Build the legend as (text, font, colour, indent) rows, then size the canvas to fit.
    rows: list[tuple[str, object, tuple[int, int, int], int]] = []

    def para(text: str, font, color, indent: int = 0) -> None:
        for ln in _wrap(probe, text, font, inner - indent):
            rows.append((ln, font, color, indent))

    if boxes:
        para("On your photo:", fonts.small, GREY)
        for i, b in enumerate(boxes, start=1):
            tag = {"act": "work here", "avoid": "do not touch", "stop": "watch for this"}.get(
                b.kind, "work here"
            )
            para(f"{i}. {b.label} — {tag} (roughly here)", fonts.small, KIND_COLOR.get(b.kind, GREEN), 18)
        rows.append(("", fonts.small, INK, 0))

    para(step.action, fonts.body, INK)
    if step.do_not_touch:
        rows.append(("", fonts.small, INK, 0))
        para("Do not touch: " + " · ".join(step.do_not_touch), fonts.body, RED)
    if step.stop_condition:
        rows.append(("", fonts.small, INK, 0))
        para("Stop if: " + step.stop_condition, fonts.body, ORANGE)
    rows.append(("", fonts.small, INK, 0))
    para("Next photo must show: " + step.evidence_required, fonts.body, GREEN)

    head_h = _line_h(fonts.title) + (_line_h(fonts.small) if job_title else 0) + 10
    body_h = sum(_line_h(f) for _t, f, _c, _i in rows)
    H = PAD + head_h + 12 + ph + 18 + body_h + PAD

    card = Image.new("RGB", (CARD_W, H), PAPER)
    d = ImageDraw.Draw(card)
    y = PAD

    d.text((PAD, y), f"Step {step.id} of {total} — {step.title}", fill=INK, font=fonts.title)
    y += _line_h(fonts.title)
    if job_title:
        d.text((PAD, y), job_title, fill=GREY, font=fonts.small)
        y += _line_h(fonts.small)
    y += 10
    d.line([PAD, y, CARD_W - PAD, y], fill=(220, 220, 220), width=2)
    y += 12

    card.paste(marked, (PAD, y))
    y += ph + 18

    for text, font, color, indent in rows:
        if text:
            d.text((PAD + indent, y), text, fill=color, font=font)
        y += _line_h(font)

    card.save(dest, quality=92)
    return dest


def make_card(
    step: Step,
    total: int,
    photo_path: str,
    dest: str | Path,
    job_title: str = "",
    model_id: str | None = None,
    boxes: list[Box] | None = None,
) -> tuple[Path, list[Box]]:
    """Locate then render. Pass ``boxes`` to skip the model call."""
    found = boxes if boxes is not None else locate(step, photo_path, model_id)
    return render_card(step, total, photo_path, found, dest, job_title), found
