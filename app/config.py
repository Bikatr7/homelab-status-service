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
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com"
        },
        {
            "name": "Personal Website (bikatr7.com)",
            "url": "https://bikatr7.com",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com"
        },
        {
            "name": "Personal Website API (api.kadenbilyeu.com)",
            "url": "https://api.kadenbilyeu.com",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com"
        },
        {
            "name": "Git (git.kadenbilyeu.com)",
            "url": "https://git.kadenbilyeu.com",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com"
        },
        {
            "name": "Git (git.bikatr7.com)",
            "url": "https://git.bikatr7.com",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com"
        },
        {
            "name": "Kakusui API (api.kakusui.org)",
            "url": "https://api.kakusui.org",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com,kakusui.org,easytl.org"
        },
        {
            "name": "EasyTL Website (easytl.org)",
            "url": "https://easytl.org",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com,easytl.org"
        },
        {
            "name": "TetraGroup Website (tetragroup.io)",
            "url": "https://tetragroup.io",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com,tetragroup.io"
        },
        {
            "name": "Momentum (momentum.kadenbilyeu.com)",
            "url": "https://momentum.kadenbilyeu.com",
            "check_type": "http",
            "expected_status": "200",
            "domains": "kadenbilyeu.com,bikatr7.com"
        },
    ]

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
