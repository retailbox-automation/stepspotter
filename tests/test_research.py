"""Finding the manufacturer's manual, entirely offline.

Every seam that touches the network is injected here — search, download, page fetch —
so this file proves the parsing, the ranking, the page-picking and the caching without
opening a socket. The one thing it deliberately asserts about the network is negative:
with the switch off, the fake search is never called at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stepspotter import research
from stepspotter.research import (
    Hit,
    extract_assembly,
    guess_product,
    parse_hits,
    research_product,
    slug,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ddg_sample.html"
MANUAL_PDF = "https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf"


@pytest.fixture(autouse=True)
def research_on(monkeypatch):
    """conftest switches research off for the whole suite; this file is the exception.

    Nothing here reaches the network anyway — every seam is injected — but the switch
    short-circuits before the seams, so it has to come back on to test them at all.
    """
    monkeypatch.setenv("STEPSPOTTER_RESEARCH", "1")


# -- reading the product out of what a person typed --------------------------------


@pytest.mark.parametrize(
    "task, expected",
    [
        ("assemble my Westinghouse ePX3030 pressure washer", "Westinghouse ePX3030"),
        ("attach the Ryobi RY31012 surface cleaner", "Ryobi RY31012"),
        ("my APC BX1350M battery backup needs a new battery", "APC BX1350M"),
        ("Install the Honeywell TH6220 thermostat on the hallway wall", "Honeywell TH6220"),
        # negatives — and a negative is the whole safety valve: no product, no network
        ("fix the leaking kitchen faucet", None),
        ("assemble my new pressure washer out of the box", None),
        # a year is a date, not a model number
        ("I bought this in 2026 and want to hang a shelf", None),
    ],
)
def test_guess_product(task, expected):
    assert guess_product(task) == expected


def test_slug_is_windows_safe():
    assert slug("Westinghouse ePX3030") == "westinghouse-epx3030"
    assert slug("Ryobi RY-310/12") == "ryobi-ry-310-12"
    assert ":" not in slug("A:B") and "/" not in slug("A/B")


# -- parsing a real-shaped results page --------------------------------------------


def test_parse_hits_unwraps_the_redirector_and_drops_the_noise():
    hits = parse_hits(FIXTURE.read_text())
    urls = [h.url for h in hits]

    assert urls == [
        MANUAL_PDF,
        "https://www.manualslib.com/manual/123456/Westinghouse-Epx3030.html",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    # the ad and DuckDuckGo's own logo link are not results
    assert not any("example-ad" in u or "duckduckgo.com" in u for u in urls)
    # titles come back as text, with entities decoded and <b> stripped
    assert hits[0].title.startswith("ePX3030 Owner's Manual")
    assert hits[2].title == "Westinghouse ePX3030 assembly video"


# -- picking the pages a beginner needs --------------------------------------------


def _pages() -> list[str]:
    return [
        "COVER PAGE\nePX3030 Electric Pressure Washer",       # p.1
        "TABLE OF CONTENTS\nSafety .... 3\nAssembly .... 3",   # p.2
        "SAFETY RULES\nRead everything before use.",           # p.3
        "INCLUDED LIST\n1 x Handle\n2 x Screw\n1 x Lance",     # p.4
        "ASSEMBLY\nFit the handle onto the frame.",            # p.5
        "CONNECTING THE GARDEN HOSE\nAttach the inlet.",       # p.6
        "WARRANTY\nOne year, parts and labour.",               # p.7
    ]


def test_extract_assembly_picks_the_marked_pages_and_labels_them():
    ex = extract_assembly(_pages())

    assert ex.pages == [4, 5, 6]      # 1-based, and the warranty page is not in it
    assert ex.note is None
    assert "[p.4]" in ex.text and "[p.5]" in ex.text and "[p.6]" in ex.text
    assert "INCLUDED LIST" in ex.text and "1 x Handle" in ex.text
    assert "WARRANTY" not in ex.text


def test_extract_assembly_falls_back_after_the_contents_and_says_so():
    pages = [
        "COVER",
        "TABLE OF CONTENTS\nthings .... 4",
        "chapter one",
        "chapter two",
    ]
    ex = extract_assembly(pages)

    assert ex.pages == [3, 4]
    assert ex.note and "no assembly heading" in ex.note
    assert "[p.3]" in ex.text


def test_extract_assembly_is_capped_and_survives_an_empty_manual():
    big = ["ASSEMBLY " + "x" * 20000, "ASSEMBLY " + "y" * 20000]
    ex = extract_assembly(big)
    assert len(ex.text) <= research.MAX_EXCERPT_CHARS

    empty = extract_assembly([])
    assert empty.pages == [] and empty.note


# -- the whole lookup, with the network faked --------------------------------------


class FakeSearch:
    """Answers the manual query and the video query; counts every call."""

    def __init__(self, hits: list[Hit] | None = None) -> None:
        self.calls: list[str] = []
        self.hits = hits if hits is not None else parse_hits(FIXTURE.read_text())

    def __call__(self, query: str) -> list[Hit]:
        self.calls.append(query)
        return list(self.hits)


def fake_download(tmp_path: Path):
    """A downloader that writes a one-page 'PDF' we can read back with pypdf."""
    written: list[str] = []

    def _download(url: str) -> str | None:
        from pypdf import PdfWriter

        dest = tmp_path / (slug(url.rsplit("/", 1)[-1]) + ".pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with dest.open("wb") as fh:
            writer.write(fh)
        written.append(url)
        return str(dest)

    return _download, written


def test_research_product_finds_the_manual_and_caches_the_answer(tmp_path, monkeypatch):
    """The real shape of a run: search, download, read pages, cache, reuse the cache."""
    search = FakeSearch()

    # pypdf on a blank page gives no text, so stand in the pages the manual would have
    monkeypatch.setattr(research, "read_pdf_pages", lambda path: _pages())
    download, downloaded = fake_download(tmp_path)

    found = research_product(
        "assemble my Westinghouse ePX3030 pressure washer",
        search_fn=search,
        download_fn=download,
    )

    assert found.status == "found"
    assert found.product == "Westinghouse ePX3030"
    assert found.manual_url == MANUAL_PDF          # the maker's own PDF outranks ManualsLib
    assert downloaded == [MANUAL_PDF]              # and ManualsLib was never downloaded
    assert found.manual_pages == [4, 5, 6]
    assert "[p.4]" in found.excerpt
    assert [v.url for v in found.videos] == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]

    # the answer is on disk, keyed by the product, and the second call is free
    cached = research.cache_path("Westinghouse ePX3030")
    assert cached.is_file()
    assert json.loads(cached.read_text())["manual_url"] == MANUAL_PDF

    again = research_product("assemble my Westinghouse ePX3030 pressure washer")
    assert again.manual_url == MANUAL_PDF
    assert search.calls == ["Westinghouse ePX3030 owner's manual pdf",
                            "Westinghouse ePX3030 assembly video youtube"]


def test_no_product_in_the_task_means_no_search_at_all():
    search = FakeSearch()
    found = research_product("fix the leaking kitchen faucet", search_fn=search)

    assert found.status == "no_product"
    assert search.calls == []


def test_the_switch_stops_it_before_any_lookup(monkeypatch):
    """STEPSPOTTER_RESEARCH=0 has to short-circuit, not just discard the result."""
    monkeypatch.setenv("STEPSPOTTER_RESEARCH", "0")
    search = FakeSearch()

    found = research_product("assemble my Westinghouse ePX3030 pressure washer", search_fn=search)

    assert found.status == "no_product"
    assert "switched off" in (found.note or "")
    assert search.calls == []


def test_a_download_that_fails_is_a_status_not_an_exception():
    search = FakeSearch()
    found = research_product(
        "assemble my Westinghouse ePX3030 pressure washer",
        search_fn=search,
        download_fn=lambda url: None,      # every candidate refuses to download
        fetch_fn=lambda url, timeout=10: (0, ""),   # and the aggregator page is dead too
    )

    assert found.status == "not_found"
    assert found.manual_url is None
    assert found.product == "Westinghouse ePX3030"
    assert [v.url for v in found.videos] == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_a_raising_search_is_reported_as_failed_and_never_cached():
    def boom(query: str):
        raise TimeoutError("the search engine did not answer")

    found = research_product("assemble my Westinghouse ePX3030 pressure washer", search_fn=boom)

    assert found.status == "failed"
    assert "did not answer" in (found.note or "")
    assert not research.cache_path("Westinghouse ePX3030").is_file()


def test_search_never_raises_when_the_network_is_gone(monkeypatch):
    monkeypatch.setattr(research, "fetch", lambda *a, **k: (0, ""))
    assert research.search("anything at all") == []


def test_summarize_reads_like_something_a_person_would_hear(monkeypatch):
    search = FakeSearch()
    monkeypatch.setattr(research, "read_pdf_pages", lambda path: _pages())
    monkeypatch.setattr(research, "download", lambda url, *a, **k: "/dev/null.pdf")

    found = research_product("my Westinghouse ePX3030 arrived", search_fn=search)
    text = research.summarize(found)

    assert MANUAL_PDF in text
    assert "1 x Handle" in text          # the included list, read off the excerpt
    assert "youtube.com" in text


# ------------------------------------------------------ whose PDF is this, really


def test_a_two_letter_brand_does_not_claim_every_host_containing_those_letters():
    """The rank-0 slot means "the maker's own site". A substring test gives it away.

    "lg" sits inside "manualguide", "ge" inside "packagedocs" — a bare
    ``brand in host`` hands a stranger's PDF the top of the list for any short brand.
    """
    assert not research.is_manufacturer_host("manualguide.com", "lg")
    assert not research.is_manufacturer_host("packagedocs.com", "ge")
    assert not research.is_manufacturer_host("bestmanuals.com", "man")

    # the brand's own hosts still count: a whole label, a hyphen-separated word,
    # or — for a brand long enough to be no coincidence — the start of a label
    assert research.is_manufacturer_host("support.ge.com", "ge")
    assert research.is_manufacturer_host("lg-electronics.com", "lg")
    assert research.is_manufacturer_host("cdn.westinghouseoutdoorpower.com", "westinghouse")
    assert research.is_manufacturer_host("ryobitools.com", "ryobi")


def test_an_unrelated_pdf_ranks_below_the_makers_own_for_a_short_brand():
    """End of the same defect, at the ranking layer the picker actually uses."""
    stranger = research.Hit(title="LG TV manual", url="https://manualguide.com/lg/tv.pdf")
    maker = research.Hit(title="LG TV manual", url="https://www.lg.com/manuals/tv.pdf")

    assert research._rank(stranger, "lg") == 1   # a PDF, but not the maker's
    assert research._rank(maker, "lg") == 0


def test_a_rate_limited_run_never_downgrades_a_manual_we_already_found(tmp_path, monkeypatch):
    """A search engine having a bad minute must not empty a good cache.

    Real event, 09.09: DuckDuckGo answered HTTP 202 with a challenge page — zero
    results, indistinguishable from "no manual exists" — and a ``--fresh`` run
    replaced the working ePX3030 entry with a not_found one. The next plan would
    have been ungrounded with nothing on screen to say so.
    """
    search = FakeSearch()
    monkeypatch.setattr(research, "read_pdf_pages", lambda path: _pages())
    download, _ = fake_download(tmp_path)

    good = research_product(
        "assemble my Westinghouse ePX3030 pressure washer",
        search_fn=search,
        download_fn=download,
    )
    assert good.status == "found"

    # now the engine goes quiet: every query comes back empty, as under a rate limit
    blocked = research_product(
        "assemble my Westinghouse ePX3030 pressure washer",
        search_fn=lambda query: [],
        use_cache=False,
    )
    assert blocked.status == "not_found"          # this run is honest about itself
    on_disk = json.loads(research.cache_path("Westinghouse ePX3030").read_text())
    assert on_disk["status"] == "found"           # but the good answer is still there
    assert on_disk["manual_url"] == MANUAL_PDF

    # and the next ordinary run reads the manual back, not the bad minute
    assert research_product("assemble my Westinghouse ePX3030 pressure washer").manual_url == MANUAL_PDF
