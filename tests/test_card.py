"""Card rendering and box handling. No model calls — boxes are supplied by hand."""

from PIL import Image

from stepspotter.marker import SMALL_BOX_AREA, fit_title, prepare_boxes, render_card, snap_to_grid
from stepspotter.models import Box, Step

STEP = Step(
    id=3,
    title="Punch down the blue cable",
    action="Push each coloured wire into the slot with the same colour on the jack (the small snap-in socket).",
    do_not_touch=["the black coax cables", "the grey power block"],
    stop_condition="if anything is warm, buzzing or smells burnt, stop and contact a human",
    evidence_required="all eight wires seated in the jack with no copper showing",
    highlight_targets=["telecom punch-down module"],
)


def test_a_small_box_is_widened_to_whole_grid_cells():
    """Spike A: small hardware is where the model's boxes lied. A cell block says
    'look around here'; a tight wrong rectangle says 'it is exactly there'."""
    tiny = Box(label="F connector", x0=0.36, y0=0.36, x1=0.42, y1=0.42)
    assert tiny.area < SMALL_BOX_AREA
    out = prepare_boxes([tiny])[0]
    assert (out.x0, out.x1, out.y0, out.y1) == (0.25, 0.5, 0.25, 0.5)
    assert out.area > tiny.area


def test_a_large_box_is_left_alone():
    big = Box(label="the panel", x0=0.1, y0=0.1, x1=0.8, y1=0.9)
    out = prepare_boxes([big])[0]
    assert (out.x0, out.y0, out.x1, out.y1) == (0.1, 0.1, 0.8, 0.9)


def test_snap_to_grid_never_leaves_the_frame():
    edge = Box(label="corner", x0=0.99, y0=0.99, x1=1.0, y1=1.0)
    out = snap_to_grid(edge)
    assert 0.0 <= out.x0 < out.x1 <= 1.0
    assert 0.0 <= out.y0 < out.y1 <= 1.0


def test_render_card_writes_a_readable_image(photo, tmp_path):
    boxes = [
        Box(label="telecom punch-down module", x0=0.08, y0=0.38, x1=0.82, y1=0.65, kind="act"),
        Box(label="black coax connectors", x0=0.05, y0=0.52, x1=0.12, y1=0.60, kind="avoid"),
    ]
    dest = tmp_path / "card.jpg"
    out = render_card(STEP, 7, photo, boxes, dest, job_title="Connect two network cables")

    assert out.is_file() and out.stat().st_size > 20_000
    img = Image.open(out)
    # The card is the photo plus a legend, so it is always taller than it is wide here.
    assert img.width == 1100
    assert img.height > img.width


def test_a_card_renders_with_no_boxes_at_all(photo, tmp_path):
    """The verifier's words are the product; a card must still be useful when the
    model located nothing (which it should do rather than guess)."""
    out = render_card(STEP, 7, photo, [], tmp_path / "bare.jpg")
    assert out.is_file() and out.stat().st_size > 10_000


def test_a_long_title_wraps_to_more_than_one_line_instead_of_clipping():
    """Real fixture case: 'Step 1 of 9 \u2014 Photograph the existing punch-down
    wiring' clipped past the card edge as a single un-wrapped line. fit_title must
    wrap it, never truncate it."""
    text = "Step 1 of 9 \u2014 Photograph the existing punch-down wiring"
    lines, font = fit_title(text)
    assert len(lines) >= 2
    # No word from the original title is lost — never clip, only wrap/shrink.
    assert " ".join(lines).replace("  ", " ") == text or set(text.split()) <= set(
        " ".join(lines).split()
    )


def test_a_short_title_stays_on_one_line_at_full_size():
    lines, font = fit_title("Step 3 of 7 \u2014 Punch down the blue cable")
    assert len(lines) == 1


def test_render_card_with_a_very_long_title_and_job_name_succeeds(photo, tmp_path):
    long_step = STEP.model_copy(
        update={
            "title": "Confirm the low-voltage panel has no mains breakers before continuing"
        }
    )
    out = render_card(
        long_step,
        9,
        photo,
        [],
        tmp_path / "long-title.jpg",
        job_title="Terminate two long Cat5e cable runs into brand-new keystone jacks at the office wall box",
    )
    assert out.is_file() and out.stat().st_size > 10_000
