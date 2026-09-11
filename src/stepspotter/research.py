"""Research — find the manufacturer's own manual before writing a single step.

Why this exists: the first real job this was built for was a Westinghouse ePX3030
pressure washer out of the box. There is no assembly video for that model, and the
model's memory of it is a guess. The official PDF, on the other hand, exists, names
every part, and puts the assembly on pages 10-12. A plan that follows the manual's
order and part names is a plan the person can check against the paper in the box.

Everything here is best-effort and must never raise into the planner: a repair with
no manual is still a repair. Three seams are injectable (``search_fn``,
``download_fn``, ``fetch_fn``) so the tests run offline, and the whole module can be
switched off with ``STEPSPOTTER_RESEARCH=0`` — which returns before any socket opens.

No API key anywhere, and five places to look, in this order: the cache written by an
earlier run, the cache baked into the container image, a hand-checked index of models
we film with, DuckDuckGo, and Brave. Whichever one answers is written into the job's
trace, along with why the ones before it did not — a demo that quietly fell back to
"no manual" should say so on screen, not look identical to a grounded one.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from stepspotter import store

#: A desktop browser UA. DuckDuckGo's HTML endpoint answers a bare urllib UA with a
#: challenge page that parses to zero hits — which looks exactly like "no results".
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SEARCH_HTML = "https://html.duckduckgo.com/html/"
SEARCH_LITE = "https://lite.duckduckgo.com/lite/"

#: The second engine, tried only when DuckDuckGo gives us nothing. Checked live on
#: 2026-09-11 from this machine: DuckDuckGo answered **HTTP 202** with a challenge
#: page for every query (the rate limit; it parses to zero hits and is indistinguish-
#: able from "no manual exists"), while Brave answered 200 and put the manufacturer's
#: own PDF at rank 0 for "Westinghouse ePX3030 manual pdf". No key, no account.
#: Also checked and rejected that day: Mojeek (captcha page), Ecosia (HTTP 403),
#: Bing's RSS feed (200, but the results had nothing to do with the query).
SEARCH_BRAVE = "https://search.brave.com/search"

#: A hand-checked model -> manual URL map, shipped next to the cache. Every URL in it
#: was fetched with curl and came back 200 with a PDF content type; the file records
#: the date. It exists because a search engine is a moving part and a demo is not the
#: moment to discover that.
INDEX_NAME = "index.json"

#: Read-only manual cache shipped inside the image (``COPY data/manuals``). The env
#: var is what the Dockerfiles set; in a source tree the repo's own data/manuals is
#: found without it.
MANUALS_ENV = "STEPSPOTTER_MANUALS"

#: Pages worth reading to a beginner holding a box of parts. Case-insensitive.
ASSEMBLY_MARKERS = (
    "ASSEMBLY",
    "INCLUDED LIST",
    "INSTALLING",
    "CONNECTING",
    "STARTING AND STOPPING",
    "INSTALLING NOZZLES",
)

MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_EXCERPT_CHARS = 7000
FALLBACK_PAGES = 6

#: Aggregator sites that host manuals behind a viewer page rather than a direct PDF.
#: Accepted only when a real PDF link can be pulled off the page.
AGGREGATORS = ("manualslib.com", "manuals.plus", "manua.ls")


# ---------------------------------------------------------------- typed shapes


class Hit(BaseModel):
    """One search result: what it called itself, and where it points."""

    title: str = ""
    url: str


class VideoHit(BaseModel):
    """A video someone else already made of this exact model. Title only, no download."""

    title: str = ""
    url: str


class Excerpt(BaseModel):
    """The part of the manual a beginner needs, with the page it came from attached."""

    text: str = ""
    pages: list[int] = Field(default_factory=list, description="1-based PDF page numbers")
    note: str | None = Field(
        default=None,
        description="set when the pages were guessed rather than matched on a heading",
    )


class ManualHit(BaseModel):
    """A downloaded manual: where it came from, where it now sits, and its text."""

    url: str
    path: str
    pages: list[str] = Field(default_factory=list, description="text of each PDF page")
    source: str = Field(default="", description="index, ddg, brave or search_fn")


class Research(BaseModel):
    """What we found out about the person's actual product before planning anything."""

    product: str = ""
    status: Literal["found", "not_found", "no_product", "failed"] = "no_product"
    manual_url: str | None = None
    manual_path: str | None = None
    manual_pages: list[int] = Field(default_factory=list)
    excerpt: str = ""
    videos: list[VideoHit] = Field(default_factory=list)
    note: str | None = None
    source: str = Field(
        default="",
        description="which of cache/bundled/index/ddg/brave/search_fn answered THIS run",
    )
    trail: list[str] = Field(
        default_factory=list,
        description="what was tried before that, and why it did not answer",
    )

    @property
    def usable(self) -> bool:
        return self.status == "found" and bool(self.excerpt.strip())


