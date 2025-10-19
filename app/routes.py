from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
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
    start_time = datetime.utcnow() - timedelta(hours=hours)

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
        return 100.0

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

    result = await db.execute(
        select(Incident)
        .where(
            and_(
                Incident.service_id == service_id,
                Incident.started_at >= start_time,
                Incident.status == "resolved",
                Incident.duration.isnot(None),
                Incident.duration < 60
            )
        )
    )
    short_incidents = result.scalars().all()

    short_outage_checks = 0
    for incident in short_incidents:
        if incident.ended_at:
            result = await db.execute(
                select(func.count(HealthCheck.id))
                .where(
                    and_(
                        HealthCheck.service_id == service_id,
                        HealthCheck.timestamp >= incident.started_at,
                        HealthCheck.timestamp <= incident.ended_at,
                        HealthCheck.status != "up"
                    )
                )
            )
            short_outage_checks += result.scalar_one()

    adjusted_up_checks = up_checks + short_outage_checks

    return (adjusted_up_checks / total_checks) * 100 if total_checks > 0 else 100.0

@router.get("/services", response_model=List[ServiceStatus])
async def get_services(domain: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Service))
    services = result.scalars().all()

    service_statuses = []
    for service in services:
        if domain and service.domains:
            service_domains = [d.strip() for d in service.domains.split(',')]
            if domain not in service_domains:
                continue

        latest_check_result = await db.execute(
            select(HealthCheck)
            .where(HealthCheck.service_id == service.id)
            .order_by(desc(HealthCheck.timestamp))
            .limit(1)
        )
        latest_check = latest_check_result.scalar_one_or_none()

        incident_result = await db.execute(
            select(Incident)
            .where(
                and_(
                    Incident.service_id == service.id,
                    Incident.status == "ongoing"
                )
            )
            .order_by(desc(Incident.started_at))
            .limit(1)
        )
        current_incident = incident_result.scalar_one_or_none()

        uptime_24h = await calculate_uptime(db, service.id, 24)
        uptime_7d = await calculate_uptime(db, service.id, 168)
        uptime_30d = await calculate_uptime(db, service.id, 720)

        service_status = ServiceStatus(
            id=service.id,
            name=service.name,
            status=latest_check.status if latest_check else "unknown",
            response_time=latest_check.response_time if latest_check else None,
            uptime_24h=uptime_24h,
            uptime_7d=uptime_7d,
            uptime_30d=uptime_30d,
            last_check=latest_check.timestamp if latest_check else None,
            current_incident={
                "id": current_incident.id,
                "started_at": current_incident.started_at.isoformat(),
                "description": current_incident.description
            } if current_incident else None,
            domains=service.domains
        )
        service_statuses.append(service_status)

    return service_statuses

@router.get("/services/{service_id}/history", response_model=List[HealthCheckResponse])
async def get_service_history(
    service_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.utcnow() - timedelta(hours=hours)

    result = await db.execute(
        select(HealthCheck)
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.timestamp >= start_time
            )
        )
        .order_by(desc(HealthCheck.timestamp))
    )
    checks = result.scalars().all()

    return checks

@router.get("/services/{service_id}/stats", response_model=UptimeStats)
async def get_service_stats(
    service_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.utcnow() - timedelta(hours=hours)

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
    limit: int = 50,
    ongoing_only: bool = False,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.utcnow() - timedelta(days=days)

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