"""Spike A — can a Bedrock vision model (via Strands) give reliable pass/fail
verdicts on claims about a real photo, and usable normalized bounding boxes?

Run:
  # export AWS creds in the SAME command (ambient ~/.aws is a different account)
  python spikes/spike_vision.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from strands import Agent
from strands.models import BedrockModel

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(parents=True, exist_ok=True)
PHOTOS = Path(
    "<workspace>/"
    "docs/design-reference-2026-09-09/raw-photos-onq"
)
MAX_PX = 1280
REGION = "us-east-1"
# None -> Strands/Bedrock default (global.anthropic.claude-sonnet-4-6, verified 2026-09-02)
MODEL_ID = os.environ.get("SPIKE_MODEL_ID") or None
FALLBACK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


# ---------------------------------------------------------------- schemas
class Box(BaseModel):
    label: str = Field(description="short name of the object found")
    x0: float = Field(ge=0.0, le=1.0, description="left edge, fraction of image width")
    y0: float = Field(ge=0.0, le=1.0, description="top edge, fraction of image height")
    x1: float = Field(ge=0.0, le=1.0, description="right edge, fraction of image width")
    y1: float = Field(ge=0.0, le=1.0, description="bottom edge, fraction of image height")


class LocateResult(BaseModel):
    boxes: list[Box] = Field(
        default_factory=list,
        description="one box per object actually visible; omit objects that are not visible",
    )


class StepVerdict(BaseModel):
    passed: bool = Field(description="true only if the photo clearly shows the claim is satisfied")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="one short sentence citing what is or is not visible")
    evidence_boxes: list[Box] = Field(default_factory=list)


LOCATE_SYSTEM = (
    "You are a precise visual inspector for home low-voltage wiring photos. "
    "You return normalized bounding boxes in [0,1] where (0,0) is the TOP-LEFT of the image "
    "and (1,1) is the BOTTOM-RIGHT. x0<x1, y0<y1. "
    "Box only what you can actually see. If an asked-for object is not visible, omit it entirely "
    "rather than guessing a location. Keep boxes tight around the object."
)

VERDICT_SYSTEM = (
    "You verify whether a photo proves a specific claim about a wiring installation step. "
    "You are strict: passed=true ONLY when the photo itself clearly shows the claim is satisfied. "
    "If the relevant thing is not visible in the frame, out of focus, or ambiguous, "
    "return passed=false and say in the reason that the evidence is not visible. "
    "Never assume anything outside the frame. Boxes are normalized [0,1], origin top-left."
)


# ---------------------------------------------------------------- helpers
def load_downscaled(path: Path, max_px: int = MAX_PX) -> tuple[bytes, Image.Image]:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_px / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue(), img


def image_block(jpeg_bytes: bytes) -> dict:
    # Bedrock converse content-block shape, exactly as strands.types.media.ImageContent
    return {"image": {"format": "jpeg", "source": {"bytes": jpeg_bytes}}}


def make_agent(system_prompt: str, model_id: str | None) -> Agent:
    kwargs = {"region_name": REGION}
    if model_id:
        kwargs["model_id"] = model_id
    return Agent(model=BedrockModel(**kwargs), system_prompt=system_prompt, callback_handler=None)


def ask(system_prompt: str, text: str, jpeg_bytes: bytes, schema, model_id):
    """One structured-output call. Returns (result, seconds, model_id_used)."""
    for mid in (model_id, FALLBACK_MODEL_ID):
        agent = make_agent(system_prompt, mid)
        used = getattr(agent.model, "config", {}).get("model_id", mid or "<default>")
        t0 = time.time()
        try:
            res = agent.structured_output(schema, [{"text": text}, image_block(jpeg_bytes)])
            return res, time.time() - t0, used
        except Exception as exc:  # noqa: BLE001
            print(f"    !! {used} failed: {type(exc).__name__}: {str(exc)[:220]}", file=sys.stderr)
            if mid == FALLBACK_MODEL_ID:
                raise
    raise RuntimeError("unreachable")


PALETTE = [(255, 59, 48), (0, 200, 83), (0, 122, 255), (255, 149, 0), (175, 82, 222), (0, 210, 210)]


def draw_boxes(img: Image.Image, boxes: list[Box], dest: Path) -> None:
    canvas = img.copy()
    d = ImageDraw.Draw(canvas)
    W, H = canvas.size
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    for i, b in enumerate(boxes):
        color = PALETTE[i % len(PALETTE)]
        x0, y0 = b.x0 * W, b.y0 * H
        x1, y1 = b.x1 * W, b.y1 * H
        d.rectangle([x0, y0, x1, y1], outline=color, width=5)
        label = f"{i+1}. {b.label}"
        tb = d.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ly = max(0, y0 - th - 8)
        d.rectangle([x0, ly, x0 + tw + 10, ly + th + 8], fill=color)
        d.text((x0 + 5, ly + 3), label, fill=(255, 255, 255), font=font)
    canvas.save(dest, quality=90)


# ---------------------------------------------------------------- cases
LOCATE_CASES: list[tuple[str, list[str]]] = [
    ("01-panel-overview", ["blue Cat5e cables", "black coax splitter",
                           "cut blue cable hanging outside the panel"]),
    ("02-panel-inside", ["blue Cat5e cables", "black coax cables", "metal splitter"]),
    ("03-telecom-module", ["telecom punch-down module", "blue cables", "black coax connectors"]),
    ("04-office-jack-front", ["wall plate", "keystone jack opening"]),
    ("05-office-jack-open", ["keystone jack", "terminated wire pairs"]),
    ("06-dining-node-white-cable", ["white cable"]),
]

VERDICT_CASES: list[dict] = [
    dict(photo="01-panel-overview", expected=True,
         claim="the panel door is removed and the inside of the panel is visible"),
    dict(photo="01-panel-overview", expected=False,
         claim="a keystone jack has been installed on the end of the blue cable"),
    dict(photo="05-office-jack-open", expected=True,
         claim="the wall jack is open and wire pairs are terminated into it"),
    dict(photo="05-office-jack-open", expected=False,
         claim="the circuit breaker is switched OFF"),
    dict(photo="03-telecom-module", expected=True,
         claim="blue cables are punched down into the telecom module"),
    dict(photo="03-telecom-module", expected=False,
         claim="the two blue cables have been removed from the phone block"),
    dict(photo="06-dining-node-white-cable", expected=True,
         claim="a white network cable is present"),
    dict(photo="06-dining-node-white-cable", expected=False,
         claim="the cable is plugged into a network switch"),
]



# ---------------------------------------------------------------- part 3: grid
class GridHit(BaseModel):
    label: str
    cells: list[str] = Field(description="grid cell names like A1, B3 that the object occupies")


class GridResult(BaseModel):
    hits: list[GridHit] = Field(default_factory=list)


GRID_N = 4
GRID_SYSTEM = (
    "You are a precise visual inspector. The image is divided into a 4x4 grid. "
    "Columns are A,B,C,D from LEFT to RIGHT. Rows are 1,2,3,4 from TOP to BOTTOM. "
    "Cell A1 is the top-left cell, D4 is the bottom-right cell. "
    "Name the cells an object occupies. If the object is not visible, omit it."
)


def draw_grid(img: Image.Image, hits: list[GridHit], dest: Path) -> None:
    canvas = img.copy()
    ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    W, H = canvas.size
    cw, ch = W / GRID_N, H / GRID_N
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 16)
    except Exception:  # noqa: BLE001
        font = small = ImageFont.load_default()
    for i, h in enumerate(hits):
        r, g, b = PALETTE[i % len(PALETTE)]
        for cell in h.cells:
            cell = cell.strip().upper()
            if len(cell) < 2 or cell[0] not in "ABCD" or not cell[1:].isdigit():
                continue
            cx, cy = "ABCD".index(cell[0]), int(cell[1:]) - 1
            if not (0 <= cy < GRID_N):
                continue
            d.rectangle([cx * cw, cy * ch, (cx + 1) * cw, (cy + 1) * ch],
                        fill=(r, g, b, 70), outline=(r, g, b, 255), width=4)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
    d2 = ImageDraw.Draw(canvas)
    for c in range(GRID_N):
        for rr in range(GRID_N):
            d2.text((c * cw + 6, rr * ch + 4), f"{'ABCD'[c]}{rr+1}", fill=(255, 255, 0), font=small)
    for i, h in enumerate(hits):
        d2.text((10, H - 30 * (len(hits) - i)), f"{h.label}: {','.join(h.cells)}",
                fill=PALETTE[i % len(PALETTE)], font=font)
    canvas.save(dest, quality=90)


def run_grid(photo_fn, models_used: set) -> list:
    print("\n=== PART 3: GRID (4x4) ===")
    rows = []
    for stem, objects in LOCATE_CASES:
        jpg, img = photo_fn(stem)
        want = "; ".join(f'"{o}"' for o in objects)
        text = (
            f"Photo of home low-voltage wiring ({stem}). The image is a 4x4 grid "
            "(columns A-D left to right, rows 1-4 top to bottom).\n"
            f"For each of these objects, list the grid cells it occupies: {want}.\n"
            "Omit any object that is not visible."
        )
        try:
            res, secs, used = ask(GRID_SYSTEM, text, jpg, GridResult, MODEL_ID)
        except Exception as exc:  # noqa: BLE001
            print(f"  {stem}: ERROR {exc}")
            continue
        models_used.add(used)
        dest = OUT / f"{stem}-grid.jpg"
        draw_grid(img, res.hits, dest)
        print(f"  {stem}: {secs:.1f}s -> {dest.name}")
        for h in res.hits:
            print(f"      {h.label:45s} {','.join(h.cells)}")
        rows.append((stem, [h.model_dump() for h in res.hits], round(secs, 2)))
    return rows


@dataclass
class Row:
    cells: list = field(default_factory=list)


def main() -> int:
    cache: dict[str, tuple[bytes, Image.Image]] = {}

    def photo(stem: str):
        if stem not in cache:
            cache[stem] = load_downscaled(PHOTOS / f"{stem}.jpg")
        return cache[stem]

    locate_rows, verdict_rows = [], []
    models_used: set[str] = set()

    print("\n=== PART 1: LOCATE ===")
    for stem, objects in LOCATE_CASES:
        jpg, img = photo(stem)
        want = "; ".join(f'"{o}"' for o in objects)
        text = (
            f"This is a photo of home low-voltage wiring ({stem}).\n"
            f"Locate each of these objects if visible: {want}.\n"
            "Return one box per object you can actually see, using its exact name as the label. "
            "Omit any object that is not visible."
        )
        try:
            res, secs, used = ask(LOCATE_SYSTEM, text, jpg, LocateResult, MODEL_ID)
        except Exception as exc:  # noqa: BLE001
            print(f"  {stem}: ERROR {exc}")
            locate_rows.append((stem, "ERROR", str(exc)[:120], 0.0))
            continue
        models_used.add(used)
        dest = OUT / f"{stem}-locate.jpg"
        draw_boxes(img, res.boxes, dest)
        print(f"  {stem}: {len(res.boxes)} boxes in {secs:.1f}s -> {dest.name}")
        for b in res.boxes:
            print(f"      {b.label:45s} ({b.x0:.2f},{b.y0:.2f})-({b.x1:.2f},{b.y1:.2f})")
        locate_rows.append((stem, objects, [b.model_dump() for b in res.boxes], secs))

    print("\n=== PART 2: VERDICT ===")
    for case in VERDICT_CASES:
        jpg, _img = photo(case["photo"])
        text = (
            "Claim about this photo:\n"
            f"  \"{case['claim']}\"\n"
            "Does this photo prove the claim? Answer passed=true only if the photo clearly shows it. "
            "If the subject of the claim is not visible in this photo, answer passed=false and say so."
        )
        try:
            res, secs, used = ask(VERDICT_SYSTEM, text, jpg, StepVerdict, MODEL_ID)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {case['photo']}: {exc}")
            verdict_rows.append({**case, "got": None, "error": str(exc)[:160], "secs": 0.0})
            continue
        models_used.add(used)
        ok = "OK " if res.passed == case["expected"] else "MISS"
        print(f"  [{ok}] {case['photo']} exp={case['expected']} got={res.passed} "
              f"conf={res.confidence:.2f} ({secs:.1f}s)")
        print(f"        claim : {case['claim']}")
        print(f"        reason: {res.reason}")
        verdict_rows.append({**case, "got": res.passed, "conf": res.confidence,
                             "reason": res.reason,
                             "boxes": [b.model_dump() for b in res.evidence_boxes],
                             "secs": secs, "correct": res.passed == case["expected"]})

    n_true = sum(1 for r in verdict_rows if r["expected"] and r.get("correct"))
    n_false = sum(1 for r in verdict_rows if not r["expected"] and r.get("correct"))
    print(f"\nVERDICT SCORE: true-claims accepted {n_true}/4, false-claims rejected {n_false}/4")
    print(f"models used: {sorted(models_used)}")

    grid_rows = run_grid(photo, models_used)

    (OUT / "raw-results.json").write_text(json.dumps(
        {"locate": [[s, o, b, round(t, 2)] for s, o, b, t in locate_rows],
         "verdict": verdict_rows,
         "grid": grid_rows,
         "models_used": sorted(models_used)}, indent=2, default=str))
    print(f"raw results -> {OUT / 'raw-results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