# ---------------------------------------------------------------- product name


_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]*")
_YEARISH = re.compile(r"^(19|20)\d{2}$")


def guess_product(task: str) -> str | None:
    """Pull "Brand Model" out of what the person typed, or return None.

    The rule of thumb: a capitalised, all-letters brand word followed within two
    tokens by a token carrying at least two digits — "Westinghouse ePX3030",
    "Ryobi RY31012", "APC BX1350M". Returning None matters as much as matching:
    no product means no network call at all, so a plain "fix the leaking faucet"
    never touches the internet.
    """
    if not task:
        return None
    tokens = _WORD.findall(task)
    for i, tok in enumerate(tokens):
        if len(tok) < 2 or not tok.isalpha() or not tok[0].isupper():
            continue
        for model in tokens[i + 1 : i + 3]:
            digits = sum(ch.isdigit() for ch in model)
            if digits < 2:
                continue
            # A bare year is a date, not a model number ("bought in 2026").
            if _YEARISH.match(model):
                continue
            return f"{tok} {model}"
    return None


def slug(product: str) -> str:
    """Windows-safe cache key: lowercase, every run of non-alphanumerics -> one dash."""
    s = re.sub(r"[^a-z0-9]+", "-", product.lower()).strip("-")
    return s or "product"


# ---------------------------------------------------------------- the network


