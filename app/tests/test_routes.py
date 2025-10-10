import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from routes import calculate_uptime, router
from database import Service, HealthCheck, Incident

@pytest.mark.asyncio
async def test_calculate_uptime_all_up(test_db, test_service):
    for i in range(10):
        check = HealthCheck(
            service_id=test_service.id,
            timestamp=datetime.utcnow() - timedelta(hours=i),
            status="up",
            response_time=100.0,
            status_code=200
        )
        test_db.add(check)
    await test_db.commit()

    uptime = await calculate_uptime(test_db, test_service.id, 24)
    assert uptime == 100.0

@pytest.mark.asyncio
async def test_calculate_uptime_partial(test_db, test_service):
    for i in range(10):
        status = "up" if i % 2 == 0 else "down"
        check = HealthCheck(
            service_id=test_service.id,
            timestamp=datetime.utcnow() - timedelta(hours=i),
            status=status,
            response_time=100.0 if status == "up" else None,
            status_code=200 if status == "up" else None
        )
        test_db.add(check)
    await test_db.commit()

    uptime = await calculate_uptime(test_db, test_service.id, 24)
    assert 40.0 <= uptime <= 60.0

@pytest.mark.asyncio
async def test_calculate_uptime_no_data(test_db, test_service):
    uptime = await calculate_uptime(test_db, test_service.id, 24)
    assert uptime == 100.0

@pytest.mark.asyncio
async def test_get_services_endpoint(test_db, test_service, test_health_check):
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from routes import router as api_router
    from config import settings
    from database import get_db as original_get_db

    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_PREFIX)

    async def override_get_db():
        yield test_db

    test_app.dependency_overrides[original_get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/api/services")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        assert data[0]["name"] == test_service.name

@pytest.mark.asyncio
async def test_get_service_history(test_db, test_service):
    for i in range(5):
        check = HealthCheck(
            service_id=test_service.id,
            timestamp=datetime.utcnow() - timedelta(hours=i),
            status="up",
            response_time=100.0,
            status_code=200
        )
        test_db.add(check)
    await test_db.commit()

    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from routes import router as api_router
    from config import settings
    from database import get_db as original_get_db

    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_PREFIX)

    async def override_get_db():
        yield test_db

    test_app.dependency_overrides[original_get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get(f"/api/services/{test_service.id}/history?hours=24")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 5

@pytest.mark.asyncio
async def test_get_service_stats(test_db, test_service):
    for i in range(10):
        status = "up" if i < 8 else "down"
        check = HealthCheck(
            service_id=test_service.id,
            timestamp=datetime.utcnow() - timedelta(hours=i),
            status=status,
            response_time=100.0 if status == "up" else None,
            status_code=200 if status == "up" else None
        )
        test_db.add(check)
    await test_db.commit()

    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from routes import router as api_router
    from config import settings
    from database import get_db as original_get_db

    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_PREFIX)

    async def override_get_db():
        yield test_db

    test_app.dependency_overrides[original_get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get(f"/api/services/{test_service.id}/stats?hours=24")
        assert response.status_code == 200

        data = response.json()
        assert data["total_checks"] == 10
        assert data["successful_checks"] == 8
        assert data["failed_checks"] == 2
        assert data["uptime_percentage"] == 80.0

@pytest.mark.asyncio
async def test_get_incidents(test_db, test_service, test_incident):
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from routes import router as api_router
    from config import settings
    from database import get_db as original_get_db

    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_PREFIX)

    async def override_get_db():
        yield test_db

    test_app.dependency_overrides[original_get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/api/incidents")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        assert data[0]["service_name"] == test_service.name
        assert data[0]["status"] == "ongoing"

@pytest.mark.asyncio
async def test_get_incidents_ongoing_only(test_db, test_service):
    incident1 = Incident(
        service_id=test_service.id,
        started_at=datetime.utcnow() - timedelta(hours=2),
        ended_at=datetime.utcnow() - timedelta(hours=1),
        duration=3600,
        status="resolved",
        description="Resolved incident"
    )
    incident2 = Incident(
        service_id=test_service.id,
        started_at=datetime.utcnow(),
        status="ongoing",
        description="Ongoing incident"
    )
    test_db.add(incident1)
    test_db.add(incident2)
    await test_db.commit()

    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from routes import router as api_router
    from config import settings
    from database import get_db as original_get_db

    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_PREFIX)

    async def override_get_db():
        yield test_db

    test_app.dependency_overrides[original_get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/api/incidents?ongoing_only=true")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "ongoing"
