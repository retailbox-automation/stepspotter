# The gate, refusing — from a browser, on a live run

Until 12.09 the one mechanic this project is built on could not be reached from the UI:
"Next step" only appears once a photo has passed, so a judge clicking around never saw
a refusal. The step card now carries **Skip the photo and move on**, which asks anyway
and is cancelled by the same `BeforeToolCall` hook that stops the model.

| File | What it shows |
|---|---|
| `skip-refusal-2026-09-12.png` | Step 1 of 9, then the refusal: the reason in words, and the photo it is waiting for. The step counter has not moved. |
| `skip-refusal-trace-2026-09-12.png` | *See what it did*: **You — asked to move on without sending a photo**, then **Gate (code, not the model) — refused**. Two actors, two rows, no paths and no ids. |
| `after-a-passing-photo-2026-09-12.png` | The right photo passes and the buttons swap: *Next step* appears, the skip button and its caption are gone. One way forward on screen at a time. |

## How these were taken (2026-09-12)

Real clicks in Chrome at a 390x844 phone viewport, against a local server on
`127.0.0.1:8151` (`uvicorn stepspotter.web.app:app`) with AWS credentials exported —
**live Bedrock**, not fixtures. The run is the packaged demo job: *Try a demo job* →
the Planner wrote 9 steps → the skip button → the refusal above → *Send the right
photo* → "That looks done" → *Next step* → step 2 of 9.

Nothing in the refusal is UI text: `POST /api/jobs/<id>/advance` sends the
`advance_step` tool through a real `HookRegistry`, and the sentence on screen is the
string the hook put in `event.cancel_tool`. `intent=skip` only labels the ask on the
trace; the gate never sees it, which is why the same press after a passing photo
advances the step.
