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
