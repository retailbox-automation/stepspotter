# Running and deploying StepSpotter

The web UI is one FastAPI app (`stepspotter.web.app:app`) serving a single HTML page
plus a small JSON API. It holds no state of its own: every job is a file under
`$STEPSPOTTER_DATA/jobs/`, and everything that happened is appended to
`<job_id>.trace.jsonl`.

## Run it on your own machine

```bash
PY=".../spike/.venv/bin/python"          # or a venv with `pip install -e .`
while IFS='=' read -r k v; do case "$k" in AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY) export "$k=$v";; esac; done < path/to/.env
export AWS_DEFAULT_REGION=us-east-1
PYTHONPATH=src "$PY" -m stepspotter.cli serve --host 0.0.0.0 --port 8080
```

Then open `http://<your-mac's-LAN-ip>:8080` **on the phone** — the photo inputs use
`capture="environment"`, so the phone opens the rear camera straight into the page.
Two notes from doing exactly this:

* port 8080 on this Mac is already taken by the WhatsApp bridge; the live smoke ran
  on `--port 8137`. Check with `lsof -nP -iTCP:8080 -sTCP:LISTEN` before blaming the app.
* a job survives a reload: the page puts `?job=<job_id>` in the address bar, and a
  cold load with that parameter comes back to the same step. Nothing is kept in the
  browser.

### Environment

| Variable | Needed | What it does |
|---|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | yes | Bedrock (planner, marker, verifier). On AWS, prefer an instance role and set neither. |
| `AWS_DEFAULT_REGION` | yes | `us-east-1` in every run so far. |
| `STEPSPOTTER_DATA` | no | Where jobs, cards, photos and traces are written. Defaults to `<repo>/data`. In a container set it to a mounted path — `/data` in the Dockerfile. |
| `STEPSPOTTER_MODEL` | no | Override the Bedrock model id. Unset uses the Strands default (`global.anthropic.claude-sonnet-4-6`), which is what every spike and the live smoke ran on. |
| `STEPSPOTTER_PAUSED` | no | `1` turns the two spending endpoints into a 503 with a sentence a judge can read. The page, old jobs and `/healthz` stay up. The kill switch — see [OPERATIONS-JUDGING.md](OPERATIONS-JUDGING.md). |
| `STEPSPOTTER_JOBS_PER_IP_HOUR` | no | New jobs one address may start per hour. Default **6**. |
| `STEPSPOTTER_PHOTOS_PER_IP_HOUR` | no | Evidence photos one address may have checked per hour. Default **30**. |
| `STEPSPOTTER_MAX_JOBS_PER_DAY` | no | New jobs the whole service will start in a UTC day, whoever is asking. Default **150**. |
| `STEPSPOTTER_MAX_PHOTOS_PER_DAY` | no | Evidence photos the whole service will check in a UTC day, whoever is asking. Default **300**. |

The last four are read on every request by `src/stepspotter/web/limits.py`; a junk or
non-positive value falls back to the default, so a typo can never open the tap. Only
`POST /api/jobs` and `POST /api/jobs/{id}/photo` are metered — the ones that call
Bedrock. `GET /`, `/healthz`, the card image, advance, escalate and the trace are free.

The Bedrock export has one trap worth repeating: a stale `~/.aws/credentials` is
picked up ambiently, so an export that never reached the process shows up as
`Operation not allowed` rather than as a missing-credentials error. Export and run in
the **same** shell command.

## Container

```bash
docker build -t stepspotter .
docker run --rm -p 8080:8080 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION=us-east-1 \
  -v "$PWD/data:/data" stepspotter
```

`HEALTHCHECK` polls `GET /healthz` in-container with urllib (the slim image has no
curl). The image runs as uid 10001, not root, and writes only to `/data`.

Both images are built and pushed as of 2026-09-09: the web image runs on App Runner
(`--platform linux/amd64`) and the Guide image runs on AgentCore Runtime
(`--platform linux/arm64`, `Dockerfile.agentcore`). See **What is deployed right now**.

## What is deployed right now (2026-09-11)

Both halves are live in **us-east-1**, account `7620****7428`, paid from the hackathon
AWS credits. Everything below was read back from AWS with `describe`/`get` calls, not
from the exit code of the command that created it.

