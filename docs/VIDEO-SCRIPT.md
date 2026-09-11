# Video script — StepSpotter

Target runtime: **2:40**, under the 5-minute Devpost cap with real room to spare.
Voice-over is first person, plain, a little rough — this is read live off these
beats, not word-for-word off a page (rule 17: a script read aloud sounds read
aloud). First-person, present tense, no narrator voice.

## Shot-by-shot

**The video opens on the refusal, not on me.** The first thing a judge sees is the app
saying "Not yet" to a wrong photo and the next step staying locked. The biography comes
after that, as the reason the refusal matters — not as a warm-up to sit through. Devpost
judges scrub; the thing that makes this project different has to be on screen before the
first scrub.

| Time | On screen | Voice-over | Capture notes |
|---|---|---|---|
| 0:00–0:08 | **Cold open on the money shot.** A wrong photo goes in — a closed jack faceplate, RJ-45 port only. StepSpotter answers **"Not yet,"** with the reason. The step counter does not move; no way forward. Overlay one line of the real trace: `advance: error \| cancelled: True`. | "I sent it the wrong photo, and it said no. Not the model deciding to be careful — a line of code that won't let the next step fire until a photo proves the last one is done." | Real footage, run live. The recorded live run this is cut from is `clips/03-wrong-photo-refused.mp4` (see the timecode map below). Do not simulate it. |
| 0:08–0:30 | Phone in hand over the open low-voltage panel, StepSpotter's step card on the screen over a photo of that actual panel. | "I never owned a home. I grew up in an apartment, everything after that was rented. Then my kids were born, we moved to Orlando, and I bought a house — and I realized I didn't know how to do the simplest things in it. Not because I couldn't. Nobody ever showed me. So it gives me one step at a time, on my own photo." | The hook footage, now in second position. Hand holding phone with the panel behind it, card legible. |
| 0:30–0:50 | Back to the sequence from the cold open, played out: the right photo goes in, **"That looks done,"** the next step unlocks and the card advances. | "When the photo actually shows the step done, it moves on. That's the only way forward it has." | `clips/04-right-photo-pass.mp4`. Same job, same session as the cold open, so the two halves obviously belong together. |
| 0:50–1:20 | A step card showing a stop condition — hot, swollen, smells burnt. Cut to a staged unsafe state and the app escalating instead of failing. A person as the next action. | "And if something looks actually unsafe — hot, swollen, smells burnt — it doesn't just fail the step and let me keep going. It stops the whole thing and hands it to a person. That's a different kind of 'no' than 'try again.'" | Staged photo only — do not photograph a real hazard. A verifier reason string naming the hazard is enough on screen. |
| 1:20–2:10 | The rendered architecture diagram (`docs/architecture.png`), then real code: the `BeforeToolCallEvent` hook and the `cancel_tool` line, then the typed `StepVerdict`. | "This runs on Strands Agents, from AWS. A Planner that turns the job into steps, a Verifier that only looks at your photo and returns a typed answer — pass, fail, or stop, never free text — and a Gate, which is a Strands `BeforeToolCall` hook. It sits in front of the 'move to next step' tool call and cancels it in code if there's no passing verdict on file. The model doesn't get a vote. I tested that by writing a prompt telling the model to skip ahead no matter what, and the gate still stopped it." | Show real code, not slides — `src/stepspotter/gate.py` and `src/stepspotter/models.py`. Zoom on `cancel_tool = "..."` and on `structured_output_model=StepVerdict`. |
| 2:10–2:35 | The published eval reports on screen — `docs/eval-results/2026-09-09.md` **and** `2026-09-11.md`. Read the numbers off the files. Include the 2026-09-11 **MISS** row. | "There's a test set in the repo, and both runs are published. Three steps off real photos of my panel, three photos built to fool it. First run: three of three steps, three of three bad photos rejected. Second run: it refused a step I had actually done, because a cable was lying across the port labels. That miss is in the report. What didn't move either time is the red-team score — nothing has got past the gate." | **Read the numbers off the file on screen; do not quote from memory.** Showing the miss is the point of this beat, not a caveat to it. Never claim the 12-step set until it exists in `docs/eval-results/`. |
| 2:35–2:40 | Close on the finished panel. Text card: "StepSpotter — one photo at a time." URL card. | "This is for anyone who never had someone to show them." | Keep the close short — Devpost's own advice is not to pad once the demo is shown. |

**Two rules for every frame of screen material:**

1. **Only raw, unmarked photos appear on camera.** The annotated Russian-language sheets
   under `docs/dogfood-epx3030-2026-09-09/` were made for my own use, by hand, and are not
   this product's output. Nothing from that folder goes in the video. What the app drew
   itself, on a raw phone photo, is the only annotated image allowed on screen.
2. **Every word on screen is English** — the app UI, the terminal, the code, the titles,
   the captions, the file names visible in any editor or Finder window. Check the frame
   before rolling, not in the edit.

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
| 0:00–0:08 cold open (the refusal) | Closed faceplate submitted for the punch-down step | Photograph the handle **resting** on the frame, not screwed down, and submit it for the "four screws in" step. Expected: "Not yet" naming the screws. Run it live; do not stage the answer. |
| 0:08–0:30 hook (biography) | Phone over the open panel, the step card legible — read the step count off the screen, do not caption it from here | Phone over the unopened box on the garage floor, machine half out (the grounded plan came back 11 steps long on 9 Sep; read the real count off the screen on the day) |
| Extra beat, ~0:30 (branch B only) | — | Type "assemble my Westinghouse ePX3030 pressure washer". On screen: `status: found`, the manual URL, `pages: 10, 11, 12, 13, 14`. Voice-over: "There is no assembly video for this machine anywhere. I checked. But the manufacturer's manual is a PDF on their site — so it goes and gets it, and every step tells me which page it came from." |
| 0:30–0:50 the pass | The right photo for the punch-down step, "That looks done" | The handle screwed down, four screws visible, submitted for the same step |
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

## Timecode map for the already-recorded live run

A full live run against the deployed app is already recorded, cut and timecoded —
real clicks, real Bedrock calls, the genuine fail-then-pass sequence (job
`job-20260911-125505-b179`). The beat-by-beat map of where each moment sits, which
clip file it is in, and what still needs Michael on camera, is §5 of
`docs/video-prep-2026-09-11/NOTES.md` in the parent project folder (with §3 of the
same file on which task + photo combination actually produces a live refusal, and
which one does not). Cut the beats above against that map rather than re-recording
the app from scratch.

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
