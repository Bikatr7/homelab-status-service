# Homelab Status Service

Self-hosted service monitoring and uptime tracking for homelab infrastructure. Monitors configured services via HTTP health checks, tracks incidents, and displays a status page.

## Stack

FastAPI + SQLAlchemy + APScheduler + SQLite + Vanilla JS frontend

## API Endpoints

- `GET /api/services?domain={domain}` - List all services with current status
- `GET /api/services/{id}/history?hours=24` - Service health check history
- `GET /api/services/{id}/stats?hours=24` - Uptime statistics
- `GET /api/incidents?limit=50&ongoing_only=false&days=30` - Incident history
- `GET /api/health` - API health check

## Configuration

Edit services in `app/config.py`:

```python
SERVICES = [
    {
        "name": "My Service",
        "url": "https://example.com",
        "check_type": "http",
        "expected_status": "200",
        "domains": "example.com,other.com"
    }
]
```

Environment variables:
- `DATABASE_URL` - Database connection (default: `sqlite+aiosqlite:///./status.db`)
- `CHECK_INTERVAL` - Health check interval in seconds (default: 60)
- `TIMEOUT` - HTTP timeout in seconds (default: 10)

## Development

Install dependencies:
```bash
pip install -r app/requirements-dev.txt
```

Run locally:
```bash
cd app
uvicorn main:app --reload
```

Run tests:
```bash
cd app
pytest
```

Run with coverage:
```bash
pytest --cov=. --cov-report=html
```

## Deployment

```bash
docker-compose up -d
```

The service runs on port 8000. Traefik labels are configured for multiple domains.

Live instances:
- https://status.kadenbilyeu.com
- https://status.bikatr7.com
- https://status.kakusui.org
- https://status.easytl.org
- https://status.tetragroup.io

## License

GNU Affero General Public License v3.0
