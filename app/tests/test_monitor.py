import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
import httpx

from monitor import (
    check_http_service,
    perform_health_check,
    handle_incident,
    run_health_checks,
    cleanup_old_checks
)
from database import Service, HealthCheck, Incident

@pytest.mark.asyncio
async def test_check_http_service_success():
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        status, response_time, status_code, error = await check_http_service("https://example.com")

        assert status == "up"
        assert response_time > 0
        assert status_code == 200
        assert error is None

@pytest.mark.asyncio
async def test_check_http_service_404():
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        status, response_time, status_code, error = await check_http_service("https://example.com")

        assert status == "degraded"
        assert response_time > 0
        assert status_code == 404
        assert "HTTP 404" in error

@pytest.mark.asyncio
async def test_check_http_service_timeout():
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TimeoutException("Timeout")
        )

        status, response_time, status_code, error = await check_http_service("https://example.com")

        assert status == "down"
        assert response_time is None
        assert status_code is None
        assert error == "Connection timeout"

@pytest.mark.asyncio
async def test_check_http_service_connection_error():
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        status, response_time, status_code, error = await check_http_service("https://example.com")

        assert status == "down"
        assert response_time is None
        assert status_code is None
        assert "Connection error" in error

@pytest.mark.asyncio
async def test_check_http_service_redirect():
    mock_response = MagicMock()
    mock_response.status_code = 301

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        status, response_time, status_code, error = await check_http_service("https://example.com")

        assert status == "up"
        assert status_code == 301

@pytest.mark.asyncio
async def test_perform_health_check(test_service):
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        check = await perform_health_check(test_service)

        assert check.service_id == test_service.id
        assert check.status == "up"
        assert check.response_time > 0
        assert check.status_code == 200

@pytest.mark.asyncio
async def test_handle_incident_create_new(test_db, test_service):
    await handle_incident(test_db, test_service, "down")
    await test_db.commit()

    from sqlalchemy import select
    result = await test_db.execute(
        select(Incident).where(Incident.service_id == test_service.id)
    )
    incident = result.scalar_one()

    assert incident.status == "ongoing"
    assert incident.description == f"{test_service.name} is down"

@pytest.mark.asyncio
async def test_handle_incident_resolve_existing(test_db, test_service, test_incident):
    await handle_incident(test_db, test_service, "up")
    await test_db.commit()

    from sqlalchemy import select
    result = await test_db.execute(
        select(Incident).where(Incident.id == test_incident.id)
    )
    incident = result.scalar_one()

    assert incident.status == "resolved"
    assert incident.ended_at is not None
    assert incident.duration is not None

@pytest.mark.asyncio
async def test_handle_incident_already_down(test_db, test_service, test_incident):
    from sqlalchemy import select

    result_before = await test_db.execute(
        select(Incident).where(Incident.service_id == test_service.id)
    )
    count_before = len(result_before.scalars().all())

    await handle_incident(test_db, test_service, "down")
    await test_db.commit()

    result_after = await test_db.execute(
        select(Incident).where(Incident.service_id == test_service.id)
    )
    count_after = len(result_after.scalars().all())

    assert count_after == count_before

@pytest.mark.asyncio
async def test_run_health_checks_integration(test_db, test_service):
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        with patch('monitor.AsyncSessionLocal') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db

            await run_health_checks()

            from sqlalchemy import select
            result = await test_db.execute(
                select(HealthCheck).where(HealthCheck.service_id == test_service.id)
            )
            checks = result.scalars().all()

            assert len(checks) > 0

@pytest.mark.asyncio
async def test_cleanup_old_checks(test_db, test_service):
    old_check = HealthCheck(
        service_id=test_service.id,
        timestamp=datetime.utcnow() - timedelta(days=35),
        status="up",
        response_time=100.0,
        status_code=200
    )
    test_db.add(old_check)
    await test_db.commit()

    with patch('monitor.AsyncSessionLocal') as mock_session:
        mock_session.return_value.__aenter__.return_value = test_db

        await cleanup_old_checks(days=30)

        from sqlalchemy import select
        result = await test_db.execute(
            select(HealthCheck).where(HealthCheck.service_id == test_service.id)
        )
        checks = result.scalars().all()

        assert len(checks) == 0
