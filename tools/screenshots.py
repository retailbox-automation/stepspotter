"""Generate Devpost-gallery screenshots of StepSpotter's different surfaces.

Starts its own uvicorn server against a fresh STEPSPOTTER_DATA dir, drives it
with python-playwright (phone viewport), and saves PNGs to data/demo/screens/.

Run with the project venv, AWS creds exported in the same shell, and STEPSPOTTER_DATA
set by this script itself (not inherited) so the run is isolated:

    while IFS='=' read -r key val; do
      case "$key" in AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_DEFAULT_REGION) export "$key=$val";; esac
    done < "/Users/oskolamicheal/Projects/Retailbox - CockroachDB Hackathon/.env"
    PY=".../spike/.venv/bin/python"
    "$PY" tools/screenshots.py
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "demo" / "screens"
DATA_DIR = REPO / "data" / "demo" / "screens-run"
PORT = 8142
BASE = f"http://127.0.0.1:{PORT}"
GOOD_PHOTO = REPO.parent / "docs" / "design-reference-2026-09-09" / "raw-photos-onq" / "03-telecom-module.jpg"
WRONG_PHOTO = REPO.parent / "docs" / "design-reference-2026-09-09" / "raw-photos-onq" / "05-office-jack-open.jpg"
TASK_TEXT = (
    "Terminate two Cat5e runs into new keystone jacks and land them at the telecom "
    "module, then test the link."
)


def wait_for_server(url: str, timeout: float = 30.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"server never came up at {url}")


def main() -> int:
    if not GOOD_PHOTO.is_file() or not WRONG_PHOTO.is_file():
        print(f"MISSING photo(s): {GOOD_PHOTO} / {WRONG_PHOTO}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    import shutil

    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    import os

    env = os.environ.copy()
    env["STEPSPOTTER_DATA"] = str(DATA_DIR)
    env["PYTHONPATH"] = str(REPO / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    py = sys.executable

    server = subprocess.Popen(
        [py, "-m", "uvicorn", "stepspotter.web.app:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        try:
            wait_for_server(BASE + "/healthz", timeout=20)
        except Exception:
            if server.poll() is not None:
                out = server.stdout.read().decode(errors="replace") if server.stdout else ""
                print("SERVER DIED:\n" + out, file=sys.stderr)
            raise
        run_shots()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
    return 0


def run_shots() -> None:
    from playwright.sync_api import sync_playwright

    shots: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 430, "height": 932}, device_scale_factor=2)
        page.set_default_timeout(60_000)

        def snap(name: str, full_page: bool = False):
            path = OUT / name
            page.screenshot(path=str(path), full_page=full_page, animations="disabled", caret="hide")
            shots.append(name)
            print(f"saved {name}")

        # 1. start screen, empty
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_selector("#screen-start:not(.hide)")
        snap("01-start-empty.png")

        # 2. start screen, filled
        page.fill("#task", TASK_TEXT)
        page.set_input_files("#startPhoto", str(GOOD_PHOTO))
        page.wait_for_selector("#startPhotoLabel.has")
        snap("02-start-filled.png")

        # 3. planning/loading — click and grab it fast before the response lands
        page.click("#startBtn")
        try:
            page.wait_for_selector("#startBtn:disabled", timeout=5000)
            snap("03-planning.png")
        except Exception:
            print("planning state too fast to catch — skipping 03")

        # wait for the plan (Bedrock call ~30-60s) — either the step screen or vendor refusal
        page.wait_for_selector(
            "#screen-step:not(.hide), #screen-vendor:not(.hide)", timeout=90_000
        )

        if page.is_visible("#screen-vendor:not(.hide)"):
            print("planner refused to a vendor — capturing that screen instead of steps")
            snap("04-vendor-refusal.png")
            return

        # 4. step 1 card, viewport + full page
        page.wait_for_selector("#cardImg[src]")
        page.wait_for_load_state("networkidle")
        time.sleep(1)  # let the card image finish rendering
        snap("04-step1-viewport.png")
        snap("04b-step1-fullpage.png", full_page=True)

        # 5. verdict "Not yet" — submit the wrong photo
        # The verdict box renders BELOW the fold under the card image, so a plain
        # viewport screenshot after this looked byte-identical to the step card —
        # scroll it into view before snapping.
        page.set_input_files("#stepPhoto", str(WRONG_PHOTO))
        page.wait_for_selector("#verdictBox .verdict", timeout=60_000)
        page.locator("#verdictBox .verdict").scroll_into_view_if_needed()
        time.sleep(0.5)
        snap("05-verdict-not-yet.png")

        # 6. try the correct evidence photo — may or may not pass, report either way
        page.set_input_files("#stepPhoto", str(GOOD_PHOTO))
        page.wait_for_function(
            "document.querySelector('#verdictBox .verdict') && "
            "document.querySelector('#verdictBox .verdict').className.indexOf('pass') === -1 "
            "|| true",
            timeout=60_000,
        )
        page.locator("#verdictBox .verdict").scroll_into_view_if_needed()
        time.sleep(1)
        if page.is_visible(".verdict.pass"):
            print("verifier passed on the second try — capturing pass + Next step")
            snap("06-verdict-pass.png")
        else:
            print("verifier still says not-yet on the second photo — capturing that state, no forced pass")
            snap("06-verdict-second-try.png")

        # 7. trace view
        page.click("#traceBtn")
        page.wait_for_selector("#screen-trace:not(.hide)")
        snap("07-trace.png", full_page=True)
        page.click("#backBtn")
        page.wait_for_selector("#screen-step:not(.hide)")

        # 8. stop -> escalate
        page.click("#stopBtn")
        page.wait_for_selector("#screen-stopped:not(.hide)", timeout=30_000)
        snap("08-stopped.png")

        browser.close()

    print("\nshots:", ", ".join(shots))


if __name__ == "__main__":
    raise SystemExit(main())
