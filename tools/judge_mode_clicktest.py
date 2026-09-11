"""Click through the judge-mode demo the way a judge would, on a phone-sized screen.

Real clicks on real buttons at 390x844, against a server that is calling Bedrock for
real: no JS calls into the page's own functions, no bare API POSTs, no fixtures. What
the screenshots show is what the browser painted.

    .venv/bin/python tools/judge_mode_clicktest.py --base http://127.0.0.1:8139 \
        --out ../docs/judge-mode-2026-09-11

Checks it makes, beyond taking pictures:
  * the first screen names what this is, links the repo, and offers the demo;
  * the waiting state names a stage and counts seconds (the 35s of silence that
    reviewers read as "it broke");
  * the wrong photo is REFUSED and "Next step" stays hidden;
  * the right photo passes and "Next step" appears;
  * the readable trace contains no filesystem path and no job id;
  * nothing scrolls sideways at 390px, on any screen.

Exit code is non-zero if any check fails, and the failure is printed with what was on
screen at the time. A refusal that does not happen is a failed test, not a surprise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

PHONE = {"width": 390, "height": 844}

FORBIDDEN = {
    "a filesystem path": re.compile(r"/(?:Users|home|tmp|private|var|data|app)/"),
    "a photo filename": re.compile(r"\.jpe?g\b"),
    "a job id": re.compile(r"\bjob-\d{8}-\d{6}-[0-9a-f]{4}\b"),
}


class Check:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def that(self, ok: bool, what: str, detail: str = "") -> None:
        self.rows.append((bool(ok), what, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  — {detail}" if detail else ""))

    @property
    def failed(self) -> list[tuple[bool, str, str]]:
        return [r for r in self.rows if not r[0]]


def no_sideways_scroll(page: Page) -> tuple[bool, str]:
    """The whole point of 390px: a long manual URL used to widen the document."""
    body, view = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    return body <= view + 1, f"scrollWidth={body} clientWidth={view}"


def shoot(page: Page, out: Path, name: str) -> Path:
    path = out / name
    page.screenshot(path=str(path), full_page=False)
    print(f"    shot {name}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8139")
    ap.add_argument("--out", required=True)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    check = Check()
    events: list[dict] = []

    def note(what: str, **extra) -> None:
        events.append({"t": round(time.time() - t0, 2), "what": what, **extra})

    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(
            viewport=PHONE,
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            ),
        )
        page = ctx.new_page()

        # ---------------------------------------------------------- first screen
        print("\n1. The first screen")
        page.goto(args.base, wait_until="networkidle")
        page.wait_for_selector("#demoCard:not(.hide)", timeout=10_000)
        body = page.inner_text("main")
        check.that("one step at a time" in body, "says what this is")
        check.that("next step stays locked" in body.lower(), "says the next step is locked")
        check.that(
            page.locator("a", has_text="Source code on GitHub").count() == 1,
            "links to the repository",
        )
        check.that(page.locator("#demoBtn").is_visible(), "offers 'Try a demo job'")
        ok, detail = no_sideways_scroll(page)
        check.that(ok, "first screen does not scroll sideways", detail)
        shoot(page, out, "01-first-screen.png")

        # ---------------------------------------------------------- the demo plan
        print("\n2. The demo job — a real Planner call")
        with page.expect_response(
            lambda r: r.url.endswith("/api/demo/jobs") and r.request.method == "POST",
            timeout=180_000,
        ) as planned:
            page.click("#demoBtn")
            note("clicked Try a demo job")
            # Catch the waiting state while it is genuinely waiting.
            page.wait_for_timeout(2500)
            waiting = page.inner_text("#demoWait")
            shoot(page, out, "02-planning-waiting.png")
        note("plan returned", status=planned.value.status)
        check.that(planned.value.status == 200, "the demo job planned", f"HTTP {planned.value.status}")
        check.that(
            any(s in waiting for s in ("Looking at your photo", "safe to do yourself",
                                       "manual", "Writing the steps")),
            "waiting state names a stage",
            waiting.replace("\n", " ")[:90],
        )
        check.that(bool(re.search(r"\b\d+s\b", waiting)), "waiting state counts seconds", waiting[:60])

        page.wait_for_selector("#screen-step:not(.hide)", timeout=180_000)
        page.wait_for_selector("#demoBar:not(.hide)", timeout=10_000)
        page.wait_for_function("() => { const i=document.getElementById('cardImg'); return i.complete; }",
                               timeout=60_000)
        step_text = page.inner_text("#screen-step")
        note("step card rendered")
        check.that("step 1 of" in step_text.lower(), "step 1 is on screen",
                   step_text.splitlines()[0] if step_text else "")
        check.that(
            page.locator("#photoBtn").is_hidden() and page.locator("#demoWrongBtn").is_visible(),
            "demo replaces the camera with two buttons",
        )
        ok, detail = no_sideways_scroll(page)
        check.that(ok, "step screen does not scroll sideways", detail)
        shoot(page, out, "03-step-card.png")

        # ---------------------------------------------------------- the refusal
        print("\n3. The wrong photo — a real Verifier call, expected to refuse")
        with page.expect_response(
            lambda r: "/demo-photo" in r.url and r.request.method == "POST", timeout=180_000
        ) as wrong:
            page.click("#demoWrongBtn")
            note("clicked Send the wrong photo")
            page.wait_for_timeout(1200)
            checking = page.inner_text("#stepWait")
            shoot(page, out, "04-checking-photo.png")
        payload = wrong.value.json()
        note("wrong verdict", passed=payload["verdict"]["passed"])
        check.that("Checking your photo" in checking or "Comparing it" in checking,
                   "photo check names a stage", checking.replace("\n", " ")[:80])
        page.wait_for_selector("#verdictBox .verdict", timeout=30_000)
        page.wait_for_function("() => !document.getElementById('stepWait').textContent.trim()",
                               timeout=30_000)
        verdict = page.inner_text("#verdictBox")
        check.that(payload["verdict"]["passed"] is False,
                   "the live model refused the wrong photo", payload["verdict"]["reason"][:110])
        check.that("Not yet" in verdict, "screen shows 'Not yet'", verdict.replace("\n", " ")[:90])
        check.that(page.locator("#nextBtn").is_hidden(), "'Next step' stays hidden after a refusal")
        page.locator("#verdictBox").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shoot(page, out, "05-wrong-photo-refused.png")

        # ---------------------------------------------------------- the pass
        print("\n4. The right photo — a real Verifier call, expected to pass")
        with page.expect_response(
            lambda r: "/demo-photo" in r.url and r.request.method == "POST", timeout=180_000
        ) as right:
            page.click("#demoRightBtn")
            note("clicked Send the right photo")
        good = right.value.json()
        note("right verdict", passed=good["verdict"]["passed"])
        page.wait_for_function(
            "() => { const b=document.getElementById('stepWait'); return !b.textContent.trim(); }",
            timeout=60_000,
        )
        verdict2 = page.inner_text("#verdictBox")
        check.that(good["verdict"]["passed"] is True,
                   "the live model passed the right photo", good["verdict"]["reason"][:110])
        check.that("That looks done" in verdict2, "screen shows 'That looks done'",
                   verdict2.replace("\n", " ")[:90])
        check.that(page.locator("#nextBtn").is_visible(), "'Next step' appears only now")
        page.locator("#verdictBox").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shoot(page, out, "06-right-photo-passed.png")

        # ---------------------------------------------------------- through the gate
        print("\n5. Next step — through the real gate hook")
        with page.expect_response(
            lambda r: r.url.endswith("/advance") and r.request.method == "POST", timeout=120_000
        ) as adv:
            page.click("#nextBtn")
            note("clicked Next step")
        moved = adv.value.json()
        check.that(moved["blocked"] is False, "the gate allowed the move")
        page.wait_for_selector("#screen-step:not(.hide)", timeout=30_000)
        check.that("step 2 of" in page.inner_text("#stepNo").lower(), "now on step 2",
                   page.inner_text("#stepNo"))
        shoot(page, out, "07-step-2.png")

        # ---------------------------------------------------------- the trace
        print("\n6. 'See what it did' — the readable trace")
        page.click("#traceBtn")
        page.wait_for_selector("#screen-trace:not(.hide) ol.trace li", timeout=30_000)
        trace_text = page.inner_text("#traceList")
        for what, pattern in FORBIDDEN.items():
            hit = pattern.search(trace_text)
            check.that(hit is None, f"the readable trace shows no {what}",
                       "" if hit is None else f"found {hit.group(0)!r}")
        raw_rows = page.evaluate(
            """async (id) => (await (await fetch("/api/jobs/"+id+"/trace?view=raw")).json()).rows""",
            page.url.split("job=")[-1],
        )
        blocks = [r for r in raw_rows if r.get("event") == "gate_block"]
        if blocks:
            check.that("Gate (code, not the model)" in trace_text,
                       "the gate's refusal is named as code")
        else:
            print("  note  no gate_block this run: the page hides 'Next step' until a photo\n        passes, so a click-through never asks to skip. See the README.")
        check.that("Allowed — the photo had passed" in trace_text,
                   "the move to step 2 is shown as allowed only after a pass")
        check.that("Checker" in trace_text and "Planner" in trace_text, "actors are named in plain words")
        ok, detail = no_sideways_scroll(page)
        check.that(ok, "trace screen does not scroll sideways", detail)
        shoot(page, out, "08-trace-readable.png")
        # The verdicts and the gate are further down a phone-height list.
        page.locator("#traceList li").last.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shoot(page, out, "08b-trace-verdicts.png")

        page.click("#rawLink")
        page.wait_for_selector("ol.trace.raw li", timeout=15_000)
        check.that("start_job" in page.inner_text("#traceList"), "the raw log is still one click away")
        shoot(page, out, "09-trace-raw.png")

        (out / "clicktest-events.json").write_text(json.dumps(events, indent=2))
        browser.close()

    print(f"\n{len(check.rows) - len(check.failed)}/{len(check.rows)} checks passed "
          f"in {round(time.time() - t0)}s")
    if check.failed:
        print("FAILED:")
        for _ok, what, detail in check.failed:
            print(f"  - {what} {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
