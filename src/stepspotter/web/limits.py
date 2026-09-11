"""Guard rails for a demo that spends money on every photo.

The judging window is 23 days long and the URL is public with no login. Every
``POST /api/jobs`` is a Sonnet-vision call on Bedrock, and every evidence photo is
another one. The AWS Budget at $45 *tells* somebody after the fact; it does not stop
anything. This module is the part that actually stops things:

* **per-IP** — how many jobs and how many photo checks one address may run per hour;
* **a global daily cap on each of them** — the blast radius of one bad day, whoever is
  asking. Both spending endpoints have one, because the per-address window is keyed on a
  header the caller controls: rotate ``X-Forwarded-For`` and the hourly window is gone.
  The day counter is what is left standing, so it has to cover *every* endpoint that
  calls a model, not only job starts;
* **a kill switch** — ``STEPSPOTTER_PAUSED=1`` turns the two spending endpoints into a
  plain 503 with a sentence a judge can read, while the page, the finished jobs and
  ``/healthz`` stay up.

What is deliberately *not* limited: ``GET /`` and ``/healthz`` (they cost nothing and a
health check that can be rate-limited is a way to take yourself down), the card image
(rendered once per step and then served from disk, so its cost is already bounded by
the job cap), advance/escalate/trace (no model behind them).

Counters live in this process. App Runner runs this service at min=max=1 instance, so
one process *is* the service; the day counters are additionally mirrored to small files
under ``$STEPSPOTTER_DATA/limits/`` so that an app reload does not hand the next
visitor a fresh budget. A container replacement does reset it — that is the same
ephemeral disk that loses jobs, and it is written down in docs/DEPLOY.md rather than
papered over.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from collections import deque
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stepspotter import store

#: What a paused demo says. Short, human, and it points at the thing that still works.
PAUSED_MESSAGE = (
    "Demo paused to protect the hackathon budget — see the video/README. "
    "The code and the walkthrough show the whole flow."
)

DEFAULT_JOBS_PER_IP_HOUR = 6
DEFAULT_PHOTOS_PER_IP_HOUR = 30
DEFAULT_MAX_JOBS_PER_DAY = 150
#: A photo check is one vision call, and the card drawn for the next step is a second
#: one — so ~300 checks a day is the same order of image calls as the 150-job ceiling
#: (3 calls each) the $45 budget was drawn around. Roughly 20 complete repairs a day,
#: far above judging traffic; raise STEPSPOTTER_MAX_PHOTOS_PER_DAY if a judge hits it.
DEFAULT_MAX_PHOTOS_PER_DAY = 300
WINDOW_SECONDS = 3600
#: Stop tracking addresses once the table gets silly (a scanner sweep, a CDN).
MAX_TRACKED_IPS = 20_000

JOBS = "jobs"
PHOTOS = "photos"


def _int_env(name: str, default: int) -> int:
    """An env var that must be a positive int, or the default. A typo never opens the tap."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def paused() -> bool:
    """Read the kill switch on every request, so a restart with a new env takes effect."""
    return os.environ.get("STEPSPOTTER_PAUSED", "").strip().lower() in {"1", "true", "yes", "on"}


