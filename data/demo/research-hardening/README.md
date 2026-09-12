# The manual lookup, proven on the thing that ships — 2026-09-11

Why this folder exists: a hosted container starts with an empty filesystem, and on this
day DuckDuckGo answered this machine with **HTTP 202** (its rate-limit challenge page,
which parses to zero results and looks exactly like "no manual exists") and Brave, after
a handful of queries, with **429**. Left alone, a judge's run would plan without the
manual and look identical to a grounded one. These files are the check that it cannot.

| File | What it shows |
|---|---|
| `offline-container.log` | Both images run with `--network none`. The ePX3030 and the RY31012 come back `found` from the copy baked into the image; a model in neither the cache nor the index comes back `not_found` and names every rung it tried. |
| `online-container.log` | The same image with the network up, taken while both engines were refusing: `Legrand EN0800` is still found because `index.json` sends it straight to Legrand's own URL, and `Westinghouse ePX3050` — in neither cache nor index — honestly fails with `duckduckgo: HTTP 202` and `brave: HTTP 429` on its trail. That contrast is the whole argument for baking the cache. |
| `live-engine-cascade.log` | The engines themselves, from this Mac, over eight minutes: both rate-limited, then Brave carrying a lookup DuckDuckGo could not (13:15:29Z). |
| `ui-step-card-manual-from-image.png` | The step card a person sees when the manual came out of the image: *"Manual found via the copy baked into the image (no network) — pages 10, 11, 12, 13, 14"*. |
| `ui-step-card-no-manual-warning.png` | The same card when nothing was found: *"No manual found, so these steps come from the photo alone"*, followed by what was tried. An ungrounded plan says so on screen. |

The two screenshots were taken in a real browser against a local server with the model
calls faked — no Bedrock, no network. What they prove is the wiring: baked cache →
`Research` → the job trace → the JSON the phone renders → the line under the step.
