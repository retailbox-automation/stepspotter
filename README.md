# StepSpotter

**One small step at a time, on *your own* photo — and the next step stays locked
until your photo proves the last one was done safely.** Built on **Strands Agents**
(AWS) for the Agents for Humans hackathon, Everyday Agents track.

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
  the second run of the same job is instant and offline. A later run that finds
  nothing leaves that cache alone: search engines rate-limit, and a bad minute must
  not empty a manual you already have.
- **Never fatal.** A dead search engine, a scanned manual with no text layer, a 404 —
  each comes back as a status, and the repair carries on without it.

## Strands Agents features used

Every line below is in this repository; nothing here is aspirational.

| Strands API | Where | What it does here |
|---|---|---|
| `Agent(...)` + `strands.models.BedrockModel` | `src/stepspotter/vision.py:65-66` | every vision call — planning, marking, verifying — goes through one Strands agent on Amazon Bedrock |
| `structured_output_model=` on the invocation, read back as `result.structured_output` | `src/stepspotter/vision.py:84-85` | typed objects instead of parsed text. `Agent.structured_output(...)` is deprecated in 1.54.0; this is the current call shape |
| Typed outputs in use | `src/stepspotter/planner.py:90` (`Plan`), `src/stepspotter/verifier.py:53` (`StepVerdict`) | the plan and the pass/fail verdict are Pydantic models the SDK fills, not free text a regex has to survive |
| `HookProvider` + `registry.add_callback(BeforeToolCallEvent, ...)` | `src/stepspotter/gate.py:30, 47-50` | the gate registers itself in front of every tool call |
| `event.cancel_tool = "<reason>"` | `src/stepspotter/gate.py:81` | the refusal itself: `advance_step` is cancelled in code, and the string is the message the user reads |
| `event.interrupt(...)` | `src/stepspotter/gate.py:64` and `:137` | a hazard stops the whole run (`stop_reason='interrupt'`) instead of failing one call and letting the loop continue |
| `@tool` × 6 | `src/stepspotter/guide.py:253, 277, 291, 306, 332, 347` | `start_job`, `find_manual`, `show_step`, `submit_photo`, `advance_step`, `escalate` — the Guide's whole surface |
| `strands.session.FileSessionManager` passed as `Agent(session_manager=...)` | `src/stepspotter/guide.py:397-403` | the conversation survives a restart; resuming a job is the SDK's job, not a homemade chat log |
| `HookRegistry` + a hand-built `BeforeToolCallEvent` | `src/stepspotter/guide.py:484-504` | the web UI does not talk to the model at all, and still goes through the *same* gate object — one policy, two front doors |
| Amazon Bedrock AgentCore Runtime entrypoint | `src/stepspotter/agentcore_entry.py:54, 60, 236` | `BedrockAgentCoreApp` + `@app.entrypoint`, deployed and READY (`docs/DEPLOY.md`) |

Not used, so not claimed: `strands_tools` built-ins, `MCPClient`, and the
`vended_interventions` helpers. The human-in-the-loop path here is the hook's own
`event.interrupt(...)`.

## The checkable number

The eval harness runs every fixture photo through the same `advance_step` / gate
code path the app itself uses, and exits non-zero if any red-team photo gets past
the gate on any repeat.

**What has actually been run and published** (`docs/eval-results/2026-09-09.md`,
live against Bedrock, `--repeat 1`): the checked-in smoke fixture —
`fixtures/onq-keystone-smoke/`, 3 steps off real photos of my own low-voltage
panel — **3/3 steps confirmed, 3/3 wrong photos rejected**, 100% boolean agreement.
The three red-team photos are a front-face jack instead of an open wall box, a
different room's cabling instead of the panel, and no photo at all.

The full target set — the same job written out as 12 steps, red-team rows R1–R6 —
is specified in [`docs/EVAL-PLAN.md`](docs/EVAL-PLAN.md) and **not yet run**: it
needs the evidence photos from the finished job, which do not exist yet. That
document marks which rows are real and which are still the target shape, and every
result we do run gets published with its misses intact.

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

- Run the full 12-step eval set in `docs/EVAL-PLAN.md` on photos of the finished
  job and publish every result, misses included.
- A "what do I even need to do?" mode — the jobs a first-year homeowner doesn't
  know exist (condensate line, dryer vent, water-heater valve), proposed as small
  photo-verified jobs instead of a checklist to read.
- Job state in S3 instead of the instance's `/tmp`, so a job survives a restart of
  the hosted app.
- Ask / re-plan mid-job: today the plan is fixed when the job starts, and questions
  only work in the chat mode, not in the web UI.
- Segmentation instead of a bounding box, so "this cable, not that one" is exact
  rather than a soft highlight.
- Tighter IAM for the hosted agent, and sign-in on the public URL.

## Status

| Piece | Status |
|---|---|
| Spikes A + B (Verifier structured output, Gate `BeforeToolCall` hook, live Bedrock) | ✅ Done — `spikes/SPIKE-A-RESULT.md`, `spikes/SPIKE-B-RESULT.md` |
| Core (Planner, Marker, Verifier, Gate, Guide, models, store) | ✅ Done — `src/stepspotter/`; `python -m pytest -q` → **95 passed, 1 skipped** (the skip is the one test that needs live AWS credentials) |
| Web UI (phone-first, FastAPI, camera capture) | ✅ Done — `src/stepspotter/web/` |
| Manual research (find the maker's PDF, ground the plan, cite the page) | ✅ Done — `src/stepspotter/research.py`, `docs/research-epx3030-2026-09-09.md` |
| Eval harness + smoke fixtures | ✅ Done — `src/stepspotter/evalharness.py`, `fixtures/onq-keystone-smoke/`; published run: `docs/eval-results/2026-09-09.md` |
| Full 12-step eval set (`docs/EVAL-PLAN.md` §2, red-team R1–R6) | ⛔ Not run — waiting on evidence photos from the finished job |
| Deploy — phone web app | ✅ Live on AWS App Runner: <https://w7ihmvgxxj.us-east-1.awsapprunner.com> (`/healthz` 200) |
| Deploy — Guide agent on Amazon Bedrock AgentCore Runtime | ✅ `stepspotter_guide` READY — see `docs/DEPLOY.md` |

## Setup

```bash
git clone <this repo>
cd stepspotter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,agentcore]"
```

The `agentcore` extra carries `bedrock-agentcore`, which the AgentCore entrypoint
imports; without it `pytest` stops at collection on `tests/test_agentcore_entry.py`.
Nothing in that extra calls AWS on import.

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
python -m pytest -q                      # 95 passed, 1 skipped — the full suite
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
inside a breaker panel, gas lines, roofing, or structural work.** The Planner has a
safety fork for exactly those: it answers `safety_class="vendor_required"`, returns
an empty step list and a plain reason instead of a plan
(`src/stepspotter/planner.py:26-35, 95-98`; `tests/test_web.py::test_vendor_required_returns_no_steps`).
That fork is a model judgment, not a certified hazard classifier, so treat this as a
tool for the kind of job you'd already be comfortable doing with a good video and a
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
