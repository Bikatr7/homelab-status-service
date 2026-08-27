from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, desc, case
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pydantic import BaseModel

from database import get_db, Service, HealthCheck, Incident

router = APIRouter()

class ServiceStatus(BaseModel):
    id: int
    name: str
    status: str
    response_time: Optional[float]
    uptime_24h: float
    uptime_7d: float
    uptime_30d: float
    last_check: Optional[datetime]
    current_incident: Optional[dict]
    domains: Optional[str]

    class Config:
        from_attributes = True

class HealthCheckResponse(BaseModel):
    id: int
    service_id: int
    timestamp: datetime
    status: str
    response_time: Optional[float]
    status_code: Optional[int]
    error_message: Optional[str]

    class Config:
        from_attributes = True

class IncidentResponse(BaseModel):
    id: int
    service_id: int
    service_name: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration: Optional[int]
    status: str
    description: Optional[str]

    class Config:
        from_attributes = True

class UptimeStats(BaseModel):
    period: str
    uptime_percentage: float
    total_checks: int
    successful_checks: int
    failed_checks: int
    average_response_time: Optional[float]

async def calculate_uptime(db: AsyncSession, service_id: int, hours: int) -> float:
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(func.count(HealthCheck.id))
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time
            )
        )
    )
    total_checks = result.scalar_one()

    if total_checks == 0:
        return 0.0

    result = await db.execute(
        select(func.count(HealthCheck.id))
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time,
                HealthCheck.status == "up"
            )
        )
    )
    up_checks = result.scalar_one()

    return (up_checks / total_checks) * 100 if total_checks > 0 else 100.0

@router.get("/services", response_model=List[ServiceStatus])
async def get_services(domain: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    services = (await db.execute(select(Service))).scalars().all()

    if domain:
        filtered = []
        for svc in services:
            if not svc.domains:
                continue
            service_domains = [d.strip() for d in svc.domains.split(',') if d.strip()]
            if domain in service_domains:
                filtered.append(svc)
        services = filtered

    if not services:
        return []

    service_ids = [s.id for s in services]

    latest_checks_sub = (
        select(
            HealthCheck.service_id,
            func.max(HealthCheck.timestamp).label("max_ts")
        )
        .where(HealthCheck.service_id.in_(service_ids))
        .group_by(HealthCheck.service_id)
        .subquery()
    )
    latest_checks_result = await db.execute(
        select(HealthCheck).join(
            latest_checks_sub,
            and_(
                HealthCheck.service_id == latest_checks_sub.c.service_id,
                HealthCheck.timestamp == latest_checks_sub.c.max_ts
            )
        )
    )
    latest_checks = {c.service_id: c for c in latest_checks_result.scalars().all()}

    ongoing_incidents_sub = (
        select(
            Incident.service_id,
            func.max(Incident.started_at).label("max_started")
        )
        .where(
            and_(
                Incident.status == "ongoing",
                Incident.service_id.in_(service_ids)
            )
        )
        .group_by(Incident.service_id)
        .subquery()
    )
    ongoing_incidents_result = await db.execute(
        select(Incident).join(
            ongoing_incidents_sub,
            and_(
                Incident.service_id == ongoing_incidents_sub.c.service_id,
                Incident.started_at == ongoing_incidents_sub.c.max_started
            )
        )
    )
    ongoing_incidents = {i.service_id: i for i in ongoing_incidents_result.scalars().all()}

    async def bulk_uptime(hours: int):
        window_start = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(
                HealthCheck.service_id,
                func.count(HealthCheck.id).label("total"),
                func.sum(case((HealthCheck.status == "up", 1), else_=0)).label("success"),
                func.avg(HealthCheck.response_time).label("avg_resp")
            )
            .where(
                and_(
                    HealthCheck.timestamp >= window_start,
                    HealthCheck.service_id.in_(service_ids)
                )
            )
            .group_by(HealthCheck.service_id)
        )
        rows = (await db.execute(stmt)).all()
        uptime_map = {}
        for service_id, total, success, avg_resp in rows:
            if total and success is not None:
                uptime_map[service_id] = (success / total) * 100
            else:
                uptime_map[service_id] = 0.0
        return uptime_map

    uptime_24 = await bulk_uptime(24)
    uptime_7d = await bulk_uptime(168)
    uptime_30d = await bulk_uptime(720)

    service_statuses = []
    for service in services:
        latest_check = latest_checks.get(service.id)
        current_incident = ongoing_incidents.get(service.id)

        service_statuses.append(
            ServiceStatus(
                id=service.id,
                name=service.name,
                status=latest_check.status if latest_check else "unknown",
                response_time=latest_check.response_time if latest_check else None,
                uptime_24h=uptime_24.get(service.id, 0.0),
                uptime_7d=uptime_7d.get(service.id, 0.0),
                uptime_30d=uptime_30d.get(service.id, 0.0),
                last_check=latest_check.timestamp if latest_check else None,
                current_incident={
                    "id": current_incident.id,
                    "started_at": current_incident.started_at.isoformat(),
                    "description": current_incident.description
                } if current_incident else None,
                domains=service.domains
            )
        )

    return service_statuses

@router.get("/services/{service_id}/history", response_model=List[HealthCheckResponse])
async def get_service_history(
    service_id: int,
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(HealthCheck)
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time
            )
        )
        .order_by(desc(HealthCheck.timestamp))
        .limit(2000)
    )
    checks = result.scalars().all()

    return checks

@router.get("/services/{service_id}/stats", response_model=UptimeStats)
async def get_service_stats(
    service_id: int,
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(func.count(HealthCheck.id))
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time
            )
        )
    )
    total_checks = result.scalar_one()

    result = await db.execute(
        select(func.count(HealthCheck.id))
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time,
                HealthCheck.status == "up"
            )
        )
    )
    successful_checks = result.scalar_one()

    result = await db.execute(
        select(func.avg(HealthCheck.response_time))
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time,
                HealthCheck.response_time.isnot(None)
            )
        )
    )
    avg_response_time = result.scalar_one()

    uptime_percentage = (successful_checks / total_checks * 100) if total_checks > 0 else 100.0

    return UptimeStats(
        period=f"{hours}h",
        uptime_percentage=uptime_percentage,
        total_checks=total_checks,
        successful_checks=successful_checks,
        failed_checks=total_checks - successful_checks,
        average_response_time=avg_response_time
    )

@router.get("/incidents", response_model=List[IncidentResponse])
async def get_incidents(
    limit: int = Query(default=50, ge=1, le=100),
    ongoing_only: bool = False,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.now(timezone.utc) - timedelta(days=days)

    query = select(Incident, Service.name).join(Service)

    if ongoing_only:
        query = query.where(Incident.status == "ongoing")

    query = query.where(Incident.started_at >= start_time)

    query = query.order_by(desc(Incident.started_at)).limit(limit)

    result = await db.execute(query)
    incidents_with_names = result.all()

    return [
        IncidentResponse(
            id=incident.id,
            service_id=incident.service_id,
            service_name=service_name,
            started_at=incident.started_at,
            ended_at=incident.ended_at,
            duration=incident.duration,
            status=incident.status,
            description=incident.description
        )
        for incident, service_name in incidents_with_names
    ]
