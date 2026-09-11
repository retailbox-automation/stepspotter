"""Two marks, never five — and the phone gets a picture, not a picture of words.

The numbers in LIVE_FIVE are not invented: they are the boxes a real Bedrock run
returned for the panel photo on 2026-09-09
(``data/demo/onq-keystone/jobs/job-20260909-102907-6057.trace.jsonl``). Their union
covers about nine tenths of that frame, which is the defect this module fixes.
"""

from __future__ import annotations

from PIL import Image

from stepspotter.marker import (
    AVOID_MAX_AREA,
    MAX_MARKS,
    choose_marks,
    hazard_score,
    render_card,
    render_marked_photo,
)
from stepspotter.models import Box, Step

STEP = Step(
    id=1,
    title="Punch down the blue cable",
    action="Push each coloured wire into the slot with the same colour on the jack.",
    do_not_touch=["the black coax cables", "the ground wire", "the other terminated cables"],
    stop_condition="if anything is warm or smells burnt, stop and contact a human",
    evidence_required="all eight wires seated with no copper showing",
    highlight_targets=["punch-down terminals"],
)

#: Verbatim from the live trace named in the module docstring.
LIVE_FIVE = [
    Box(label="blue Cat5e cables entering the phone/punch-down block", x0=0.08, y0=0.0, x1=0.75, y1=0.55, kind="act"),
    Box(label="individual wire colors in the terminal slots", x0=0.18, y0=0.38, x1=0.72, y1=0.52, kind="act"),
    Box(label="coaxial (TV cable) connectors and splitter", x0=0.22, y0=0.22, x1=0.72, y1=0.42, kind="avoid"),
    Box(label="any black cables not identified as Cat5e", x0=0.55, y0=0.28, x1=1.0, y1=0.95, kind="avoid"),
    Box(label="yellow-green ground wire at the bottom", x0=0.1, y0=0.88, x1=0.55, y1=0.98, kind="avoid"),
]


def test_five_live_boxes_become_two_marks():
    marks, left = choose_marks(LIVE_FIVE, STEP)
    assert len(marks) == MAX_MARKS == 2
    assert [m.box.kind for m in marks] == ["act", "avoid"]
    # Nothing the model said is lost — it is carried as words instead.
    assert len(left) == 3
    assert {b.label for b in left} | {m.box.label for m in marks} >= {b.label for b in LIVE_FIVE[2:]}


def test_the_two_marks_no_longer_cover_the_photo():
    """The five live boxes cover ~90% of the frame; two marks must be a pointer."""
    before = _coverage(LIVE_FIVE)
    after = _coverage([m.box for m in choose_marks(LIVE_FIVE, STEP)[0]])
    assert before > 0.6   # measured: 0.66 of the frame is under at least one box
    assert after < 0.2    # measured: 0.12
    assert after < before / 3


def _coverage(boxes, n: int = 100) -> float:
    """Fraction of the frame under at least one box, on an n x n sample grid."""
    hit = 0
    for r in range(n):
        y = (r + 0.5) / n
        for c in range(n):
            x = (c + 0.5) / n
            if any(b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1 for b in boxes):
                hit += 1
    return hit / (n * n)


def test_the_drawn_warning_is_the_dangerous_one_not_the_first_one():
    """'Do not touch' is a ranking, not a list: the ground wire outranks 'other cables'."""
    _marks, _left = choose_marks(LIVE_FIVE, STEP)
    warn = [m for m in _marks if m.box.kind == "avoid"][0]
    assert "ground" in warn.box.label
    assert hazard_score(warn.box) > hazard_score(LIVE_FIVE[2])  # beats the coax splitter


def test_a_declared_hazard_outranks_every_plain_warning():
    boxes = [
        Box(label="the keystone jack", x0=0.3, y0=0.3, x1=0.6, y1=0.6, kind="act"),
        Box(label="ground wire", x0=0.1, y0=0.8, x1=0.3, y1=0.9, kind="avoid"),
        Box(label="scorched insulation", x0=0.62, y0=0.3, x1=0.8, y1=0.5, kind="stop"),
    ]
    marks, left = choose_marks(boxes, STEP)
    assert [m.box.kind for m in marks] == ["act", "stop"]
    assert [b.label for b in left] == ["ground wire"]


def test_a_blanket_warning_is_never_drawn_only_written():
    """A red box over half the photo warns about nothing in particular."""
    blanket = Box(label="everything on the right", x0=0.4, y0=0.0, x1=1.0, y1=1.0, kind="avoid")
    assert blanket.area > AVOID_MAX_AREA
    boxes = [Box(label="the jack", x0=0.1, y0=0.1, x1=0.3, y1=0.3, kind="act"), blanket]
    marks, left = choose_marks(boxes, STEP)
    assert [m.box.kind for m in marks] == ["act"]
    assert left == [blanket]


