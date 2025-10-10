from pydantic_settings import BaseSettings
from typing import List, Dict

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./status.db"
    API_PREFIX: str = "/api"
    CHECK_INTERVAL: int = 60
    TIMEOUT: int = 10

    SERVICES: List[Dict[str, str]] = [
        {
            "name": "Personal Website (kadenbilyeu.com)",
            "url": "https://kadenbilyeu.com",
            "check_type": "http",
            "expected_status": "200"
        },
        {
            "name": "Personal Website (bikatr7.com)",
            "url": "https://bikatr7.com",
            "check_type": "http",
            "expected_status": "200"
        },
        {
            "name": "Personal Website API (kadenbilyeu.com)",
            "url": "https://api.kadenbilyeu.com",
            "check_type": "http",
            "expected_status": "200"
        },
        {
            "name": "Git (kadenbilyeu.com)",
            "url": "https://git.kadenbilyeu.com",
            "check_type": "http",
            "expected_status": "200"
        },
        {
            "name": "Git (bikatr7.com)",
            "url": "https://git.bikatr7.com",
            "check_type": "http",
            "expected_status": "200"
        },
        {
            "name": "Kakusui Website (kakusui.org)",
            "url": "https://kakusui.org",
            "check_type": "http",
            "expected_status": "200"
        },
        {
            "name": "Kakusui API (kakusui.org)",
            "url": "https://api.kakusui.org",
            "check_type": "http",
            "expected_status": "200"
        },
    ]

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