def _open(req: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed hosts
        return getattr(resp, "status", 200) or 200, resp.read()


def fetch(url: str, timeout: float = 10, data: bytes | None = None) -> tuple[int, str]:
    """GET (or POST) a page as text. Returns (status, body); (0, "") on any failure."""
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        status, raw = _open(req, timeout)
    except Exception:  # noqa: BLE001 - a dead search engine is not a dead repair
        return 0, ""
    return status, raw.decode("utf-8", errors="replace")


_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
_ATTR = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    """Anchor innards as a plain title: tags out, entities decoded, whitespace collapsed.

    The collapse matters: DuckDuckGo bolds the query words, so stripping ``<b>`` from
    "assembly <b>video</b>" otherwise leaves a double space in the middle of a title.
    """
    return " ".join(_html.unescape(_TAGS.sub(" ", fragment)).split())


def unwrap(href: str) -> str:
    """DuckDuckGo wraps results as ``/l/?uddg=<urlencoded>``. Give back the real URL."""
    if "uddg=" not in href:
        return href
    query = href.split("?", 1)[-1]
    for key, values in urllib.parse.parse_qs(query).items():
        if key == "uddg" and values:
            return urllib.parse.unquote(values[0])
    return href


def parse_hits(body: str) -> list[Hit]:
    """Pull result anchors out of a DuckDuckGo HTML or Lite page.

    Attribute order is not stable, so anchors are matched first and their attributes
    read afterwards rather than with one clever regex. ``result__a`` is the HTML
    endpoint's class, ``result-link`` the Lite one; a bare ``uddg=`` link is accepted
    too, because that wrapper is the one thing both pages have always had.
    """
    hits: list[Hit] = []
    seen: set[str] = set()
    for attrs_raw, inner in _ANCHOR.findall(body):
        attrs = dict(_ATTR.findall(attrs_raw))
        href = attrs.get("href", "")
        if not href:
            continue
        # Exact class names, not substrings: the sponsored anchor on the HTML page is
        # ``result__a--ad``, which a substring test happily accepts as a result.
        classes = attrs.get("class", "").split()
        wanted = "result__a" in classes or "result-link" in classes or "uddg=" in href
        if not wanted:
            continue
        url = unwrap(href)
        if not url.startswith("http") or url in seen:
            continue
        if "duckduckgo.com" in urllib.parse.urlparse(url).netloc:
            continue
        seen.add(url)
        hits.append(Hit(title=_text(inner), url=url))
    return hits


def parse_brave_hits(body: str) -> list[Hit]:
    """Pull result anchors out of a Brave Search results page.

    Brave's class names are build hashes (``svelte-14r20fy``) and change without
    notice, so keying on them would rot silently. Instead the results *region* is
    sliced out — everything between ``id="mixed-main"`` and the end of ``<main>`` —
    and every external link inside it is a result. That survives a re-skin, and it
    keeps the header, the sidebar and the footer (which links to hackerone.com and
    to Brave's own status page) out of the hit list.

    Titles come out as "SiteName host > breadcrumb > page title": noisier than
    DuckDuckGo's, and only ever shown next to a video link. The URL is what ranks.
    """
    start = body.find('id="mixed-main"')
    end = body.find("</main>", start if start >= 0 else 0)
    region = body[start:end] if start >= 0 and end > start else body
    hits: list[Hit] = []
    seen: set[str] = set()
    for attrs_raw, inner in _ANCHOR.findall(region):
        href = dict(_ATTR.findall(attrs_raw)).get("href", "")
        if not href.startswith("http"):
            continue
        host = urllib.parse.urlparse(href).netloc.lower()
        if "brave.com" in host or "brave.app" in host:
            continue
        if href in seen:
            continue
        seen.add(href)
        hits.append(Hit(title=_text(inner)[:120], url=href))
    return hits


def search_ddg(
    query: str, timeout: float = 10, fetch_fn: Callable[..., tuple[int, str]] | None = None
) -> tuple[list[Hit], str]:
    """DuckDuckGo, three ways. Returns (hits, why-it-gave-nothing)."""
    getter = fetch_fn or fetch
    encoded = urllib.parse.urlencode({"q": query})
    attempts = (
        (f"{SEARCH_HTML}?{encoded}", None),
        (SEARCH_HTML, encoded.encode()),  # the HTML endpoint prefers a POST
        (f"{SEARCH_LITE}?{encoded}", None),
    )
    seen: list[int] = []
    for url, data in attempts:
        status, body = getter(url, timeout=timeout, data=data)
        seen.append(status)
        if status != 200 or not body:
            continue
        hits = parse_hits(body)
        if hits:
            return hits, ""
    if 202 in seen:
        return [], "duckduckgo: HTTP 202, the rate-limit challenge page"
    if all(st == 0 for st in seen):
        return [], "duckduckgo: no answer at all (offline, or the host is blocked)"
    return [], f"duckduckgo: answered {seen} and parsed to zero results"


def search_brave(
    query: str, timeout: float = 10, fetch_fn: Callable[..., tuple[int, str]] | None = None
) -> tuple[list[Hit], str]:
    """Brave Search. Returns (hits, why-it-gave-nothing)."""
    getter = fetch_fn or fetch
    url = f"{SEARCH_BRAVE}?{urllib.parse.urlencode({'q': query})}"
    status, body = getter(url, timeout=timeout)
    if status != 200 or not body:
        return [], f"brave: HTTP {status}"
    hits = parse_brave_hits(body)
    return hits, "" if hits else "brave: answered 200 but parsed to zero results"


#: Tried in order, first one with hits wins. Name -> function, and the name is what
#: ends up in the trace, so "which engine actually answered" is never a guess.
ENGINES: tuple[tuple[str, Callable[..., tuple[list[Hit], str]]], ...] = (
    ("ddg", search_ddg),
    ("brave", search_brave),
)


def search_all(
    query: str, timeout: float = 10, fetch_fn: Callable[..., tuple[int, str]] | None = None
) -> tuple[list[Hit], str, list[str]]:
    """Every engine until one answers. Returns (hits, engine name, what was skipped)."""
    skipped: list[str] = []
    for name, engine in ENGINES:
        hits, why = engine(query, timeout=timeout, fetch_fn=fetch_fn)
        if hits:
            return hits, name, skipped
        skipped.append(why or f"{name}: no results")
    return [], "", skipped


def search(query: str, timeout: float = 10) -> list[Hit]:
    """Search the open web. Never raises; an empty list means "we could not look"."""
    return search_all(query, timeout=timeout)[0]


def download(url: str, dest_dir: str | None = None, timeout: float = 30) -> str | None:
    """Save a PDF under ``data/manuals/``. Returns the path, or None if it is not a PDF.

    Capped at 30 MB and read in chunks: a mis-ranked hit can be a 400 MB service
    manual, and a repair should not stall on someone else's scan.
    """
    root = store.data_root() / "manuals" if dest_dir is None else Path(dest_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = slug(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1] or "manual") + ".pdf"
    dest = root / name
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    return None
                chunks.append(chunk)
    except Exception:  # noqa: BLE001
        return None
    raw = b"".join(chunks)
    if not raw.startswith(b"%PDF"):
        return None  # an HTML "download" page dressed up as a .pdf link
    dest.write_bytes(raw)
    return str(dest)


_PDF_LINK = re.compile(r'https?://[^\s"\'<>]+\.pdf', re.I)


def derive_pdf_link(page_url: str, fetch_fn: Callable[..., tuple[int, str]] | None = None) -> str | None:
    """Aggregator pages hide the real PDF behind a viewer. Find it, or give up."""
    getter = fetch_fn or fetch
    status, body = getter(page_url, timeout=10)
    if status != 200 or not body:
        return None
    found = _PDF_LINK.findall(body)
    return found[0] if found else None


def read_pdf_pages(path: str) -> list[str]:
    """Text of every page, in order. A page that will not parse comes back empty."""
    import logging

    from pypdf import PdfReader

    # pypdf logs a wall of font-encoding warnings on ordinary manuals. They are not
    # actionable here — the text still comes out — and they bury the CLI's own output.
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    reader = PdfReader(path)
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page must not lose the manual
            pages.append("")
    return pages


# ---------------------------------------------------------------- the pieces


def writable_manuals_dir() -> Path:
    """Where a fresh lookup writes. Ephemeral on App Runner; that is the whole problem."""
    return store.data_root() / "manuals"


def bundled_manuals_dir() -> Path | None:
    """The read-only cache that ships inside the image, or None when there is none.

    ``STEPSPOTTER_MANUALS`` is what the Dockerfiles set (``/app/data/manuals``). In a
    source checkout the repo's own ``data/manuals`` is found without it — and when
    that IS the writable dir (no ``STEPSPOTTER_DATA`` set), it is not returned twice.
    """
    env = os.environ.get(MANUALS_ENV)
    candidate = Path(env).expanduser() if env else Path(__file__).resolve().parents[2] / "data" / "manuals"
    if not candidate.is_dir():
        return None
    try:
        if candidate.resolve() == writable_manuals_dir().resolve():
            return None
    except OSError:  # a path that cannot be resolved is not the writable one
        pass
    return candidate


def manuals_dirs() -> list[tuple[str, Path]]:
    """(name, dir) pairs to read from, best first: this run's cache, then the image's."""
    out: list[tuple[str, Path]] = [("cache", writable_manuals_dir())]
    bundled = bundled_manuals_dir()
    if bundled is not None:
        out.append(("bundled", bundled))
    return out


def load_index() -> dict[str, dict]:
    """The hand-checked model -> manual map, merged across the dirs above.

    Later dirs do not overwrite earlier ones: an entry a person put in the writable
    dir beats the one baked into the image.
    """
    merged: dict[str, dict] = {}
    for _name, directory in reversed(manuals_dirs()):
        path = directory / INDEX_NAME
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text())
        except Exception:  # noqa: BLE001 - a broken index is no index, not a crash
            continue
        entries = raw.get("manuals") if isinstance(raw, dict) else None
        if isinstance(entries, dict):
            merged.update({str(k): v for k, v in entries.items() if isinstance(v, dict)})
    return merged


