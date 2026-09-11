# Devpost gallery — the shots, in order, with their captions

Eleven files live in `data/demo/screens/` — ten images and one terminal output
(checked 11 Sep 2026, `ls data/demo/screens/`).
Devpost's gallery takes 4–10 images; this is the order to upload them in, and the
caption to paste under each. Captions are written for someone who has not read the
description yet — each one says what the screen is doing, not what it is called.

| # | File | Caption for the gallery |
|---|---|---|
| 1 | `04b-step1-fullpage.png` | One step at a time, drawn on your own photo: what to do, what not to touch, and what your evidence photo has to show. |
| 2 | `05-verdict-not-yet.png` | The wrong photo gets "Not yet" and a reason. The step counter does not move — a Strands `BeforeToolCall` hook cancelled the advance in code. |
| 3 | `06-verdict-second-try.png` | The right photo passes, and only then does the next step unlock. |
| 4 | `07-trace.png` | Every decision is on the record: each tool call, each verdict, each refusal, in the order they happened. |
| 5 | `08-stopped.png` | A hazard is not a failed step. The run stops for a person instead of letting the loop continue. |
| 6 | `10-step-card.jpg` | The step card itself — the highlight is a soft hint from the vision model, snapped to a grid, never a claim that the part is exactly there. |
| 7 | `02-start-filled.png` | The whole input: one sentence about the job, one photo. No forms, no account. |
| 8 | `03-planning.png` | Planning: the job and the first photo become an ordered plan, each step with its own required evidence. |
| 9 | `09-eval-output.txt` (render as an image, or screenshot the terminal) | The eval harness run that is published in the repo: 3/3 steps confirmed, 3/3 wrong photos rejected, exit code non-zero if any red-team photo had got past. |
| 10 | `docs/architecture.png` | Eight roles on Strands Agents — safety fork, Researcher, Planner, Guide, Verifier, Gate, Marker, Memory — on Amazon Bedrock, deployed to AgentCore Runtime and App Runner. |

Not in the gallery, on purpose: `01-start-empty.png` (the same screen as #7 with nothing
typed) and `04-step1-viewport.png` (the cropped version of #1). Both are near-duplicates,
and a gallery of near-duplicates reads as three screens of work instead of ten.

The architecture diagram is rendered and checked in: **`docs/architecture.png`**
(2184x1109, white background) and `docs/architecture.svg`, generated from the mermaid
block in `docs/ARCHITECTURE.md` with mermaid-cli 11.17.0:

```
npx -y @mermaid-js/mermaid-cli@11 -i arch.mmd -o architecture.png -w 2200 -H 1600 -b white
```

The same PNG is the file to attach to Devpost's own **"Architecture diagram"** upload
field, which is a required field on the submission form — a copy is staged for that at
`docs/devpost-form-2026-09-11/architecture.png` in the parent project folder.

---

## Regenerating these screenshots

`tools/screenshots.py` starts its own uvicorn server against a throwaway
`STEPSPOTTER_DATA` dir, drives it with python-playwright at a phone viewport
(430x932, deviceScaleFactor 2), and saves 9 PNGs to `data/demo/screens/` covering
the empty and filled start screen, the planning spinner, a step card (viewport and
full page), a "Not yet" verdict, a second-try verdict, the trace view, and the
stopped/escalated screen. Run it with the project venv and AWS creds exported in
the same shell:

```
while IFS='=' read -r key val; do
  case "$key" in AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_DEFAULT_REGION) export "$key=$val";; esac
done < /path/to/aws.env
PY=/path/to/venv/bin/python
"$PY" -m pip install -e ".[shots]" && "$PY" -m playwright install chromium
"$PY" tools/screenshots.py
```

The CLI eval run and step-card JPG that round out the gallery are generated
separately and copied in by hand:

```
PYTHONPATH=src "$PY" -m stepspotter.cli eval fixtures/ --repeat 1 > data/demo/screens/09-eval-output.txt
cp data/demo/screens-run/jobs/<job-id>/step-01.jpg data/demo/screens/10-step-card.jpg
```

Gotcha: the verdict box renders below the fold under the card image, so a plain
viewport screenshot taken right after submitting a photo can come out byte-identical
to the step-card shot — `scroll_into_view_if_needed()` on `#verdictBox .verdict`
before snapping.
