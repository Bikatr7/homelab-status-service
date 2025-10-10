import pytest
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from datetime import datetime

from database import Base, Service, HealthCheck, Incident

TEST_DB_PATH = Path(__file__).parent / "test_status.db"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def test_engine():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{TEST_DB_PATH}",
        echo=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()

    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

@pytest.fixture
async def test_db(test_engine):
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with async_session() as session:
        yield session
        await session.rollback()

@pytest.fixture
async def test_service(test_db):
    service = Service(
        name="Test Service",
        url="https://example.com",
        check_type="http",
        expected_status="200",
        enabled=True
    )
    test_db.add(service)
    await test_db.commit()
    await test_db.refresh(service)
    return service

@pytest.fixture
async def test_service_down(test_db):
    service = Service(
        name="Down Service",
        url="https://down.example.com",
        check_type="http",
        expected_status="200",
        enabled=True
    )
    test_db.add(service)
    await test_db.commit()
    await test_db.refresh(service)
    return service

@pytest.fixture
async def test_health_check(test_db, test_service):
    check = HealthCheck(
        service_id=test_service.id,
        timestamp=datetime.utcnow(),
        status="up",
        response_time=150.5,
        status_code=200,
        error_message=None
    )
    test_db.add(check)
    await test_db.commit()
    await test_db.refresh(check)
    return check

@pytest.fixture
async def test_incident(test_db, test_service):
    incident = Incident(
        service_id=test_service.id,
        started_at=datetime.utcnow(),
        ended_at=None,
        duration=None,
        status="ongoing",
        description="Test incident"
    )
    test_db.add(incident)
    await test_db.commit()
    await test_db.refresh(incident)
    return incident