def index_files() -> list[Path]:
    """The index.json files that actually exist, best first. Empty means none shipped."""
    return [d / INDEX_NAME for _name, d in manuals_dirs() if (d / INDEX_NAME).is_file()]


def index_lookup(product: str) -> tuple[str | None, str]:
    """The manual URL for this exact model, or (None, why not).

    "No index at all" and "an index without this model" are different failures and the
    trace says which: the first is a packaging mistake, the second is ordinary.
    """
    key = slug(product)
    if not index_files():
        return None, "index: no index.json alongside the cache"
    entries = load_index()
    entry = entries.get(key)
    if not entry:
        return None, f"index: no entry for {key}"
    url = str(entry.get("url") or "").strip()
    if not url.startswith("http"):
        return None, f"index: entry for {key} has no usable url"
    return url, ""


def is_manufacturer_host(host: str, brand: str) -> bool:
    """Does this host belong to the brand itself, rather than merely contain its letters?

    The test is per dot-label, never a bare substring of the whole host. A plain
    ``brand in host`` promotes an unrelated PDF to the top for any short brand:
    "lg" sits inside "manua**lg**uide.com" and "ge" inside "packa**ge**docs.com".

    A label counts when it *is* the brand ("ge.com", "support.ge.com"), when one of
    its hyphen-separated words is the brand ("ryobi-tools.com"), or — for brands long
    enough that the coincidence is implausible — when it starts with the brand
    ("cdn.**westinghouse**outdoorpower.com", "**ryobi**tools.com"). Four characters is
    that threshold; a two- or three-letter brand must match a whole label or word.
    Losing rank 0 costs a manufacturer's PDF only its head start — it is still ranked
    as a PDF — while a wrong rank 0 puts a stranger's document in front of the planner.
    """
    if not brand:
        return False
    for label in host.split("."):
        words = label.split("-")
        if brand in words or re.sub(r"[^a-z0-9]", "", label) == brand:
            return True
        if len(brand) >= 4 and label.startswith(brand):
            return True
    return False


