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
* a rough estimate (a box the model drew small, which is where spike A's errors
  live) is drawn as a numbered PIN with a soft reach-ring, not as a rectangle: a
  pin says "around here", a rectangle claims an edge it does not have;
* nothing is ever cropped to a box.

And the count is capped at two. A live run on the panel photo came back with five
boxes — two green, three red, one of them a band across blank wall — and they
covered about nine tenths of the frame. Five highlights on a cluttered photo is the
same as none: there is nothing left to look at. So exactly one work zone and at
most one hazard are DRAWN; every other "do not touch" is carried as words under the
photo, where the page can read it out and translate it. The cap is enforced twice —
asked for in the prompt, and cut in ``choose_marks`` no matter what the model sends.
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
        description=(
            "AT MOST TWO boxes: one kind='act' for the single place to work, and at "
            "most one kind='avoid'/'stop' for the single most dangerous thing next to "
            "it. Box only what you can actually see. Anything else the person should "
            "leave alone goes in also_avoid as words, not as a box."
        ),
    )
    also_avoid: list[str] = Field(
        default_factory=list,
        description=(
            "short names of the other things to leave alone in this photo. These are "
            "written under the photo as text instead of being drawn on it."
        ),
    )


LOCATE_SYSTEM = (
    "You mark objects on a photo of home hardware so a beginner can find them. "
    "You return normalized boxes in [0,1] where (0,0) is the TOP-LEFT of the image and "
    "(1,1) is the BOTTOM-RIGHT, with x0<x1 and y0<y1. "
    "Box only what you can actually see. If an object you were asked about is not "
    "visible, omit it entirely rather than guessing where it might be. "
    "Set kind='act' for the thing the person must work on, kind='avoid' for anything "
    "they must leave alone, kind='stop' for something hazardous. "
    "MARK AT MOST TWO THINGS: the one place to work, and the one most dangerous thing "
    "to keep away from. Photos of home hardware are cluttered; a photo with five "
    "highlights on it points at nothing. Put every other warning in also_avoid as "
    "words — it is printed under the photo, in full, either way."
)

GRID_N = 4
SMALL_BOX_AREA = 0.08  # below this fraction of the frame, snap out to grid cells


