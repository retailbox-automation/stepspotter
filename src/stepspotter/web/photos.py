"""Photos arriving from a phone camera, made safe for the rest of the pipeline.

Two things are true of every phone upload and of no test fixture:

* it is big — 3 to 12 MB, 4000px on the long edge. Bedrock re-encodes it anyway
  (vision.load_photo caps at 1280px), so carrying the original around only costs
  disk and upload time;
* it is EXIF-rotated. iPhones store the sensor frame plus an orientation tag. PIL
  ignores that tag, so a portrait photo lands sideways, the marker draws its boxes
  on a sideways picture, and the verifier judges a sideways picture. Applying
  ``ImageOps.exif_transpose`` once, here at the door, is the only place this has to
  be remembered.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

MAX_PX = 1600


def save_upload(raw: bytes, dest: Path, max_px: int = MAX_PX) -> Path:
    """Write one uploaded photo to ``dest`` as an upright, downscaled JPEG."""
    if not raw:
        raise ValueError("that upload was empty")
    dest.parent.mkdir(parents=True, exist_ok=True)
    from io import BytesIO

    img = Image.open(BytesIO(raw))
    img = ImageOps.exif_transpose(img)  # honour the phone's orientation tag
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, max_px / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    img.save(dest, format="JPEG", quality=88)
    return dest