def _rank(hit: Hit, brand: str) -> int | None:
    """Lower is better. None means "not a manual, skip it"."""
    parsed = urllib.parse.urlparse(hit.url)
    host = parsed.netloc.lower()
    is_pdf = parsed.path.lower().endswith(".pdf")
    if is_pdf and is_manufacturer_host(host, brand):
        return 0  # the manufacturer's own PDF
    if is_pdf:
        return 1
    if any(a in host for a in AGGREGATORS):
        return 2
    return None


def _readable_manual(url: str, downloader: Callable[[str], str | None], source: str) -> ManualHit | None:
    """Download a URL and read it, or None. A scan with no text layer counts as None."""
    path = downloader(url)
    if not path:
        return None
    pages = read_pdf_pages(path)
    if not any(page.strip() for page in pages):
        return None  # a scan with no text layer tells the planner nothing
    return ManualHit(url=url, path=path, pages=pages, source=source)


def find_manual(
    product: str,
    search_fn: Callable[[str], list[Hit]] | None = None,
    download_fn: Callable[[str], str | None] | None = None,
    fetch_fn: Callable[..., tuple[int, str]] | None = None,
    use_index: bool = True,
    trail: list[str] | None = None,
) -> ManualHit | None:
    """Find the owner's manual: the checked index first, then the search engines.

    ``trail`` collects one line per source that did not answer, in order, so the job's
    trace can show that the index was empty and DuckDuckGo was rate-limited before
    Brave came up with the PDF — rather than only the happy end of the story.
    """
    downloader = download_fn or download
    note = trail if trail is not None else []

    if use_index:
        url, why = index_lookup(product)
        if url:
            found = _readable_manual(url, downloader, "index")
            if found is not None:
                return found
            note.append(f"index: {url} would not download or had no text layer")
        else:
            note.append(why)

    if search_fn is not None:
        hits, engine = search_fn(f"{product} owner's manual pdf"), "search_fn"
    else:
        hits, engine, skipped = search_all(f"{product} owner's manual pdf", fetch_fn=fetch_fn)
        note.extend(skipped)
    if not hits:
        return None

    brand = re.sub(r"[^a-z0-9]", "", product.split()[0].lower()) if product.split() else ""
    ranked = sorted(
        ((r, h) for h in hits if (r := _rank(h, brand)) is not None),
        key=lambda pair: pair[0],
    )
    for rank, hit in ranked:
        url = hit.url
        if rank == 2:  # an aggregator page: only useful if it yields a real PDF
            url = derive_pdf_link(hit.url, fetch_fn) or ""
            if not url:
                continue
        found = _readable_manual(url, downloader, engine)
        if found is not None:
            return found
    return None


