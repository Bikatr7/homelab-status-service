from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from database import HealthCheck, Incident, Service, get_db
from overview import build_payload, collect, counted_segments, group_events, segments, timeline
from routes import router

NOW = datetime(2026, 9, 24, 18, tzinfo=timezone.utc)


def test_elapsed_time_not_sample_count():
    start = NOW - timedelta(hours=24)
    # A 10-hour outage sampled half as frequently as the healthy period.
    checks = [(start + timedelta(minutes=i), "down" if i < 600 else "up")
              for i in range(1440) if i >= 600 or i % 2 == 0]
    parts = segments(checks, start, NOW)
    totals = {state: sum((b-a).total_seconds() for a,b,s in parts if s == state)
              for state in ("up", "down", "unknown")}
    assert totals == {"up": 14*3600, "down": 10*3600, "unknown": 0}
    buckets = timeline(parts, start, NOW)
    assert sum(b["down_seconds"] for b in buckets) == 36000


def test_gap_is_not_invented_uptime_or_downtime():
    start = NOW - timedelta(hours=1)
    parts = segments([(start, "up"), (NOW - timedelta(minutes=1), "down")], start, NOW)
    assert [(int((b-a).total_seconds()), s) for a,b,s in parts] == [
        (180, "up"), (3360, "unknown"), (60, "down")]


def test_boundary_sample_and_naive_sqlite_utc():
    start = NOW - timedelta(minutes=1)
    checks = [((start - timedelta(seconds=10)).replace(tzinfo=None), "up")]
    assert segments(checks, start, NOW) == [(start, NOW, "up")]
    assert segments([], start, NOW) == [(start, NOW, "unknown")]
    assert segments([(start - timedelta(hours=1), "down")], start, NOW) == [(start, NOW, "unknown")]


def test_brief_outage_visible_in_bucket():
    start = NOW - timedelta(hours=24)
    parts = [(start, start + timedelta(seconds=1), "down"),
             (start + timedelta(seconds=1), NOW, "up")]
    bucket = timeline(parts, start, NOW)[0]
    assert bucket["status"] == "down"
    assert bucket["down_seconds"] == 1


@pytest.mark.parametrize("check_time", [None, NOW - timedelta(seconds=180), NOW + timedelta(seconds=1)])
def test_empty_stale_and_future_checks_are_unknown(check_time):
    service = SimpleNamespace(id=1, name="Public site", url="https://example.com")
    latest = {1: SimpleNamespace(timestamp=check_time, status="up", response_time=1)} if check_time else {}
    payload = build_payload([service], [], latest, [], NOW-timedelta(hours=24), NOW)
    assert payload["services"][0]["status"] == "unknown"
    assert payload["services"][0]["uptime"] is None
    assert payload["services"][0]["coverage"] == 0
    assert payload["generated_at"].endswith("Z")
    assert payload["events"][0]["kind"] == "gap"


def test_group_only_near_simultaneous_overlapping_different_services():
    def event(sid, offset, length):
        start = NOW + timedelta(seconds=offset)
        end = start + timedelta(seconds=length)
        return dict(kind="outage", service_id=sid, started_at=start, ended_at=end, through=end)
    groups = group_events([event(1, 0, 36000), event(2, 30, 36000),
                           event(3, 3600, 10), event(1, 40, 10)])
    assert len(groups) == 3
    correlated = next(group for group in groups if len(group["items"]) == 2)
    assert correlated["duration_seconds"] == 36030
    assert correlated["started_at"].endswith("Z")


@pytest.mark.asyncio
async def test_domain_filter_and_incident_overlapping_window(test_db):
    visible = Service(name="Visible", url="https://public.example", domains="example.com", enabled=True)
    hidden = Service(name="Other public site", url="https://other.example", domains="other.example", enabled=True)
    disabled = Service(name="Disabled", url="https://disabled.example", domains="example.com", enabled=False)
    for service in (visible, hidden, disabled):
        service.check_type = "http"
        service.expected_status = "200"
    test_db.add_all([visible, hidden, disabled]); await test_db.commit()
    now = datetime.now(timezone.utc)
    for service in (visible, hidden, disabled):
        test_db.add(HealthCheck(service_id=service.id, timestamp=now, status="up"))
        test_db.add(Incident(service_id=service.id, started_at=now-timedelta(days=2),
                             ended_at=now-timedelta(hours=1), status="resolved"))
    await test_db.commit()
    result = await collect(test_db, "example.com", 24)
    assert [s["name"] for s in result["services"]] == ["Visible"]
    outages = [e for e in result["events"] if e["kind"] == "outage"]
    assert len(outages) == 1
    assert outages[0]["items"][0]["service_name"] == "Visible"
    assert outages[0]["started_at"] < result["window_start"]
    assert all(s["last_check"].endswith("Z") for s in result["services"])
    assert (await collect(test_db, "unrelated.example", 24))["services"] == []


