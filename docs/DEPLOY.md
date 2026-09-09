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

**Not yet built here:** the Docker daemon was not running on this machine during the
build session, so the Dockerfile is unverified. Build it once before relying on it.

## Path A — AWS App Runner (recommended for the judges' URL)

App Runner gives an HTTPS URL, runs any HTTP container on any port, and needs no load
balancer. Sketch, from an authenticated shell:

```bash
ACC=$(aws sts get-caller-identity --query Account --output text); REGION=us-east-1
aws ecr create-repository --repository-name stepspotter --region $REGION
aws ecr get-login-password --region $REGION | docker login --username AWS \
  --password-stdin $ACC.dkr.ecr.$REGION.amazonaws.com
docker build -t stepspotter . && docker tag stepspotter:latest $ACC.dkr.ecr.$REGION.amazonaws.com/stepspotter:latest
docker push $ACC.dkr.ecr.$REGION.amazonaws.com/stepspotter:latest

# One IAM role App Runner assumes to pull from ECR (AWSAppRunnerServicePolicyForECRAccess),
# and one INSTANCE role the running container assumes, holding bedrock:InvokeModel.
aws apprunner create-service --service-name stepspotter --region $REGION \
  --source-configuration '{
     "AuthenticationConfiguration":{"AccessRoleArn":"arn:aws:iam::'$ACC':role/AppRunnerECRAccessRole"},
     "AutoDeploymentsEnabled":false,
     "ImageRepository":{"ImageIdentifier":"'$ACC'.dkr.ecr.'$REGION'.amazonaws.com/stepspotter:latest",
       "ImageRepositoryType":"ECR",
       "ImageConfiguration":{"Port":"8080","RuntimeEnvironmentVariables":{"AWS_DEFAULT_REGION":"'$REGION'","STEPSPOTTER_DATA":"/data"}}}}' \
  --instance-configuration '{"Cpu":"1 vCPU","Memory":"2 GB","InstanceRoleArn":"arn:aws:iam::'$ACC':role/StepSpotterBedrockRole"}' \
  --health-check-configuration '{"Protocol":"HTTP","Path":"/healthz","Interval":10,"Timeout":5}'
```

Two things to decide before this is a real demo URL:

* **Storage.** App Runner instances have ephemeral disk and can scale to more than one
  instance, so `/data` is not shared and not durable. For a demo, pin
  `MaxSize: 1`. For anything longer-lived, jobs, cards and traces belong in S3 (they
  are already just files behind `store.py`, which is the seam to change).
* **Access.** The app has no login. Anything on that URL can start a job that costs
  Bedrock calls. Keep it unlisted for judging, or put it behind CloudFront with a
  header check.

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

That is a real refactor (an invocations adapter plus moving photo storage to S3, since
photos cannot travel through a JSON prompt), not a config change. Un-attempted so far,
and the AgentCore Runtime quota on this account has not been checked. Build for
`--platform linux/arm64` if you take it on.

## What proves it works

```bash
PYTHONPATH=src "$PY" -m pytest -q            # 31 passed, 1 skipped (the skip needs AWS)
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

### Deploying it (not done — needs an approved spend)

Two toolchains exist and the Strands docs now point at the newer one:

* **`@aws/agentcore` (npm)** — "the recommended tool for new projects"; the pip starter
  toolkit prints `The Starter Toolkit CLI is no longer supported` on every command.
  Install with `npm install -g @aws/agentcore`. **Not installed or tried here**, so its
  flags are not written down below — read `agentcore --help` first.
* **`bedrock-agentcore-starter-toolkit` 0.3.12 (pip)** — installed and interrogated
  here, so the verbs below are its real ones (`launch` is gone; it is `deploy` now):

```bash
# from the repo root, with AWS creds exported in the SAME command (see above)
pip install bedrock-agentcore-starter-toolkit
"$PY" -m pip freeze > requirements.txt      # the toolkit wants a requirements file

agentcore configure --entrypoint src/stepspotter/agentcore_entry.py \
                    --name stepspotter-guide \
                    --requirements-file requirements.txt \
                    --region us-east-1 \
                    --non-interactive          # execution role + ECR repo auto-created

agentcore deploy                 # cloud CodeBuild builds ARM64 — no local Docker needed
                                 # --local-build to build with the Docker above instead
agentcore invoke '{"prompt": "what can you do?"}'
agentcore status                 # config + runtime details
```

`agentcore configure` writes `.bedrock_agentcore.yaml` in the repo root (git-ignore it
if it ends up holding account ids). **Rollback:** `agentcore destroy --dry-run` first,
then `agentcore destroy --force` — it removes the runtime endpoint, the agent runtime,
the ECR images, the CodeBuild project and the execution role (add
`--delete-ecr-repo` for the repository itself).

**IAM.** The deploying identity here is the IAM *user* `fleetmemory-cli`. It can already
read AgentCore control-plane state (`aws bedrock-agentcore-control list-agent-runtimes
--region us-east-1` returns `{"agentRuntimes": []}` — nothing deployed on this account
yet). The rest is **unverified**: a toolkit deploy also needs ECR create/push, CodeBuild
project + start-build, an S3 source bucket, CloudWatch Logs, `iam:CreateRole` +
`iam:PassRole` for the execution role it creates, and
`bedrock-agentcore-control:CreateAgentRuntime` / `bedrock-agentcore:InvokeAgentRuntime`.
The *execution role* the runtime assumes needs `bedrock:InvokeModel` (the planner,
marker and verifier all call Bedrock), ECR pull, and Logs write. Expect the first
`agentcore deploy` to fail on a missing permission and read the error rather than
pre-granting a wildcard.

**Cost.** Consumption-based: AgentCore Runtime bills for the CPU/memory a session
actually consumes (sessions are idle-timed out; `--idle-timeout` defaults to 900 s),
*plus* the Bedrock tokens each turn spends, plus ECR storage, CodeBuild minutes and
CloudWatch. The 44 s photo turn above is three model calls, so a demo session is not
free. Current rates: the Bedrock AgentCore pricing page — do not quote from here.

**Verify after deploying.** `agentcore invoke '{"prompt":"what can you do?"}'` (a
`runtimeSessionId` must be 33+ characters if you call `invoke_agent_runtime` with boto3
directly), then CloudWatch logs for the runtime, then a photo turn — the answer must
carry a `job_id` and a `trace_tail`, and the trace is what proves the gate ran.

### Known gaps, stated plainly

* **State is per-session and disposable.** `STEPSPOTTER_DATA=/tmp/stepspotter` in
  `Dockerfile.agentcore`. AgentCore gives each `runtimeSessionId` its own microVM, so
  that directory is private to one repair — and gone when the session ends. Jobs,
  cards and traces belong in S3 for anything real; `store.py` is the seam.
* **No AgentCore Memory.** The Guide uses `FileSessionManager` keyed by `job_id`, which
  lives in that same disposable `/tmp`.
* **No observability wiring.** Turning on CloudWatch traces means adding
  `aws-opentelemetry-distro` and running `opentelemetry-instrument python -m
  stepspotter.agentcore_entry`; the toolkit does this itself unless you pass
  `--disable-otel`. Untried here.
* **The image floats.** `pyproject.toml` pins `strands-agents>=1.54.0`, so the ARM64
  build pulled 1.55.0 while the local venv is on 1.54.0. Pin before a deploy you
  intend to keep.
* **No auth.** `/invocations` is protected by IAM at the Runtime boundary, not by
  anything in this code.
