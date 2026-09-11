"""Where the manual came from — cache, image, index, DuckDuckGo, Brave — offline.

The demo risk this file exists for: App Runner throws the filesystem away between
containers, so a judge's request starts with an empty cache, and on 2026-09-11
DuckDuckGo answered this machine with HTTP 202 (its rate-limit challenge) for every
query. That combination degrades silently — the plan is simply ungrounded and looks
the same on screen. Each test below pins one rung of the ladder that replaces it:

    cache -> the copy baked into the image -> the checked index -> DDG -> Brave -> none

Nothing here opens a socket: search, download and page fetch are all injected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stepspotter import research
from stepspotter.research import Hit, find_manual, research_product, slug

BRAVE_FIXTURE = Path(__file__).parent / "fixtures" / "brave_sample.html"
MANUAL_PDF = "https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf"
TASK = "assemble my Westinghouse ePX3030 pressure washer"
REPO_INDEX = Path(__file__).resolve().parents[1] / "data" / "manuals" / "index.json"


@pytest.fixture(autouse=True)
def research_on(monkeypatch):
    """conftest switches research off for the suite; these tests are about it."""
    monkeypatch.setenv("STEPSPOTTER_RESEARCH", "1")


@pytest.fixture
def bundled(tmp_path, monkeypatch) -> Path:
    """An empty read-only manual dir, standing in for the one inside the image."""
    d = tmp_path / "image-manuals"
    d.mkdir()
    monkeypatch.setenv(research.MANUALS_ENV, str(d))
    return d


def bake(directory: Path, product: str, pages: list[int] | None = None) -> Path:
    """Write the kind of entry tools/bake_manual_cache.py produces: excerpt, no PDF."""
    res = research.Research(
        product=product,
        status="found",
        manual_url=MANUAL_PDF,
        manual_path=None,
        manual_pages=pages or [10, 11],
        excerpt="[p.10]\nASSEMBLY\nAttach the handle with the two bolts.",
        source="index",
        note="cached excerpt only — the PDF itself is not shipped",
    )
    path = directory / f"{slug(product)}.json"
    path.write_text(res.model_dump_json(indent=2))
    return path


def exploding_search(query: str):
    raise AssertionError(f"the network was used for {query!r}")


def fake_download(tmp_path: Path):
    """A downloader that writes a one-page PDF we can read back, and records the URL."""
    got: list[str] = []

    def _download(url: str) -> str | None:
        from pypdf import PdfWriter

        dest = tmp_path / (slug(url.rsplit("/", 1)[-1]) + ".pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with dest.open("wb") as fh:
            writer.write(fh)
        got.append(url)
        return str(dest)

    return _download, got


def _pages() -> list[str]:
    return ["cover", "contents", "safety", "ASSEMBLY\nFit the handle.", "more assembly"]


# -- rung 1 and 2: the two caches ---------------------------------------------------


def test_the_copy_baked_into_the_image_answers_with_no_network(bundled):
    """The judge's first request: empty writable cache, image cache does the work."""
    bake(bundled, "Westinghouse ePX3030")

    found = research_product(TASK, search_fn=exploding_search, download_fn=exploding_search)

    assert found.status == "found"
    assert found.source == "bundled"
    assert found.manual_url == MANUAL_PDF
    assert found.usable                      # an excerpt with no PDF beside it is enough
    assert found.manual_path is None
    assert "originally found via index" in found.trail[0]


def test_the_writable_cache_wins_over_the_image_copy(bundled, tmp_path, monkeypatch):
    """A lookup this container already did beats the one shipped months ago."""
    bake(bundled, "Westinghouse ePX3030", pages=[10, 11])
    fresh = research.cache_path("Westinghouse ePX3030")
    fresh.parent.mkdir(parents=True, exist_ok=True)
    bake(fresh.parent, "Westinghouse ePX3030", pages=[99])

    found = research_product(TASK, search_fn=exploding_search)

    assert found.source == "cache"
    assert found.manual_pages == [99]


