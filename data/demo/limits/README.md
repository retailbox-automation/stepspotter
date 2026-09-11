# What a judge sees when a limit stops them

Both shots were taken by filling the real form and clicking the real button in a
browser against the app (a local server with fake model functions, so no Bedrock call
was spent proving a refusal). The point of keeping them is the second half of each: the
button has gone back to **Plan my steps** — the page is not stuck on *Working…*, which
is the failure everybody actually ships when they bolt a rate limit onto a single-page
app.

| File | What it shows | How it was produced |
|---|---|---|
| `ui-429-rate-limited.png` | The per-address cap refusing a second job, in words | `STEPSPOTTER_JOBS_PER_IP_HOUR=1`, one job already started from this address, then Plan my steps |
| `ui-503-paused.png` | The kill switch: *Demo paused to protect the hackathon budget — see the video/README* | `STEPSPOTTER_PAUSED=1`, then Plan my steps |

No page code was changed to make either of these work. `web/page.py`'s `api()` helper
already throws `body.detail` for any non-OK response, every caller prints it, and every
caller clears its spinner in a `finally` — so a 429 or a 503 shaped like the ones in
`web/limits.py` renders as a sentence on its own.

Operating notes, alarm ARNs and the runbooks: `docs/OPERATIONS-JUDGING.md`.