def find_videos(
    product: str,
    search_fn: Callable[[str], list[Hit]] | None = None,
    fetch_fn: Callable[..., tuple[int, str]] | None = None,
) -> list[VideoHit]:
    """Up to five YouTube results for this exact model. Titles and links only.

    ``fetch_fn`` is threaded through for the same reason as everywhere else: without
    it a test that injects a fake page for the manual would still open a real socket
    here, and the video search would be the one thing in the module that goes online.
    """
    query = f"{product} assembly video youtube"
    hits = search_fn(query) if search_fn is not None else search_all(query, fetch_fn=fetch_fn)[0]
    out: list[VideoHit] = []
    seen: set[str] = set()
    for hit in hits:
        host = urllib.parse.urlparse(hit.url).netloc.lower()
        if "youtube.com" not in host and "youtu.be" not in host:
            continue
        if hit.url in seen:
            continue
        seen.add(hit.url)
        out.append(VideoHit(title=hit.title, url=hit.url))
        if len(out) == 5:
            break
    return out


def _contents_page(pages: list[str]) -> int:
    """Index of the table of contents, or -1. Used only for the fallback excerpt."""
    for i, text in enumerate(pages[:8]):
        upper = text.upper()
        if "TABLE OF CONTENTS" in upper or upper.strip().startswith("CONTENTS"):
            return i
    return -1


def _marker_pages(pages: list[str], headings_only: bool) -> list[int]:
    """Indexes of pages carrying an assembly marker, as a heading or anywhere at all."""
    out: list[int] = []
    for i, text in enumerate(pages):
        upper = text.upper()
        if headings_only:
            lines = [ln.strip() for ln in upper.splitlines() if ln.strip()]
            hit = any(ln.startswith(m) for ln in lines for m in ASSEMBLY_MARKERS)
        else:
            hit = any(m in upper for m in ASSEMBLY_MARKERS)
        if hit:
            out.append(i)
    return out


