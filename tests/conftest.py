"""Shared fixtures. Tests never write into the repo's data/ dir, never read the manual
cache the repo ships, and never call a model unless they are marked `integration`.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: Six real photos of a home low-voltage panel, the same set both spikes ran on.
PHOTOS = (
    ROOT.parent / "docs" / "design-reference-2026-09-09" / "raw-photos-onq"
)


@pytest.fixture
def photo() -> str:
    p = PHOTOS / "03-telecom-module.jpg"
    if not p.is_file():
        pytest.skip(f"reference photos not available at {PHOTOS}")
    return str(p)


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Point every job/trace/card write at a tmp dir for the duration of one test.

    ``STEPSPOTTER_RESEARCH=0`` goes with it: the default JobService now looks a
    product up on the open web before planning, and a test suite must not depend on
    a search engine. A test that wants the lookup injects its own fake search, which
    the switch does not touch.
    """
    monkeypatch.setenv("STEPSPOTTER_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("STEPSPOTTER_RESEARCH", "0")
    # The repo ships a read-only manual cache (data/manuals/) that the container image
    # copies in, and research.py reads it when the writable cache misses. A test must
    # not silently pass because the real ePX3030 answer was sitting there: point the
    # bundled dir at a path that does not exist. A test that wants it sets it itself.
    monkeypatch.setenv("STEPSPOTTER_MANUALS", str(tmp_path / "no-bundled-cache"))
    yield tmp_path / "data"


def has_aws() -> bool:
    return bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))


needs_aws = pytest.mark.skipif(not has_aws(), reason="no AWS credentials in the environment")
