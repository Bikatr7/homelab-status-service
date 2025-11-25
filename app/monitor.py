import httpx
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from config import settings
from database import Service, HealthCheck, Incident, AsyncSessionLocal
import logging

logger = logging.getLogger(__name__)

async def check_http_service(url: str, timeout: int = 10) -> tuple[str, float, int, str]:
    try:
        start_time = time.time()
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=timeout)
            response_time = (time.time() - start_time) * 1000

            if response.status_code < 400:
                return "up", response_time, response.status_code, None

            return "down", response_time, response.status_code, f"HTTP {response.status_code}"
    except httpx.TimeoutException:
        return "down", None, None, "Connection timeout"
    except httpx.ConnectError as e:
        return "down", None, None, f"Connection error: {str(e)}"
    except Exception as e:
        return "down", None, None, f"Error: {str(e)}"

async def perform_health_check(service: Service) -> HealthCheck:
    if service.check_type == "http":
        status, response_time, status_code, error = await check_http_service(
            service.url,
            settings.TIMEOUT
        )
    else:
        status, response_time, status_code, error = await check_http_service(
            service.url,
            settings.TIMEOUT
        )

    check = HealthCheck(
        service_id=service.id,
        timestamp=datetime.now(timezone.utc),
        status=status,
        response_time=response_time,
        status_code=status_code,
        error_message=error
    )

    return check

async def handle_incident(db: AsyncSession, service: Service, current_status: str):
    def ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    result = await db.execute(
        select(Incident)
        .where(Incident.service_id == service.id)
        .order_by(desc(Incident.started_at))
        .limit(1)
    )
    latest_incident = result.scalar_one_or_none()

    if current_status == "down":
        if not latest_incident or latest_incident.status == "resolved":
            new_incident = Incident(
                service_id=service.id,
                started_at=datetime.now(timezone.utc),
                status="ongoing",
                description=f"{service.name} is down"
            )
            db.add(new_incident)
            logger.warning(f"New incident created for {service.name}")
    else:
        if latest_incident and latest_incident.status == "ongoing":
            latest_incident.ended_at = datetime.now(timezone.utc)
            duration = int(
                (ensure_utc(latest_incident.ended_at) - ensure_utc(latest_incident.started_at)).total_seconds()
            )
            latest_incident.duration = duration
            latest_incident.status = "resolved"

            logger.info(f"Incident resolved for {service.name} (duration: {duration}s)")

async def run_health_checks():
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Service).where(Service.enabled == True)
            )
            services = result.scalars().all()

            for service in services:
                check = await perform_health_check(service)
                db.add(check)
                await handle_incident(db, service, check.status)

                logger.info(f"Health check for {service.name}: {check.status} ({check.response_time}ms)")

            await db.commit()
        except Exception as e:
            logger.error(f"Error during health checks: {str(e)}")
            await db.rollback()

async def cleanup_old_checks(days: int = 30):
    async with AsyncSessionLocal() as db:
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            deleted = await db.execute(
                HealthCheck.__table__.delete().where(HealthCheck.timestamp < cutoff_date)
            )
            await db.commit()
            logger.info(f"Cleaned up {deleted.rowcount or 0} old health checks")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            await db.rollback()