def test_the_image_copy_is_never_written_to(bundled):
    """The bundled dir is read-only by contract: a miss must not land in it."""
    bake(bundled, "Westinghouse ePX3030")
    before = sorted(p.name for p in bundled.iterdir())

    research_product("assemble my Ryobi RY31099 thing", search_fn=lambda q: [], use_cache=True)

    assert sorted(p.name for p in bundled.iterdir()) == before
    assert not (bundled / "ryobi-ry31099.json").exists()


# -- rung 3: the checked index ------------------------------------------------------


def test_the_index_goes_straight_to_the_makers_url_and_never_searches(
    bundled, tmp_path, monkeypatch
):
    """With the model in the index there is no search for the manual at all."""
    (bundled / research.INDEX_NAME).write_text(
        json.dumps({"manuals": {"westinghouse-epx3030": {"url": MANUAL_PDF}}})
    )
    monkeypatch.setattr(research, "read_pdf_pages", lambda path: _pages())
    download, got = fake_download(tmp_path)
    searched: list[str] = []

    found = research_product(
        TASK,
        search_fn=lambda q: searched.append(q) or [],
        download_fn=download,
    )

    assert found.status == "found"
    assert found.source == "index"
    assert got == [MANUAL_PDF]
    # only the video query was searched; the manual never needed an engine
    assert searched == ["Westinghouse ePX3030 assembly video youtube"]
    assert any("cache: nothing cached" in line for line in found.trail)


def test_an_index_url_that_will_not_download_falls_through_to_the_search(bundled, tmp_path, monkeypatch):
    """A dead link in the index must not become "no manual" — the engines still run."""
    (bundled / research.INDEX_NAME).write_text(
        json.dumps({"manuals": {"westinghouse-epx3030": {"url": "https://example.com/gone.pdf"}}})
    )
    monkeypatch.setattr(research, "read_pdf_pages", lambda path: _pages())
    download, got = fake_download(tmp_path)

    def picky_download(url: str) -> str | None:
        return None if "example.com" in url else download(url)

    hits = [Hit(title="the maker's PDF", url=MANUAL_PDF)]
    trail: list[str] = []
    manual = find_manual(
        "Westinghouse ePX3030", search_fn=lambda q: hits, download_fn=picky_download, trail=trail
    )

    assert manual is not None and manual.url == MANUAL_PDF
    assert manual.source == "search_fn"
    assert any("would not download" in line for line in trail)


def test_a_model_that_is_not_in_the_index_says_so_in_the_trail(bundled):
    (bundled / research.INDEX_NAME).write_text(json.dumps({"manuals": {}}))
    trail: list[str] = []

    find_manual("Acme ZZ9000", search_fn=lambda q: [], trail=trail)

    assert trail and "no entry for acme-zz9000" in trail[0]


# -- rung 4 and 5: the two engines --------------------------------------------------


def rate_limited_ddg_then_brave(monkeypatch):
    """A fetch seam that reproduces 2026-09-11: DDG answers 202, Brave answers 200."""
    seen: list[str] = []
    brave_body = BRAVE_FIXTURE.read_text()

    def _fetch(url: str, timeout: float = 10, data: bytes | None = None) -> tuple[int, str]:
        seen.append(url)
        if "duckduckgo.com" in url:
            return 202, "<html><body>anomalous traffic, solve this challenge</body></html>"
        if url.startswith(research.SEARCH_BRAVE):
            return 200, brave_body
        return 0, ""

    return _fetch, seen


