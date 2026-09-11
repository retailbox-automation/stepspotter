"""The guard rails on a public demo: per-IP caps, a daily cap, and the kill switch.

Every test here is offline — no model is called. What is being checked is the thing a
judge or a bored bot would actually hit: the N-th request works and the N+1-th comes
back as a sentence they can read, the free routes stay free, and a paused demo says so
instead of spending.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from stepspotter import store
from stepspotter.guide import JobService
from stepspotter.models import Box, Plan, Step, StepVerdict
from stepspotter.web.app import create_app
from stepspotter.web.limits import JOBS, PHOTOS, Limiter, bucket_for, client_ip


def _photo_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (80, 100, 130)).save(buf, format="JPEG")
    return buf.getvalue()


def _plan(task: str, photo: str, model_id=None) -> Plan:
    return Plan(
        job_title="Two jacks",
        safety_class="diy_ok",
        steps=[
            Step(
                id=1,
                title="Punch down the cable",
                action="Press the wires into the jack.",
                evidence_required="eight wires seated",
            ),
            Step(id=2, title="Test it", action="Read the tester lights.", evidence_required="all pairs lit"),
        ],
    )


def _service() -> JobService:
    return JobService(
        plan_fn=_plan,
        verify_fn=lambda step, photo, model_id=None: StepVerdict(
            step_id=step.id, passed=True, reason="Looks done."
        ),
        locate_fn=lambda step, photo, model_id=None: [
            Box(label="jack", x0=0.3, y0=0.3, x1=0.6, y1=0.6, kind="act")
        ],
    )


def _client() -> TestClient:
    return TestClient(create_app(_service()))


def _post_job(client: TestClient, ip: str = "203.0.113.7"):
    return client.post(
        "/api/jobs",
        data={"task": "connect two cables"},
        files={"photo": ("p.jpg", _photo_bytes(), "image/jpeg")},
        headers={"X-Forwarded-For": ip},
    )


# --------------------------------------------------------------------- per-IP caps
def test_nth_job_passes_and_the_next_one_is_429_with_a_sentence(monkeypatch):
    """Must-differ: the run that is inside the cap really does succeed."""
    monkeypatch.setenv("STEPSPOTTER_JOBS_PER_IP_HOUR", "3")
    client = _client()

    codes = [_post_job(client).status_code for _ in range(3)]
    assert codes == [200, 200, 200]

    over = _post_job(client)
    assert over.status_code == 429
    body = over.json()
    assert body["error"] == "rate_limited" and body["scope"] == "per_ip" and body["limit"] == 3
    # `detail` is the field web/page.py renders; it has to read like a sentence.
    assert "3 jobs an hour" in body["detail"] and "README" in body["detail"]
    assert int(over.headers["Retry-After"]) > 0


def test_a_second_address_still_gets_its_own_budget(monkeypatch):
    monkeypatch.setenv("STEPSPOTTER_JOBS_PER_IP_HOUR", "1")
    client = _client()
    assert _post_job(client, ip="198.51.100.1").status_code == 200
    refused = _post_job(client, ip="198.51.100.1")
    assert refused.status_code == 429
    # a configurable cap cannot hard-code a plural: "1 job an hour", not "1 jobs"
    assert "1 job an hour" in refused.json()["detail"]
    assert _post_job(client, ip="198.51.100.2").status_code == 200


def test_photo_checks_have_their_own_counter(monkeypatch):
    """A job's own photos must not be spent by the job that created them, and vice versa."""
    monkeypatch.setenv("STEPSPOTTER_JOBS_PER_IP_HOUR", "1")
    monkeypatch.setenv("STEPSPOTTER_PHOTOS_PER_IP_HOUR", "2")
    client = _client()
    job = _post_job(client).json()["job_id"]

    def shot():
        return client.post(
            f"/api/jobs/{job}/photo",
            files={"photo": ("e.jpg", _photo_bytes(), "image/jpeg")},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )

    assert [shot().status_code for _ in range(2)] == [200, 200]
    blocked = shot()
    assert blocked.status_code == 429 and "photo checks" in blocked.json()["detail"]


