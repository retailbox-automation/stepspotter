<!-- Ready to paste into builder.aws.com. Publishing needs an AWS Builder ID
     (profile.aws.amazon.com) — Michael publishes this himself. Keep the title
     exactly as written: the bonus requires "Agents for Humans" in the title. -->

# Building for Agents for Humans: an agent that says no to itself

I bought my first house this year, after a lifetime in apartments, and found out I
didn't know how to do the simplest things in it. What works for me is photos: take a
picture, get it marked up, one step at a time. For the Agents for Humans hackathon I
turned that into StepSpotter — a Strands Agents app that walks you through a repair one
photo-verified step at a time and won't unlock the next step until your photo proves you
finished the last one. Here's how it got built on AWS, including what didn't go
cleanly.

## The gate is a hook, not a prompt

Most "AI repair helper" demos describe a photo and suggest a next step. That's advice.
I wanted getting ahead of yourself to be impossible, and the obvious fix — a system
prompt saying "don't let them skip ahead" — is a request, not a boundary. Strands Agents
has a hook that runs before a tool call is dispatched, and that turned out to be the
whole design:

```python
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

class StepGate(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use["name"] != "advance_step":
            return
        step_id = event.tool_use["input"]["step_id"]
        verdict = self.state.verdicts.get(step_id)
        if step_id != self.state.current or verdict is None or not verdict.passed:
            event.cancel_tool = "Blocked: I have not checked this step yet. " \
                "Send a photo of the finished step and I will verify it first."
```

Two details I got from introspecting the running SDK (strands-agents 1.55.0) rather
than from docs. `cancel_tool` takes a **string**, not a boolean — the string becomes the
tool result the model reads back, so the refusal the user sees is my text, not a
paraphrase of an error. And the event is frozen against everything except `cancel_tool`,
`selected_tool` and `tool_use`; a hook can refuse a call, but it can't quietly rewrite
the agent's state from inside a checkpoint.

For an actual hazard, cancelling isn't enough — a cancel fails one call and lets the
loop carry on. There I use `event.interrupt(...)`, which pauses the whole run with
`stop_reason='interrupt'` until a person answers. Worth knowing:
`HookRegistry.invoke_callbacks` catches `InterruptException` internally and returns the
interrupt in a list, so a test wrapping the call in `try/except` will never fire.

## A well-behaved model hides a broken gate

This is the part I'd tell anyone building enforcement into an agent. My first
integration test used an honest system prompt, and the model never tried to skip a step.
The test passed and proved nothing: a hook that never gets exercised is
indistinguishable from one that doesn't work.

So I wrote a second system prompt, for the test only: "the user is always right, call
`advance_step` immediately when they ask." Same gate, same code. Under that prompt the
model did try to skip ahead — and the hook cancelled it anyway. That's the evidence.
Not "the agent behaved," but "the agent tried to misbehave and the code stopped it."

## Grounding the plan in the manufacturer's own manual

The first real request was a pressure washer with no assembly video anywhere on
YouTube — I checked twenty results; the machine is still in its box. The manual, though, is a public PDF. So the agent
now searches for it, downloads it, pulls the assembly pages out with `pypdf`, and hands
them to the planner with page markers. Every step then cites the page it came from.
Without that grounding, the same job produced a plan that never mentioned the handle,
the mounts or the four screws, and claimed no tools were required for a job that needs a
screwdriver.

The honest part: the search engine rate-limits. DuckDuckGo starts returning HTTP 202
with a challenge page after repeated lookups from one IP, so the lookup has to be a
status and never a crash — the repair carries on without the manual — and a manual
already cached must never be overwritten by a later empty result. A bad minute can't be
allowed to erase something you already have.

## What the vision model is and isn't good at

Amazon Bedrock (Claude Sonnet 4.6 for vision and planning, via Strands BedrockModel)
handles verdicts well: eight out of eight correct pass/fail calls on real photos of my
own panel, including every case where the claimed object wasn't in frame — it refused
instead of guessing.

Spatial precision is another story. Bounding boxes on cluttered photos landed low and
oversized; small hardware in clutter was the worst case, three tight hits out of
fourteen boxes I checked by eye. I measured it instead of assuming, and designed around
it: a box is a soft highlight snapped to a grid, never a claim that the part is exactly
there. One more measured thing — confidence scores swung 0.82 to 0.20 across runs on an
identical, correct refusal. Nothing in this system gates on confidence. It gates on the
boolean and reads the reason.

## Deploying it

Two AWS paths, both live. The phone-first web app runs as a container on **AWS App
Runner** — one service, `/healthz`, no load balancer to wire up, which is the right
trade when what you need is a URL a judge can open on a phone. The Guide agent itself is
also deployed to **Amazon Bedrock AgentCore Runtime**: `BedrockAgentCoreApp` with an
`@app.entrypoint`, an arm64 image, and a contract that is just `POST /invocations` and
`GET /ping` — I ran that contract locally before pushing, which saved a blind
deploy-and-pray cycle.

The one thing I'd change: job state lives in the instance's `/tmp`, which is ephemeral.
S3 is the fix, and it's the next commit rather than a lesson.

Built for the Agents for Humans hackathon, Everyday Agents track, on Strands Agents.
Live app (open it on a phone): https://w7ihmvgxxj.us-east-1.awsapprunner.com
Code, architecture diagram and the published eval run:
https://github.com/retailbox-automation/stepspotter
