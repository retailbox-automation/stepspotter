# Devpost submission text — StepSpotter

Track: **Everyday Agents**. Built on **Strands Agents** (AWS), end to end.

---

**StepSpotter gives you one home-repair step at a time, drawn on your own photo, and
refuses to unlock the next step until a photo proves you finished the last one safely.
The refusal is a Strands Agents hook cancelling a tool call in code — not a prompt
asking a model to be careful.**

## Inspiration

I never owned a home. I grew up in an apartment, every place I lived in as an adult was
rented. Then my kids were born, we moved to Orlando and I bought a house — and I realized I
didn't know how to do the simplest things around it. Not because I'm not capable. Nobody
ever showed me.

Hiring someone is the obvious answer. I tried: roughly three dozen contractors hired or
quoted since we bought the house, more than half of those jobs failed, stalled or had to be
redone. The ones I did myself went better.

What works for me is my phone. I take a photo, and someone explains it back on that exact
photo — a circle around the part I need, an arrow, "not this one, that one." One thing at a
time. That is the only reason I got through replacing a UPS battery and terminating network
jacks in my own panel this month without calling anyone.

StepSpotter is that, built into an agent, with one rule: it cannot take my word that a step
is done. It has to see it.


## What it does

You give StepSpotter one repair job and a first photo. It hands back **one step** — what to
do, what not to touch, and what your next photo has to show. You do it, send a photo, and
the agent checks that photo against that step. If the photo doesn't prove the step is done,
it says why in plain words and asks for another. It will not move you forward on your say-so.

Name a brand and a model — "assemble my Westinghouse ePX3030 pressure washer" — and it
finds the manufacturer's own manual first, pulls out the assembly pages, and writes the
steps in the manual's order and part names, **each step citing the page it came from**. The
photo still outranks the manual: if what's in front of you doesn't match, the step says so.

A photo showing something unsafe — heat, swelling, a burnt smell, bare wire — doesn't just
fail the step: it stops the run and hands it to a person. A job that needs a licensed trade
never gets a plan at all.


## How we built it

**Strands Agents** is the SDK end to end, and each role maps to a feature of it:

- **Verifier** — reads one photo against one claim and returns a typed verdict (pass /
  fail / stop, with a reason) via `structured_output_model=`: a real `StepVerdict` object,
  not free text scraped with a regex.