# ------------------------------------------------------------------- the daily cap
def test_the_daily_cap_holds_across_different_addresses(monkeypatch):
    monkeypatch.setenv("STEPSPOTTER_JOBS_PER_IP_HOUR", "50")
    monkeypatch.setenv("STEPSPOTTER_MAX_JOBS_PER_DAY", "2")
    client = _client()
    assert _post_job(client, ip="192.0.2.1").status_code == 200
    assert _post_job(client, ip="192.0.2.2").status_code == 200
    over = _post_job(client, ip="192.0.2.3")
    assert over.status_code == 429
    assert over.json()["error"] == "daily_cap" and over.json()["scope"] == "global_day"
    assert "2 jobs for today" in over.json()["detail"]


def test_the_day_counter_survives_a_reload_of_the_app(monkeypatch, isolated_data):
    """A restarted process must not hand the next visitor a fresh day's budget."""
    monkeypatch.setenv("STEPSPOTTER_MAX_JOBS_PER_DAY", "2")
    first = _client()
    assert _post_job(first).status_code == 200

    second = _client()  # same STEPSPOTTER_DATA, new process-in-spirit
    assert second.app.state.limiter.day_count() == 1
    assert _post_job(second, ip="192.0.2.9").status_code == 200
    assert _post_job(second, ip="192.0.2.10").status_code == 429


def test_a_refused_request_is_not_counted():
    """Tapping while over the limit must not push the reset further away."""
    now = [1_000_000.0]
    lim = Limiter(jobs_per_ip_hour=1, max_jobs_per_day=99, clock=lambda: now[0], persist=False)
    assert lim.check(JOBS, "1.1.1.1") is None
    first_refusal = lim.check(JOBS, "1.1.1.1")
    now[0] += 30
    second_refusal = lim.check(JOBS, "1.1.1.1")
    assert first_refusal is not None and second_refusal is not None
    # the wait shrank by the 30 s that passed; it did not restart
    assert second_refusal.retry_after < first_refusal.retry_after


def test_the_window_slides_open_again():
    now = [1_000_000.0]
    lim = Limiter(jobs_per_ip_hour=2, max_jobs_per_day=99, clock=lambda: now[0], persist=False)
    assert lim.check(JOBS, "1.1.1.1") is None
    assert lim.check(JOBS, "1.1.1.1") is None
    assert lim.check(JOBS, "1.1.1.1") is not None
    now[0] += 3601
    assert lim.check(JOBS, "1.1.1.1") is None


# --------------------------------------------------------------------- kill switch
def test_paused_returns_503_and_says_why(monkeypatch):
    monkeypatch.setenv("STEPSPOTTER_PAUSED", "1")
    client = _client()
    r = _post_job(client)
    assert r.status_code == 503
    assert r.json()["error"] == "paused"
    assert "Demo paused to protect the hackathon budget" in r.json()["detail"]
    assert "video/README" in r.json()["detail"]


def test_paused_leaves_the_page_and_health_up(monkeypatch):
    """A paused demo still opens, still passes its health check, and still shows old jobs."""
    client = _client()
    job = _post_job(client).json()["job_id"]
    monkeypatch.setenv("STEPSPOTTER_PAUSED", "1")
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get(f"/api/jobs/{job}").status_code == 200
    assert _post_job(client).status_code == 503


def test_the_switch_only_answers_to_real_values(monkeypatch):
    monkeypatch.setenv("STEPSPOTTER_PAUSED", "0")
    assert _post_job(_client()).status_code == 200
    monkeypatch.setenv("STEPSPOTTER_PAUSED", "")
    assert _post_job(_client()).status_code == 200


# ------------------------------------------------------------- what is never limited
def test_health_and_reads_are_never_limited(monkeypatch):
    """A health check you can rate-limit is a way to take your own service down."""
    monkeypatch.setenv("STEPSPOTTER_JOBS_PER_IP_HOUR", "1")
    client = _client()
    job = _post_job(client).json()["job_id"]
    assert _post_job(client).status_code == 429  # the tap is closed

    for _ in range(30):
        assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get(f"/api/jobs/{job}").status_code == 200
    assert client.get(f"/api/jobs/{job}/card").status_code == 200
    assert client.post(f"/api/jobs/{job}/advance").status_code == 200
    assert client.get(f"/api/jobs/{job}/trace").status_code == 200


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("POST", "/api/jobs", JOBS),
        ("POST", "/api/jobs/job-1/photo", PHOTOS),
        ("POST", "/api/jobs/job-1/photo/", PHOTOS),
        ("POST", "/api/jobs/job-1/advance", None),
        ("POST", "/api/jobs/job-1/escalate", None),
        ("GET", "/api/jobs", None),
        ("GET", "/healthz", None),
        ("GET", "/", None),
    ],
)
def test_which_routes_are_metered(method, path, expected):
    assert bucket_for(method, path) == expected