def test_duckduckgo_rate_limited_falls_through_to_brave(tmp_path, monkeypatch):
    fetch_fn, seen = rate_limited_ddg_then_brave(monkeypatch)
    monkeypatch.setattr(research, "read_pdf_pages", lambda path: _pages())
    download, got = fake_download(tmp_path)
    trail: list[str] = []

    manual = find_manual(
        "Westinghouse ePX3030",
        download_fn=download,
        fetch_fn=fetch_fn,
        use_index=False,
        trail=trail,
    )

    assert manual is not None
    assert manual.url == MANUAL_PDF          # Brave put the maker's own PDF at rank 0
    assert manual.source == "brave"
    assert any("HTTP 202" in line for line in trail), trail
    assert any("duckduckgo.com" in u for u in seen)   # DDG really was tried first


def test_search_all_names_the_engine_that_answered_and_why_the_first_did_not(monkeypatch):
    fetch_fn, _seen = rate_limited_ddg_then_brave(monkeypatch)

    hits, engine, skipped = research.search_all("Westinghouse ePX3030 manual", fetch_fn=fetch_fn)

    assert engine == "brave"
    assert hits and hits[0].url == MANUAL_PDF
    assert skipped == ["duckduckgo: HTTP 202, the rate-limit challenge page"]


def test_both_engines_down_is_an_empty_answer_with_two_reasons(monkeypatch):
    def dead(url: str, timeout: float = 10, data: bytes | None = None) -> tuple[int, str]:
        return 0, ""

    hits, engine, skipped = research.search_all("anything", fetch_fn=dead)

    assert hits == [] and engine == ""
    assert len(skipped) == 2
    assert "duckduckgo" in skipped[0] and "brave" in skipped[1]


def test_parse_brave_hits_reads_the_results_and_ignores_the_chrome():
    hits = research.parse_brave_hits(BRAVE_FIXTURE.read_text())

    assert hits[0].url == MANUAL_PDF
    urls = [h.url for h in hits]
    assert len(urls) == len(set(urls))                       # deduped
    assert all("brave.com" not in u and "brave.app" not in u for u in urls)
    assert not any("hackerone.com" in u for u in urls)       # the footer is not a result


# -- the floor: nothing found, and what it must not break ---------------------------


def test_a_dead_search_never_shadows_the_manual_baked_into_the_image(bundled):
    """The worst realistic demo minute: no cache of our own, no engines, image saves it."""
    bake(bundled, "Westinghouse ePX3030")

    blocked = research_product(TASK, search_fn=lambda q: [], use_cache=False)
    assert blocked.status == "not_found"          # this run is honest about itself
    assert blocked.source == "none"
    assert blocked.trail                           # and says what it tried

    # nothing was written that could hide the good answer from the next request
    assert not research.cache_path("Westinghouse ePX3030").exists()
    assert research_product(TASK, search_fn=exploding_search).status == "found"


def test_the_switch_still_short_circuits_before_any_source(monkeypatch, bundled):
    bake(bundled, "Westinghouse ePX3030")
    monkeypatch.setenv("STEPSPOTTER_RESEARCH", "0")

    off = research_product(TASK, search_fn=exploding_search)

    assert off.status == "no_product" and off.source == "none"


# -- the cache we actually ship -----------------------------------------------------


def test_the_index_we_ship_is_honest_about_every_url():
    """Repo integrity, no network: every listed manual carries its check and its date."""
    raw = json.loads(REPO_INDEX.read_text())
    assert raw["_checked"] and raw["_how_checked"]
    assert raw["manuals"], "the index ships with no models"
    for key, entry in raw["manuals"].items():
        assert key == slug(key), f"{key} is not a lookup key research.slug would produce"
        assert entry["url"].startswith("https://"), key
        assert entry["checked"] and entry["result"].startswith("200 "), key
        assert entry["what"] and entry["host"], key


def test_every_baked_entry_is_loadable_and_grounds_a_plan():
    """A baked file with no excerpt would ship a demo that silently is not grounded."""
    baked = sorted(p for p in REPO_INDEX.parent.glob("*.json") if p.name != research.INDEX_NAME)
    assert baked, "no manual is baked into the image"
    for path in baked:
        res = research.Research.model_validate_json(path.read_text())
        assert res.status == "found" and res.usable, path.name
        assert res.manual_url and res.manual_pages, path.name
        assert res.manual_path is None, f"{path.name} points at a PDF that is not shipped"
        assert path.name == f"{slug(res.product)}.json"