- **Gate** — the piece that matters most. A Strands `BeforeToolCallEvent` hook sets
  `event.cancel_tool = "<reason>"`, killing the `advance_step` call before the SDK
  dispatches it, unless the Verifier already passed the current step. We proved it live
  against Bedrock with a deliberately permissive prompt ("the user is always right, call
  advance_step immediately"). The model tried to skip ahead. The hook stopped it anyway.
  Prompt says yes, code says no. A hazard gets `event.interrupt(...)` from the same hook —
  a cancel fails one call and lets the loop continue; an interrupt stops the whole run.
- **Planner** — job plus first photo into an ordered typed `Plan`. Its first decision is who
  should do the job at all: `safety_class="vendor_required"` empties the step list in code,
  so the refusal is structural, not a sentence the model may forget.
- **Researcher** — finds the manufacturer's manual and extracts the assembly pages with page
  markers. No API key; five sources tried in order (this container's cache, the cache baked
  into the image, a checked index, DuckDuckGo, Brave), and the card names the one that
  answered.
- **Marker** — draws the highlight on your photo, snapped to a grid: a hint, not a claim.
- **Guide** — the agent you talk to: six `@tool` functions and a Strands
  `FileSessionManager`, so a job survives a restart instead of starting over.

The phone web app runs on AWS App Runner; the Guide agent also runs on Amazon Bedrock
AgentCore Runtime. The web UI never talks to the model directly — it routes through the
same `StepGate` object the agent uses: one policy behind two front doors.

Every feature named here has a file and line in the README's own table. Not claimed,
because not used: `strands_tools`, `MCPClient`, `vended_interventions`, "agent as tool".


## Challenges we ran into

- **The vision model's bounding boxes drift.** On cluttered photos of a panel they landed
  low and oversized — 3 tight hits out of 14 boxes checked by eye. So a box is a soft
  highlight snapped to a grid, never a crisp "it is exactly here."
- **Confidence scores are not stable run to run — the pass/fail boolean is.** The same
  photo and claim gave 0.82 on one run and 0.20 on the next, for an identical, correct
  refusal. So we gate on the boolean.
- **A well-behaved model hides a broken gate.** With an honest prompt the model never tried
  to skip a step, which proves nothing. The permissive-prompt test is the only one that
  exercises the hook.
- **The search engine rate-limits you exactly when you're demoing.** DuckDuckGo answers
  HTTP 202 after repeated lookups from one IP, which parses to zero results and looks
  identical to "no manual exists." So the demo model's manual is baked into the image, a
  cached manual is never overwritten by a later empty result, and the card names its source.


## Accomplishments that we're proud of

- A code-level gate — not a prompt — that a permissive "just do what they say" system prompt
  could not talk past, proven live against Bedrock, not only in a unit test.
- A plan citing the manufacturer's page on every step, for a machine with no assembly video
  anywhere.
- 8/8 correct pass/fail verdicts on real photos of my own panel, including every case where
  the claimed object wasn't in the frame — it refused instead of guessing.
- Two published eval runs with the misses left in, 6/6 red-team photos rejected across both,
  and 184 tests that pass offline on a fresh clone (`pip install -e ".[dev,agentcore]"`, measured 11 Sept).


## What we learned

Refusing to let someone "just claim" a step is done is a harder engineering problem than
describing what's in a photo — and it is also the actual product. The interesting part
wasn't getting a vision model to draw a box. It was making the "no" enforceable in code
instead of hoping the model stays polite.


## What's next

- Run the 12-step eval set on photos of the finished job and publish every result.
- A "what do I even need to do?" mode — I didn't know a Florida house needs its condensate
  line cleared until it went wrong.
- Ask and re-plan mid-job: the plan is fixed at the start, questions work only in chat.
- Job state in S3 instead of `/tmp`; segmentation instead of a box; tighter IAM and
  sign-in on the public URL.



## How this maps to the judging criteria

**Technical Implementation** — eight roles on Strands, the hook system used as an
enforcement boundary rather than for logging, 184 tests passing offline on a fresh clone,
the phone app live
on App Runner and the Guide agent READY on AgentCore Runtime. Every SDK claim has a file and
line in the README.

**Design** — one phone-first flow: name the job, photograph it, get the step drawn on your
own photo, submit evidence, get a plain verdict, read the trace. The refusal, the hazard
stop and the "call a pro" answer are designed screens, not errors.

**Potential Impact** — the audience is first-time homeowners with nobody to show them. The
checkable case: my Westinghouse ePX3030 has **no assembly video on YouTube** (20 results
checked, 9 Sep 2026) and a manual that is a public PDF. Given the model name, StepSpotter
found it and produced **11 steps, 11 citing a manual page**; without it, the same job gave
9 steps that never mention the handle, the two mounts or the four screws, and report "no
tools required" for a job that needs a screwdriver. Both runs:
`docs/research-epx3030-2026-09-09.md`.

**Creativity & Originality** — plenty of tools describe a repair photo. The non-obvious
move is a `BeforeToolCall` hook that makes the agent refuse *itself*, proven by attacking it
with a prompt written to defeat it. The domain shows in the small things: per-step stop
conditions, "don't touch" zones, a manual page on every step, and a refusal to plan
anything involving mains or gas.

**Presentation** — the video runs the real app on a real job in my house, including the
moment it refuses a wrong photo and the eval miss it doesn't hide.


## Testing instructions for judges

**1. The live app — no install, no account:**
<https://w7ihmvgxxj.us-east-1.awsapprunner.com>. Open it on a phone if you can; the photo
buttons go straight to the rear camera. `/healthz` returns `{"ok":true,...}`.

- Type a job — e.g. *"terminate the office network cable into a keystone jack"* — and
  attach a photo. Not in front of a panel? Use `fixtures/onq-keystone-smoke/steps/*.jpg`,
  in order.
- **The thing to try:** submit `fixtures/onq-keystone-smoke/redteam/R1-wrong-photo.jpg` as
  evidence instead. Expected: a "Not yet" verdict naming what's missing, the step counter
  unchanged, no way forward — `event.cancel_tool` firing in `src/stepspotter/gate.py`, and
  the trace shows it.
- **The manual research, live on that same URL:** start a job with the task *"assemble
  Westinghouse ePX3030 pressure washer"* and any photo. The step cards come back citing
  manual pages, and the source line reads *"Manual found via the copy baked into the image
  — pages 10–14"* — the container answering from its build-time cache, so the demo doesn't
  depend on a search engine's mood.
- Ask it to plan something behind a breaker panel or a gas line. Expected: no steps, one
  sentence telling you to call a professional.

**2. Cold, from the repo** — no AWS account needed. Python 3.12+:

```bash
git clone https://github.com/retailbox-automation/stepspotter && cd stepspotter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q                            # 171 passed, 8 skipped
stepspotter research "Westinghouse ePX3030"    # finds the maker's manual, offline
```

Install `".[dev,agentcore]"` instead and it is 184 passed, 7 skipped. Those counts come from
a real fresh clone, and every skip names its own reason under `pytest -rs`.

With Bedrock credentials exported in the same shell command, `stepspotter serve` runs the
web UI and `stepspotter eval fixtures/ --repeat 2` runs the harness. Both published runs are
in `docs/eval-results/`, misses included: 2026-09-09, 3/3 steps and 3/3 red-team; 2026-09-11,
**2/3 steps** (a cable covered the port labels, so the Verifier refused a step that was
done) and 3/3 red-team. The 12-step set in `docs/EVAL-PLAN.md` has not been run.


## Built with

Strands Agents SDK (Python), Amazon Bedrock (Claude Sonnet 4.6 for vision, Claude Haiku 4.5
for cheap turns), Amazon Bedrock AgentCore Runtime, AWS App Runner, Docker, Python 3.12,
FastAPI, Pydantic, Pillow, pypdf, pytest.