def client_ip(request: Request) -> tuple[str | None, str]:
    """Who is asking, and how we know — ``(address, source)``; ``None`` means we cannot tell.

    App Runner terminates TLS in front of the container, so the socket peer is the proxy:
    on the live service every request arrives from ``169.254.172.3``. The caller is
    therefore only knowable from a forwarded header, and **App Runner's developer guide
    does not say whether it sets one** (read 2026-09-11; it documents TLS termination and
    says nothing about ``X-Forwarded-For``).

    So this does not assume. If a forwarded header is there, it is the client. If it is
    not, and the peer is the link-local address of an AWS proxy, we return ``None`` —
    everyone would otherwise share one bucket and the first judge of the hour would lock
    out every judge after them. Unidentifiable traffic falls through to the global daily
    cap, which still bounds the money. Wrong in the loose direction, on purpose.

    A forwarded header is spoofable, like every header — a caller who sends a different
    one per request gets a fresh hourly window every time. The daily caps are what stands
    behind it when somebody is actually trying rather than merely curious, which is why
    there is one per spending endpoint and not only on job starts.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first, "x-forwarded-for"
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real, "x-real-ip"
    host = getattr(getattr(request, "client", None), "host", None)
    if not host:
        return None, "unknown"
    # 169.254.0.0/16 — a proxy hop, not a visitor.
    if host.startswith("169.254."):
        return None, "proxy-peer"
    return host, "peer"


class Decision:
    """A refusal: the status to send, the JSON body, and how long to wait."""

    def __init__(self, status: int, detail: str, error: str, retry_after: int, **extra) -> None:
        self.status = status
        self.retry_after = max(1, int(retry_after))
        # `detail` is the field the page already renders: web/page.py's api() helper
        # throws Error(body.detail || body.message) and every caller prints it into the
        # UI and clears its spinner in a finally block. A 429 shaped like this shows up
        # as a sentence, not as "Working…" forever.
        self.body = {"detail": detail, "error": error, "retry_after_seconds": self.retry_after}
        self.body.update(extra)

    def response(self) -> JSONResponse:
        return JSONResponse(
            self.body, status_code=self.status, headers={"Retry-After": str(self.retry_after)}
        )


class Limiter:
    """Sliding-window counters per IP plus one global counter per UTC day."""

    def __init__(
        self,
        jobs_per_ip_hour: int | None = None,
        photos_per_ip_hour: int | None = None,
        max_jobs_per_day: int | None = None,
        max_photos_per_day: int | None = None,
        clock: Callable[[], float] = time.time,
        persist: bool = True,
    ) -> None:
        self.jobs_per_ip_hour = jobs_per_ip_hour or _int_env(
            "STEPSPOTTER_JOBS_PER_IP_HOUR", DEFAULT_JOBS_PER_IP_HOUR
        )
        self.photos_per_ip_hour = photos_per_ip_hour or _int_env(
            "STEPSPOTTER_PHOTOS_PER_IP_HOUR", DEFAULT_PHOTOS_PER_IP_HOUR
        )
        self.max_jobs_per_day = max_jobs_per_day or _int_env(
            "STEPSPOTTER_MAX_JOBS_PER_DAY", DEFAULT_MAX_JOBS_PER_DAY
        )
        self.max_photos_per_day = max_photos_per_day or _int_env(
            "STEPSPOTTER_MAX_PHOTOS_PER_DAY", DEFAULT_MAX_PHOTOS_PER_DAY
        )
        self.clock = clock
        self.persist = persist
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._day: str = ""
        self._day_counts: dict[str, int] = {JOBS: 0, PHOTOS: 0}
        self._lock = threading.Lock()

    def day_cap(self, bucket: str) -> int:
        return self.max_jobs_per_day if bucket == JOBS else self.max_photos_per_day

    # ------------------------------------------------------------------ day counter
    def _today(self) -> str:
        return _dt.datetime.fromtimestamp(self.clock(), _dt.timezone.utc).strftime("%Y-%m-%d")

    def _day_file(self, bucket: str, day: str):
        return store.data_root() / "limits" / f"{bucket}-{day}.json"

    def _load_day(self, bucket: str, day: str) -> int:
        if not self.persist:
            return 0
        try:
            return int(json.loads(self._day_file(bucket, day).read_text())[bucket])
        except Exception:  # noqa: BLE001 - a missing or corrupt counter file is not an outage
            return 0

    def _save_day(self, bucket: str, day: str, count: int) -> None:
        if not self.persist:
            return
        try:
            p = self._day_file(bucket, day)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"day": day, bucket: count}))
        except Exception:  # noqa: BLE001 - never fail a repair because a counter would not write
            pass

    def _roll_day(self) -> None:
        day = self._today()
        if day != self._day:
            self._day = day
            self._day_counts = {b: self._load_day(b, day) for b in (JOBS, PHOTOS)}

    def day_count(self, bucket: str = JOBS) -> int:
        with self._lock:
            self._roll_day()
            return self._day_counts[bucket]

    # ------------------------------------------------------------------- per-IP
    def _prune(self, key: tuple[str, str], now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            if len(self._hits) >= MAX_TRACKED_IPS:
                self._sweep(now)
            # If the sweep freed nothing, the table is full of live windows (a flood of
            # spoofed addresses). Track this one in a deque nobody keeps: the per-address
            # window is skipped, the daily cap still counts it, and the table neither
            # grows without bound nor pays an O(n) sweep on every further request.
            if len(self._hits) < MAX_TRACKED_IPS:
                self._hits[key] = hits
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        return hits

    def _sweep(self, now: float) -> None:
        """Drop addresses whose whole window has expired. Cheap, and only on pressure."""
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
            self._hits.pop(key, None)

    # -------------------------------------------------------------------- check
    def check(self, bucket: str, ip: str | None) -> Decision | None:
        """Count one request. ``None`` means go ahead; a ``Decision`` means refuse.

        ``ip is None`` means the caller could not be told apart from every other caller
        (see ``client_ip``): the per-address window is skipped and only the global daily
        cap applies. A refused request is NOT counted either — a person who keeps tapping
        while they are over the limit should not push their own reset further away.
        """
        if paused():
            return Decision(503, PAUSED_MESSAGE, "paused", retry_after=3600)

        now = self.clock()
        with self._lock:
            per_ip = self.jobs_per_ip_hour if bucket == JOBS else self.photos_per_ip_hour
            hits = None if ip is None else self._prune((bucket, ip), now)
            if hits is not None and len(hits) >= per_ip:
                wait = int(WINDOW_SECONDS - (now - hits[0])) + 1
                # "1 job an hour" and "6 jobs an hour" both have to read like English:
                # the cap is configurable, so the sentence cannot hard-code a plural.
                one = per_ip == 1
                what = ("job" if one else "jobs") if bucket == JOBS else (
                    "photo check" if one else "photo checks"
                )
                return Decision(
                    429,
                    f"This demo allows {per_ip} {what} an hour from one address, so the "
                    f"hackathon credits last until judging ends. Try again in "
                    f"{max(1, wait // 60)} min — the README has the full walkthrough.",
                    "rate_limited",
                    retry_after=wait,
                    scope="per_ip",
                    limit=per_ip,
                    window_seconds=WINDOW_SECONDS,
                )

            # Both spending buckets have a day cap. The per-address window above is keyed
            # on a header the caller sends, so it is the only counter a rotating
            # X-Forwarded-For cannot walk around.
            self._roll_day()
            cap = self.day_cap(bucket)
            if self._day_counts[bucket] >= cap:
                midnight = _dt.datetime.fromtimestamp(now, _dt.timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + _dt.timedelta(days=1)
                wait = int(midnight.timestamp() - now)
                noun = ("jobs" if bucket == JOBS else "photo checks") if cap != 1 else (
                    "job" if bucket == JOBS else "photo check"
                )
                return Decision(
                    429,
                    f"This demo has run its {cap} {noun} for today — "
                    "that cap is what keeps the hackathon credits alive for the whole "
                    "judging window. It resets at midnight UTC; the README and the "
                    "video show the same flow end to end.",
                    "daily_cap",
                    retry_after=wait,
                    scope="global_day",
                    limit=cap,
                    bucket=bucket,
                    day=self._day,
                )
            self._day_counts[bucket] += 1
            self._save_day(bucket, self._day, self._day_counts[bucket])

            if hits is not None:
                hits.append(now)
            return None

    # -------------------------------------------------------------------- status
    def snapshot(self) -> dict:
        """What the limits are and how much of today is gone. For an ops read, not the UI."""
        with self._lock:
            self._roll_day()
            return {
                "paused": paused(),
                "jobs_per_ip_hour": self.jobs_per_ip_hour,
                "photos_per_ip_hour": self.photos_per_ip_hour,
                "max_jobs_per_day": self.max_jobs_per_day,
                "max_photos_per_day": self.max_photos_per_day,
                "jobs_today": self._day_counts[JOBS],
                "photos_today": self._day_counts[PHOTOS],
                "day": self._day,
                "tracked_addresses": len({ip for _b, ip in self._hits}),
            }


def bucket_for(method: str, path: str) -> str | None:
    """Which counter a request belongs to, or ``None`` for the free routes."""
    if method != "POST" or not path.startswith("/api/jobs"):
        return None
    tail = path.rstrip("/")
    if tail == "/api/jobs":
        return JOBS
    if tail.endswith("/photo"):
        return PHOTOS
    return None


def install_limits(app: FastAPI, limiter: Limiter | None = None) -> Limiter:
    """Hang the guard in front of the two endpoints that spend money.

    Middleware, not a dependency, so the whole thing is one import and one call in
    app.py and nothing about the routes has to change.
    """
    lim = limiter or Limiter()
    app.state.limiter = lim
    # Say out loud, once, what this build will actually enforce. `GET /api/jobs/limits/
    # trace` on the live URL then answers "what caps is the deployed image running?"
    # without shelling into anything — the same place the refusals land.
    store.trace("limits", "configured", **lim.snapshot())

    seen: dict[str, bool] = {}

    @app.middleware("http")
    async def _guard(request: Request, call_next):  # noqa: ANN001, ANN202
        bucket = bucket_for(request.method, request.url.path)
        if bucket is None:
            return await call_next(request)
        ip, source = client_ip(request)
        if not seen.get(source):
            # Once per process per source: the trace is how we find out, from the real
            # deployment, whether App Runner forwards the caller at all. `GET
            # /api/jobs/limits/trace` on the live URL answers it without a redeploy.
            seen[source] = True
            store.trace("limits", "client_source", source=source, identified=ip is not None)
        decision = lim.check(bucket, ip)
        if decision is not None:
            store.trace(
                "limits", decision.body["error"], bucket=bucket, ip=ip, path=request.url.path
            )
            return decision.response()
        return await call_next(request)

    return lim
