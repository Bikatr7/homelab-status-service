import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from sqlalchemy import select

from database import Service, HealthCheck, Incident
from monitor import run_health_checks

@pytest.mark.asyncio
async def test_full_monitoring_cycle_service_up(test_db, test_service):
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        with patch('monitor.AsyncSessionLocal') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db

            await run_health_checks()

            result = await test_db.execute(
                select(HealthCheck).where(HealthCheck.service_id == test_service.id)
            )
            checks = result.scalars().all()

            assert len(checks) > 0
            assert checks[-1].status == "up"
            assert checks[-1].status_code == 200

            result = await test_db.execute(
                select(Incident).where(Incident.service_id == test_service.id)
            )
            incidents = result.scalars().all()
            assert len(incidents) == 0

@pytest.mark.asyncio
async def test_full_monitoring_cycle_service_down(test_db, test_service):
    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("Connection failed")
        )
        with patch('monitor.AsyncSessionLocal') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db

            await run_health_checks()

            result = await test_db.execute(
                select(HealthCheck).where(HealthCheck.service_id == test_service.id)
            )
            checks = result.scalars().all()

            assert len(checks) > 0
            assert checks[-1].status == "down"

            result = await test_db.execute(
                select(Incident).where(Incident.service_id == test_service.id)
            )
            incidents = result.scalars().all()
            assert len(incidents) > 0
            assert incidents[-1].status == "ongoing"

@pytest.mark.asyncio
async def test_service_recovery_flow(test_db, test_service):
    with patch('monitor.AsyncSessionLocal') as mock_session:
        mock_session.return_value.__aenter__.return_value = test_db

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection failed")
            )
            await run_health_checks()

        result = await test_db.execute(
            select(Incident).where(Incident.service_id == test_service.id)
        )
        incidents = result.scalars().all()
        assert len(incidents) > 0
        assert incidents[-1].status == "ongoing"

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            await run_health_checks()

        await test_db.refresh(incidents[-1])
        assert incidents[-1].status == "resolved"
        assert incidents[-1].ended_at is not None
        assert incidents[-1].duration is not None

@pytest.mark.asyncio
async def test_multiple_services_monitoring(test_db):
    services = []
    for i in range(3):
        service = Service(
            name=f"Service {i}",
            url=f"https://service{i}.example.com",
            check_type="http",
            expected_status="200",
            enabled=True
        )
        test_db.add(service)
        services.append(service)
    await test_db.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        with patch('monitor.AsyncSessionLocal') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db

            await run_health_checks()

            result = await test_db.execute(select(HealthCheck))
            checks = result.scalars().all()

            assert len(checks) >= 3

@pytest.mark.asyncio
async def test_disabled_service_not_monitored(test_db):
    disabled_service = Service(
        name="Disabled Service",
        url="https://disabled.example.com",
        check_type="http",
        expected_status="200",
        enabled=False
    )
    test_db.add(disabled_service)
    await test_db.commit()

    with patch('monitor.AsyncSessionLocal') as mock_session:
        mock_session.return_value.__aenter__.return_value = test_db

        await run_health_checks()

        result = await test_db.execute(
            select(HealthCheck).where(HealthCheck.service_id == disabled_service.id)
        )
        checks = result.scalars().all()

        assert len(checks) == 0

@pytest.mark.asyncio
async def test_degraded_service_status(test_db, test_service):
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        with patch('monitor.AsyncSessionLocal') as mock_session:
            mock_session.return_value.__aenter__.return_value = test_db

            await run_health_checks()

            result = await test_db.execute(
                select(HealthCheck).where(HealthCheck.service_id == test_service.id)
            )
            checks = result.scalars().all()

            assert len(checks) > 0
            assert checks[-1].status == "degraded"
            assert checks[-1].status_code == 500
