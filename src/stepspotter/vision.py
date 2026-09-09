"""Shared plumbing for the three model-facing agents: photos in, typed answers out.

Verified against strands-agents 1.54.0 (spikes A and B, 2026-09-09):

* content blocks are the Bedrock converse shape —
  ``{"image": {"format": "jpeg", "source": {"bytes": ...}}}``; ``format`` is a bare
  string, not a MIME type;
* ``Agent.structured_output(...)`` is DEPRECATED — pass
  ``structured_output_model=`` into the invocation and read ``.structured_output``;
* a fresh ``Agent`` per call, always: reusing one leaks the previous photo into the
  conversation history and the next answer describes the wrong picture.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import TypeVar

from PIL import Image
from pydantic import BaseModel

from strands import Agent
from strands.models import BedrockModel

M = TypeVar("M", bound=BaseModel)

REGION = os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
#: Leave unset for the Strands/Bedrock default (global.anthropic.claude-sonnet-4-6),
#: which is the vision model both spikes ran on.
MODEL_ID = os.environ.get("STEPSPOTTER_MODEL") or None
MAX_PX = 1280


class PhotoMissing(FileNotFoundError):
    """The photo the person referred to is not on disk."""


def load_photo(path: str | Path, max_px: int = MAX_PX) -> tuple[bytes, Image.Image]:
    """Read a photo, downscale it, and return (jpeg bytes for the model, PIL image)."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise PhotoMissing(f"No photo at {p}")
    img = Image.open(p).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_px / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue(), img


def image_block(jpeg_bytes: bytes) -> dict:
    return {"image": {"format": "jpeg", "source": {"bytes": jpeg_bytes}}}


def make_agent(system_prompt: str, model_id: str | None = None) -> Agent:
    """A fresh single-shot agent. No tools, no callback noise, no shared history."""
    kwargs: dict = {"region_name": REGION}
    mid = model_id or MODEL_ID
    if mid:
        kwargs["model_id"] = mid
    return Agent(
        model=BedrockModel(**kwargs),
        system_prompt=system_prompt,
        callback_handler=None,
    )


def ask_typed(
    system_prompt: str,
    text: str,
    schema: type[M],
    jpeg_bytes: bytes | None = None,
    model_id: str | None = None,
) -> M:
    """One structured-output call, with or without a photo attached."""
    blocks: list[dict] = [{"text": text}]
    if jpeg_bytes is not None:
        blocks.append(image_block(jpeg_bytes))
    agent = make_agent(system_prompt, model_id)
    result = agent(blocks, structured_output_model=schema)
    out = result.structured_output
    if out is None:  # pragma: no cover - model refused to fill the schema
        raise RuntimeError("the model returned no structured output")
    return out
