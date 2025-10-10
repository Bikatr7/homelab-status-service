import pytest
from datetime import datetime
from sqlalchemy import select

from database import Service, HealthCheck, Incident

@pytest.mark.asyncio
async def test_create_service(test_db):
    service = Service(
        name="New Service",
        url="https://test.com",
        check_type="http",
        expected_status="200",
        enabled=True
    )
    test_db.add(service)
    await test_db.commit()

    result = await test_db.execute(
        select(Service).where(Service.name == "New Service")
    )
    fetched = result.scalar_one()

    assert fetched.name == "New Service"
    assert fetched.url == "https://test.com"
    assert fetched.check_type == "http"
    assert fetched.enabled is True

@pytest.mark.asyncio
async def test_service_relationships(test_db, test_service, test_health_check):
    from sqlalchemy.orm import selectinload

    result = await test_db.execute(
        select(Service)
        .where(Service.id == test_service.id)
        .options(selectinload(Service.checks))
    )
    service = result.scalar_one()

    assert len(service.checks) == 1
    assert service.checks[0].status == "up"

@pytest.mark.asyncio
async def test_create_health_check(test_db, test_service):
    check = HealthCheck(
        service_id=test_service.id,
        timestamp=datetime.utcnow(),
        status="up",
        response_time=200.0,
        status_code=200,
        error_message=None
    )
    test_db.add(check)
    await test_db.commit()

    result = await test_db.execute(
        select(HealthCheck).where(HealthCheck.service_id == test_service.id)
    )
    fetched = result.scalar_one()

    assert fetched.status == "up"
    assert fetched.response_time == 200.0
    assert fetched.status_code == 200

@pytest.mark.asyncio
async def test_create_incident(test_db, test_service):
    incident = Incident(
        service_id=test_service.id,
        started_at=datetime.utcnow(),
        status="ongoing",
        description="Service is down"
    )
    test_db.add(incident)
    await test_db.commit()

    result = await test_db.execute(
        select(Incident).where(Incident.service_id == test_service.id)
    )
    fetched = result.scalar_one()

    assert fetched.status == "ongoing"
    assert fetched.description == "Service is down"
    assert fetched.ended_at is None

@pytest.mark.asyncio
async def test_resolve_incident(test_db, test_incident):
    test_incident.ended_at = datetime.utcnow()
    test_incident.duration = 300
    test_incident.status = "resolved"
    await test_db.commit()

    result = await test_db.execute(
        select(Incident).where(Incident.id == test_incident.id)
    )
    fetched = result.scalar_one()

    assert fetched.status == "resolved"
    assert fetched.duration == 300
    assert fetched.ended_at is not None

@pytest.mark.asyncio
async def test_cascade_delete_service(test_db, test_service, test_health_check, test_incident):
    service_id = test_service.id

    await test_db.delete(test_service)
    await test_db.commit()

    result = await test_db.execute(
        select(HealthCheck).where(HealthCheck.service_id == service_id)
    )
    assert result.scalar_one_or_none() is None

    result = await test_db.execute(
        select(Incident).where(Incident.service_id == service_id)
    )
    assert result.scalar_one_or_none() is None
