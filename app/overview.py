"""Time-based status reporting. Missing checks are unknown, never healthy."""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from time import monotonic
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import HealthCheck, Incident, Service, get_db

router = APIRouter()
STALE_SECONDS = max(180, settings.CHECK_INTERVAL * 3)
MIN_OUTAGE_SECONDS = 60


def utc(value):
    # SQLite strips timezone information; all stored timestamps are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value):
    return utc(value).isoformat().replace("+00:00", "Z") if value else None


def segments(checks, start, end, stale_seconds=STALE_SECONDS):
    """Hold a sample only until the next check or its freshness deadline."""
    result = []

    def append(left, right, state):
        left, right = max(left, start), min(right, end)
        if right <= left:
            return
        if result and result[-1][2] == state and result[-1][1] == left:
            result[-1] = (result[-1][0], right, state)
        else:
            result.append((left, right, state))

    cursor = start
    for i, (timestamp, state) in enumerate(checks):
        timestamp = utc(timestamp)
        next_time = utc(checks[i + 1][0]) if i + 1 < len(checks) else end
        stop = min(timestamp + timedelta(seconds=stale_seconds), next_time, end)
        if timestamp > cursor:
            append(cursor, timestamp, "unknown")
        append(timestamp, stop, state if state in ("up", "down") else "unknown")
        cursor = max(cursor, stop)
    append(cursor, end, "unknown")
    return result


def timeline(parts, start, end, count=96):
    width = (end - start) / count
    buckets = []
    cursor = 0
    for i in range(count):
        left, right = start + width * i, start + width * (i + 1)
        totals = {"up": 0.0, "down": 0.0, "unknown": 0.0}
        while cursor < len(parts) and parts[cursor][1] <= left:
            cursor += 1
        j = cursor
        while j < len(parts) and parts[j][0] < right:
            a, b, state = parts[j]
            totals[state] += max(0, (min(b, right) - max(a, left)).total_seconds())
            j += 1
        state = "down" if totals["down"] else "unknown" if totals["unknown"] else "up"
        buckets.append({"status": state, "down_seconds": round(totals["down"], 2),
                        "unknown_seconds": round(totals["unknown"], 2)})
    return buckets


def counted_segments(checks, start, end, incidents):
    """Ignore short failures without clipping a longer outage at the window edge."""
    context_start = min(start, utc(checks[0][0])) if checks else start
    raw = segments(checks, context_start, end)
    result = []
    for left, right, state in raw:
        if state == "down":
            matching = [incident for incident in incidents
                        if utc(incident.started_at) < right
                        and (utc(incident.ended_at) if incident.ended_at else end) > left]
            if matching:
                qualifies = any(((utc(i.ended_at) if i.ended_at else end) - utc(i.started_at)).total_seconds()
                                > MIN_OUTAGE_SECONDS for i in matching)
            else:
                qualifies = (right - left).total_seconds() > MIN_OUTAGE_SECONDS
            if not qualifies:
                state = "up"
        left, right = max(left, start), min(right, end)
        if left >= right:
            continue
        if result and result[-1][2] == state and result[-1][1] == left:
            result[-1] = (result[-1][0], right, state)
        else:
            result.append((left, right, state))
    return result


def group_events(events):
    """Group near-simultaneous, overlapping records, without asserting a cause."""
    groups = []
    for event in sorted(events, key=lambda e: e["started_at"]):
        match = next((group for group in reversed(groups)
                      if group["kind"] == event["kind"]
                      and (event["started_at"] - group["started_at"]).total_seconds() <= 180
                      and event["started_at"] <= group["through"]
                      and event["service_id"] not in {item["service_id"] for item in group["items"]}), None)
        if match:
            match["items"].append(event)
            match["through"] = max(match["through"], event["through"])
        else:
            groups.append({"kind": event["kind"], "started_at": event["started_at"],
                           "through": event["through"], "items": [event]})
    for group in groups:
        group["ended_at"] = None if any(e["ended_at"] is None for e in group["items"]) else group["through"]
        group["duration_seconds"] = (group["through"] - group["started_at"]).total_seconds()
        for obj in [group, *group["items"]]:
            obj.pop("through", None)
            for key in ("started_at", "ended_at"):
                obj[key] = iso(obj[key])
    return sorted(groups, key=lambda e: (e["ended_at"] is None, e["started_at"]), reverse=True)


