import pytest
from config import Settings

def test_default_config():
    settings = Settings()

    assert settings.DATABASE_URL == "sqlite+aiosqlite:///./status.db"
    assert settings.API_PREFIX == "/api"
    assert settings.CHECK_INTERVAL == 60
    assert settings.TIMEOUT == 10

def test_services_configured():
    settings = Settings()

    assert len(settings.SERVICES) > 0
    assert all("name" in s for s in settings.SERVICES)
    assert all("url" in s for s in settings.SERVICES)
    assert all("check_type" in s for s in settings.SERVICES)
    assert all("expected_status" in s for s in settings.SERVICES)

def test_service_urls_valid():
    settings = Settings()

    for service in settings.SERVICES:
        assert service["url"].startswith("http://") or service["url"].startswith("https://")

def test_check_interval_positive():
    settings = Settings()
    assert settings.CHECK_INTERVAL > 0

def test_timeout_positive():
    settings = Settings()
    assert settings.TIMEOUT > 0
