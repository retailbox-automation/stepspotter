"""Bake one model's manual into the cache that ships inside the container image.

    python tools/bake_manual_cache.py "Westinghouse ePX3030" \
        https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf

App Runner's filesystem is ephemeral: a lookup written on one request is gone by the
next container, so every judge's first run would go out to a search engine — and on
2026-09-11 DuckDuckGo answered this machine with HTTP 202 for every query. The answer
is to ship the answer. This writes ``data/manuals/<slug>.json`` with the assembly
excerpt, the page numbers and the manufacturer's URL, and deliberately does NOT keep
the PDF: the excerpt is what the planner reads, and an 11 MB binary does not belong in
a public repo. ``manual_path`` is therefore null in a baked entry, and the note says so.

Run it from a checkout with the network up; the image then needs neither.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stepspotter import research  # noqa: E402


def bake(product: str, url: str, out_dir: Path) -> int:
    print(f"downloading {url}")
    scratch = out_dir / "_tmp"
    pdf = research.download(url, dest_dir=str(scratch))
    if pdf is None:
        print("  that URL did not come back as a PDF — nothing written", file=sys.stderr)
        return 1
    pages = research.read_pdf_pages(pdf)
    excerpt = research.extract_assembly(pages)
    if not excerpt.text.strip():
        print("  the PDF has no readable text layer — nothing written", file=sys.stderr)
        return 1

    res = research.Research(
        product=product,
        status="found",
        manual_url=url,
        manual_path=None,  # the excerpt travels; the 11 MB PDF does not
        manual_pages=excerpt.pages,
        excerpt=excerpt.text,
        source="index",
        trail=[f"baked from {url} by tools/bake_manual_cache.py"],
        note=excerpt.note
        or "cached excerpt only — the PDF itself is not shipped, open manual_url for it",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{research.slug(product)}.json"
    dest.write_text(res.model_dump_json(indent=2))
    # The PDF and its scratch dir must not survive: data/manuals is copied into the
    # image wholesale, and an empty _tmp/ riding along is noise at best.
    Path(pdf).unlink(missing_ok=True)
    if scratch.is_dir() and not any(scratch.iterdir()):
        scratch.rmdir()
    print(f"  {len(pages)} pages read, pages {excerpt.pages} kept, {len(excerpt.text)} chars")
    print(f"  wrote {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("product", help='e.g. "Westinghouse ePX3030"')
    ap.add_argument("url", help="a direct link to the manufacturer's PDF")
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "data" / "manuals"),
        help="where to write (default: the repo's data/manuals, which the image copies)",
    )
    args = ap.parse_args(argv)
    return bake(args.product, args.url, Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