def build_payload(services, rows, latest, incidents, start, now, history="all", checks_started_at=None):
    by_service = defaultdict(list)
    for service_id, timestamp, status in rows:
        by_service[service_id].append((timestamp, status))
    incidents_by_service = defaultdict(list)
    for incident in incidents:
        incidents_by_service[incident.service_id].append(incident)
    output, events, parts_by_id = [], [], {}
    for service in services:
        parts = counted_segments(by_service[service.id], start, now, incidents_by_service[service.id])
        parts_by_id[service.id] = parts
        totals = {state: sum((b - a).total_seconds() for a, b, s in parts if s == state)
                  for state in ("up", "down", "unknown")}
        check = latest.get(service.id)
        fresh = check is not None and 0 <= (now - utc(check.timestamp)).total_seconds() < STALE_SECONDS
        observed = totals["up"] + totals["down"]
        current_status = check.status if fresh and check.status in ("up", "down") else "unknown"
        if current_status == "down" and (not parts or parts[-1][2] != "down"):
            current_status = "checking"
        output.append({"id": service.id, "name": service.name,
                       "hostname": urlsplit(service.url).hostname,
                       "status": current_status,
                       "last_check": iso(check.timestamp) if check else None,
                       "response_time": check.response_time if fresh else None,
                       "uptime": totals["up"] / observed * 100 if observed else None,
                       "coverage": observed / (now - start).total_seconds() * 100,
                       "down_seconds": round(totals["down"], 2),
                       "unknown_seconds": round(totals["unknown"], 2),
                       "timeline": timeline(parts, start, now)})
        for a, b, state in parts:
            if state == "unknown" and (b - a).total_seconds() >= STALE_SECONDS:
                events.append({"kind": "gap", "service_id": service.id, "service_name": service.name,
                               "started_at": a, "ended_at": b if b < now else None, "through": b,
                               "duration_seconds": (b - a).total_seconds(), "unobserved_seconds": (b - a).total_seconds()})
    names = {s.id: s.name for s in services}
    for incident in incidents:
        begin = utc(incident.started_at)
        finish = utc(incident.ended_at) if incident.ended_at else now
        if (finish - begin).total_seconds() <= MIN_OUTAGE_SECONDS:
            continue
        if history == "window" and finish < start:
            continue
        missing = sum(max(0, (min(b, finish) - max(a, begin)).total_seconds())
                      for a, b, state in parts_by_id[incident.service_id] if state == "unknown")
        events.append({"kind": "outage", "service_id": incident.service_id,
                       "service_name": names[incident.service_id], "started_at": begin,
                       "ended_at": utc(incident.ended_at) if incident.ended_at else None,
                       "through": finish, "duration_seconds": max(0, (finish - begin).total_seconds()),
                       "unobserved_seconds": missing})
    return {"generated_at": iso(now), "window_start": iso(start), "window_end": iso(now),
            "stale_after_seconds": STALE_SECONDS, "check_interval_seconds": settings.CHECK_INTERVAL,
            "minimum_outage_seconds": MIN_OUTAGE_SECONDS,
            "history_scope": history,
            "history_started_at": iso(min((utc(i.started_at) for i in incidents), default=None)),
            "checks_started_at": iso(checks_started_at),
            "services": output, "events": group_events(events)}


async def collect(db, domain, hours, history="all"):
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    services = list((await db.execute(select(Service).where(Service.enabled.is_(True))
                                     .order_by(Service.id))).scalars())
    if domain:
        services = [s for s in services if domain in [d.strip() for d in (s.domains or "").split(",")]]
    ids = [s.id for s in services]
    if not ids:
        return build_payload([], [], {}, [], start, now, history)
    checks_started_at = (await db.execute(select(func.min(HealthCheck.timestamp)).where(
        HealthCheck.service_id.in_(ids)))).scalar_one()
    latest_sub = select(HealthCheck.service_id, func.max(HealthCheck.timestamp).label("ts")).where(
        HealthCheck.service_id.in_(ids)).group_by(HealthCheck.service_id).subquery()
    latest = {c.service_id: c for c in (await db.execute(select(HealthCheck).join(latest_sub, and_(
        HealthCheck.service_id == latest_sub.c.service_id, HealthCheck.timestamp == latest_sub.c.ts)))).scalars()}
    rows = (await db.execute(select(HealthCheck.service_id, HealthCheck.timestamp, HealthCheck.status).where(
        HealthCheck.service_id.in_(ids), HealthCheck.timestamp >= start - timedelta(seconds=STALE_SECONDS),
        HealthCheck.timestamp <= now).order_by(HealthCheck.service_id, HealthCheck.timestamp))).all()
    incidents_result = await db.execute(select(Incident).where(
        Incident.service_id.in_(ids), Incident.started_at <= now))
    incidents = list(incidents_result.scalars())
    return await asyncio.to_thread(build_payload, services, rows, latest, incidents, start, now, history, checks_started_at)


@router.get("/overview")
async def overview(request: Request, hours: int = Query(default=24, ge=24, le=720),
                   history: Literal["all", "window"] = "all",
                   domain: str | None = Query(default=None, max_length=253), db: AsyncSession = Depends(get_db)):
    if hours not in (24, 168, 720):
        raise HTTPException(status_code=422, detail="Choose a 24-hour, 7-day, or 30-day window.")
    # Bounded, per-app cache avoids repeatedly scanning 30 days for simultaneous visitors.
    if not hasattr(request.app.state, "overview_cache"):
        request.app.state.overview_cache = {}
        request.app.state.overview_lock = asyncio.Lock()
    key = (domain, hours, history)
    async with request.app.state.overview_lock:
        cache = request.app.state.overview_cache
        cached = cache.get(key)
        if cached and monotonic() - cached[0] < 20:
            return cached[1]
        result = await collect(db, domain, hours, history)
        if len(cache) >= 16:
            cache.pop(next(iter(cache)))
        cache[key] = (monotonic(), result)
        return result
