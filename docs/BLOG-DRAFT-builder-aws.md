# Building a repair agent for Agents for Humans that can say no to itself

I bought my first house a few years ago, after living in apartments my whole
life. I had no idea how to do basic repairs, and the thing that actually
worked for me was photos — take a picture, get it marked up, one step at a
time. That habit turned into a hackathon project: StepSpotter, a Strands
Agents app that walks someone through a home repair one photo-verified step
at a time. This post is about the one piece of it I think is worth writing up
on its own: a code-level gate that a well-behaved model can hide, and how we
proved ours actually works.

## The problem with trusting the model to be careful

Most "AI home repair helper" demos ask a vision model to look at a photo and
describe what it sees, then trust its own next-step suggestion. That's fine
for advice. It's not fine for a workflow where getting ahead of yourself has
a real cost — skip a step in terminating a network jack and you re-punch it;
skip the wrong step in something higher-stakes and it's worse than that.

The obvious fix is a system prompt: "don't let the user skip ahead unless
they've shown you proof." We tried exactly that, and it worked — right up
until we deliberately broke it. A prompt is a request. Nothing enforces it
except the model's own disposition to comply, and a model's disposition is
not a security boundary.

## The pattern: BeforeToolCallEvent as a veto, not a request

Strands Agents exposes a hook system that runs before a tool call is actually
dispatched. We use it to gate one specific tool, `advance_step`, which is the
only way the agent's loop can move a job from its current step to the next
one.

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

Two things worth being precise about, because we learned both the hard way by
introspecting the running SDK rather than trusting the docs alone (strands-agents
1.54.0):

**`cancel_tool` wants a string, not just a boolean.** Setting it to `True`
gets you a generic SDK error message. Setting it to a string means the model
receives that exact text as the tool's result and reads it back to the user
in its own words. The refusal the user actually sees comes from your code,
not from the model paraphrasing a boolean.

**The event object is frozen against everything except `cancel_tool`,
`selected_tool`, and `tool_use`.** Try to write any other field and it raises
`AttributeError`. That's a deliberate constraint, and it's a good one — it
means a hook can refuse or observe a call, but it can't quietly rewrite the
agent's other state from inside a callback that's supposed to be a narrow
checkpoint.

For a genuine hazard — a photo showing something actually unsafe — cancelling
isn't enough, because a cancel just fails one tool call and lets the agent
keep going. We use `event.interrupt(name, reason)` instead, which raises
`InterruptException` and pauses the *entire* run with `stop_reason='interrupt'`
until a human resumes it with an answer. Cancel says "not this call." Interrupt
says "stop everything." We needed both, and conflating them would have meant a
hazard just produces a polite retry prompt instead of actually halting.

One gotcha worth flagging for anyone building on this: `HookRegistry.invoke_callbacks`
catches `InterruptException` internally and returns the interrupt in a list rather
than letting it propagate up as a raised exception. We found that by reading the
registry's source, not by guessing from the name — if your test harness wraps the
call in a `try/except InterruptException`, it will never fire, because the SDK
already caught it for you.

## Why we didn't trust our own gate until we tried to break it

Here's the part that actually matters more than the code snippet above: **a
correctly-behaving model can make a broken gate look like a working one.**

Our first integration test used an honest, careful system prompt. The model
never even attempted to call `advance_step` without evidence — it just... didn't
try. The test passed. It also proved nothing, because a hook that never gets
exercised is indistinguishable from a hook that doesn't work.

So we wrote a second, deliberately permissive system prompt for the test
only: "the user is always right, call `advance_step` immediately when they
ask." Same gate, same code, different prompt. Under that prompt, the model
*did* try to skip ahead on its own — and the hook still cancelled the call.
That's the actual evidence the gate works: not "the agent behaved nicely,"
but "the agent tried to misbehave and the code stopped it anyway."

If you're building anything that claims to enforce a rule on an agent, this
is the test to run: don't just check that a polite prompt produces polite
behavior. Write the prompt that tries to defeat your own gate and confirm it
still holds. Anything less is testing the model's manners, not your
enforcement.

## The eval, and publishing the miss

We built a small eval harness around a real repair job — an OnQ low-voltage
panel, two Cat5e runs terminated into keystone jacks, tested with a cable
tester — as a set of steps with a required evidence photo each, plus a
red-team set of deliberately wrong or unsafe photos: a photo of the wrong
object, a photo submitted for the wrong step, an unreadable photo, a hazard,
and no photo at all.

The rule we set for ourselves before running it: publish every result,
including the ones that fail, rather than reporting a single success
percentage. When we ran it, one step genuinely failed — a photo of a punched-down
telecom module where a cable crossed the frame and obscured the port labels
the step needed legible. The verifier correctly said it couldn't tell, rather
than guessing the labels were probably fine. That's the report as it actually
came back, not a cleaned-up version of it: two of three steps confirmed on
the first pass, all red-team cases correctly rejected, and one genuine,
reproducible refusal on an evidence photo that really was ambiguous.

We think that's the more honest way to report an eval for something whose
entire pitch is "it won't let you fake it." A perfect score on a small,
hand-picked sample would tell you less about the gate than one clearly
explained miss does.

## What this is for

StepSpotter isn't trying to be a general home-repair chatbot. It's a narrow
claim: for low-voltage, low-consequence work, an agent can hand you one step
at a time and refuse to move you forward until your own photo proves the
last one was done — and that refusal can live in code instead of in a prompt
asking the model to be careful. The vision model's spatial precision has real
limits, which we measured and designed around rather than papered over. The
gate itself, tested the way we tested it, held every time we tried to make it
fail.

Built for the Agents for Humans hackathon, Everyday Agents track, on Strands
Agents (AWS).
