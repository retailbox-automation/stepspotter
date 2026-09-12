# Running StepSpotter through judging (15.09 – 08.10.2026)

Submission closes 14.09. After that the demo has to survive **23 days unattended** on a
public URL with no login, where every `POST /api/jobs` is three Bedrock calls with an
image on it. Devpost's own update to entrants put it plainly: an open endpoint is *"an
invitation to run up charges"*.

This file is the part nobody writes until it has already gone wrong: what can break,
**who finds out**, and what to do about it. The deploy mechanics — build, push, roll
back — stay in [DEPLOY.md](DEPLOY.md); this is the operating half.

Live URL: **https://w7ihmvgxxj.us-east-1.awsapprunner.com** · account `7620****7428`,
`us-east-1` · App Runner service `stepspotter`
(`arn:aws:apprunner:us-east-1:7620****7428:service/stepspotter/cee52fc66d5a4e23b40a9088eed84725`).

> **State of play.** The alarms, the SNS topic and its confirmed subscription are live
> on the account **now**. The request caps and the kill switch are code — they start
> guarding the judges' URL only when a build containing `web/limits.py` is pushed.
> Until then §1 tells you that money is leaving; nothing stops it.

---

## 1. What can break, and who hears about it

| What | How likely over 23 days | Who finds out today | In how long |
|---|---|---|---|
| Bedrock spend climbs — a bot, a loop, a curious crowd | the one the organiser warned about | **Alarm `stepspotter-request-flood`** → e-mail; then the $45 Budget at 50/80/100 % | ~5 min / next day |
| The app throws 5xx (bad deploy, Bedrock throttle, a bug) | plausible | **Alarm `stepspotter-5xx`** → e-mail | ~5 min |
| Credits run out, Bedrock starts refusing | possible if the flood is not caught | the 5xx alarm, once calls start failing | ~5 min after the first failures |
| **The service is down and nobody is visiting** | possible | **nobody — see §5** | — |
| An instance is replaced; jobs in flight vanish | likely at least once | the judge, mid-repair | immediately |
| A judge hits a rate limit and thinks it is broken | likely | nobody, unless they say so on Devpost | — |

Everything in bold already exists and was tested end to end on 2026-09-11. The one row
without an owner is §5, and it is stated rather than quietly left out.

### The alerts, concretely

* **SNS topic** `arn:aws:sns:us-east-1:7620****7428:stepspotter-alerts`
* **Subscription** — `admin@retailbox-automation.com`, protocol `email`, state
  **confirmed** (`arn:…:stepspotter-alerts:6ae859a3-5f0d-4334-a880-c651b5891876`).
  A mailbox, deliberately: not a banner on a Mac that may be shut.
* **`stepspotter-5xx`** — `AWS/AppRunner` `5xxStatusResponses`, Sum ≥ 3 over 5 minutes,
  missing data treated as *not breaching*. Alarm **and** OK go to the topic, so a
  recovery is announced too.
* **`stepspotter-request-flood`** — `Requests`, Sum ≥ 400 over 5 minutes. The caps in
  `web/limits.py` hold the money down; this says somebody is leaning on them.
* **AWS Budget `stepspotter-hackathon`** — $45/month, mail at 50 / 80 / 100 %. It was
  already there; nothing here duplicates it. It reports, it does not stop.

Proof the path works, not just that it was created (2026-09-11):

```bash
aws cloudwatch set-alarm-state --alarm-name stepspotter-5xx --state-value ALARM \
  --state-reason "End-to-end test of the alert path"
# alarm history: "Successfully executed action arn:aws:sns:…:stepspotter-alerts"
# inbox:         ALARM: "stepspotter-5xx" in US East (N. Virginia)   14:12:55 UTC
aws cloudwatch set-alarm-state --alarm-name stepspotter-5xx --state-value OK --state-reason "test over"
```

Re-run those two lines any time you want to know the wire is still live. An alarm that
has never fired is indistinguishable from one that is broken.

---

## 2. The caps that keep the credits alive

`src/stepspotter/web/limits.py`, in front of the only two endpoints that spend money:

| Limit | Default | Env var |
|---|---|---|
| New jobs per hour, per address | 6 | `STEPSPOTTER_JOBS_PER_IP_HOUR` |
| Photo checks per hour, per address | 30 | `STEPSPOTTER_PHOTOS_PER_IP_HOUR` |
| New jobs per UTC day, whole service | 150 | `STEPSPOTTER_MAX_JOBS_PER_DAY` |
| Photo checks per UTC day, whole service | 300 | `STEPSPOTTER_MAX_PHOTOS_PER_DAY` |

The **demo button counts as the real thing**: it swaps the photo, not the model, so
`POST /api/demo/jobs` is metered as a job and `POST /api/jobs/<id>/demo-photo` as a
photo check. It is the endpoint a judge is most likely to press repeatedly.

The address is the first hop of `X-Forwarded-For` (App Runner terminates TLS in front
of the container). Headers are forgeable — a caller who sends a new one per request
gets a fresh hourly window every time — so **every endpoint that spends money has a
day cap too**, not only job starts. Those two counters are the ones that hold.

**While filming or demoing, raise the per-address cap.** Six jobs an hour is generous
for a judge and tight for somebody shooting takes: a recording session from one address
will hit it. Set `STEPSPOTTER_JOBS_PER_IP_HOUR` higher for the day (the §3(a) call, one
variable) and put it back afterwards — or film against a local server, which is free.
Jobs are already being run against the live URL from other work on this repo, so this is
not hypothetical.

Not limited on purpose: `GET /` and `/healthz` (a health check you can rate-limit is a
way to take your own service down), the card image (drawn once per step, then served
from disk), advance, escalate, the trace. None of them call a model. That includes the
step card's *Skip the photo and move on* button — the one that shows a judge the gate
refusing in code: it rides `POST /api/jobs/<id>/advance`, so pressing it twenty times
costs nothing and cannot exhaust anyone's hourly allowance.

A refusal is **HTTP 429** with a readable body, and the page already renders it — the
JS helper throws `body.detail` and every caller prints it and clears its spinner, so a
judge sees a sentence instead of *Working…* forever. Screenshots of both states, taken
by clicking the real button in a browser: `data/demo/limits/`.

```json
{"detail":"This demo allows 6 jobs an hour from one address, so the hackathon credits
last until judging ends. Try again in 60 min — the README has the full walkthrough.",
 "error":"rate_limited","retry_after_seconds":3600,"scope":"per_ip","limit":6,
 "window_seconds":3600}
```
(copied from the seventh `curl` of a run of seven against a local server with the
defaults in force — the first six returned 200.)

Every refusal is also appended to the trace under job id `limits`
(`$STEPSPOTTER_DATA/jobs/limits.trace.jsonl`), so "a judge says he got a 429" is
answerable from the box rather than from memory.

### One thing we could not check before deploying: does App Runner forward the caller?

On the live service every request reaches the container from **`169.254.172.3`** — the
proxy, not the visitor (`INFO: 169.254.172.3:37574 - "POST /api/jobs HTTP/1.1" 200 OK`
in the application log, read 2026-09-11). So a per-address cap depends entirely on a
forwarded header, and **App Runner's developer guide does not say it sets one.** It
documents TLS termination and says nothing about `X-Forwarded-For`.

Rather than assume, the code refuses to guess: if no forwarding header is present and
the peer is a link-local proxy address, the caller is *unidentified* — the per-address
window is skipped and only the global daily cap applies. That is deliberately the loose
direction. The tight direction would put every judge in one bucket and let the first one
of the hour lock out the rest, which is the worse failure by a distance; the money stays
bounded either way, because the day caps (150 jobs, 300 photo checks) are enforced
regardless of whether we can tell callers apart.

**Settle it with one request after the next deploy**, no code needed:

```bash
curl -s -X POST https://w7ihmvgxxj.us-east-1.awsapprunner.com/api/jobs -F task=probe -F photo=@any.jpg -o /dev/null
curl -s https://w7ihmvgxxj.us-east-1.awsapprunner.com/api/jobs/limits/trace
# {"event":"client_source","source":"x-forwarded-for","identified":true}   -> per-IP caps are live
# {"event":"client_source","source":"proxy-peer","identified":false}       -> only the daily cap is
```
The first metered request per process writes that row on purpose. If it says
`proxy-peer`, the per-address caps are doing nothing and the daily cap is the whole
guard — worth knowing before deciding whether 150/day is still the right number.

The same trace opens with a `configured` row listing the caps the running image is
actually enforcing, so *"which limits does the deployed build have?"* never has to be
answered from memory or from this file:

```json
{"at":"2026-09-11T14:33:15+00:00","job_id":"limits","event":"configured","paused":false,
 "jobs_per_ip_hour":6,"photos_per_ip_hour":30,"max_jobs_per_day":150,"jobs_today":0,
 "day":"2026-09-11","tracked_addresses":0}
```

---

## 3. The kill switch

Two of them, and they are not the same thing.

**(a) `STEPSPOTTER_PAUSED=1` — the polite one.** The page still loads, `/healthz` still
passes, finished jobs still read back; starting a job or checking a photo returns 503:

> Demo paused to protect the hackathon budget — see the video/README. The code and the
> walkthrough show the whole flow.

```bash
# takes effect after the deployment finishes — about 3 minutes
aws apprunner update-service --service-arn arn:aws:apprunner:us-east-1:7620****7428:service/stepspotter/cee52fc66d5a4e23b40a9088eed84725 \
  --source-configuration '{"ImageRepository":{"ImageIdentifier":"7620****7428.dkr.ecr.us-east-1.amazonaws.com/stepspotter:web","ImageRepositoryType":"ECR","ImageConfiguration":{"Port":"8080","RuntimeEnvironmentVariables":{"AWS_DEFAULT_REGION":"us-east-1","AWS_REGION":"us-east-1","PORT":"8080","STEPSPOTTER_DATA":"/tmp/stepspotter","STEPSPOTTER_PAUSED":"1"}}},"AuthenticationConfiguration":{"AccessRoleArn":"arn:aws:iam::7620****7428:role/stepspotter-apprunner-ecr-access"},"AutoDeploymentsEnabled":false}'
aws apprunner describe-service --service-arn <arn> --query 'Service.Status'   # RUNNING again = live
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://w7ihmvgxxj.us-east-1.awsapprunner.com/api/jobs  # expect 503
```

Pass the **whole** `--source-configuration` — App Runner replaces it, so a partial one
drops the other variables. Lowering a cap instead of pausing outright is the same call
with `STEPSPOTTER_MAX_JOBS_PER_DAY` set to something small.

**(b) `aws apprunner pause-service` — the blunt one.** Instant, and it also stops the
$10.22/month of provisioned memory. Judges get a proxy error, not a sentence, so this
is for "the money is actually running away", not for tidying:

```bash
aws apprunner pause-service  --service-arn <arn>   # stops serving AND billing
aws apprunner resume-service --service-arn <arn>   # ~1-2 min to come back
```

Use (a) during judging — a judge who reads *why* it is paused will go to the video;
one who gets a proxy error writes it off as broken.

---

## 4. Runbooks

**A judge reports a 429.** Expected if they were exploring fast. Confirm from the
trace: `curl -s $URL/api/jobs/limits/trace` shows each refusal with its bucket and
address. If several different judges are hitting it, raise
`STEPSPOTTER_JOBS_PER_IP_HOUR` (the §3 call, one variable) rather than removing the
cap. Reply on the Devpost thread with the README link — the flow is fully documented
there, and the walkthrough video shows the same run end to end.

**`stepspotter-request-flood` fires.** Somebody is hammering. Look at where from:

```bash
aws logs filter-log-events --log-group-name /aws/apprunner/stepspotter/cee52fc66d5a4e23b40a9088eed84725/application \
  --start-time $(( ($(date +%s) - 3600) * 1000 )) --filter-pattern '"/api/jobs"' | head -50
```
Then check the day counter — if the global cap is already holding (429s with
`"error":"daily_cap"`), the money is bounded and nothing urgent is needed. If it is
not, pause with §3(a) and look again in the morning.

**`stepspotter-5xx` fires.** Read the failures, not the successes:

