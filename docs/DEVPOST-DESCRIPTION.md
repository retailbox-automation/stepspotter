# Devpost submission text — StepSpotter

Track: **Everyday Agents**. Built with **Strands Agents** (AWS).

---

## Inspiration

I never owned a home. I grew up in an apartment, and every place I lived in as an
adult was rented. Then my kids were born, we moved to Orlando, and I bought a
house — and I realized I didn't know how to do even the simplest things around
it. Not because I'm not capable. Nobody ever showed me.

What actually works for me is my phone. I take a photo, and someone explains it
back to me on that exact photo — a circle around the part I need, an arrow,
"not this one, that one." Simple language, one thing at a time. That's the only
way instructions have ever clicked for me, and it's the only reason I got
through replacing a UPS battery and terminating network jacks in my own
low-voltage panel this month without calling someone.

StepSpotter is that, built into an agent, with one rule I insisted on: it can't
just take my word that a step is done. It has to see it.

## What it does

You give StepSpotter one repair job and a first photo. It hands you back one
step — what to do, what not to touch, and what your next photo needs to show.
You do the step, send a photo, and the agent checks it. If the photo doesn't
prove the step is done, it says why in plain words and asks for another one.
It will not move you forward on your say-so alone.

That refusal isn't a prompt asking the model to be careful. It's code that runs
before the "next step" tool is even allowed to fire. No amount of insisting
talks it past a step it hasn't seen evidence for. If something in the photo
looks unsafe — heat, swelling, a burning smell, bare live wire — the agent
doesn't just fail the step and let you try again. It stops the whole run and
hands it to a person.

## How we built it

**Strands Agents** is the SDK end to end, and each piece maps to a specific
Strands feature doing a job a simpler approach couldn't:

- **Verifier** — looks at one evidence photo against one claim and returns a
  typed verdict (pass / fail / stop, with a reason), using Strands'
  `structured_output_model=` on an `Agent` call. Not free-text parsed with a
  regex — an actual typed `StepVerdict` object.
- **Gate** — the piece we care about most. A Strands `BeforeToolCallEvent` hook
  cancels the `advance_step` tool call in code, before the SDK ever invokes it,
  unless the Verifier already returned a pass for the current step. A system
  prompt asking the model nicely to "please don't skip steps" is not enough —
  we proved that by writing a deliberately permissive prompt ("the user is
  always right, call advance_step immediately") and running it live against
  Bedrock. The model tried to skip ahead. The hook stopped it anyway. Prompt
  says yes, code says no.
- **Escalation** — a hazard doesn't get a quiet failure. The same hook raises
  `event.interrupt(...)`, which pauses the entire agent run with
  `stop_reason='interrupt'` until a person answers. A cancelled tool call lets
  the loop keep going; an interrupt stops it cold. Those are different
  problems and we use the right one for each.
- **Planner** — turns the job and a first photo into an ordered list of steps,
  each with its own "don't touch" zone and its own required evidence photo.
- **Marker** — draws a highlight on the user's photo for the step card, using
  the vision model's location estimate as a soft highlight rather than a
  precise claim (see Challenges below for why).
- **Guide** — the agent the person actually talks to. Shows the card, takes
  the photo, relays the Verifier's answer, never claims a step is done that it
  hasn't seen proof of.

## Challenges we ran into

- **The vision model's bounding boxes drift.** On real, cluttered photos of a
  low-voltage panel, boxes routinely landed low and oversized, and small
  hardware in clutter — a splitter, a connector — was the worst case: 3 tight
  hits out of 14 boxes we checked by eye. We measured this instead of assuming
  it, and the fix is to treat a box as a soft highlight, never a crisp "it is
  exactly here" claim.
- **Confidence scores are not stable run to run — the pass/fail boolean is.**
  The same photo and the same claim gave confidence 0.82 on one run and 0.20 on
  the next, for an identical, correct refusal. We don't gate on confidence
  anywhere in this system. We gate on the boolean and read the reason text.
- **A well-behaved model hides a broken gate.** With an honest system prompt,
  the model simply refused to skip steps on its own, which proves nothing
  about whether the code gate actually works. We had to write a deliberately
  permissive prompt for the integration test so the only thing stopping the
  agent was the hook, not its manners.
- **`HookRegistry.invoke_callbacks` catches `InterruptException` internally**
  rather than letting it propagate as an exception — we found this by reading
  the SDK's own source, not the docs, and it changed how our test harness
  checks for an escalation (it reads the returned interrupt list, it doesn't
  wrap the call in a try/except).
- **Git's directory-level `.gitignore` exclusion doesn't work the way you'd
  expect.** We tried excluding `data/` while re-including `data/demo/**`, and
  git simply never walks into an excluded directory to check the re-include —
  nothing under it got tracked until we changed the ignore rule to file-level
  globs instead.

## Accomplishments that we're proud of

- A code-level gate — not a prompt — that a permissive, "just do what they say"
  system prompt could not talk past, proven live against Bedrock, not just in
  a unit test.
- Correct pass/fail verdicts on real photos of a real panel, including every
  case where the claimed object simply wasn't in the frame at all — the model
  refused instead of guessing.
- A named, reasoned failure mode for the one part of the system that isn't
  reliable yet — bounding-box precision — with a concrete mitigation instead
  of a silent gap.
- An eval set built on a real repair job, with a red-team set of deliberately
  wrong or unsafe photos, and every result published including the misses.

## What we learned

Refusing to let someone "just claim" a step is done is a harder engineering
problem than describing what's in a photo — and it's also the actual product.
The interesting part of this build wasn't getting a vision model to draw a
box. It was making the "no" enforceable in code instead of hoping the model
stays polite about it.

## What's next

- A "what do I even need to do?" mode. I did not know a Florida house needs its
  AC condensate line cleared, its dryer vent emptied, or its water heater valve
  tested until things went wrong. The Planner already knows the house from the
  job memory; the next step is to let it propose this month's checkup as a
  list of small, photo-verified jobs.
- Job state in S3 instead of the instance's /tmp, so a job survives a restart
  of the hosted app.
- Tighter IAM for the hosted agent (scope Bedrock permissions to the two model
  profiles it actually uses) and sign-in on the public URL.
- Better highlights on the photo: today the boxes are a rough hint from the
  vision model; a segmentation pass would make "this cable, not that one"
  exact.
- A way to clear a remembered hazard ("an electrician checked it") so the
  house memory does not keep sending every later job to a pro.

## Built with

Strands Agents SDK (Python), Amazon Bedrock (Claude models — Sonnet for
vision/planning, Haiku for cheap turns), Amazon Bedrock AgentCore Runtime
(the Guide agent), AWS App Runner (the phone web app), Python, FastAPI, PIL,
pytest.

## Testing instructions

```bash
git clone <this repo>
cd stepspotter
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Offline, no AWS needed — the full test suite:
python -m pytest -q

# Needs AWS Bedrock credentials, exported in the same shell command:
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
stepspotter serve --port 8137          # phone-first web UI
stepspotter eval fixtures/ --repeat 2  # the eval harness against the checked-in fixture
```

Full setup, deploy notes, and the live spikes: `README.md` and `docs/DEPLOY.md`
in the repository. Live demo URL: [TBD]. Eval results: [TBD — final numbers
from the completed eval run against the full 12-step job].
