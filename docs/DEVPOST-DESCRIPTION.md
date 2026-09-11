# Devpost submission text — StepSpotter

Track: **Everyday Agents**. Built on **Strands Agents** (AWS).

---

**StepSpotter gives you one home-repair step at a time, drawn on your own photo, and
refuses to unlock the next step until a photo proves you finished the last one
safely. The refusal is a Strands Agents hook cancelling a tool call in code — not a
prompt asking a model to be careful.**

## Inspiration

I never owned a home. I grew up in an apartment, and every place I lived in as an
adult was rented. Then my kids were born, we moved to Orlando, and I bought a house —
and I realized I didn't know how to do even the simplest things around it. Not because
I'm not capable. Nobody ever showed me.

The obvious answer is to hire someone. I tried that. Since buying the house I have
hired or quoted roughly three dozen contractors, and more than half of those jobs
failed, stalled, or had to be redone. An unlicensed electrician left three circuits
dead on a $999 job and refused a refund. A mold company billed for square footage its
own lab had marked unaffected. A moving crew took payment and never showed up. The
jobs I ended up doing myself went better.

So I do more myself now, and what works for me is my phone. I take a photo, and
someone explains it back to me on that exact photo — a circle around the part I need,
an arrow, "not this one, that one." One thing at a time. That is the only way
instructions have ever clicked for me, and the only reason I got through replacing a
UPS battery and terminating network jacks in my own low-voltage panel this month
without calling anyone.

StepSpotter is that, built into an agent, with one rule I insisted on: it cannot take
my word that a step is done. It has to see it.

## What it does

You give StepSpotter one repair job and a first photo. It hands back **one step** —
what to do, what not to touch, and what your next photo has to show. You do it, send a
photo, and the agent checks that photo against that step. If the photo doesn't prove
the step is done, it says why in plain words and asks for another one. It will not move
you forward on your say-so alone.

Name a brand and a model — "assemble my Westinghouse ePX3030 pressure washer" — and it
finds the manufacturer's own manual first, pulls out the assembly pages, and writes the
steps in the manual's order and part names, **each step citing the page it came from**.
Your photo still outranks the manual: if what's in front of you doesn't match the
diagram, the step says so.

If a photo shows something unsafe — heat, swelling, a burnt smell, bare live wire — it
doesn't fail the step and let you retry. It stops the whole run and hands it to a
person. Jobs that need a licensed trade (inside a breaker panel, gas, roofing) never get
a plan at all: the Planner returns an empty step list and one sentence telling you to
call a pro.

## How we built it

**Strands Agents** is the SDK end to end, and each role maps to a specific Strands
feature doing a job a simpler approach couldn't:

- **Verifier** — reads one evidence photo against one claim and returns a typed verdict
  (pass / fail / stop, with a reason) via `structured_output_model=` on the invocation.
  A real `StepVerdict` object, not free text scraped with a regex.