```bash
for g in application service; do
  aws logs filter-log-events --log-group-name /aws/apprunner/stepspotter/cee52fc66d5a4e23b40a9088eed84725/$g \
    --start-time $(( ($(date +%s) - 1800) * 1000 )) --filter-pattern '?ERROR ?Traceback ?Exception ?Throttling' | head -40
done
```
`ThrottlingException` or `AccessDenied` from Bedrock is a credits/quota problem, not a
code problem — go to **credits** below. A Traceback right after a push is a bad deploy:
roll back, it is two commands and no rebuild, in
[DEPLOY.md § Redeploy of 2026-09-11 — and how to undo it](DEPLOY.md#redeploy-of-2026-09-11--and-how-to-undo-it)
(re-point `web-rollback-<date>` onto `:web`, then `aws apprunner start-deployment`).

**Credits run out.** Check what is left before guessing:
```bash
aws ce get-cost-and-usage --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE
```
Credits sit under Billing → Credits (IAM access to Billing was enabled for the admin
user on 09.09). If they are nearly gone, pause with §3(a) rather than letting judges
meet a 502: a paused demo with an honest sentence and a working video reads far better
than a broken one.

**Jobs disappear.** An instance replacement takes `/tmp/stepspotter` with it. Nothing to
fix — start a new job. This is written down in
[DEPLOY.md § Storage](DEPLOY.md#storage--the-one-thing-that-is-not-production-shaped)
and is a deliberate demo trade-off, not a surprise.

**Who reads the Devpost forum.** Mikhail. The entrant updates and the discussion thread
for *Agents for Humans* are the only channel the organisers use to reach entrants
during judging; the manager is shawni@devpost.com. Judges ask questions there, and a
question left for a week reads as an abandoned project. Worth a look twice a week for
the 23 days — a repeating Tasks-calendar entry is the cheapest way to not forget.

---

## 5. The gap that is still open: nobody is told when it goes dark

If the service stops serving and nobody happens to visit, **no alarm fires** — and it
is worth being precise about why, because the obvious fix does not work. App Runner's
`ActiveInstances` metric looks like a liveness signal and is not: AWS's own
documentation says *"if the `ActiveInstances` metric displays zero, it means that there
are no requests for the service. It does not indicate that the number of instances for
your service is zero."* An alarm on it would fire every quiet night and be muted within
a week. `Requests` has the same shape — no visitors is not an outage.

What exists today is `~/Library/LaunchAgents/com.retailbox.stepspotter-healthz.plist`
on Mikhail's Mac, polling `/healthz`. Reading the script: after three consecutive
failures it appends `ALERT healthz failing x3` to a log file **and does nothing else** —
the notification line was removed on 09.09 and left as a no-op. So the current
detector needs the Mac awake *and* somebody reading a log file.

Three ways to close it. Two cost money, so they are Mikhail's call, not the lane's:

1. **Free — point the Mac watcher at the SNS topic.** One line in
   `stepspotter/data/watch/healthz-watch.sh`, in place of the `: # no-op`:
   ```bash
   aws sns publish --region us-east-1 \
     --topic-arn arn:aws:sns:us-east-1:7620****7428:stepspotter-alerts \
     --subject "StepSpotter healthz failing x$n" \
     --message "$ts last=$http  https://w7ihmvgxxj.us-east-1.awsapprunner.com/healthz"
   ```
   Turns a log line into an e-mail for $0. Still dies with the Mac, and the script needs
   credentials in its environment. Better than nothing, not a real answer.
2. **~$1/month — a Route 53 health check** on `w7ihmvgxxj.us-east-1.awsapprunner.com`
   `/healthz` plus an alarm on its `HealthCheckStatus` into the same topic. Probes from
   several AWS regions, independent of any Mac. Basic checks on an AWS endpoint in the
   same account are free up to 50, but HTTPS counts as an optional feature at **$1.00
   per month** (Route 53 pricing page, read 2026-09-11), and App Runner only speaks
   HTTPS. Needs a yes on the dollar.
3. **Free but needs a signup** — an outside uptime service on its free tier (5-minute
   checks, e-mail alerts). No AWS cost, one more account to own.

Recommendation: **2**, for the 23 days, then delete it with the service. A dollar to
know within five minutes that the thing the judges are scoring has stopped answering is
the cheapest line in this whole file. Not created, because it spends money that was not
signed off.

---

## 6. When judging ends

Winners are announced around 14.10. After that, **delete the App Runner service** — it
is $10.22/month of provisioned memory doing nothing — along with these alarms and the
topic. Full teardown list in [DEPLOY.md § Taking it down](DEPLOY.md#taking-it-down),
plus:

```bash
aws cloudwatch delete-alarms --alarm-names stepspotter-5xx stepspotter-request-flood
aws sns delete-topic --topic-arn arn:aws:sns:us-east-1:7620****7428:stepspotter-alerts
```