def locate(step: Step, photo_path: str, model_id: str | None = None) -> list[Box]:
    """Ask where this step's targets are. Returns [] rather than guessing.

    ``also_avoid`` on the answer is deliberately not returned: it exists so the model
    has somewhere to put the other warnings instead of drawing them, and the words
    themselves are already on the card and the page as ``step.do_not_touch``. What
    does come back can still be longer than two boxes — a model asked for two
    sometimes sends five — so ``choose_marks`` cuts it again before anything is drawn.
    """
    targets = list(step.highlight_targets)
    avoid = list(step.do_not_touch)
    if not targets and not avoid:
        return []
    want = "; ".join(f'"{t}"' for t in targets) or "(nothing specific)"
    dont = "; ".join(f'"{t}"' for t in avoid)
    prompt = (
        "This is the person's own photo of what they are working on.\n"
        f"The one place to work, if visible — box it with kind='act': {want}.\n"
        + (
            f"Things to keep away from: {dont}.\n"
            "Box ONLY the single most dangerous one of those, with kind='avoid' (or "
            "kind='stop' if it is an actual hazard). Put the rest in also_avoid as words.\n"
            if dont
            else ""
        )
        + "Use the object's own name as the label. Omit anything that is not visible. "
        "Two boxes at the most."
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


# --------------------------------------------------------------------- choosing

#: How many marks may ever be drawn on one photo: one work zone, one hazard.
MAX_MARKS = 2
#: Two act boxes are merged into one work zone only while the merge stays this tight.
ACT_UNION_MAX = 0.34
#: A "do not touch" box bigger than this is a blanket, not a warning — it becomes text.
AVOID_MAX_AREA = 0.38
#: A small box whose longest side is under this is an estimate of a point: draw a pin.
ROUGH_SIDE = 0.35

#: Words that make one "do not touch" more dangerous than another. Crude on purpose:
#: the alternative is a second model call to rank warnings, and a wrong ranking here
#: costs a red box on the second-worst hazard while the worst is still printed as text.
HAZARD_WORDS: dict[str, float] = {
    "live": 4, "mains": 4, "volt": 4, "120": 4, "240": 4, "breaker": 4, "power": 3,
    "capacitor": 4, "gas": 4, "propane": 4, "electric": 2, "ground": 2, "earth": 2,
    "battery": 3, "water": 2, "hot": 2, "steam": 2, "blade": 3, "sharp": 2,
    "fan": 1, "spring": 2, "pressure": 2, "terminal": 1, "wire": 1, "wiring": 1,
}


@dataclass
class Mark:
    """One thing actually drawn on the photo, with how sure we are where it is.

    ``rough`` is the model's own uncertainty as far as we can observe it: spike A
    found the boxes that missed were the small ones, so a box the model drew under
    ``SMALL_BOX_AREA`` is treated as an estimate and drawn as a pin, not a rectangle.
    """

    box: Box            # the box as drawn (grid-snapped when rough)
    raw: Box            # what the model actually returned
    rough: bool
    style: str          # "box" or "pin"


def _iou_touch(a: Box, b: Box) -> bool:
    """Do these two overlap, or sit within a hair of each other?"""
    pad = 0.04
    return not (
        a.x1 + pad < b.x0 or b.x1 + pad < a.x0 or a.y1 + pad < b.y0 or b.y1 + pad < a.y0
    )


def _union(a: Box, b: Box) -> Box:
    label = a.label if b.label in a.label else f"{a.label} + {b.label}"
    return a.model_copy(
        update={
            "x0": min(a.x0, b.x0), "y0": min(a.y0, b.y0),
            "x1": max(a.x1, b.x1), "y1": max(a.y1, b.y1),
            "label": label,
        }
    )


#: Words too common to prove two labels mean the same thing. Without this, "the
#: phone/punch-down block" matched the target "punch-down terminals" on the word
#: "down", and the general-area box beat the specific one.
STOP_WORDS = frozenset(
    "down left right side back front near with that this from your into onto over "
    "under next same some each also only just very they them there where when".split()
)


def _tokens(text: str) -> set[str]:
    words = text.lower().replace("-", " ").replace("/", " ").replace(",", " ").split()
    return {w.rstrip("s") for w in words if len(w) > 3 and w not in STOP_WORDS}


def _label_hit(label: str, target: str) -> bool:
    """Loose word overlap — the model renames things ('the panel' vs 'panel cover')."""
    return bool(_tokens(label) & _tokens(target))


def hazard_score(box: Box, work: Box | None = None) -> float:
    """How much this warning earns the one red mark on the photo."""
    text = box.label.lower()
    score = sum(w for word, w in HAZARD_WORDS.items() if word in text)
    if box.kind == "stop":
        score += 10  # the model called it a hazard outright
    if work is not None and _iou_touch(box, work):
        score += 2  # within reach of the hand doing the step
    score -= 4 * box.area  # a band across the photo warns about nothing in particular
    return score


def pick_work(boxes: list[Box], step: Step | None = None) -> tuple[Box | None, list[Box]]:
    """The single work zone, and the act boxes that were folded into or dropped from it.

    The first target the planner named wins; neighbouring act boxes are merged in only
    while the result stays tight, so "cable 1 terminals" and "cable 2 terminals" become
    one zone instead of the second one silently disappearing.
    """
    acts = [b for b in boxes if b.kind == "act"]
    if not acts:
        return None, []
    targets = list(step.highlight_targets) if step else []

    def rank(pair: tuple[int, Box]) -> tuple[int, int, int]:
        i, b = pair
        order = len(targets) + 1
        for k, t in enumerate(targets):
            if _label_hit(b.label, t):
                order = k
                break
        # A box covering a third of the frame is "the general area", not a work zone;
        # when the model offers both, the specific one wins even if it came second.
        return (order, 0 if b.area <= ACT_UNION_MAX else 1, i)

    best = min(enumerate(acts), key=rank)[1]
    work = best
    folded = [best]
    for b in acts:
        if b in folded:
            continue
        u = _union(work, b)
        if _iou_touch(work, b) and u.area <= ACT_UNION_MAX:
            work = u
            folded.append(b)
    return work, [b for b in acts if b not in folded]


def pick_hazard(boxes: list[Box], work: Box | None) -> tuple[Box | None, list[Box]]:
    """The one warning that gets drawn, and the ones that stay words."""
    warns = [b for b in boxes if b.kind in ("avoid", "stop")]
    if not warns:
        return None, []
    drawable = [b for b in warns if b.area <= AVOID_MAX_AREA]
    if not drawable:
        return None, warns  # every warning was a blanket; none of them is a pointer
    best = max(drawable, key=lambda b: (hazard_score(b, work), -b.area))
    return best, [b for b in warns if b is not best]


def choose_marks(
    boxes: list[Box], step: Step | None = None, style: str = "auto", n: int = GRID_N
) -> tuple[list[Mark], list[Box]]:
    """Cut a model's answer down to what may be drawn. Returns (marks, left as words).

    ``style="auto"`` draws a rectangle for a box the model was specific about and a
    numbered pin for a small (rough) one. ``"box"`` and ``"pin"`` force one or the
    other, which is what the before/after sheets in docs/marker-2026-09-11 compare.
    """
    clean = [b.normalized() for b in boxes]
    work, spare_acts = pick_work(clean, step)
    hazard, spare_warns = pick_hazard(clean, work)

    marks: list[Mark] = []
    for raw in [b for b in (work, hazard) if b is not None][:MAX_MARKS]:
        # Rough = small in BOTH directions, which is exactly the shape spike A saw
        # the model miss. A long thin strip ("the row of wire slots") is small by area
        # but specific about where it is, and a circle would be a worse description
        # of it than the rectangle the model drew.
        rough = raw.area < SMALL_BOX_AREA and max(raw.x1 - raw.x0, raw.y1 - raw.y0) < ROUGH_SIDE
        drawn = snap_to_grid(raw, n) if rough else raw
        marks.append(
            Mark(box=drawn, raw=raw, rough=rough, style=style if style != "auto" else ("pin" if rough else "box"))
        )
    return marks, spare_acts + spare_warns


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
    title_small: ImageFont.ImageFont
    body: ImageFont.ImageFont
    small: ImageFont.ImageFont
    small2: ImageFont.ImageFont
    badge: ImageFont.ImageFont


def _fonts() -> _Fonts:
    def f(size: int):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:  # noqa: BLE001 - any box without that font
            return ImageFont.load_default()

    return _Fonts(
        title=f(40), title_small=f(30), body=f(25), small=f(20), small2=f(16), badge=f(30)
    )


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


def fit_title(text: str, width: int = CARD_W - 2 * PAD, max_lines: int = 2) -> tuple[list[str], "ImageFont.ImageFont"]:
    """Wrap the card title to at most ``max_lines``, shrinking the font once if a
    long title (e.g. a long step name) does not fit at the normal size.

    A step title with a long job name plus a wordy step name used to be drawn as
    one un-wrapped line and clipped past the card edge. This never clips: if the
    title still does not fit in ``max_lines`` at the smaller font, all wrapped
    lines are returned anyway (the card grows taller) rather than dropping words.
    """
    fonts = _fonts()
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = _wrap(probe, text, fonts.title, width)
    if len(lines) <= max_lines:
        return lines, fonts.title
    lines = _wrap(probe, text, fonts.title_small, width)
    return lines, fonts.title_small


def fit_subtitle(text: str, width: int = CARD_W - 2 * PAD, max_lines: int = 2) -> tuple[list[str], "ImageFont.ImageFont"]:
    """Same idea as ``fit_title`` for the job-name subtitle under the step title."""
    fonts = _fonts()
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = _wrap(probe, text, fonts.small, width)
    if len(lines) <= max_lines:
        return lines, fonts.small
    lines = _wrap(probe, text, fonts.small2, width)
    return lines, fonts.small2


def _badge(d: ImageDraw.ImageDraw, cx: float, cy: float, n: int, color, rad: int) -> None:
    """The numbered dot. Sized off the photo width so it survives a 390px phone."""
    d.ellipse(
        [cx - rad, cy - rad, cx + rad, cy + rad], fill=color, outline=PAPER, width=max(3, rad // 7)
    )
    font = _badge_font(int(rad * 1.25))
    txt = str(n)
    tb = d.textbbox((0, 0), txt, font=font)
    d.text(
        (cx - (tb[2] - tb[0]) / 2, cy - (tb[3] - tb[1]) / 2 - tb[1]), txt, fill=PAPER, font=font
    )


def _badge_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _draw_marks_on_photo(img: Image.Image, marks: list[Mark]) -> Image.Image:
    """Draw at most two marks. Nothing is cropped, and nothing is drawn thin.

    Everything scales off the photo's own width, because the photo is looked at on a
    390px phone: the old fixed 6px outline and 22px badge came out at under 2px and
    7px there, which is why the first sheets read as coloured haze rather than as a
    pointer. A rough estimate is drawn as a pin inside a soft reach-ring instead of a
    rectangle — the ring is the honest shape for "somewhere in here".
    """
    canvas = img.convert("RGBA")
    W, H = canvas.size
    unit = max(W, H)
    line = max(4, int(round(unit / 150)))
    rad = max(14, int(round(unit / 30)))

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for m in marks:
        r, g, bl = KIND_COLOR.get(m.box.kind, GREEN)
        x0, y0, x1, y1 = m.box.x0 * W, m.box.y0 * H, m.box.x1 * W, m.box.y1 * H
        if m.style == "pin":
            cx, cy = (m.raw.x0 + m.raw.x1) / 2 * W, (m.raw.y0 + m.raw.y1) / 2 * H
            reach = max(rad * 2.4, max(x1 - x0, y1 - y0) / 2)
            d.ellipse(
                [cx - reach, cy - reach, cx + reach, cy + reach],
                fill=(r, g, bl, 40),
                outline=(r, g, bl, 200),
                width=line,
            )
        else:
            # The fill fades as the box grows: a big box tinted solid hides the very
            # thing it points at. The outline carries the meaning either way.
            alpha = 48 if m.box.area < 0.25 else 26
            d.rectangle(
                [x0, y0, x1, y1], fill=(r, g, bl, alpha), outline=(r, g, bl, 255), width=line
            )
    canvas = Image.alpha_composite(canvas, overlay).convert("RGB")

    d2 = ImageDraw.Draw(canvas)
    placed: list[tuple[float, float]] = []
    for i, m in enumerate(marks, start=1):
        color = KIND_COLOR.get(m.box.kind, GREEN)
        if m.style == "pin":
            # The pin IS the position, so it never moves; a box badge may.
            cx = (m.raw.x0 + m.raw.x1) / 2 * W
            cy = (m.raw.y0 + m.raw.y1) / 2 * H
        else:
            cx, cy = _badge_spot(m.box, W, H, rad, placed)
        placed.append((cx, cy))
        _badge(d2, cx, cy, i, color, rad)
    return canvas


def _badge_spot(
    box: Box, W: int, H: int, rad: int, placed: list[tuple[float, float]]
) -> tuple[float, float]:
    """A corner of this box that does not sit on top of a badge already drawn.

    Two boxes that share a corner used to stack badge 2 on badge 1, and the numbers in
    the legend then pointed at a dot nobody could see (case D of the before/after set).
    """
    inset = rad + max(6, rad // 3)
    corners = [
        (box.x0 * W + inset, box.y0 * H + inset),
        (box.x1 * W - inset, box.y0 * H + inset),
        (box.x0 * W + inset, box.y1 * H - inset),
        (box.x1 * W - inset, box.y1 * H - inset),
    ]
    clear = rad * 2.3
    for cx, cy in corners:
        cx = min(max(cx, rad + 4), W - rad - 4)
        cy = min(max(cy, rad + 4), H - rad - 4)
        if all((cx - px) ** 2 + (cy - py) ** 2 >= clear**2 for px, py in placed):
            return cx, cy
    cx, cy = corners[0]
    return min(max(cx, rad + 4), W - rad - 4), min(max(cy, rad + 4), H - rad - 4)


def _draw_boxes_on_photo(img: Image.Image, boxes: list[Box]) -> Image.Image:
    """Boxes in, marked photo out — kept for callers that hold plain boxes."""
    marks, _left = choose_marks(boxes)
    return _draw_marks_on_photo(img, marks)


PHOTO_W = 1200


def render_marked_photo(
    photo_path: str,
    boxes: list[Box],
    dest: str | Path,
    width: int = PHOTO_W,
    step: Step | None = None,
    style: str = "auto",
) -> Path:
    """The photo with its one or two numbered marks on it and NOTHING else — no words.

    This is what the phone shows. The web page owns the words — title, action, the
    do-not-touch list, the stop condition — as real HTML text, so a step is read once
    rather than twice, and the text stays selectable, translatable and screen-readable
    at whatever size the phone is set to. Baking the same sentences into the JPEG as
    well is how the first build ended up with a page you had to scroll past its own
    duplicate. ``render_card`` keeps the printed-sheet layout for the CLI and eval.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _bytes, photo = load_photo(photo_path)
    marks, _left = choose_marks(boxes, step, style)
    marked = _draw_marks_on_photo(photo, marks)
    if marked.width != width:
        h = int(marked.height * (width / marked.width))
        marked = marked.resize((width, h), Image.LANCZOS)
    marked.save(dest, quality=92)
    return dest


def render_card(
    step: Step,
    total: int,
    photo_path: str,
    boxes: list[Box],
    dest: str | Path,
    job_title: str = "",
    layout: str = "card",
    style: str = "auto",
) -> Path:
    """Render one step to ``dest``. No model calls — pure PIL, so tests can run it.

    ``layout="card"`` (default) is the printed sheet: title, photo, legend, the step
    written underneath in the same colours. ``layout="photo"`` is the photo and its
    marks alone, for a surface that renders the words itself.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if layout == "photo":
        return render_marked_photo(photo_path, boxes, dest, step=step, style=style)

    _bytes, photo = load_photo(photo_path)
    marks, left_as_words = choose_marks(boxes, step, style)
    marked = _draw_marks_on_photo(photo, marks)

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

    if marks:
        para("On your photo:", fonts.small, GREY)
        for i, m in enumerate(marks, start=1):
            b = m.box
            tag = {"act": "work here", "avoid": "do not touch", "stop": "watch for this"}.get(
                b.kind, "work here"
            )
            where = "somewhere inside the circle" if m.style == "pin" else "roughly here"
            para(
                f"{i}. {b.label} — {tag} ({where})",
                fonts.small,
                KIND_COLOR.get(b.kind, GREEN),
                18,
            )
        # Everything the model wanted to draw but did not get a mark is still said in
        # words — except the ones the step already says in its own "Do not touch" line
        # below, and except leftover work boxes, which the action sentence covers. A
        # legend that repeats the next paragraph is the duplication this card had before.
        said = " ".join(step.do_not_touch).lower()
        extra = [
            b
            for b in left_as_words
            if b.kind in ("avoid", "stop") and not _label_hit(b.label, said)
        ]
        if extra:
            para(
                "Also leave alone (not marked): " + " · ".join(b.label for b in extra),
                fonts.small,
                RED,
                18,
            )
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

    title_text = f"Step {step.id} of {total} — {step.title}"
    title_lines, title_font = fit_title(title_text, inner)
    subtitle_lines, subtitle_font = fit_subtitle(job_title, inner) if job_title else ([], fonts.small)

    head_h = sum(_line_h(title_font) for _ in title_lines)
    head_h += sum(_line_h(subtitle_font) for _ in subtitle_lines)
    head_h += 10
    body_h = sum(_line_h(f) for _t, f, _c, _i in rows)
    H = PAD + head_h + 12 + ph + 18 + body_h + PAD

    card = Image.new("RGB", (CARD_W, H), PAPER)
    d = ImageDraw.Draw(card)
    y = PAD

    for ln in title_lines:
        d.text((PAD, y), ln, fill=INK, font=title_font)
        y += _line_h(title_font)
    for ln in subtitle_lines:
        d.text((PAD, y), ln, fill=GREY, font=subtitle_font)
        y += _line_h(subtitle_font)
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
    layout: str = "card",
    style: str = "auto",
) -> tuple[Path, list[Box]]:
    """Locate then render. Pass ``boxes`` to skip the model call.

    The boxes returned are everything the model found, not just the one or two that
    were drawn — the job state keeps the full answer, and ``choose_marks`` decides
    again at render time, so a later change to the cap redraws old jobs correctly.
    """
    found = boxes if boxes is not None else locate(step, photo_path, model_id)
    return (
        render_card(step, total, photo_path, found, dest, job_title, layout, style),
        found,
    )
