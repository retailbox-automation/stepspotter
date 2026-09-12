# Form A after the design pass — 12.09.2026

Six shots from `feat-chat-master`, taken by clicking as a person in `chrome-qa` at
390 × 844 (mobile, touch, DPR 3) against `tools/demo_server.py` on a spare port. Real
mouse events on real controls: no `element.click()`, no injected state, no staged pass.
Every one is from the build that is committed on this branch.

| Shot | What it is there to prove |
|---|---|
| `01-first-screen.png` | what a phone lands on: one message, one text box, one photo button, and the demo offer for a judge with no panel |
| `02-composer-photo-thumbnail.png` | the photo you are about to send is **shown**, read in the browser before anything is uploaded — not described as "Photo ready" |
| `03-step-card-and-step-chip.png` | the header: the job title ellipsises, **"Step 1 of 3" does not**. The card below is untouched — two marks, one green to work in, one red to leave alone |
| `04-gate-refusal-in-the-feed.png` | the point of the project. The agent's red *"Not done yet"*, then the refusal in its own smaller neutral centred block under **"Gate (code, not the model)"** |
| `05-step-2-after-the-pass.png` | the pass opens step 2, the refusal stays on screen above it, the header chip moves to *Step 2 of 3* |
| `06-dark-mode.png` | the same feed under emulated dark mode: all three speakers in one frame, and the three meanings still told apart by colour |

Shot 04 is the one to look at if there is only time for one.

**Known limits of this evidence.** The a11y tree was wrong about this page twice (it
reported the camera emoji still present and no thumbnail when a screenshot showed the
opposite), so every claim here rests on the image, not the tree. And the whole walk runs
the fake planner/verifier in `demo_server.py` — the server logic is `main`'s and
unchanged, so what these shots prove is arrangement, not model behaviour.
