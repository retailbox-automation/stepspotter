"""Drive form A the way a person does, on a phone-sized screen, and photograph it.

    python tools/demo_server.py --port 8141 &
    python tools/shots_chat.py --base http://127.0.0.1:8141 --out <dir>

Real clicks on real controls at 390x844 — no screenshots of hand-built HTML, no
JS-injected state. Every picture is a state the server put the page in. The photos
uploaded are the checked-in OnQ panel photos in fixtures/.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "onq-keystone-smoke"
START_PHOTO = FIX / "steps" / "01-confirm-panel.jpg"
WRONG_PHOTO = FIX / "redteam" / "R1-wrong-photo.jpg"
GOOD_PHOTO = FIX / "steps" / "02-seat-pairs.jpg"
THIRD_PHOTO = FIX / "steps" / "03-telecom-landing.jpg"

TASK = "Finish the two blue cables in the panel and test them"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8141")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--short",
        action="store_true",
        help="stop after the gate refusal and prefix names with L — for a live Bedrock run, "
        "where a pass cannot be guaranteed and nothing may be staged to fake one",
    )
    ap.add_argument("--prefix", default="")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shots: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        )
        page = ctx.new_page()

        def shot(name: str, wait: float = 0.45) -> None:
            time.sleep(wait)
            name = args.prefix + name
            path = out / name
            page.screenshot(path=str(path))
            shots.append(name)
            print("  ", name)

        def settle(text: str, timeout: int = 15000) -> None:
            page.wait_for_selector(f"text={text}", timeout=timeout)

        print("form A:")
        page.goto(f"{args.base}/chat")
        page.wait_for_selector("#actBtn")
        shot("01-start-empty.png")

        page.fill("#task", TASK)
        page.set_input_files("#startPhoto", str(START_PHOTO))
        shot("02-start-filled.png")

        page.click("#actBtn")
        settle("Step 1 of", timeout=180000)   # a live plan is a vision call: be patient
        page.wait_for_selector(".step img", state="attached")
        time.sleep(1.2)  # let the card image decode before the shutter
        shot("03-step-1-card.png")
        page.mouse.move(195, 500)   # the pointer has to be over the feed to scroll it
        page.mouse.wheel(0, 620)
        shot("04-step-1-card-scrolled.png")

        # a photo that does not prove the step
        page.set_input_files("#stepPhoto", str(WRONG_PHOTO))
        settle("Not done yet", timeout=180000)
        shot("05-photo-not-done.png")

        # try to skip anyway -> the gate, not the browser, says no
        page.click('button.link[data-act="advance"]')
        settle("I am not opening the next step")
        shot("06-gate-refusal.png")

        if args.short:
            browser.close()
            print(f"\n{len(shots)} screenshots -> {out}")
            return 0

        # a photo that does prove it
        page.set_input_files("#stepPhoto", str(GOOD_PHOTO))
        settle("That is done")
        shot("07-step-1-passed.png")

        page.click("#actBtn")  # Next step
        settle("Step 2 of 3")
        time.sleep(1.2)
        shot("08-step-2-card.png")

        page.fill("#ask", "what is a keystone jack?")
        page.click("#askBtn")
        settle("scripted demo answer")
        shot("09-question-answered.png")

        page.click("#whyBtn")
        page.wait_for_selector("#sheet.on")
        shot("10-why-the-trace.png")
        page.click("#closeSheet")

        # finish the job
        page.set_input_files("#stepPhoto", str(WRONG_PHOTO))
        settle("Not done yet")
        page.set_input_files("#stepPhoto", str(GOOD_PHOTO))
        settle("That is done")
        page.click("#actBtn")
        settle("Step 3 of 3")
        page.set_input_files("#stepPhoto", str(WRONG_PHOTO))
        settle("Not done yet")
        page.set_input_files("#stepPhoto", str(THIRD_PHOTO))
        settle("That is done")
        page.click("#actBtn")
        settle("All 3 steps are done")
        shot("11-all-steps-done.png")

        # a second job, stopped for a person from inside the step card
        page.goto(f"{args.base}/chat")
        page.fill("#task", TASK)
        page.set_input_files("#startPhoto", str(START_PHOTO))
        page.click("#actBtn")
        settle("Step 1 of 3")
        page.click('button.link[data-act="escalate"]')
        settle("A person has this now")
        shot("12-stopped-for-a-person.png")

        # the same job reopened on a phone that locked and came back
        job_url = page.url
        page.goto("about:blank")
        page.goto(job_url)
        settle("A person has this now")
        shot("13-reopened-after-reload.png")

        print("form B (today, for comparison):")
        page.goto(f"{args.base}/")
        page.wait_for_selector("#startBtn")
        shot("14-form-B-today-start.png")
        page.fill("#task", TASK)
        page.set_input_files("#startPhoto", str(START_PHOTO))
        page.click("#startBtn")
        page.wait_for_selector("#screen-step:not(.hide)", timeout=20000)
        time.sleep(1.2)
        shot("15-form-B-today-step.png")

        browser.close()

    print(f"\n{len(shots)} screenshots -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