| What | Name / id | Where |
|---|---|---|
| Web UI (phone-first) | App Runner service `stepspotter` | **https://w7ihmvgxxj.us-east-1.awsapprunner.com** |
| Guide agent | AgentCore Runtime `stepspotter_guide`, id `stepspotter_guide-Af1MWv8fnL`, version 2 | `arn:aws:bedrock-agentcore:us-east-1:7620****7428:runtime/stepspotter_guide-Af1MWv8fnL` |
| Web image | ECR `stepspotter:web` — linux/amd64, 127.0 MB, `sha256:e0de4935…` | `<acct>.dkr.ecr.us-east-1.amazonaws.com/stepspotter` |
| Guide image | ECR `stepspotter-agentcore:guide` — linux/arm64, `sha256:14deb1de…` | `<acct>.dkr.ecr.us-east-1.amazonaws.com/stepspotter-agentcore` |
| Pull role | IAM `stepspotter-apprunner-ecr-access` (`AWSAppRunnerServicePolicyForECRAccess`, trusts `build.apprunner.amazonaws.com`) | IAM |
| Container role | IAM `stepspotter-apprunner-instance` (inline `stepspotter-bedrock-invoke`, trusts `tasks.apprunner.amazonaws.com`) | IAM |
| Runtime role | IAM `stepspotter-agentcore-execution` (inline `stepspotter-agentcore-runtime`, trusts `bedrock-agentcore.amazonaws.com`) | IAM |
| Scaling | App Runner auto-scaling config `stepspotter-single` rev 1 — min 1, max 1, concurrency 100 | App Runner |
| Spend guard | AWS Budget `stepspotter-hackathon` — $45/month, e-mail at 50 / 80 / 100 % | Billing (global) |
| Alerts | SNS `stepspotter-alerts` → admin@retailbox-automation.com (**confirmed** 2026-09-11), alarms `stepspotter-5xx` and `stepspotter-request-flood` | CloudWatch / SNS |
| Request caps | `web/limits.py` — 6 jobs + 30 photo checks per hour per address, 150 jobs + 300 photo checks per day for the whole service, `STEPSPOTTER_PAUSED` kill switch | in the image |
| Logs | `/aws/apprunner/stepspotter/<service-id>/{application,service}` and `/aws/bedrock-agentcore/runtimes/stepspotter_guide-Af1MWv8fnL-DEFAULT` | CloudWatch |

**There are no AWS access keys anywhere in either deployment.** Both containers get
Bedrock through a role: `AWS_ACCESS_KEY_ID` is unset in App Runner's environment, and
the first live job on that URL planned nine steps off a real photo — which only works
if `bedrock:InvokeModel` reached the model through `stepspotter-apprunner-instance`.

## Redeploy of 2026-09-11 — and how to undo it

The merge of the manual-research work (baked manual cache, five-source ladder) was
pushed to both deployments on 2026-09-11. Both images are pulled by a **mutable tag**
(`:web`, `:guide`), so a push replaces what the tag points at. Before pushing, the
previous digests were given their own permanent tags, because "roll back" is worthless
if the old image is only reachable by a digest nobody wrote down:

| | Previous (rollback point) | Now live |
|---|---|---|
| `stepspotter:web` | `sha256:833d2f07…`, also tagged **`web-rollback-20260911`** | `sha256:e0de4935…` |
| `stepspotter-agentcore:guide` | `sha256:c5098995…`, also tagged **`guide-rollback-20260911`** | `sha256:14deb1de…` |
| AgentCore Runtime version | 1 | 2 |

Neither repository has a lifecycle policy, so the old images do not expire.

To roll back, re-point the tag at the old digest and redeploy — no rebuild:

```bash
# web: retag the rollback digest back onto :web, then redeploy the service
MAN=$(aws ecr batch-get-image --repository-name stepspotter \
        --image-ids imageTag=web-rollback-20260911 --query 'images[0].imageManifest' --output text)
aws ecr put-image --repository-name stepspotter --image-tag web --image-manifest "$MAN" \
  --image-manifest-media-type application/vnd.docker.distribution.manifest.v2+json
aws apprunner start-deployment --service-arn <service arn>

# guide: same, then update the runtime (it makes a new version pointing at the old image)
MAN=$(aws ecr batch-get-image --repository-name stepspotter-agentcore \
        --image-ids imageTag=guide-rollback-20260911 --query 'images[0].imageManifest' --output text)
aws ecr put-image --repository-name stepspotter-agentcore --image-tag guide --image-manifest "$MAN" \
  --image-manifest-media-type application/vnd.docker.distribution.manifest.v2+json
aws bedrock-agentcore-control update-agent-runtime --agent-runtime-id stepspotter_guide-Af1MWv8fnL ...
```