@pytest.mark.asyncio
async def test_history_not_cut_off_after_fifty_records(test_db, test_service):
    now = datetime.now(timezone.utc)
    for minute in range(70):
        start = now - timedelta(minutes=2*minute+2)
        test_db.add(Incident(service_id=test_service.id, started_at=start,
                            ended_at=start+timedelta(seconds=61), status="resolved"))
    await test_db.commit()
    result = await collect(test_db, None, 24)
    assert len([e for e in result["events"] if e["kind"] == "outage"]) == 70


@pytest.mark.parametrize("seconds,expected", [(10, 0), (59, 0), (60, 0), (61, 61), (120, 120)])
def test_minute_threshold_applies_to_uptime_timeline_and_events(seconds, expected):
    start = NOW - timedelta(minutes=5)
    begin = start + timedelta(minutes=1)
    finish = begin + timedelta(seconds=seconds)
    service = SimpleNamespace(id=1, name="Public site", url="https://example.com")
    incident = SimpleNamespace(service_id=1, started_at=begin, ended_at=finish)
    rows = [(1, start, "up"), (1, begin, "down"), (1, finish, "up"), (1, NOW-timedelta(seconds=1), "up")]
    latest = {1: SimpleNamespace(timestamp=NOW-timedelta(seconds=1), status="up", response_time=1)}
    payload = build_payload([service], rows, latest, [incident], start, NOW)
    result = payload["services"][0]
    assert result["down_seconds"] == expected
    assert sum(b["down_seconds"] for b in result["timeline"]) == pytest.approx(expected, abs=.5)
    assert len([e for e in payload["events"] if e["kind"] == "outage"]) == (1 if expected else 0)


def test_long_outage_tail_is_not_ignored_at_window_boundary():
    start = NOW - timedelta(minutes=5)
    incident = SimpleNamespace(started_at=start-timedelta(hours=1), ended_at=start+timedelta(seconds=20))
    parts = counted_segments([(start-timedelta(seconds=5), "down"), (incident.ended_at, "up")], start, NOW, [incident])
    assert parts[0] == (start, start+timedelta(seconds=20), "down")


def test_fresh_short_failure_is_checking_not_confirmed_down():
    start = NOW-timedelta(minutes=1)
    service = SimpleNamespace(id=1, name="Public", url="https://example.com")
    incident = SimpleNamespace(service_id=1, started_at=NOW-timedelta(seconds=20), ended_at=None)
    rows = [(1, start, "up"), (1, incident.started_at, "down")]
    latest = {1: SimpleNamespace(timestamp=incident.started_at, status="down", response_time=None)}
    payload = build_payload([service], rows, latest, [incident], start, NOW)
    assert payload["services"][0]["status"] == "checking"
    assert payload["services"][0]["down_seconds"] == 0
    assert not payload["events"]


@pytest.mark.asyncio
async def test_full_archive_includes_old_incidents_and_can_filter_window(test_db, test_service):
    now = datetime.now(timezone.utc)
    for days in (1, 200):
        start = now-timedelta(days=days)
        test_db.add(Incident(service_id=test_service.id, started_at=start,
                            ended_at=start+timedelta(minutes=10), status="resolved"))
    await test_db.commit()
    all_history = await collect(test_db, None, 24, "all")
    window = await collect(test_db, None, 24, "window")
    assert len([e for e in all_history["events"] if e["kind"] == "outage"]) == 2
    assert len([e for e in window["events"] if e["kind"] == "outage"]) == 1
    assert all_history["history_started_at"] < all_history["window_start"]


@pytest.mark.asyncio
async def test_overview_query_validation_and_timezone(test_db):
    app = FastAPI(); app.include_router(router, prefix="/api")
    async def override():
        yield test_db
    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for hours in (24, 168, 720):
            response = await client.get(f"/api/overview?hours={hours}")
            assert response.status_code == 200
            assert response.json()["window_start"].endswith("Z")
        for hours in (0, 25, 721, "invalid"):
            assert (await client.get(f"/api/overview?hours={hours}")).status_code == 422


def test_public_assets_have_no_internal_identity():
    from pathlib import Path
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    files = [frontend / "index.html", frontend / "preview.html", *list((frontend / "assets").glob("*"))]
    # These must never be shipped in public assets, including comments/source.
    import os
    forbidden = ("192.168.", "wi-fi", "same network", *filter(None, os.getenv("STATUS_PRIVATE_TERMS", "").lower().split(",")))
    for path in files:
        if path.exists():
            content = path.read_text().lower()
            assert not any(value in content for value in forbidden), path.name
