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

Eight roles, named like a small crew rather than software layers:

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
- **Safety fork** — the Planner's first decision, before it writes a single step: is
  this actually a DIY job, or does it need a licensed trade? A job that needs a pro
  comes back with an empty step list and one sentence, not a plan.
- **Memory** — what this house already has and where we stopped, plus the conversation
  itself, so closing the phone mid-repair doesn't start the job over.

![StepSpotter architecture: the person, the Guide agent, the plan-once roles (safety fork, researcher, planner), the per-step loop (verifier, gate, marker) and the AWS services underneath](docs/architecture.png)

Full role-by-role breakdown, the Strands feature behind each one, and the diagram
source: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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
source:  bundled — the copy baked into the image (no network)
manual:  https://cdn.westinghouseoutdoorpower.com/owners_manuals/ePX3030_manual_web.pdf
pages:   10, 11, 12, 13, 14
```

Same job, with and without the manual, run live end to end:
[`docs/research-epx3030-2026-09-09.md`](docs/research-epx3030-2026-09-09.md). Short
version — without it, the plan never mentions the handle, the two mounts or the four
screws, and reports "no tools required" for a job that needs a screwdriver.

**Five places to look, in that order, and it tells you which one answered.** The cache
this container already wrote → the cache baked into the image at build time
(`data/manuals/`, copied in by both Dockerfiles) → a hand-checked model-to-URL index
(`data/manuals/index.json`, every entry fetched and recorded with its date) →
DuckDuckGo → Brave. The step card on the phone says *"Manual found via the copy baked
into the image"*, or, when nothing was found, *"No manual found, so these steps come
from the photo alone"* with the list of what was tried — an ungrounded plan is never
allowed to look like a grounded one. Why the ladder: a hosted container starts with an
empty filesystem, and on 2026-09-11 DuckDuckGo answered us with HTTP 202 (its
rate-limit challenge) for every query, which parses to zero results and is indistinguish-
able from "no manual exists". `python tools/bake_manual_cache.py "<brand model>" <url>`
adds a model to the baked cache: excerpt, pages and the maker's link, without the PDF.
Both images run offline, the engines caught refusing live, and the two step cards a
person sees: [`data/demo/research-hardening/`](data/demo/research-hardening/).

- **No API key.** DuckDuckGo and Brave's HTML pages and `pypdf`; a stranger can run it cold.
- **Switch it off** with `STEPSPOTTER_RESEARCH=0` — it returns before any socket
  opens. The test suite sets exactly that, so nothing offline depends on a search
  engine.
- **Nothing to look up, nothing to fetch.** No brand-and-model in what you typed
  means no network call at all.
- **Cached** per product under `data/manuals/<product>.json` (plus the PDF when this
  machine was the one that downloaded it; a baked entry carries the excerpt only), so
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

**What has actually been run and published** — the checked-in smoke fixture,
`fixtures/onq-keystone-smoke/`: 3 steps off real photos of my own low-voltage panel,
plus three red-team photos (a front-face jack instead of an open wall box, a different
room's cabling instead of the panel, and no photo at all). Both runs were live against
Bedrock at `--repeat 1`, and both are in the repo with their reasons intact:

| Run | Steps confirmed | Red-team rejected | Overall |
|---|---|---|---|
| [`docs/eval-results/2026-09-09.md`](docs/eval-results/2026-09-09.md) | 3/3 | 3/3 | PASS |
| [`docs/eval-results/2026-09-11.md`](docs/eval-results/2026-09-11.md) | **2/3** | 3/3 | **FAIL** |

The second run is the honest one to read. Step 3 missed: a black cable lay across the
telecom module and covered the port numbers, so the Verifier refused a step that was
in fact done — *"the port labels are not fully legible as required."* That is a real
miss against a real photo, the harness exited non-zero for it, and it is published
exactly as it came out. The number that did not move either day is the one that
matters: **6/6 wrong photos rejected across both runs** — nothing got past the gate.

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
- 8/8 correct pass/fail verdicts on real photos of a real panel in Spike A,
  including all four cases where the claimed object simply wasn't in the frame
  (`spikes/SPIKE-A-RESULT.md` §1 — run twice, identical booleans both times).
- Two published eval runs against those same photos, 6/6 red-team photos rejected
  across both, and the one genuine step miss left in the report instead of edited
  out (`docs/eval-results/`).
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
| Core (Planner, Marker, Verifier, Gate, Guide, models, store) | ✅ Done — `src/stepspotter/`; `python -m pytest -q` → from a fresh clone, **184 passed, 7 skipped** with the `agentcore` extra and **171 passed, 8 skipped** without it; on the machine that also holds the raw photo archive, 190 / 1 and 177 / 2 |
| Web UI (phone-first, FastAPI, camera capture) | ✅ Done — `src/stepspotter/web/` |
| Manual research (find the maker's PDF, ground the plan, cite the page) | ✅ Done — `src/stepspotter/research.py`, `docs/research-epx3030-2026-09-09.md` |
| Eval harness + smoke fixtures | ✅ Done — `src/stepspotter/evalharness.py`, `fixtures/onq-keystone-smoke/`; published run: `docs/eval-results/2026-09-09.md` |
| Full 12-step eval set (`docs/EVAL-PLAN.md` §2, red-team R1–R6) | ⛔ Not run — waiting on evidence photos from the finished job |
| Deploy — phone web app | ✅ Live on AWS App Runner: <https://w7ihmvgxxj.us-east-1.awsapprunner.com> (`/healthz` 200). Redeployed 2026-09-11 with the baked manual cache — a live ePX3030 job on that URL cites *"the copy baked into the image (no network)"*, so the demo does not depend on a search engine |
| Deploy — Guide agent on Amazon Bedrock AgentCore Runtime | ✅ `stepspotter_guide` READY, version 2 (2026-09-11) — invoked live, resolves the ePX3030 manual to pages 10–14 from the baked excerpt; see `docs/DEPLOY.md` |

## Setup

**Requires Python 3.12 or newer** — `brew install python@3.12` on macOS, or
`pyenv install 3.12`, or your distribution's `python3.12` package. Nothing here is
tested on 3.11 or older.

```bash
git clone https://github.com/retailbox-automation/stepspotter && cd stepspotter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q      # 171 passed, 8 skipped — no AWS account, no credentials, no network
```

That is the whole cold start, and those numbers are from an actual fresh clone, not
from this working copy. Each skip says out loud why it skipped (`pytest -q -rs`): one
needs live AWS credentials, one needs the optional AgentCore SDK, and six render a
card against the raw photo archive that lives outside this repo — they are the only
tests in the suite that want a file a stranger doesn't get.

Add the AgentCore door as well if you want those thirteen tests to run too:

```bash
pip install -e ".[dev,agentcore]"
python -m pytest -q                      # 184 passed, 7 skipped from a fresh clone
python -m pytest -q tests/test_gate.py   # 6/6 — the Gate contract on its own
```

The `agentcore` extra carries `bedrock-agentcore`, which only the AgentCore
entrypoint imports; without it `tests/test_agentcore_entry.py` skips itself instead
of failing collection. Nothing in that extra calls AWS on import.

### If you want the parts that need AWS

Everything above is offline. The web UI, the eval harness and the spikes make real
Amazon Bedrock calls, and need three things on your account:

1. **Credentials exported in the same shell command** you run the app with. An
   ambient `~/.aws/credentials` or a stale `AWS_PROFILE` pointing at a different
   account produces a `ValidationException: Operation not allowed` that reads like
   throttling but is really the wrong account:

   ```bash
   export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=us-east-1
   unset AWS_PROFILE      # if you have one set for another account
   ```

2. **IAM permissions** on that identity: `bedrock:InvokeModel` and
   `bedrock:InvokeModelWithResponseStream`, in `us-east-1`.

3. **Model access** for Anthropic models in the Bedrock console (*Bedrock → Model
   access*), in `us-east-1` — Claude Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`,
   the default here) and Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5`). Without
   it you get the same `ValidationException: Operation not allowed`, which is why it
   is worth ruling out before you go looking for a bug in this repo.

Run the phone-first web UI (needs the AWS export above):

```bash
stepspotter serve --port 8137
```
Then open `http://<your-machine's-LAN-ip>:8137` on a phone — the photo inputs use
`capture="environment"` and open the rear camera directly. Full deploy notes
(App Runner, AgentCore Runtime, Docker): `docs/DEPLOY.md`.

**No panel in front of you?** The first screen has a **Try a demo job** button. It
runs the whole thing on three photos of a real low-voltage panel shipped inside the
package (`src/stepspotter/web/demo_photos/`), and then offers *Send the wrong photo*
and *Send the right photo* in place of the camera. Everything behind those buttons is
live: the Planner writes the plan, the Verifier judges each photo, and the gate hook
decides whether "Next step" is allowed. No verdict is canned, and because the model is
not deterministic the plan differs run to run — the page shows whatever actually came
back.

| Endpoint | What it does |
|---|---|
| `POST /api/demo/jobs` | start the demo job on the packaged start photo |
| `POST /api/jobs/{id}/demo-photo` (`which=wrong\|right`) | send a packaged photo to the real Verifier |
| `GET /api/jobs/{id}/trace?view=human` | who did what, what came back, why — no paths, no ids |
| `GET /api/jobs/{id}/trace?view=raw` | the operator's log, behind the page's "raw" link |

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