# -- the source has to reach the screen, not just the object ------------------------


def test_the_job_trace_and_the_api_carry_where_the_manual_came_from(bundled, tmp_path):
    """A grounded run and an ungrounded one must not look the same to a judge.

    The chain checked here is the whole point of the feature: baked cache -> Research
    -> the job's trace -> the JSON the phone renders. If any link drops the source,
    the page shows a manual link with no way to tell it came from the image rather
    than from a live search that might have failed.
    """
    import io

    from fastapi.testclient import TestClient
    from PIL import Image

    from stepspotter import store
    from stepspotter.guide import JobService
    from stepspotter.models import Plan, Step
    from stepspotter.web.app import create_app

    bake(bundled, "Westinghouse ePX3030")

    def _plan(task, photo, model_id=None, research=None) -> Plan:
        assert research is not None and research.usable, "the planner got no manual"
        return Plan(
            job_title="Assemble the pressure washer",
            safety_class="diy_ok",
            steps=[
                Step(
                    id=1,
                    title="Fit the handle",
                    action="Slide the handle on and put the two bolts in.",
                    evidence_required="both bolts in the handle",
                    source="manual p.10",
                )
            ],
        )

    service = JobService(plan_fn=_plan)
    client = TestClient(create_app(service))
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 120, 120)).save(buf, format="JPEG")

    created = client.post(
        "/api/jobs",
        data={"task": TASK},
        files={"photo": ("start.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["job_id"]

    rows = [r for r in store.read_trace(job_id) if r["event"] == "research"]
    assert rows, "the trace has no research row"
    assert rows[0]["source"] == "bundled"
    assert "baked into the image" in rows[0]["source_words"]
    assert rows[0]["manual_url"] == MANUAL_PDF

    shown = client.get(f"/api/jobs/{job_id}").json()["research"]
    assert shown["status"] == "found"
    assert shown["source"] == "bundled"
    assert "baked into the image" in shown["source_words"]
    assert shown["manual_url"] == MANUAL_PDF


def test_the_cli_prints_the_source_and_the_trail(bundled, capsys):
    from stepspotter.cli import main

    bake(bundled, "Westinghouse ePX3030")
    code = main(["research", "Westinghouse ePX3030"])
    out = capsys.readouterr().out

    assert code == 0
    assert "source:  bundled" in out
    assert "baked into the image" in out
    assert "tried:" in out


# -- a rejection keeps its status code ----------------------------------------------


def test_a_rejected_fetch_reports_the_status_the_server_gave(monkeypatch):
    """429 must not be flattened to 0: one is a rate limit, the other is a dead host.

    Live, 2026-09-11: a burst of six lookups had DuckDuckGo answering 202 and Brave
    answering 429. "brave: HTTP 429" is something a person can act on (wait, or bake
    the model into the cache); "brave: HTTP 0" reads as "the internet is broken".
    """
    import urllib.error

    def raising(req, timeout):
        raise urllib.error.HTTPError(
            "https://search.brave.com/search", 429, "Too Many Requests", {}, None
        )

    monkeypatch.setattr(research, "_open", raising)

    assert research.fetch("https://search.brave.com/search?q=x") == (429, "")
    hits, why = research.search_brave("anything")
    assert hits == [] and why == "brave: HTTP 429"


def test_a_host_that_never_answers_is_still_status_zero(monkeypatch):
    def dead(req, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(research, "_open", dead)

    assert research.fetch("https://html.duckduckgo.com/html/?q=x") == (0, "")
    _hits, why = research.search_ddg("anything")
    assert "no answer at all" in why
