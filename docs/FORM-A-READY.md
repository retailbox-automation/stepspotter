# Form A is ready to merge — the decision, and what deploying it costs

Branch **`feat-chat-master`** (worktree `stepspotter-forma/`). Merge-ready, **not merged
and not deployed**: `main` and the live URL are untouched until Mikhail picks a form.

The question this branch exists to answer is the one left open on 09.09: what does a
phone land on — a chat, or the screen stack? This is form A, caught up with everything
`main` has learned since the prototype, so the two can be opened side by side on the
same server instead of compared from memory.

> **Updated 12.09** — this branch has since been merged up to `main` (it carries the
> skip button's server side) and the feed has had the design pass described in
> [§ The design pass](#the-design-pass-12092026). Still **not merged down, not deployed**.

## What changed against `main`

Eight files, 1993 lines added, 15 changed. Nothing in the planner, the verifier, the
gate, the research ladder, the limits or the trace was touched.

| File | What |
|---|---|
| `src/stepspotter/web/chat_page.py` | **new** — form A, one HTML file, no build step |
| `src/stepspotter/web/feed.py` | **new** — the transcript, rebuilt from the job's trace |
| `src/stepspotter/web/ask.py` | **new** — a typed question, answered by a Guide with no tools |
| `src/stepspotter/web/app.py` | the routes below, four feed/card/ask endpoints, one trace fix |
| `tests/test_chat_ui.py` | **new** — 24 tests |
| `tests/test_web.py` | form-B page assertions now read `/steps` (22 lines) |
| `tools/demo_server.py`, `tools/shots_chat.py` | **new** — run and photograph form A with no AWS account |

### The routes

| Path | Serves |
|---|---|
| `/` and `/chat` | **form A**, the chat master |
| `/steps` and `/jobs` | **form B**, the screen stack, whole and still tested |

Form B is not retired and not frozen: it keeps every one of its tests, it still gets the
demo, the research line and the trace view. Both pages call the same endpoints, the same
`StepGate`, the same trace. Only the arrangement of the screen differs.

### The demo now works inside the chat

This was the gap that made the prototype unmergeable. After `main` added the judge demo,
form A still opened on a text box and a camera button — a reviewer with ten minutes and
no low-voltage panel had no way in at all.

* the offer appears on the first screen, and **only when the three photos are installed**
  (`GET /api/demo` decides; a button that 503s is worse than no button);
* once a demo job is running, the two packaged photos take the place of the single action
  button while a photo is what is wanted. The one-action rule is a rule about someone
  standing in front of an open panel holding a phone; a reviewer at a desk has no camera
  to open, and the refusal is the thing they came to see, so both photos have to be
  reachable without guessing which to press first;
* labels and captions come from the server, so the page never decides which photo is the
  wrong one;
* the moment the verdict passes, the demo bar disappears and the single **Next step**
  button comes back. Demo mode changes where the JPEG comes from and nothing else.

### One server fix that came with the prototype

`POST /advance` traced nothing on the **hazard** path (it raises an interrupt instead of
going through the gate's `on_block`), so a reloaded feed lost the one refusal that
matters most. It now writes a `gate_stop` row. This affects form B too — for the better.

## How it was checked

```
.venv/bin/python -m pytest -q .
219 passed, 1 skipped, 25 warnings in 3.00s
```

Base on `main` with the photo archive present is 195 passed / 1 skipped. The 24 in
`test_chat_ui.py` are the prototype's 13, five written for the merge (the two doors, the
demo offer, the whole refuse-then-pass walk through the feed, and an unknown demo photo
being refused rather than guessed) and six written for the design pass below.

Three of the new assertions were checked by mutation, because a test that reads the page
source is the easy kind to write so that it cannot fail:

| Mutation | Caught by |
|---|---|
| `roleOf` returns `"agent"` for a block (the gate folded back into the agent) | `…names_three_actors_and_marks_each_message_with_its_role` |
| the skip link sends `intent=next` | `…move_on_anyway_takes_the_same_road_to_the_gate` |
| the `FileReader` preview removed | `…composer_shows_the_photo_it_is_about_to_send` |

Each mutation was applied to a committed tree, proved applied by a `grep` count going
1 → 0, and reverted with `git checkout` plus a `__pycache__` wipe and a re-run.

Clicked as a person, not asserted from code (`chrome-qa`, 390 × 844, iPhone user agent,
real mouse events on real controls — no `element.click()`, no injected state), against
`tools/demo_server.py` on a spare port:

1. **Try a demo job** → the real planner path, a 3-step plan, the step card drawn on the
   packaged panel photo with exactly two marks — one green to work in, one red to leave
   alone.
2. **Send the wrong photo** → *"Not done yet"*, with the offer to skip still on screen.
3. **It is fine — move on anyway** → the refusal, now under **"Gate (code, not the
   model)"**: *"Refused — no photo has passed for this step. Blocked: step 1 … did not
   pass the check."* The browser is not the gate; the hook is.
4. **Send the right photo** → *"That is done"*, the demo bar hides, **Next step** returns.
5. **Next step** → step 2 of 3, demo bar back, and the header chip moves to *Step 2 of 3*
   without truncating. Refusal and pass from the same endpoint in one session — the
   must-differ control, so the pass means something.
6. **Reload on `?job=…`** → the whole conversation comes back from the trace, refusal
   included, still drawn as the gate. Pressing *move on anyway* a second time is refused
   a second time, and both asks are on the record.
7. **A photo staged in the composer** → the thumbnail of the real file, read in the
   browser, before anything is uploaded.
8. `/steps` → form B intact (screen stack, demo card, photo button), none of the chat's
   elements in it.
9. **Dark mode**, emulated, at the same 390 px → shot 06.

Two things worth writing down about how that checking went, because both would have
produced a confident wrong answer:

* **The a11y snapshot is blind to this page's details.** It reported the camera emoji
  still in the composer and no image, when a screenshot showed the emoji gone and the
  thumbnail drawn. Every visual claim above is from a screenshot, not from the tree.
* **A snapshot taken in the same call as the click can race the handler.** Once, the
  refusal "had not appeared" and the button "was still disabled"; a second snapshot,
  taken after, showed both correct. Anything read straight off a click was re-read.

Server side, on a second unbuffered run, by curl rather than by the page:

```
POST /api/jobs/<id>/advance  intent=skip  -> blocked=True hazard=False
GET  /api/jobs/<id>/trace    -> [... verdict, skip_attempt, gate_block]
GET  /api/jobs/<id>/feed     -> [... verdict, block]
```

`tools/demo_server.py` writes no access log, so statuses were taken per-request from
`curl` (`/` 200, `/steps` 200, demo-photo 200) rather than claimed from an empty file;
the log itself held zero tracebacks.

Screenshots of 1, 2 and the refusal: `docs/design-2026-09-12-form-A-ready/`. The walk was
run again after the design pass — see the six shots in
`docs/design-2026-09-12-form-A-ship/` and its `README.md`.

## If Mikhail says yes — deploying it

Only the **web** image changes. `agentcore_entry.py` imports `store`, `guide` and
`web.photos`, none of which this branch touches, so **the guide image and the AgentCore
Runtime do not need rebuilding or redeploying.** Leave them alone.

Merge first, then build from `main`. Full context in `docs/DEPLOY.md` § Path A; the
account, roles, service and scaling config already exist and are not re-created.

```bash
# 0. merge, and prove the suite still passes on the merged tree
git -C stepspotter merge feat-chat-master
.venv/bin/python -m pytest -q .

# 1. tag the digest that is live NOW, so the rollback has a name
#    (:web is a mutable tag — a push replaces what it points at)
aws ecr batch-get-image --repository-name stepspotter --image-ids imageTag=web \
  --query 'images[0].imageManifest' --output text > /tmp/live-web.json
aws ecr put-image --repository-name stepspotter --image-tag web-rollback-20260912b \
  --image-manifest "$(cat /tmp/live-web.json)" \
  --image-manifest-media-type application/vnd.docker.distribution.manifest.v2+json
aws ecr describe-images --repository-name stepspotter \
  --image-ids imageTag=web-rollback-20260912b     # read it BACK, do not trust the put

# 2. build x86_64 explicitly (Apple Silicon builds arm64 by default and App Runner
#    fails to start AFTER the push, not before it) and push
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --output type=docker -t stepspotter:apprunner .
aws ecr get-login-password --region us-east-1 | docker login --username AWS \
  --password-stdin $ACC.dkr.ecr.us-east-1.amazonaws.com
docker tag stepspotter:apprunner $ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter:web
docker push $ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter:web

# 3. deploy and poll — do not guess when it is up
aws apprunner start-deployment --service-arn <service arn>
aws apprunner describe-service --service-arn <service arn> \
  --query 'Service.{Status:Status,Url:ServiceUrl}'
```

`--provenance=false --sbom=false` is not optional: without it buildx pushes an OCI image
index plus an attestation manifest instead of a plain single-arch manifest, and the
service cannot pull it.

**Verify by what fails, not by what answers.** `/healthz` 200 proves nothing about which
code is serving:

```bash
URL=https://w7ihmvgxxj.us-east-1.awsapprunner.com
curl -s $URL/ | grep -c 'Ask a question about this step'   # 1 = form A is on /
curl -s $URL/steps | grep -c 'I did it — take photo'       # 1 = form B still at /steps
curl -s $URL/healthz
# then read the CloudWatch application log for Traceback/ERROR/5xx in the first
# five minutes, counted against the same grep taken BEFORE the push
```

### Rollback

```bash
MAN=$(aws ecr batch-get-image --repository-name stepspotter \
        --image-ids imageTag=web-rollback-20260912b --query 'images[0].imageManifest' --output text)
aws ecr put-image --repository-name stepspotter --image-tag web --image-manifest "$MAN" \
  --image-manifest-media-type application/vnd.docker.distribution.manifest.v2+json
aws apprunner start-deployment --service-arn <service arn>
```

No rebuild, and no lifecycle policy on the repository, so the old image does not expire.
The earlier rollback points — `web-rollback-20260911` and `web-rollback-20260911b` — are
still there if the problem turns out to be older than this branch.

## The design pass (12.09.2026)

Two things landed after the branch was first written up: `main`'s skip button, and a
design pass on the feed. Both are in the merge above.

### The gate is now its own speaker

Every message carries `data-role` — `you`, `agent` or `gate` — and the name of the
speaker is printed when the speaker changes. The third role is the one that matters: a
refusal is a Strands hook cancelling a tool call, and it used to be drawn in the agent's
red verdict card with the agent's voice. That reads as *the model decided to be careful*,
which is exactly the claim this project does not make. It is now a smaller, neutral,
centred block over the line **"Gate (code, not the model)"** — visibly not one more
opinion in the stream. Shot 04.

### One road to the gate

`main` gave `POST /advance` an `intent` field and a `skip_attempt` trace row so the
record can tell a collected pass apart from someone asking to close a step on their
word. The chat's *"It is fine — move on anyway"* link now sends `intent=skip` down that
same endpoint — the page has exactly one place that posts to `/advance`, asserted by a
test, so there is no second and looser road to the next step.

The gate never sees `intent` and never cares: asked with a passing photo it still opens
the step, which is its own test.

### The rest of the pass

* **The photo you are about to send is shown.** A `FileReader` thumbnail in the composer,
  because *"Photo ready"* is a promise and a thumbnail is the only thing that catches the
  shot of your own shoes before it costs a model call and half a minute of standing in
  front of an open panel. Shot 02.
* **"Step 2 of 3" cannot be truncated.** It used to share one `nowrap` line with the job
  title and was the half the ellipsis ate; it is a chip of its own now, and only the
  title shortens. Shot 03.
* **The wait says what it is doing.** Silence for half a minute reads as a hang. After
  five quiet seconds — under that a line that appears and vanishes is just noise — the
  typing bubble becomes *"Searching for the manual…"*, then *"Planning the steps…"*, with
  a live seconds counter, which is the part that proves it is still alive. The captions
  are honest about the real sequence a plan runs; the server streams no progress, so they
  are timers, not reports, and they are named as timers in the code.
* **One 8 px rhythm and one type scale** for the chat chrome, as CSS variables. The step
  card keeps its own measurements: it is the reference sheet, not chat furniture. The
  boxes, the legend and the two-mark rule are untouched.
* **A dark palette**, tokens only, behind `prefers-color-scheme`. The hues of the three
  meanings are lifted rather than swapped, so a red box drawn into a JPEG still matches
  the red word beside it. Verified by eye under emulated dark mode, shot 06 — not by
  reading the CSS.

### One bug the clicking found

The in-feed links (*move on anyway*, *stop now*) disabled themselves on press and were
never re-enabled. Because a message is never removed from the feed, a refusal a judge had
just watched became a control that silently did nothing the second time. They re-enable
now; asking twice is allowed, each ask is its own trace row, and the gate answers it the
same way.

This was invisible to the test suite and invisible to the a11y snapshot. It showed up on
the second press, by hand.

## Risks, honestly

* **The judges' URL changes shape.** Anyone who saw the App Runner link before sees a
  different first screen after. The screenshots already in the Devpost draft and in
  `docs/SCREENSHOTS.md` are form B: merging this and deploying it without re-shooting
  them leaves the submission showing a UI that is no longer what `/` serves. Either
  re-shoot, or point the submission at `/steps`. **This is the expensive part, not the
  merge.**
* **Two faces to keep working.** Every future UI change now has two pages to land in, or
  a decision to let one rot. Worth saying out loud before merging, not after.
* **The chat has never run against live Bedrock.** Every check above used the fake
  planner/verifier in `tools/demo_server.py`. The endpoints are `main`'s, unchanged, so
  the risk is presentation (a 35-second wait, a plan of 8 steps rather than 3, a card
  that fails to draw), not correctness. `tools/shots_chat.py --short` exists to shoot a
  live run without staging a pass.
* **Ask costs a model call.** The question lane builds a Guide with **no tools**, so a
  question cannot move the job — but each question is a Bedrock call that the per-address
  hour cap does not count (`bucket_for()` only meters the POSTs that plan or verify). Low
  volume at demo scale; worth a bucket of its own if the link is ever posted publicly.
* ~~**Known nit:** at 390 px the header subtitle truncates, so *"· step 2 of 3"* is lost
  to the ellipsis.~~ **Fixed 12.09** — the counter is its own non-shrinking chip; only the
  job title ellipsises. Verified by eye at 390 px, shot 03.
* **`/jobs` is a second name for form B.** Harmless, but it is a route that exists only
  because the brief called it that. Drop it if the duplication annoys.
* **Dark mode is new and has only been looked at, not lived in.** It is a token swap
  behind `prefers-color-scheme`, so nothing structural depends on it, and it was checked
  by eye at 390 px. What has *not* been checked is a marked photo whose drawn-in red box
  sits against the dark card on a real phone screen in a dim room — the one place the
  lifted hues could still read wrong. Delete the `@media (prefers-color-scheme: dark)`
  block if it is not wanted; nothing else refers to it.
* **The stage captions are timers, not progress.** The server streams nothing, so
  *"Searching for the manual…"* is what the job does at that moment by construction, not
  a report that it is doing it. With `STEPSPOTTER_RESEARCH=0` the first caption would
  overstate — the same way form B's *"Looking up the manual…"* already does.
* **The byline only prints on a change of speaker.** Right for reading, but it means a
  screenshot cropped to a single agent message may carry no name on it. The three shots
  used in the submission all include the hand-off.
