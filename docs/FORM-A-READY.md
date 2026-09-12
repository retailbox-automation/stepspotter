# Form A is ready to merge — the decision, and what deploying it costs

Branch **`feat-chat-master`** (worktree `stepspotter-forma/`). Merge-ready, **not merged
and not deployed**: `main` and the live URL are untouched until Mikhail picks a form.

The question this branch exists to answer is the one left open on 09.09: what does a
phone land on — a chat, or the screen stack? This is form A, caught up with everything
`main` has learned since the prototype, so the two can be opened side by side on the
same server instead of compared from memory.

## What changed against `main`

Eight files, 1737 lines added, 14 changed. Nothing in the planner, the verifier, the
gate, the research ladder, the limits or the trace was touched.

| File | What |
|---|---|
| `src/stepspotter/web/chat_page.py` | **new** — form A, one HTML file, no build step |
| `src/stepspotter/web/feed.py` | **new** — the transcript, rebuilt from the job's trace |
| `src/stepspotter/web/ask.py` | **new** — a typed question, answered by a Guide with no tools |
| `src/stepspotter/web/app.py` | the routes below, four feed/card/ask endpoints, one trace fix |
| `tests/test_chat_ui.py` | **new** — 18 tests |
| `tests/test_web.py` | form-B page assertions now read `/steps` (19 lines) |
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
208 passed, 1 skipped, 25 warnings in 5.76s
```

Base on `main` with the photo archive present is 190 passed / 1 skipped. The 18 extra are
the prototype's 13 plus five written for this merge: the two doors, the demo offer, the
whole refuse-then-pass walk through the feed, and an unknown demo photo being refused
rather than guessed.

Clicked as a person, not asserted from code (`chrome-qa`, 390 × 844, iPhone user agent,
real mouse events on real controls — no `element.click()`, no injected state), against
`tools/demo_server.py` on a spare port:

1. **Try a demo job** → the real planner path, a 3-step plan, the step card drawn on the
   packaged panel photo with exactly two marks — one green to work in, one red to leave
   alone.
2. **Send the wrong photo** → *"Not done yet"*, with the offer to skip still on screen.
3. **It is fine — move on anyway** → *"I am not opening the next step. Blocked: step 1 …
   did not pass the check."* The browser is not the gate; the hook is.
4. **Send the right photo** → *"That is done"*, the demo bar hides, **Next step** returns.
5. **Next step** → step 2 of 3, demo bar back. Refusal and pass from the same endpoint in
   one session — the must-differ control, so the pass means something.
6. `/steps` → form B intact (screen stack, demo card, photo button), none of the chat's
   elements in it.

Screenshots of 1, 2 and the refusal: `docs/design-2026-09-12-form-A-ready/`.

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
aws ecr put-image --repository-name stepspotter --image-tag web-rollback-20260912 \
  --image-manifest "$(cat /tmp/live-web.json)" \
  --image-manifest-media-type application/vnd.docker.distribution.manifest.v2+json
aws ecr describe-images --repository-name stepspotter \
  --image-ids imageTag=web-rollback-20260912     # read it BACK, do not trust the put

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
        --image-ids imageTag=web-rollback-20260912 --query 'images[0].imageManifest' --output text)
aws ecr put-image --repository-name stepspotter --image-tag web --image-manifest "$MAN" \
  --image-manifest-media-type application/vnd.docker.distribution.manifest.v2+json
aws apprunner start-deployment --service-arn <service arn>
```

No rebuild, and no lifecycle policy on the repository, so the old image does not expire.
The earlier rollback points — `web-rollback-20260911` and `web-rollback-20260911b` — are
still there if the problem turns out to be older than this branch.

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
* **Known nit, not fixed here:** at 390 px the header subtitle truncates, so *"· step 2
  of 3"* is lost to the ellipsis. The step number is still on the card chip. Left alone
  deliberately — polishing form A before it is chosen is work that may be thrown away.
* **`/jobs` is a second name for form B.** Harmless, but it is a route that exists only
  because the brief called it that. Drop it if the duplication annoys.