# ------------------------------------------------------------------ address reading
class _Req:
    def __init__(self, headers, host):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


def test_the_client_is_the_first_hop_of_x_forwarded_for():
    assert client_ip(_Req({"x-forwarded-for": "203.0.113.5, 70.132.0.1"}, "10.0.0.1")) == (
        "203.0.113.5",
        "x-forwarded-for",
    )
    assert client_ip(_Req({"x-real-ip": "203.0.113.6"}, "10.0.0.1")) == ("203.0.113.6", "x-real-ip")
    assert client_ip(_Req({}, "10.0.0.1")) == ("10.0.0.1", "peer")


def test_an_aws_proxy_hop_is_not_a_visitor():
    """On App Runner every request arrives from 169.254.172.3. If nothing is forwarded,
    that address is not an identity — treating it as one would let the first judge of
    the hour lock out every judge after them."""
    assert client_ip(_Req({}, "169.254.172.3")) == (None, "proxy-peer")
    assert client_ip(_Req({}, None)) == (None, "unknown")
    # and a forwarded header still wins over the proxy hop
    assert client_ip(_Req({"x-forwarded-for": "198.51.100.4"}, "169.254.172.3")) == (
        "198.51.100.4",
        "x-forwarded-for",
    )


def test_an_unidentified_caller_falls_through_to_the_daily_cap_not_a_lockout():
    """Loose in the right direction: the money stays bounded, the demo never wrongly locks."""
    lim = Limiter(jobs_per_ip_hour=2, max_jobs_per_day=4, persist=False)
    assert [lim.check(JOBS, None) for _ in range(4)] == [None] * 4  # per-IP skipped
    refused = lim.check(JOBS, None)
    assert refused is not None and refused.body["error"] == "daily_cap"


# ------------------------------------------------------------------ where jobs live
def test_the_jobs_directory_follows_the_env_var(tmp_path, monkeypatch):
    """One variable moves jobs, cards, traces and the day counter together — the
    container sets it to /data, App Runner to /tmp/stepspotter, tests to a tmp dir."""
    elsewhere = tmp_path / "somewhere-else"
    monkeypatch.setenv("STEPSPOTTER_DATA", str(elsewhere))
    assert store.jobs_dir() == elsewhere / "jobs"

    client = _client()
    job = _post_job(client).json()["job_id"]
    assert (elsewhere / "jobs" / f"{job}.json").is_file()
    assert (elsewhere / "jobs" / f"{job}.trace.jsonl").is_file()
    assert list((elsewhere / "limits").glob("jobs-*.json")), "the day counter lands under the same root"


def test_a_refusal_is_written_to_a_trace(monkeypatch, isolated_data):
    """A judge complaining about a 429 has to be answerable from the box, not from memory."""
    monkeypatch.setenv("STEPSPOTTER_JOBS_PER_IP_HOUR", "1")
    client = _client()
    _post_job(client)
    assert _post_job(client).status_code == 429
    rows = store.read_trace("limits")
    events = [r["event"] for r in rows]
    # the first metered request records HOW the caller was identified — that row is how
    # we learn from the real deployment whether App Runner forwards anything at all
    assert events == ["configured", "client_source", "rate_limited"]
    # the build states its own caps where the refusals land, so "what is this image
    # enforcing?" is answerable from the live URL
    assert rows[0]["jobs_per_ip_hour"] == 1 and rows[0]["max_jobs_per_day"] == 150
    assert rows[1]["source"] == "x-forwarded-for" and rows[1]["identified"] is True
    assert rows[2]["ip"] == "203.0.113.7" and rows[2]["bucket"] == "jobs"


def test_a_broken_limit_value_falls_back_to_the_safe_default(monkeypatch):
    for bad in ("abc", "-5", "0", ""):
        monkeypatch.setenv("STEPSPOTTER_MAX_JOBS_PER_DAY", bad)
        assert Limiter(persist=False).max_jobs_per_day == 150