def extract_assembly(pages: list[str]) -> Excerpt:
    """The pages that tell someone how to put the thing together, page markers included.

    Markers, not page numbers: a beginner reading step 3 should be able to open the
    paper manual at the same page and see the same picture.
    """
    if not pages:
        return Excerpt(note="the manual had no readable text")

    # A marker as a HEADING beats a marker in a sentence. Page 7 of the ePX3030 manual
    # says "...when starting and stopping the pressure washer" inside a safety label:
    # a substring match drags that page in and pushes the real assembly pages out of
    # the character budget. Headings first; sentences only when no page has a heading.
    chosen = _marker_pages(pages, headings_only=True) or _marker_pages(pages, headings_only=False)
    # The contents page lists "Assembly .... 10" and so matches every marker while
    # containing no instructions at all. Drop it unless it is the only thing we have.
    toc = _contents_page(pages)
    if toc >= 0 and len(chosen) > 1:
        chosen = [i for i in chosen if i != toc]
    note = None
    if not chosen:
        start = _contents_page(pages) + 1 if _contents_page(pages) >= 0 else 1
        chosen = list(range(start, min(start + FALLBACK_PAGES, len(pages))))
        note = (
            "no assembly heading matched, so these are the first pages after the "
            "contents — treat them as background, not as the assembly section"
        )

    parts: list[str] = []
    used: list[int] = []
    budget = MAX_EXCERPT_CHARS
    for i in chosen:
        body = (pages[i] or "").strip()
        if not body:
            continue
        block = f"[p.{i + 1}]\n{body}"
        if len(block) > budget:
            block = block[: max(0, budget)].rstrip()
            if not block.strip():
                break
        parts.append(block)
        used.append(i + 1)
        budget -= len(block)
        if budget <= 0:
            break
    return Excerpt(text="\n\n".join(parts), pages=used, note=note)


# ---------------------------------------------------------------- orchestration


def enabled() -> bool:
    """``STEPSPOTTER_RESEARCH=0`` turns the whole thing off before any socket opens."""
    return os.environ.get("STEPSPOTTER_RESEARCH", "1").strip().lower() not in ("0", "false", "off", "no")


def cache_path(product: str) -> Path:
    """Where a fresh lookup is written. Reads also consider the bundled dir below."""
    return writable_manuals_dir() / f"{slug(product)}.json"


