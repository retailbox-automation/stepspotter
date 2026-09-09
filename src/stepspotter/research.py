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

No API key: DuckDuckGo's HTML endpoint and ``pypdf``. A stranger can run this cold.
"""

from __future__ import annotations

import html as _html
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


def search(query: str, timeout: float = 10) -> list[Hit]:
    """Search the open web. Never raises; an empty list means "we could not look"."""
    encoded = urllib.parse.urlencode({"q": query})
    attempts = (
        (f"{SEARCH_HTML}?{encoded}", None),
        (SEARCH_HTML, encoded.encode()),  # the HTML endpoint prefers a POST
        (f"{SEARCH_LITE}?{encoded}", None),
    )
    for url, data in attempts:
        status, body = fetch(url, timeout=timeout, data=data)
        if status != 200 or not body:
            continue
        hits = parse_hits(body)
        if hits:
            return hits
    return []


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


def _rank(hit: Hit, brand: str) -> int | None:
    """Lower is better. None means "not a manual, skip it"."""
    parsed = urllib.parse.urlparse(hit.url)
    host = parsed.netloc.lower()
    is_pdf = parsed.path.lower().endswith(".pdf")
    if is_pdf and brand and brand in host.replace("-", ""):
        return 0  # the manufacturer's own PDF
    if is_pdf:
        return 1
    if any(a in host for a in AGGREGATORS):
        return 2
    return None


def find_manual(
    product: str,
    search_fn: Callable[[str], list[Hit]] | None = None,
    download_fn: Callable[[str], str | None] | None = None,
    fetch_fn: Callable[..., tuple[int, str]] | None = None,
) -> ManualHit | None:
    """Search for the owner's manual, download it, and read its pages."""
    searcher = search_fn or search
    downloader = download_fn or download
    brand = re.sub(r"[^a-z0-9]", "", product.split()[0].lower()) if product.split() else ""

    hits = searcher(f"{product} owner's manual pdf")
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
        path = downloader(url)
        if not path:
            continue
        pages = read_pdf_pages(path)
        if not any(p.strip() for p in pages):
            continue  # a scan with no text layer tells the planner nothing
        return ManualHit(url=url, path=path, pages=pages)
    return None


def find_videos(product: str, search_fn: Callable[[str], list[Hit]] | None = None) -> list[VideoHit]:
    """Up to five YouTube results for this exact model. Titles and links only."""
    searcher = search_fn or search
    out: list[VideoHit] = []
    seen: set[str] = set()
    for hit in searcher(f"{product} assembly video youtube"):
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
    return store.data_root() / "manuals" / f"{slug(product)}.json"


def _load_cached(product: str) -> Research | None:
    p = cache_path(product)
    try:
        if p.is_file():
            return Research.model_validate_json(p.read_text())
    except Exception:  # noqa: BLE001 - a corrupt cache is no cache, not a crash
        return None
    return None


def _store_cached(res: Research) -> None:
    try:
        p = cache_path(res.product)
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
    same job is offline and instant. Failures are never cached — a search engine
    having a bad minute should not poison the next attempt.
    """
    if not enabled():
        return Research(status="no_product", note="research switched off (STEPSPOTTER_RESEARCH=0)")

    product = guess_product(task)
    if not product:
        return Research(status="no_product", note="no brand and model number in the task")

    if use_cache:
        cached = _load_cached(product)
        if cached is not None:
            return cached

    try:
        manual = find_manual(product, search_fn=search_fn, download_fn=download_fn, fetch_fn=fetch_fn)
        videos = find_videos(product, search_fn=search_fn)
    except Exception as exc:  # noqa: BLE001 - research must never break a repair
        return Research(product=product, status="failed", note=f"{type(exc).__name__}: {exc}")

    if manual is None:
        res = Research(
            product=product,
            status="not_found",
            videos=videos,
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
        lines.append(f"Pages I read: {pages}")
        if res.note:
            lines.append(f"Note: {res.note}")
        included = _included_list(res.excerpt)
        if included:
            lines.append("What the box should contain, per the manual:")
            lines.extend("  " + ln for ln in included)
    else:
        lines.append(f"No manual PDF found for {res.product}.")
    if res.videos:
        lines.append("Videos of this model:")
        lines.extend(f"  {v.title or 'video'} — {v.url}" for v in res.videos)
    return "\n".join(lines)


def _included_list(excerpt: str, limit: int = 8) -> list[str]:
    """The first few lines under an INCLUDED LIST heading — what should be in the box."""
    lines = excerpt.splitlines()
    for i, line in enumerate(lines):
        if "INCLUDED LIST" in line.upper():
            out = [ln.strip() for ln in lines[i + 1 : i + 1 + limit] if ln.strip()]
            return out
    return []