### What was checked after the push (failures, not successes)

Error counts were taken **before** the deploy and again after, so "after" had something
to compare against. Both windows: **0 Traceback, 0 ERROR, 0 Timeout, 0 5xx, 0 Exception**
across `/aws/apprunner/.../application`, `.../service` and the AgentCore log group —
190 requests logged, every one a 200. Nothing was rolled back.

What was proven, rather than assumed:

* **The new code is actually serving** — the deployed HTML contains `researchLine` and
  the string `No manual found, so these steps come from the photo alone`, which exist
  only in this build. A `/healthz` 200 alone would not have shown that.
* **The baked cache answers on App Runner, with no search engine.** A live job for
  *assemble Westinghouse ePX3030 pressure washer* planned 10 steps in 30 s and the card
  read **"Manual found via the copy baked into the image (no network) — pages 10, 11,
  12, 13, 14"**, `research.source = "bundled"`. That is the DuckDuckGo rate-limit risk
  closed on the hosted service, not just locally.
* **The gate still refuses, and still lets through.** On a job whose step 1 wanted
  labelled cables, two wrong photos were rejected and `POST /advance` — called directly,
  going around the hidden button — returned `blocked:true` and wrote a `gate_block` row.
  On a second job, a correct panel photo produced `passed:true`, the button appeared, and
  the click moved the job to step 2 of 8 (`advance` in the trace).
* **AgentCore v2 answers**, `statusCode` 200 in 6.6 s, and resolves the ePX3030 manual to
  pages 10–14 from the same baked excerpt.

Offline behaviour was checked in both images before either was pushed: the known model
resolves with `source: bundled` under `--network none`, and an unknown model
(`APC BX1350M`) returns `not_found` with the full trail — the control that shows the
probe can actually fail.

## Path A — AWS App Runner (the judges' URL)

⚠️ **App Runner is closed to new customers** (the banner on every page of its
developer guide, read 2026-09-09; AWS points new work at *Amazon ECS Express Mode*).
This account could still create a service, so the path below worked — but do not plan
a second, different account around it.

App Runner takes an **x86_64** image. Build with an explicit platform on an Apple
Silicon Mac or the service will fail to start after the push, not before it:

```bash
# creds exported in the SAME command (see Environment above); ACC = account id
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --output type=docker -t stepspotter:apprunner .
aws ecr create-repository --repository-name stepspotter --region us-east-1
aws ecr get-login-password --region us-east-1 | docker login --username AWS \
  --password-stdin $ACC.dkr.ecr.us-east-1.amazonaws.com
docker tag stepspotter:apprunner $ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter:web
docker push $ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter:web
aws ecr describe-images --repository-name stepspotter --image-ids imageTag=web
```

`--provenance=false --sbom=false` matters: without it buildx pushes an OCI *image
index* plus an attestation manifest instead of a plain single-arch manifest. The tag
`stepspotter:web-amd64` in ECR is that first, index-shaped push, kept only as a
comparison; `stepspotter:web` is the one the service pulls.

Then the two roles, the scaling config, and the service:

```bash
aws iam create-role --role-name stepspotter-apprunner-ecr-access \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Principal":{"Service":"build.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name stepspotter-apprunner-ecr-access \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess

aws iam create-role --role-name stepspotter-apprunner-instance \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
# inline policy stepspotter-bedrock-invoke:
#   bedrock:InvokeModel + bedrock:InvokeModelWithResponseStream on
#   arn:aws:bedrock:*::foundation-model/*
#   arn:aws:bedrock:*:*:inference-profile/*
#   arn:aws:bedrock:*:*:application-inference-profile/*

aws apprunner create-auto-scaling-configuration \
  --auto-scaling-configuration-name stepspotter-single \
  --min-size 1 --max-size 1 --max-concurrency 100

aws apprunner create-service --service-name stepspotter --region us-east-1 \
  --source-configuration '{"AuthenticationConfiguration":{"AccessRoleArn":"arn:aws:iam::ACC:role/stepspotter-apprunner-ecr-access"},
    "AutoDeploymentsEnabled":false,
    "ImageRepository":{"ImageIdentifier":"ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter:web","ImageRepositoryType":"ECR",
      "ImageConfiguration":{"Port":"8080","RuntimeEnvironmentVariables":{"AWS_DEFAULT_REGION":"us-east-1","AWS_REGION":"us-east-1","STEPSPOTTER_DATA":"/tmp/stepspotter","PORT":"8080"}}}}' \
  --instance-configuration '{"Cpu":"1 vCPU","Memory":"2 GB","InstanceRoleArn":"arn:aws:iam::ACC:role/stepspotter-apprunner-instance"}' \
  --auto-scaling-configuration-arn <arn of stepspotter-single> \
  --health-check-configuration '{"Protocol":"HTTP","Path":"/healthz","Interval":10,"Timeout":5,"HealthyThreshold":1,"UnhealthyThreshold":5}'
```

Why the **inference-profile** ARNs are in that policy: the default model is
`global.anthropic.claude-sonnet-4-6`, a cross-region inference profile. A call against
one needs `bedrock:InvokeModel` on the *profile* ARN **and** on the regional
foundation-model ARN, so a policy naming only the model id fails with an AccessDenied
that reads as if the model does not exist. **TODO (tighten):** the two `*` wildcards
should be narrowed to the two model ids actually used once nothing else is added.

Creation took **3 min 21 s** (`CREATE_SERVICE … SUCCEEDED`). Poll rather than guess:

```bash
aws apprunner describe-service --service-arn <arn> --query 'Service.{Status:Status,Url:ServiceUrl}'
```

### Proof this URL works, from the public internet

Every response below is saved under `data/demo/deploy-verify/`.

```bash
URL=https://w7ihmvgxxj.us-east-1.awsapprunner.com
PHOTO=docs/design-reference-2026-09-09/raw-photos-onq/03-telecom-module.jpg

curl -s $URL/healthz
# {"ok":true,"service":"stepspotter"}                                   HTTP 200, 0.23 s

curl -s -X POST $URL/api/jobs \
  -F "task=Connect the two blue Cat5e cables from the old phone block to new keystone jacks, join them with a patch cord, then test the link" \
  -F "photo=@$PHOTO;type=image/jpeg"
# job-20260909-155841-6307, safety_class diy_ok, 9 steps, 7 tools       HTTP 200, 34 s

curl -s $URL/api/jobs/<job>/card -o card.jpg
# image/jpeg, 334 KB, 1100x1726 — step 1 drawn on their own photo       HTTP 200, 6.7 s

curl -s -X POST $URL/api/jobs/<job>/photo \
  -F "photo=@docs/design-reference-2026-09-09/raw-photos-onq/05-office-jack-open.jpg"
# raw_passed false — "Blue cables are visible but there are no masking
# tape labels marked 'A' or 'B' attached to either of them."            HTTP 200, 4.0 s

curl -s -X POST $URL/api/jobs/<job>/advance
# {"blocked":true,"hazard":false,"reason":"Blocked: step 1 … did not pass
#  the check…"}  — still on step 1 of 9                                 HTTP 200

curl -s $URL/api/jobs/<job>/trace
# start_job → plan → card → verdict(passed:false) → gate_block
```

That last row is the point of the whole project: the refusal is a `gate_block` in the
trace, written by the `StepGate` hook cancelling the tool call, not by the UI hiding a
button — and it behaves the same way on a public URL as it does in `tests/test_web.py`.

### Storage — the one thing that is not production-shaped

`STEPSPOTTER_DATA=/tmp/stepspotter` on an App Runner instance. Jobs, cards, evidence
photos and traces live on that instance's ephemeral disk. `MaxSize: 1` keeps a job on
one instance for the demo, but a redeploy, a scale event or an instance replacement
loses every job in flight.

