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
| 2:10–2:35 | The eval report on screen — `docs/eval-results/2026-09-09.md`. Read the numbers off the published file, nothing rounded up. Cut to a wide shot of the finished panel, cover back on. | "There's a test set in the repo. Three steps off real photos of my panel, and three photos built to fool it — the wrong jack, a different room's cabling, and no photo at all. Three out of three steps confirmed, three out of three bad photos rejected. If a bad photo ever gets through, the run exits non-zero. That's in the repo, with the trace that produced it." | **Read the numbers off the file on screen, do not quote them from memory.** If a fuller run happens before the shoot, re-shoot this beat against the newer `docs/eval-results/` file — the number said out loud and the number on screen must be the same one. Never claim the 12-step set until it exists in `docs/eval-results/`. |
| 2:35–2:40 | Close on the finished panel, or Michael's face for one beat if he wants it. Text card: "StepSpotter — one photo at a time." URL card. | "This is for anyone who never had someone to show them. Next: a safety check before the plan even starts, so it never plans a job for a breaker panel or a gas line in the first place." | Keep the close short — Devpost's own advice is not to pad the runtime once the demo is shown. |

## Which job to film — branch A (OnQ panel) or branch B (pressure washer)

The script above is written for **branch A**: the OnQ low-voltage panel, two Cat5e runs
into keystone jacks, cable tester. It needs parts that are not ordered yet.

**Branch B — assembling a Westinghouse ePX3030 pressure washer — is shootable today**:
the machine is here in its box, the manufacturer's manual is public, and StepSpotter's
manual research has already been run live on this exact model
(`docs/research-epx3030-2026-09-09.md`). Branch B also shows something branch A cannot:
**the agent going and finding the maker's manual, and every step card carrying the page
it came from.**

Swaps, beat by beat — everything else in the table above stays:

| Beat | Branch A (OnQ panel) | Branch B (ePX3030) |
|---|---|---|
| 0:00–0:20 hook | Phone over the open panel, "Step 1 of 12" | Phone over the unopened box on the garage floor, machine half out, "Step 1 of 11" (the grounded plan came back 11 steps long on 9 Sep — read the real count off the screen on the day, do not caption it from here) |
| Extra beat, ~0:20 (branch B only) | — | Type "assemble my Westinghouse ePX3030 pressure washer". On screen: `status: found`, the manual URL, `pages: 10, 11, 12, 13, 14`. Voice-over: "There is no assembly video for this machine anywhere. I checked. But the manufacturer's manual is a PDF on their site — so it goes and gets it, and every step tells me which page it came from." |
| 0:20–0:50 refusal | Closed faceplate submitted for the punch-down step | Photograph the handle **resting** on the frame, not screwed down, and submit it for the "four screws in" step. Expected: "Not yet" naming the screws. Run it live; do not stage the answer. |
| 0:50–1:20 hazard | Staged unsafe photo in the panel | The manual's own rule: never run the pump dry, and no extension cord. Submit a photo of the machine plugged in with the garden hose **not** connected, for the first-start step. If the model does not call that out, cut this beat rather than fake it. |
| 2:35–2:40 close | Finished panel, cover on | Machine assembled, hose on, wand in hand |

Branch B's voice-over keeps the same origin lines — nothing in the hook is
panel-specific. Shoot whichever job is actually happening that day; do not shoot both
halfway.

## B-roll for branch B — ePX3030 assembly

From the assembly walkthrough in
`docs/dogfood-epx3030-2026-09-09/README-sborka-epx3030.md` (built from the official
manual, pages 10–15). One shot per step, phone-height, machine filling the frame:

- Everything out of the box laid on the floor: wand, gun, two nozzles, high-pressure
  hose, soap bottle, handle, three brackets, four screws, two wheels — this is the shot
  that makes "one step at a time" obvious before a word is said.
- The manual open on the ePX3030 assembly page beside the parts (the thing the agent
  just fetched, on paper).
- A bracket sliding onto the frame until it latches (manual p.10, FIG. 4).
- The Phillips screwdriver driving each of the four screws (p.10, FIG. 5) — the "no
  tools required" claim the un-grounded plan got wrong; this is the money shot for the
  research beat.
- A wheel pushed onto the axle until it clicks (p.11, FIG. 6).
- The wand screwed into the gun, then a tug-test on it (p.11, FIG. 7).
- The collar pulled back on the hose end, the fitting seated, the collar threaded down
  (p.12, FIG. 8) — shoot this close; "pull the collar back" is exactly the kind of
  instruction a photo explains and a sentence doesn't.
- The second hose end onto the machine, and the garden hose onto the inlet with the
  screen visible inside it (p.12).
- The 25° nozzle clicking into the wand collar (p.14, FIG. 10).
- First start: hose on, trigger squeezed until the water runs air-free, then the switch
  to I (p.13). Get the water actually running — the end of the job has to look like the
  end of a job.
- One deliberate wrong-photo take for the 0:20–0:50 beat: the handle resting unscrewed,
  held up to the camera on purpose.

Safety on camera: nothing plugged in until the water is connected, no extension cord in
frame, eye protection on for the first start.

## B-roll for branch A — the real OnQ job (from `EVAL-PLAN.md` §3)

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