def test_two_neighbouring_work_boxes_merge_into_one_zone():
    """Real case: 'cable 1 terminals' and 'cable 2 terminals' side by side. Dropping
    one would send the person to half the job; the merge stays tight."""
    boxes = [
        Box(label="blue Cat5e cable 1 punch-down terminals", x0=0.28, y0=0.42, x1=0.52, y1=0.58, kind="act"),
        Box(label="blue Cat5e cable 2 punch-down terminals", x0=0.52, y0=0.40, x1=0.72, y1=0.56, kind="act"),
    ]
    marks, left = choose_marks(boxes, STEP)
    assert len(marks) == 1 and left == []
    zone = marks[0].box
    assert (zone.x0, zone.y0, zone.x1, zone.y1) == (0.28, 0.40, 0.72, 0.58)
    assert zone.area < 0.1 and marks[0].style == "box"


def test_far_apart_work_boxes_do_not_merge_into_a_band():
    boxes = [
        Box(label="punch-down terminals", x0=0.05, y0=0.05, x1=0.2, y1=0.2, kind="act"),
        Box(label="far corner socket", x0=0.8, y0=0.8, x1=0.95, y1=0.95, kind="act"),
    ]
    marks, left = choose_marks(boxes, STEP)
    assert len(marks) == 1
    assert marks[0].box.area < 0.1
    assert [b.label for b in left] == ["far corner socket"]


def test_a_rough_small_box_is_drawn_as_a_pin_and_a_confident_one_as_a_box():
    tiny = Box(label="F connector", x0=0.36, y0=0.36, x1=0.42, y1=0.42, kind="act")
    big = Box(label="the punch-down block", x0=0.1, y0=0.3, x1=0.7, y1=0.6, kind="act")
    assert choose_marks([tiny], STEP)[0][0].style == "pin"
    assert choose_marks([big], STEP)[0][0].style == "box"
    # and the caller can force either, which is how the A/B sheets were made
    assert choose_marks([big], STEP, style="pin")[0][0].style == "pin"


def test_the_photo_layout_bakes_no_words_into_the_image(photo, tmp_path):
    """Form B's card must be the picture only: the page is the one place words live.

    The check is geometric and needs no OCR — the printed sheet adds a title band and
    a legend under the photo, so it cannot keep the photo's own aspect ratio.
    """
    src = Image.open(photo)
    aspect = src.width / src.height

    pic = render_marked_photo(photo, LIVE_FIVE, tmp_path / "photo.jpg", step=STEP)
    got = Image.open(pic)
    assert abs(got.width / got.height - aspect) < 0.01

    sheet = render_card(STEP, 9, photo, LIVE_FIVE, tmp_path / "sheet.jpg", layout="card")
    sheet_img = Image.open(sheet)
    assert sheet_img.height / sheet_img.width > got.height / got.width + 0.15


def test_render_card_photo_layout_matches_render_marked_photo(photo, tmp_path):
    a = render_card(STEP, 9, photo, LIVE_FIVE, tmp_path / "a.jpg", layout="photo")
    b = render_marked_photo(photo, LIVE_FIVE, tmp_path / "b.jpg", step=STEP)
    assert a.read_bytes() == b.read_bytes()


def test_the_printed_sheet_says_what_it_did_not_draw(photo, tmp_path):
    """The three warnings that lost the red mark are not silently gone — the legend
    prints them. This asserts the rows exist by rendering twice: a sheet built from
    five boxes must be taller than the same sheet built from the two it draws."""
    from stepspotter.marker import choose_marks as cm

    kept = [m.box for m in cm(LIVE_FIVE, STEP)[0]]
    tall = Image.open(render_card(STEP, 9, photo, LIVE_FIVE, tmp_path / "five.jpg"))
    short = Image.open(render_card(STEP, 9, photo, kept, tmp_path / "two.jpg"))
    assert tall.height > short.height


# ------------------------------------------------------------------ the web face


def test_form_b_serves_the_picture_not_the_printed_sheet(isolated_data):
    """GET /card must come back with the person's photo and its marks — same shape as
    the photo they took. A printed sheet (title band + legend) cannot be that shape,
    which is how the duplicated-text bug shows up from outside."""
    import io

    from fastapi.testclient import TestClient
    from stepspotter.guide import JobService
    from stepspotter.models import Plan
    from stepspotter.web.app import create_app

    def _plan(task, photo, model_id=None):
        return Plan(job_title="Panel job", safety_class="diy_ok", steps=[STEP])

    service = JobService(
        plan_fn=_plan,
        verify_fn=lambda step, photo, model_id=None: None,
        locate_fn=lambda step, photo, model_id=None: list(LIVE_FIVE),
    )
    client = TestClient(create_app(service))
    buf = io.BytesIO()
    Image.new("RGB", (900, 600), (90, 110, 140)).save(buf, format="JPEG")
    r = client.post(
        "/api/jobs", data={"task": "punch down the cable"},
        files={"photo": ("panel.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    card = client.get(f"/api/jobs/{job_id}/card")
    assert card.status_code == 200 and card.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(card.content))
    assert abs(img.width / img.height - 900 / 600) < 0.01
