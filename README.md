# StepSpotter

**One small step at a time, on *your own* photo — and the next step stays locked
until your photo proves the last one was done safely.**

Built with **Strands Agents** (AWS) for the Agents for Humans hackathon, Everyday
Agents track.

**Live demo: https://w7ihmvgxxj.us-east-1.awsapprunner.com** — open it on a phone; the
photo buttons go straight to the rear camera. (AWS App Runner, us-east-1. The Guide
agent also runs on Amazon Bedrock AgentCore Runtime — see `docs/DEPLOY.md`.)

## Inspiration

I never owned a home. I grew up in an apartment, and every place I lived in as an
adult was rented. Then my kids were born and we moved to Orlando and bought a
house — and I realized I didn't know how to do even the simplest things around it.
Not because I'm not capable. Nobody ever showed me.

What actually works for me is my phone. I take a photo, and someone explains it
back to me on that exact photo — a circle around the part I need, an arrow, "not
this one, that one." Simple language, one thing at a time. That's the only way
instructions have ever clicked for me, and it's the only reason I got through
replacing a UPS battery and terminating network jacks in my own low-voltage panel
this month without calling someone.

StepSpotter is that, built into an agent, with one rule I insisted on: it can't
just take my word that a step is done. It has to see it.

## What it does

You give StepSpotter one repair job and a first photo. It hands you back **one
step**, not a wall of instructions — what to do, what not to touch, and what your
next photo needs to show. You do the step, send a photo, and the agent checks it.
If the photo doesn't prove the step is done, it tells you why in plain words and
asks for another one. It will not move you forward on your say-so alone.

That refusal isn't a prompt asking the model to be careful — it's a piece of code
that runs before the "next step" tool is even allowed to fire. No amount of
insisting talks it past a step it hasn't seen evidence for.

## How we built it

Seven roles, named like a small crew rather than software layers:

- **Guide** — the agent you talk to; shows the step card, takes your photo.
- **Planner** — turns the job + a first photo into an ordered list of steps, each
  with its own "don't touch" and its own required evidence photo.
- **Marker** — draws a highlight on your photo for the card.
- **Verifier** — a separate agent whose only job is to look at your evidence photo
  and return a typed verdict: pass, fail, or stop, with a reason.
- **Gate** — a Strands `BeforeToolCall` hook that cancels the "move to next step"
  tool call in code unless the Verifier already passed the current step.
- **Researcher** — given a brand and model, finds the manufacturer's manual online
  and pulls out the assembly pages, so the Planner works from the maker's own words
  instead of a guess.
- **Safety fork** — before any of this starts: is this actually a DIY job, or does
  it need a professional?

Full role-by-role breakdown, the Strands feature behind each one, and a diagram:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Strands Agents** is the SDK end to end: typed `structured_output` for the
Verifier's verdict (not free-text parsing), and a `BeforeToolCallEvent` hook for
the gate itself — verified against strands-agents 1.54.0 by live introspection and
real Bedrock calls, not from the docs alone (`spikes/SPIKE-A-RESULT.md`,
`spikes/SPIKE-B-RESULT.md`).

## Grounded in the manufacturer's manual

Name a brand and a model — "assemble my **Westinghouse ePX3030** pressure washer" —
and StepSpotter goes and finds the maker's own manual before it writes a single step.
It searches the open web, downloads the PDF, pulls out the pages that actually cover
assembly, and hands them to the Planner with page markers. The steps then follow the
manual's order and its part names, and **each step cites the page it came from**, so
you can check it against the paper in the box. The photo still outranks the manual: if
what's in front of you doesn't match, the step says so.

```bash
stepspotter research "Westinghouse ePX3030"     # no AWS credentials needed for this one
```

```
product: Westinghouse ePX3030
status:  found
manual:  https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf
pages:   10, 11, 12, 13, 14
```

Same job, with and without the manual, run live end to end:
[`docs/research-epx3030-2026-09-09.md`](docs/research-epx3030-2026-09-09.md). Short
version — without it, the plan never mentions the handle, the two mounts or the four
screws, and reports "no tools required" for a job that needs a screwdriver.

- **No API key.** DuckDuckGo's HTML endpoint and `pypdf`; a stranger can run it cold.
- **Switch it off** with `STEPSPOTTER_RESEARCH=0` — it returns before any socket
  opens. The test suite sets exactly that, so nothing offline depends on a search
  engine.
- **Nothing to look up, nothing to fetch.** No brand-and-model in what you typed
  means no network call at all.
- **Cached** per product under `data/manuals/<product>.json` (plus the PDF itself), so
  the second run of the same job is instant and offline.
- **Never fatal.** A dead search engine, a scanned manual with no text layer, a 404 —
  each comes back as a status, and the repair carries on without it.

## The checkable number

An eval set built around a real job — an OnQ low-voltage panel, two Cat5e runs
terminated into keystone jacks, patch cords, cable-tester checks — as 12 steps
with a required evidence photo each, plus a red-team set of deliberately wrong
photos (wrong object, a step skipped ahead, no photo at all, an unsafe state, a
photo too blurry to judge). Every result — including every miss — gets published.
Plan and fixture layout: [`docs/EVAL-PLAN.md`](docs/EVAL-PLAN.md).

## Challenges we ran into

- **The vision model's bounding boxes drift.** On real, cluttered photos of a
  low-voltage panel, boxes routinely landed low and oversized, and small hardware
  in clutter (a splitter, a connector) was the worst case — 3 tight hits out of 14
  boxes. We measured it rather than assumed it, and the fix is to treat a box as a
  soft highlight, never a crisp "it is exactly here" claim (`spikes/SPIKE-A-RESULT.md`).