One variable moves all of it: `STEPSPOTTER_DATA`. The image sets `/data` (created and
chown'd to uid 10001 in the `Dockerfile`); the running App Runner service overrides it
to `/tmp/stepspotter`, which is why the two disagree — both are ephemeral, so the
difference has never mattered, and changing the service's environment is a redeploy
nobody needed. The per-day job counter that backs the global cap lives under the same
root (`$STEPSPOTTER_DATA/limits/jobs-<date>.json`), so it survives an app reload and is
thrown away with the container, exactly like the jobs. **This is deliberate for a demo
and it is not a durable store:** a judge who loses their job to an instance replacement
starts a new one; nothing is promised otherwise, on screen or in the README.

**TODO — S3-backed JobStore.** `src/stepspotter/store.py` is the whole seam: it is a
handful of path helpers plus read/write of JSON and JPEG bytes. Swapping those for an
S3 client (bucket per environment, key prefix `jobs/<job_id>/`) makes the state durable
and lets `MaxSize` rise above 1. Nothing above `store.py` needs to change.

### No auth — and what stands in for it

Anything that can reach that URL can start a job, and every job spends Bedrock tokens.
It is unlisted, not protected. Keep it that way only for judging, and delete the
service afterwards (see **Taking it down**).

Because a login was not an option for a hackathon demo, the spend is bounded instead,
in `src/stepspotter/web/limits.py`: **6 jobs and 30 photo checks per hour per address,
150 jobs and 300 photo checks per day for the whole service, and a kill switch.** Those
are the numbers that decide the worst case, so they are worth doing out loud — a job
start is three Bedrock calls with an image, so 150 jobs a day is the ceiling the $45
budget was drawn around; a photo check is one vision call plus the card drawn for the
next step, so 300 of them a day is the same order of image calls.

**Both day caps exist because the per-address one is optional for the caller.** The
address is read from `X-Forwarded-For`, which the caller sends: rotate it per request
and the hourly window never fills. The day counters are the part that cannot be walked
around, which is why there is one for photo checks and not only for job starts (a
rotating header bought 500 unbounded vision calls in a repro before that cap existed —
`tests/test_limits.py::test_a_rotating_forwarded_header_cannot_buy_unlimited_photo_checks`).
The budget alarm *tells* somebody; these *stop* it. Operating them during judging —
what fires, who hears it, how to pause — is [OPERATIONS-JUDGING.md](OPERATIONS-JUDGING.md).

## Path B — Amazon Bedrock AgentCore Runtime

Honest answer: **this UI does not fit AgentCore Runtime, and should not be forced into
it.** The Runtime contract is a container that is ARM64, listens on 8080, and exposes
exactly `POST /invocations` (one JSON request, one JSON or streamed response) and
`GET /ping`. It is an agent-invocation endpoint, not a web host: no multipart photo
upload, no `image/jpeg` responses for the card, no page to open on a phone.

What does fit there is the **Guide agent** — `stepspotter.guide.build_agent()` is
already a Strands `Agent` with the five tools and the gate hook, which is exactly the
shape AgentCore Runtime hosts. The split that makes sense:

* Guide agent → AgentCore Runtime (`/invocations` takes `{"prompt": ..., "job_id": ...}`),
  with AgentCore Memory for the session instead of `FileSessionManager`;
* this web UI → App Runner, calling that endpoint instead of building its own agent.

The invocations adapter half of that is now built and **deployed** —
`src/stepspotter/agentcore_entry.py`, running as runtime `stepspotter_guide` (photos
travel as base64, not through S3). What is still un-built is the other half: the web UI
calling that runtime instead of constructing its own `Agent` in-process. Today the two
deployments are siblings that share the code, not a client and a server.
The AgentCore Runtime quota on this account was never a problem — one runtime created
first try.

## What proves it works

```bash
PYTHONPATH=src "$PY" -m pytest -q            # 114 passed, 1 skipped (the skip needs AWS)
```

`tests/test_web.py` runs the whole browser flow offline with a fake planner and
verifier, including the part that matters: `POST /advance` before a passing photo is
refused **by the Strands gate hook**, not by the UI. See `src/stepspotter/web/gated.py`
for why the endpoint calls the tool through a real `HookRegistry` rather than moving
the step itself.

A live run against Bedrock is saved under `data/demo/web-smoke/` — plan, card, both
gate refusals, the verifier verdict and the trace, straight off the HTTP API.

## AgentCore Runtime — Guide agent

Path B above says the *web UI* does not fit AgentCore Runtime. It still doesn't. What
does fit is the **Guide agent**, and it is now built and proven locally:
`src/stepspotter/agentcore_entry.py` wraps `guide.build_agent()` — the same five
tools, the same `StepGate` hook, the same file-backed trace — in the Runtime's own
server. **Nothing has been deployed to AWS. No AWS resource has been created.** The
commands below are for whoever approves that spend.

### The contract, as verified here

`bedrock-agentcore 1.22.0`'s `BedrockAgentCoreApp` is a Starlette app that already
declares both required routes — `app.routes` gives `/invocations` (POST) and `/ping`
(GET, HEAD) — so the module only defines what one invocation *means*:

```jsonc
// POST /invocations
{"prompt": "I want to add a second network cable.",  // what the person said
 "job_id": "job-20260909-110551-36b8",               // optional: carry on a repair
 "task":   "add a second ethernet cable",            // optional: starts a job
 "photo_b64": "/9j/4AAQ..."}                         // optional: base64 JPEG/PNG
// ->
{"text": "...", "job_id": "job-...", "current_step": {...}, "trace_tail": [...]}
// plus "stop_reason": "interrupt" when the gate stops the run on a hazard,
// or "error": "bad_photo" | "empty_payload" | "agent_failed" instead of a 500.
```

Photos travel as base64 because a JSON prompt cannot carry a multipart upload; they go
through `web.photos.save_upload` (EXIF rotation, downscale) and the tools see the path.

### Proof, on this machine

```bash
# 1. offline — payload shape, job-id resolution, and a gate refusal through a real HookRegistry
PYTHONPATH=src "$PY" -m pytest -q tests/test_agentcore_entry.py     # 13 passed

# 2. local server, real Bedrock
export STEPSPOTTER_DATA=/tmp/ss PORT=8140 PYTHONPATH=src   # 8080 is taken on this Mac
"$PY" -m stepspotter.agentcore_entry &
curl -s localhost:8140/ping                                 # {"status":"Healthy",...}
curl -sX POST localhost:8140/invocations -H 'Content-Type: application/json' \
     -d '{"prompt":"what can you do?"}'

# 3. the ARM64 image the Runtime actually wants
docker build --platform linux/arm64 -f Dockerfile.agentcore -t stepspotter-agentcore:dev .
docker run -d --name ss-ac --platform linux/arm64 -p 8141:8080 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION=us-east-1 \
  stepspotter-agentcore:dev
curl -s localhost:8141/ping && docker exec ss-ac python -c "import platform;print(platform.machine())"
```

All three ran green on 2026-09-09: `/ping` 200, a text turn in 5.2 s, and a
photo + task turn that planned a 7-step job and came back with step 1 in 44 s
(planner + marker + card, three Bedrock calls). The container reported `aarch64`.
Transcripts, including the job trace: `data/demo/agentcore-local/`.

### Deploying it — done, 2026-09-09

Two CLIs wrap this, and neither was used:

* **`@aws/agentcore` (npm)** — checked live (`npx @aws/agentcore --help`). It is a
  *project* tool: `create` scaffolds a new AgentCore project and `deploy` provisions it
  through CDK. Adopting it here would mean restructuring this repo around its layout and
  bootstrapping CDK, for a runtime that is one API call.
* **`bedrock-agentcore-starter-toolkit` (pip)** — installed in the spike venv, and it
  prints `The Starter Toolkit CLI is no longer supported` on every command. Its `deploy`
  builds ARM64 in CodeBuild, which is only useful when you cannot build ARM64 locally.

This is an Apple Silicon Mac, so the ARM64 image is a native build. The deployment is
therefore the control-plane API that both CLIs call underneath — fewer moving parts,
and every step reads back from AWS:

```bash
# 1. the ARM64 image (native here; do NOT let this one build amd64 by accident)
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  --output type=docker -f Dockerfile.agentcore -t stepspotter-agentcore:deploy .
docker run --rm --platform linux/arm64 stepspotter-agentcore:deploy \
  python -c "import platform;print(platform.machine())"          # aarch64

aws ecr create-repository --repository-name stepspotter-agentcore --region us-east-1
docker tag stepspotter-agentcore:deploy $ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter-agentcore:guide
docker push $ACC.dkr.ecr.us-east-1.amazonaws.com/stepspotter-agentcore:guide

# 2. the execution role — trust policy and permissions copied from
#    docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html
#    (principal bedrock-agentcore.amazonaws.com, with aws:SourceAccount +
#     aws:SourceArn conditions; ECR pull, Logs, X-Ray, cloudwatch:PutMetricData in the
#     bedrock-agentcore namespace, GetWorkloadAccessToken*, bedrock:InvokeModel*)
aws iam create-role --role-name stepspotter-agentcore-execution ...
aws iam put-role-policy --role-name stepspotter-agentcore-execution \
  --policy-name stepspotter-agentcore-runtime ...

# 3. the runtime itself
aws bedrock-agentcore-control create-agent-runtime \
  --agent-runtime-name stepspotter_guide \
  --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"'$ACC'.dkr.ecr.us-east-1.amazonaws.com/stepspotter-agentcore:guide"}}' \
  --role-arn arn:aws:iam::$ACC:role/stepspotter-agentcore-execution \
  --network-configuration '{"networkMode":"PUBLIC"}' \
  --environment-variables '{"STEPSPOTTER_DATA":"/tmp/stepspotter","AWS_REGION":"us-east-1"}' \
  --description "StepSpotter Guide agent (Strands) behind the AgentCore Runtime contract"

aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id stepspotter_guide-Af1MWv8fnL --query status     # CREATING -> READY
```

`create-agent-runtime` returned `CREATING` and `get-agent-runtime` reported `READY`
within a minute. The name has to match `[a-zA-Z][a-zA-Z0-9_]{0,47}`, which is why it is
`stepspotter_guide` with an underscore and not a hyphen.

### Invoking it, live

`runtimeSessionId` must be 33+ characters — a short one is rejected before the container
is ever reached. Payloads go through `--cli-binary-format raw-in-base64-out` (inline
JSON) or `fileb://` (a photo payload is too big to type):

```bash
ARN=arn:aws:bedrock-agentcore:us-east-1:7620****7428:runtime/stepspotter_guide-Af1MWv8fnL

aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn $ARN \
  --runtime-session-id "stepspotter-deploy-verify-$(date +%s)-aaaaaaaaaa" \
  --payload '{"prompt":"What can you do?"}' \
  --cli-binary-format raw-in-base64-out --content-type application/json out.json

aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn $ARN \
  --runtime-session-id "stepspotter-photo-verify-$(date +%s)-bbbbbbbbbb" \
  --payload fileb://payload.json --content-type application/json out.json
# payload.json = {"task": "...", "prompt": "...", "photo_b64": "<base64 jpeg>"}
```

Both ran green on 2026-09-09 against the deployed runtime, `statusCode` 200:

| Call | Time | Result |
|---|---|---|
| `{"prompt":"What can you do?"}` | 12.0 s | the Guide explains the five-step loop; `job_id` null, empty trace |
| task + `photo_b64` of `03-telecom-module.jpg` | 47.1 s | `job-20260909-155728-ef57`, a **9-step** plan, step 1 of 9 returned with its `evidence_required`, `trace_tail` = `start_job → plan → card` |

Transcripts (and the request shape, with the base64 elided) are saved under
`data/demo/deploy-verify/agentcore/`.

CloudWatch confirms the container, not just the API:
`/aws/bedrock-agentcore/runtimes/stepspotter_guide-Af1MWv8fnL-DEFAULT` holds one stream
per invocation, and the photo turn's stream shows `Tool #1: start_job`,
`Tool #2: show_step` and the step text — the same tools the CLI and the web UI call.

```bash
aws logs describe-log-streams \
  --log-group-name /aws/bedrock-agentcore/runtimes/stepspotter_guide-Af1MWv8fnL-DEFAULT \
  --order-by LastEventTime --descending --max-items 3
```

One harmless line appears in those logs at boot: `WARNING: Invalid HTTP request
received.` — the platform's health probe opening a socket before the app is listening.
`/ping` answers afterwards, and the runtime went `READY`.

## What it costs (rates read 2026-09-09; per-service pricing pages)

| Line | Rate | Per month here |
|---|---|---|
| App Runner provisioned memory | $0.007 / GB-hour, billed while the service is `RUNNING` | 2 GB × 730 h = **$10.22** |
| App Runner active CPU | $0.064 / vCPU-hour, only while serving a request | demo traffic ≈ **$0.10–1.30** |
| AgentCore Runtime | $0.0895 / vCPU-hour + $0.00945 / GB-hour, per second, idle CPU free but memory billed for the session's life | ≈ $0.004 per session → **under $3** at demo volume |
| ECR storage | $0.10 / GB-month; 240 MB + 121 MB stored | **$0.04** |
| CloudWatch Logs | ingest + storage, tiny volumes | **< $1** |
| **Bedrock tokens** | per token, Sonnet 4.6 with images; a job start is 3 model calls (planner, marker, verifier) | **the variable** — grows with every visitor |

**Baseline with nobody visiting: about $11/month.** Under the $45 budget, and the
budget alerts at $22.50 / $36 / $45 exist precisely because Bedrock tokens on an
unauthenticated URL are the one line nobody controls. Deleting the App Runner service
after judging drops the standing cost to the $0.04 of ECR storage.

## Taking it down

```bash
# App Runner (stops the $10.22/month immediately)
aws apprunner delete-service --service-arn arn:aws:apprunner:us-east-1:ACC:service/stepspotter/cee52fc66d5a4e23b40a9088eed84725
aws apprunner delete-auto-scaling-configuration \
  --auto-scaling-configuration-arn <arn of stepspotter-single revision 1>

# AgentCore Runtime
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id stepspotter_guide-Af1MWv8fnL

# images
aws ecr delete-repository --repository-name stepspotter --force
aws ecr delete-repository --repository-name stepspotter-agentcore --force

# roles — inline policies and attachments have to go first
aws iam delete-role-policy --role-name stepspotter-apprunner-instance --policy-name stepspotter-bedrock-invoke
aws iam delete-role --role-name stepspotter-apprunner-instance
aws iam detach-role-policy --role-name stepspotter-apprunner-ecr-access \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
aws iam delete-role --role-name stepspotter-apprunner-ecr-access
aws iam delete-role-policy --role-name stepspotter-agentcore-execution --policy-name stepspotter-agentcore-runtime
aws iam delete-role --role-name stepspotter-agentcore-execution

# log groups (optional) and the budget
aws logs delete-log-group --log-group-name /aws/bedrock-agentcore/runtimes/stepspotter_guide-Af1MWv8fnL-DEFAULT
aws budgets delete-budget --account-id ACC --budget-name stepspotter-hackathon
```

Delete the App Runner service **before** its ECR repository — a service whose image is
gone still bills for provisioned memory.

### Known gaps, stated plainly

* **State is per-session and disposable.** `STEPSPOTTER_DATA=/tmp/stepspotter` in
  `Dockerfile.agentcore`. AgentCore gives each `runtimeSessionId` its own microVM, so
  that directory is private to one repair — and gone when the session ends. Jobs,
  cards and traces belong in S3 for anything real; `store.py` is the seam.
* **No AgentCore Memory.** The Guide uses `FileSessionManager` keyed by `job_id`, which
  lives in that same disposable `/tmp`.
* **Logs yes, traces no.** CloudWatch *logs* work out of the box — the deployed runtime
  writes a stream per invocation, tool calls included. OpenTelemetry *traces* are still
  off: that needs `aws-opentelemetry-distro` and `opentelemetry-instrument python -m
  stepspotter.agentcore_entry` as the container command. Untried.
* **The image floats.** `pyproject.toml` asks for `strands-agents>=1.54.0`, so the
  deployed ARM64 image resolved **1.55.0** while the local venv is on 1.54.0 — i.e. the
  thing running in AWS is not byte-identical to the thing every local test ran against.
  Pin the version in `pyproject.toml` before a deploy anyone depends on; left floating
  here because changing a dependency floor is the repo owner's call, not the deploy
  lane's.
* **The web deployment is single-instance by choice.** `stepspotter-single` is min 1 /
  max 1 so that `/tmp` state stays on one instance. Raising `MaxSize` without the S3
  store first will scatter jobs across instances and produce 404s.
* **No auth.** `/invocations` is protected by IAM at the Runtime boundary, not by
  anything in this code.