- **Gate** — the piece that matters most. A Strands `BeforeToolCallEvent` hook sets
  `event.cancel_tool = "<reason>"`, killing the `advance_step` call before the SDK
  dispatches it, unless the Verifier already passed the current step. We proved it with
  a deliberately permissive system prompt ("the user is always right, call advance_step
  immediately") live against Bedrock. The model tried to skip ahead. The hook stopped it
  anyway. Prompt says yes, code says no.
- **Escalation** — a hazard gets `event.interrupt(...)` instead, pausing the whole run
  with `stop_reason='interrupt'` until a person answers. A cancel fails one call and
  lets the loop continue; an interrupt stops it cold.
- **Planner** — job plus first photo into an ordered typed `Plan`, each step carrying
  its own "don't touch" and its own required evidence photo.
- **Researcher** — finds the manufacturer's manual, downloads the PDF, extracts the
  assembly pages with page markers. No API key: DuckDuckGo's HTML endpoint and `pypdf`,
  cached per product, switchable off with one environment variable.
- **Marker** — draws the highlight on your photo, treating the vision model's box as a
  soft highlight rather than a precise claim (see Challenges).
- **Guide** — the agent you talk to: six `@tool` functions and a Strands
  `FileSessionManager`, so a job survives a restart instead of starting over.

The phone web app is deployed on AWS App Runner; the Guide agent also runs on Amazon
Bedrock AgentCore Runtime. The web UI never talks to the model directly — it routes
through the same `StepGate` object the agent uses, so there is one policy behind two
front doors, not two copies of a rule that can drift apart.

## Challenges we ran into

- **The vision model's bounding boxes drift.** On real, cluttered photos of a
  low-voltage panel they landed low and oversized; small hardware in clutter was the
  worst case — 3 tight hits out of 14 boxes we checked by eye. We measured it instead of
  assuming, and redesigned around it: a box is a soft highlight snapped to a grid, never
  a crisp "it is exactly here."
- **Confidence scores are not stable run to run — the pass/fail boolean is.** The same
  photo and the same claim gave confidence 0.82 on one run and 0.20 on the next, for an
  identical, correct refusal. We gate on the boolean and read the reason. Nothing in
  this system gates on confidence.
- **A well-behaved model hides a broken gate.** With an honest prompt the model never
  even tried to skip a step, which proves nothing. The permissive-prompt test is the
  only one that actually exercises the hook.
- **The search engine rate-limits you exactly when you're demoing.** DuckDuckGo answers
  HTTP 202 with a challenge page after repeated lookups from one IP. The Researcher
  treats that as a status, not a crash — the repair carries on without the manual — and
  a manual already cached is never overwritten by a later empty result, because a bad
  minute must not erase something you already have.

## Accomplishments that we're proud of

- A code-level gate — not a prompt — that a permissive, "just do what they say" system
  prompt could not talk past, proven live against Bedrock rather than only in a unit
  test.
- A plan that cites the manufacturer's page for every step, for a machine with no
  assembly video anywhere.
- 8/8 correct pass/fail verdicts on real photos of my own panel, including every case
  where the claimed object wasn't in the frame — it refused instead of guessing.
- 95 tests passing offline: the gate contract, the escalation path, and the eval
  harness's own failure reporting, all covered without touching AWS.

## What we learned

Refusing to let someone "just claim" a step is done is a harder engineering problem
than describing what's in a photo — and it is also the actual product. The interesting
part wasn't getting a vision model to draw a box. It was making the "no" enforceable in
code instead of hoping the model stays polite about it.

## What's next

- Run the full 12-step eval set on photos of the finished job and publish every result,
  misses included.
- A "what do I even need to do?" mode. I did not know a Florida house needs its
  condensate line cleared or its water-heater valve tested until things went wrong.
- Ask and re-plan mid-job: today the plan is fixed when the job starts, and questions
  work only in the chat mode, not in the web UI.
- Job state in S3 instead of the instance's `/tmp`; segmentation instead of a bounding
  box; tighter IAM and sign-in on the public URL.

## Strands Agents features used

`Agent` + `BedrockModel` · `structured_output_model=` typed outputs (`Plan`,
`StepVerdict`) · `HookProvider` + `registry.add_callback(BeforeToolCallEvent, ...)` ·
`event.cancel_tool` as the gate · `event.interrupt(...)` for hazards · six `@tool`
functions · `FileSessionManager` for resumable jobs · a hand-built
`BeforeToolCallEvent` through `HookRegistry`, so the web UI shares the agent's gate ·
AgentCore Runtime entrypoint. File and line for each: the README table of the same
name. Not used, so not claimed: `strands_tools`, `MCPClient`, `vended_interventions`.

## How this maps to the judging criteria

**Technical Implementation** — *"How thoroughly and skillfully does the project use
Strands Agents? Does the code reflect genuine effort and a working, non-trivial
implementation? A live demo and/or AWS AgentCore deployment will strengthen this
score."* Seven roles on Strands, with the hook system used as an enforcement boundary
rather than for logging; 95 tests pass offline; the phone app is live on App Runner and
the Guide agent is READY on Amazon Bedrock AgentCore Runtime. Every SDK claim above has
a file and line number in the README.

**Design** — *"Does the project deliver a complete, coherent product experience — not
just a technical proof of concept?"* One phone-first flow end to end: name the job,
photograph it, get a card with the step drawn on your own photo, submit evidence, get a
plain-language verdict, and a trace view of every decision. The refusal, the hazard stop
and the "call a pro" answer are designed screens, not error states.

**Potential Impact** — *"Does the project make a credible, specific case for solving a
real problem for a real audience, and does the solution actually address that problem
based on what's demonstrated?"* The audience is first-time homeowners who have nobody
to show them and a contractor market that failed more than half the jobs I gave it. The
checkable case: my Westinghouse ePX3030 has **no assembly video on YouTube** (20 results
checked, 9 Sep 2026) and a manual that is a public PDF on the maker's CDN. Given the
model name, StepSpotter found that manual and produced **11 steps, 11 of them citing a
manual page**; without it, the same job produced 9 steps that never mention the handle,
the two mounts or the four screws, and report "no tools required" for a job that needs a
screwdriver. Both runs, verbatim: `docs/research-epx3030-2026-09-09.md`.

**Creativity & Originality** — *"Is this a creative, non-obvious use of Strands Agents
and does the team demonstrate genuine understanding of the problem space they're
working in?"* Plenty of tools describe a repair photo. The non-obvious move is using a
`BeforeToolCall` hook so the agent refuses *itself*, then proving it by attacking it
with a prompt written to defeat it. The domain understanding is in the small things:
per-step stop conditions, "don't touch" zones, a manual page on every step, and a
refusal to plan anything involving mains or gas.

**Presentation** — *"Does the video clearly demonstrate the project working end-to-end?
Does the pitch communicate what problem is solved, who it's for, and why it matters? Is
the overall presentation easy to follow?"* The video runs the real app on a real job in
my own house, including the moment it refuses a wrong photo, and names the problem, the
audience and the stakes in the first thirty seconds.

## Testing instructions for judges

**1. The live app (no install, no account):**
<https://w7ihmvgxxj.us-east-1.awsapprunner.com> — open it on a phone if you can; the
photo buttons go straight to the rear camera. Health check: `/healthz` returns
`{"ok":true,...}`.

- Type a job — e.g. *"terminate the office network cable into a keystone jack"* — and
  attach a photo. If you aren't standing in front of a panel, the repo ships usable
  ones: `fixtures/onq-keystone-smoke/steps/01-confirm-panel.jpg` to start, then
  `02-seat-pairs.jpg` and `03-telecom-landing.jpg` as evidence.
- **The thing to try:** submit `fixtures/onq-keystone-smoke/redteam/R1-wrong-photo.jpg`
  as evidence instead. Expected: a "Not yet" verdict naming what's missing, the step
  counter unchanged, and no way forward — that is `event.cancel_tool` firing in
  `src/stepspotter/gate.py`, and you can see it in the trace view.
- Ask it to plan something behind a breaker panel or a gas line. Expected: no steps at
  all and one sentence telling you to call a professional.

**2. Cold, from the repository** — nothing below needs AWS:

```bash
git clone https://github.com/retailbox-automation/stepspotter && cd stepspotter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,agentcore]"
python -m pytest -q                            # 95 passed, 1 skipped
stepspotter research "Westinghouse ePX3030"    # finds the maker's manual
```

With Bedrock credentials exported in the same shell command, `stepspotter serve
--port 8137` runs the web UI locally and `stepspotter eval fixtures/ --repeat 2` runs
the harness. Published run, misses included: `docs/eval-results/2026-09-09.md` — the
checked-in 3-step smoke fixture, **3/3 steps confirmed, 3/3 wrong photos rejected**,
100% agreement. The full 12-step set in `docs/EVAL-PLAN.md` has not been run yet; that
document marks which rows are real and which are the target shape.

## Built with

Strands Agents SDK (Python), Amazon Bedrock (Claude Sonnet 4.6 for vision and planning,
Claude Haiku 4.5 for cheap turns), Amazon Bedrock AgentCore Runtime, AWS App Runner,
Docker, Python 3.12, FastAPI, Pydantic, Pillow, pypdf, pytest.
