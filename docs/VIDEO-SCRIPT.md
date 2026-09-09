# Video script — StepSpotter

Target runtime: **2:40**, under the 5-minute Devpost cap with real room to spare.
Voice-over is first person, plain, a little rough — this is read live off these
beats, not word-for-word off a page (rule 17: a script read aloud sounds read
aloud). First-person, present tense, no narrator voice.

## Shot-by-shot

| Time | On screen | Voice-over | Capture notes |
|---|---|---|---|
| 0:00–0:20 | Phone in hand, pointed at the open low-voltage panel. StepSpotter's step card appears on the phone screen — "Step 1 of 12" — over a photo of the actual panel. | "I never owned a home. I grew up in an apartment, and every place after that was rented. Then my kids were born, we moved to Orlando, and I bought a house. And I realized I didn't know how to do the simplest things in it. Not because I couldn't. Nobody ever showed me." | Film the phone screen and the panel in the same shot if possible — hand holding phone, panel in the background, card visible. This is the hook; it has to land in the first 15 seconds. |
| 0:20–0:50 | Cut to a wrong photo being submitted — a closed jack faceplate, RJ-45 port only. StepSpotter's answer appears: "Not yet." Then cut to the "Next step" button greyed out / the app refusing to move forward. Overlay a line of the actual trace log. | "It gives me one step at a time, not a wall of instructions. And here's the part I insisted on — it can't take my word that I did it. I tried to skip ahead with the wrong photo. It said no. Not because the AI decided to be careful. There's a line of code that won't even let the 'next step' button fire until a real photo proves it." | Use the real fail-then-pass sequence from `data/demo/onq-keystone/03-fail-then-pass.log` — screen-record the actual app rejecting `04-office-jack-front`, then accepting `05-office-jack-open`. Show the trace line: `advance: error | cancelled: True`. This is the money shot — do not simulate it, run it live. |
| 0:50–1:20 | A step card showing a stop condition — hot, swollen, smells burnt. Cut to a photo of a genuinely unsafe state (staged, not live-wired) and the app escalating instead of failing. A person's name/contact appears as the next action. | "And if something looks actually unsafe — hot, swollen, smells burnt — it doesn't just fail the step and let me keep going. It stops the whole thing and hands it to a person. That's a different kind of 'no' than 'try again.'" | Staged photo only — do not photograph a real hazard. A verifier reason string naming the hazard is enough on screen. |
| 1:20–2:10 | Architecture diagram from `docs/ARCHITECTURE.md` (the mermaid flow, rendered), then cut to code: the `BeforeToolCallEvent` hook and `cancel_tool` line, then the typed `StepVerdict` output. | "This runs on Strands Agents, from AWS. Five roles: a Planner that turns the job into steps, a Verifier that only looks at your photo and returns a typed answer — pass, fail, or stop, never free text — and a Gate, which is a Strands `BeforeToolCall` hook. It sits in front of the 'move to next step' tool call and cancels it in code if there's no passing verdict on file. The model doesn't get a vote. I tested that by writing a prompt that told the model to skip ahead no matter what, and the gate still stopped it." | Show real code, not slides — `src/stepspotter/gate.py` and the `StepVerdict` model in `src/stepspotter/models.py`. Zoom on `cancel_tool = "..."` and on `structured_output_model=StepVerdict`. |
| 2:10–2:35 | The eval report table on screen — `docs/eval-results/2026-09-09.md`. Read the numbers, including the miss. Cut to a wide shot of the finished panel, cover back on. | "I ran this against 12 real steps and 6 photos built to trick it. Here's the actual number, including the one it got wrong — a photo where the label was blocked by a cable, and it correctly said it couldn't tell instead of guessing. Every result here is published, misses included." | Do not cherry-pick a clean run. Show the miss on screen with its reason text, per `EVAL-PLAN.md` §5's own rule. |
| 2:35–2:40 | Close on the finished panel, or Michael's face for one beat if he wants it. Text card: "StepSpotter — one photo at a time." URL card. | "This is for anyone who never had someone to show them. Next: a safety check before the plan even starts, so it never plans a job for a breaker panel or a gas line in the first place." | Keep the close short — Devpost's own advice is not to pad the runtime once the demo is shown. |

## B-roll to capture during the real job (from `EVAL-PLAN.md` §3)

Shoot these while doing the actual OnQ panel work, before editing:

- Wide shot of the whole open panel box (needed for step 1's "not a breaker panel" evidence).
- Close, filled-frame shots of the cable end and its label (step 2) — get close enough to read the label in the final video crop, not just close enough for a person standing there.
- Jacket stripped, four pairs visible, no nicked conductors (step 3).
- Pairs laid into the keystone jack against the T568B color chart sticker (step 4).
- Jack after punch-down, no bare copper past the terminals (step 5).
- Jack snapped into the wall plate, no gap at any edge (step 6).
- Second jack, same shots repeated (steps 7–8).
- Both patch cords plugged in at the panel (step 9).
- Legible label on each new run at the panel (step 10).
- Cable tester LEDs or pass readout for both jacks (steps 11–12) — the one part of this job with an objective, non-visual pass/fail instrument. Get the readout in focus.
- One steady, well-lit take of the "wrong photo" moment for the 0:20–0:50 beat — a closed faceplate held up on purpose, matching the real fail case already in the fixtures.
- A phone-in-hand over-the-shoulder shot for the 0:00–0:20 hook, so the opening isn't just a screen recording.

Light every shot — a room light or the phone's own flashlight propped up. Spike A's
worst misses were on dim, cluttered photos (`spikes/SPIKE-A-RESULT.md` §2). Fill the
frame with the thing, not the room, except for the one wide panel-identification shot.

## Freezedetect QA (before final export)

Any screen-recorded segment must not sit still for more than 4 seconds — a static
screen reads as "the demo froze," and judges are not required to sit through a dead
frame to find out otherwise. Run:

```bash
ffmpeg -i video-draft.mp4 -vf "freezedetect=n=-30dB:d=4" -map 0:v -f null - 2>&1 | grep freeze
```

Any `freeze_start` hit longer than the segment's intended pause gets a cut, a push-in,
or a cursor move inserted before final export.

## Music

YouTube Audio Library only (no attribution required, and it does not risk a
Content ID geo-block the way third-party tracks can — see
`Retailbox - CockroachDB Hackathon/docs/VIDEO-CRAFT-NOTES.md`). Keep it under the
voice-over, ducked further under the 0:20–0:50 refusal beat so the "Not yet" line
is the clearest audio moment in the video.

## Captions

Burn in captions — a large share of hackathon judges and social viewers watch
muted. Keep each caption line at roughly 15 characters per second, never faster
than 20 cps, and hold even a short line for at least 0.8s so it's readable.