def _load_cached(product: str) -> tuple[Research | None, str]:
    """The best cached answer and which dir it came from ("cache" or "bundled").

    The bundled copy is the demo's floor: App Runner's filesystem is ephemeral, so a
    lookup written on one request is gone by the next container, and the judge's run
    would go out to a search engine every time. The copy baked into the image cannot
    be rate-limited because it never leaves the machine.
    """
    for name, directory in manuals_dirs():
        path = directory / f"{slug(product)}.json"
        try:
            if not path.is_file():
                continue
            res = Research.model_validate_json(path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt cache is no cache, not a crash
            continue
        origin = res.source or "an earlier run"
        res.trail = [f"{name}: read from {path.name} (originally found via {origin})"]
        res.source = name
        return res, name
    return None, ""


def _store_cached(res: Research) -> None:
    """Write the answer to the cache — but never downgrade a manual we already have.

    A "not found" is usually the search engine having a bad minute, not the manual
    ceasing to exist: DuckDuckGo answers a rate-limited caller with HTTP 202 and a
    challenge page, which parses to zero results and looks exactly like "nothing out
    there". One ``--fresh`` run during such a minute used to replace a good cached
    manual with an empty one, and the next plan was silently ungrounded. A find
    always overwrites; a miss never does — and that holds for the copy baked into the
    image too, which is exactly the case a judge's first request hits.
    """
    try:
        p = cache_path(res.product)
        if res.status != "found":
            previous, _where = _load_cached(res.product)
            if previous is not None and previous.status == "found":
                return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(res.model_dump_json(indent=2))
    except Exception:  # noqa: BLE001
        pass


def research_product(
    task: str,
    search_fn: Callable[[str], list[Hit]] | None = None,
    download_fn: Callable[[str], str | None] | None = None,
    fetch_fn: Callable[..., tuple[int, str]] | None = None,
    use_cache: bool = True,
) -> Research:
    """Everything the planner gets to know about the product, or an honest empty answer.

    Cached per product under ``data/manuals/<slug>.json``, so the second run of the
    same job is offline and instant. A thrown failure is never cached at all, and a
    "not found" never replaces a manual already in the cache — a search engine having
    a bad minute should not poison the next attempt (see ``_store_cached``).
    """
    if not enabled():
        return Research(
            status="no_product",
            source="none",
            note="research switched off (STEPSPOTTER_RESEARCH=0)",
        )

    product = guess_product(task)
    if not product:
        return Research(
            status="no_product", source="none", note="no brand and model number in the task"
        )

    trail: list[str] = []
    if use_cache:
        cached, _where = _load_cached(product)
        if cached is not None:
            return cached
        trail.append("cache: nothing cached for this model yet")
    else:
        trail.append("cache: skipped (--fresh)")

    try:
        manual = find_manual(
            product,
            search_fn=search_fn,
            download_fn=download_fn,
            fetch_fn=fetch_fn,
            trail=trail,
        )
        videos = find_videos(product, search_fn=search_fn, fetch_fn=fetch_fn)
    except Exception as exc:  # noqa: BLE001 - research must never break a repair
        return Research(
            product=product,
            status="failed",
            source="none",
            trail=trail,
            note=f"{type(exc).__name__}: {exc}",
        )

    if manual is None:
        res = Research(
            product=product,
            status="not_found",
            videos=videos,
            source="none",
            trail=trail,
            note="no readable manual PDF turned up for this model",
        )
        _store_cached(res)
        return res

    excerpt = extract_assembly(manual.pages)
    res = Research(
        product=product,
        status="found",
        manual_url=manual.url,
        manual_path=manual.path,
        manual_pages=excerpt.pages,
        excerpt=excerpt.text,
        videos=videos,
        source=manual.source,
        trail=trail,
        note=excerpt.note,
    )
    _store_cached(res)
    return res


def summarize(res: Research) -> str:
    """Plain words for the Guide's ``find_manual`` tool, and for the CLI."""
    if res.status == "no_product":
        return "I could not tell which product this is — tell me the brand and model number."
    if res.status == "failed":
        return f"I could not look up {res.product} just now ({res.note})."
    lines: list[str] = []
    if res.status == "found":
        pages = ", ".join(str(p) for p in res.manual_pages) or "unknown"
        lines.append(f"Manual for {res.product}: {res.manual_url}")
        lines.append(f"Found via: {where(res)}")
        lines.append(f"Pages I read: {pages}")
        if res.note:
            lines.append(f"Note: {res.note}")
        included = _included_list(res.excerpt)
        if included:
            lines.append("What the box should contain, per the manual:")
            lines.extend("  " + ln for ln in included)
    else:
        lines.append(f"No manual PDF found for {res.product}.")
        for line in res.trail:
            lines.append(f"  tried — {line}")
    if res.videos:
        lines.append("Videos of this model:")
        lines.extend(f"  {v.title or 'video'} — {v.url}" for v in res.videos)
    return "\n".join(lines)


#: What each source is called on screen. The words matter: a judge reading "the copy
#: baked into the image" knows the demo did not depend on a search engine being up.
SOURCE_WORDS = {
    "cache": "the cache from an earlier run on this machine",
    "bundled": "the copy baked into the image (no network)",
    "index": "the checked index of models, straight to the maker's URL",
    "ddg": "a DuckDuckGo search",
    "brave": "a Brave search (DuckDuckGo did not answer)",
    "search_fn": "an injected search (a test)",
    "none": "nothing — no manual was found",
}


def where(res: Research) -> str:
    """Plain words for the source of this answer, for the CLI, the UI and the trace."""
    return SOURCE_WORDS.get(res.source, res.source or "unknown")


def _included_list(excerpt: str, limit: int = 8) -> list[str]:
    """The first few lines under an INCLUDED LIST heading — what should be in the box."""
    lines = excerpt.splitlines()
    for i, line in enumerate(lines):
        if "INCLUDED LIST" in line.upper():
            out = [ln.strip() for ln in lines[i + 1 : i + 1 + limit] if ln.strip()]
            return out
    return []
