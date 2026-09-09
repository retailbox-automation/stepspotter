# AgentCore Runtime contract — local transcript, 2026-09-09

The Guide agent behind `POST /invocations` + `GET /ping`, run on this Mac against real
Bedrock (us-east-1). Nothing was deployed to AWS; no AWS resource was created.

| File | What it is |
|---|---|
| `ping.http` | `GET /ping` -> `200 {"status":"Healthy",...}` from `python -m stepspotter.agentcore_entry` |
| `invocation-01-text.json` | a text-only turn ("what can you do?"), 5.2 s |
| `invocation-02-photo.request.json` | the request for the photo turn, base64 elided |
| `invocation-02-photo.json` | the answer: job planned (7 steps), step 1 returned, 44 s |
| `job.trace.jsonl` | the store's trace for that job — `start_job`, `plan`, `card` |
| `container-arm64.txt` | the same two calls against the `linux/arm64` image from `Dockerfile.agentcore` (`aarch64`, python 3.12.14) |

The photo was `docs/design-reference-2026-09-09/raw-photos-onq/03-telecom-module.jpg`,
sent as base64 in the JSON payload (149 KB request).