- **Confidence scores are not stable run to run — the pass/fail boolean is.** The
  same photo, the same claim, gave confidence 0.82 on one run and 0.20 on the next
  for an identical, correct refusal. We do not gate on confidence anywhere in this
  system; we gate on the boolean and read the reason.
- **A well-behaved model hides a broken gate.** With an honest system prompt, the
  model simply refused to skip steps on its own — which proves nothing about
  whether the code gate actually works. We had to write a deliberately permissive
  prompt for the integration test, so the *only* thing stopping the agent was the
  hook, not its manners.
- **The field is crowded and vision is fragile outside a staged demo.** Several
  existing tools diagnose a photo of a repair; almost none of them refuse to let
  you proceed until a *second* photo proves you actually did it. That refusal is
  the whole point, and it is also the piece most likely to break on a bad photo —
  which is why the eval set exists at all.

## Accomplishments

- A code-level gate — not a prompt — that a permissive, "just do what they say"
  system prompt could not talk past, proven live against Bedrock, not just in a
  unit test.
- 8/8 correct pass/fail verdicts on real photos of a real panel, including every
  case where the claimed object simply wasn't in the frame.
- A named, reasoned failure mode for the one part of the system that isn't
  reliable yet (bounding-box precision), with a concrete mitigation instead of a
  silent gap.

## What we learned

Refusing to let someone "just claim" a step is done is a harder engineering
problem than describing what's in a photo — and it's also the actual product.
The interesting part of this build wasn't getting a vision model to draw a box;
it was making the "no" enforceable in code instead of hoping the model stays
polite.

## What's next

- Finish the Guide/Planner/Marker roles and wire them to the already-proven
  Verifier + Gate.
- Run the full eval set in `docs/EVAL-PLAN.md` and publish every result.
- A phone-first web UI and a live deployment.
- Safety-fork triage (mains electrical, gas, roofing → "call a pro," not steps).
- Optional: memory of what's already been done in a given house, across jobs.

## Status

| Piece | Status |
|---|---|
| Spikes A + B (Verifier structured output, Gate `BeforeToolCall` hook, live Bedrock) | ✅ Done — `spikes/SPIKE-A-RESULT.md`, `spikes/SPIKE-B-RESULT.md` |
| Core (Planner, Marker, Verifier, Gate, Guide, models, store) | ✅ Done — `src/stepspotter/`, 90 tests passing (`python -m pytest -q`) |
| Web UI (phone-first, FastAPI, camera capture) | ✅ Done — `src/stepspotter/web/` |
| Manual research (find the maker's PDF, ground the plan, cite the page) | ✅ Done — `src/stepspotter/research.py`, `docs/research-epx3030-2026-09-09.md` |
| Eval harness + smoke fixtures | ✅ Done — `src/stepspotter/evalharness.py`, `fixtures/onq-keystone-smoke/` |
| Docker image | ✅ Builds locally (`docker build .`) |
| Deploy (live URL) | ⏳ Pending — see `docs/DEPLOY.md` |
| Submission video | ⏳ Pending |

## Setup

```bash
git clone <this repo>
cd stepspotter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Bedrock creds — export **in the same shell command** you run the app with; an
ambient `~/.aws/credentials` for a different account otherwise produces a
`ValidationException: Operation not allowed` that looks like throttling but isn't:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

Model access on your AWS account must include Anthropic models on Bedrock in
`us-east-1` — Claude Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`, the default)
and Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5`); no separate opt-in was
needed on the account these spikes ran on.

Run what's real today, offline, no AWS needed:

```bash
python -m pytest -q                      # 90 passed, 1 skipped — the full suite
python -m pytest -q tests/test_gate.py   # 6/6 — the Gate contract on its own
```

Run the phone-first web UI (needs the AWS export above):

```bash
stepspotter serve --port 8137
```
Then open `http://<your-machine's-LAN-ip>:8137` on a phone — the photo inputs use
`capture="environment"` and open the rear camera directly. Full deploy notes
(App Runner, AgentCore Runtime, Docker): `docs/DEPLOY.md`.

Run the eval harness against the checked-in smoke fixture (needs the AWS export
above — it makes real Bedrock calls):

```bash
stepspotter eval fixtures/ --repeat 2
```

Run the live Bedrock spikes:

```bash
python spikes/spike_vision.py            # Verifier + bounding-box spike
python spikes/spike_gate.py              # Live gate integration run
```

## Safety note

This is a DIY helper for low-voltage, low-consequence work — network cabling,
low-voltage panels, simple hardware swaps. **It is not for mains electrical work
inside a breaker panel, gas lines, roofing, or structural work.** Left unbuilt on
purpose: the safety fork that should refuse to plan those jobs at all and tell you
to call a professional instead. Until that exists, treat this as a tool for the
kind of job you'd already be comfortable doing with a good YouTube video and a
multimeter — nothing that can shock, burn, or collapse on you.

## Disclosure

No pre-existing code from any other project is in this repository. What carries
over is a *format*, not code: the annotated-photo step-card idea comes from a
personal practice of asking Claude to mark up my own home-repair photos by hand,
documented as a standing habit before this hackathon began
(`docs/design-reference-2026-09-09/`, referenced for format only). Everything in
`src/`, `spikes/`, and `tests/` was written new during the Submission Period, with
an AI coding assistant, as the rules allow.

## License

MIT (see `LICENSE`).
