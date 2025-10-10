# Homelab Status Service

Service monitoring and uptime tracking for homelab infrastructure.

## Stack

FastAPI + SQLAlchemy + APScheduler + SQLite

## API Endpoints

- `GET /api/services` - List all services with current status
- `GET /api/services/{id}/history?hours=24` - Service health check history
- `GET /api/services/{id}/stats?hours=24` - Uptime statistics
- `GET /api/incidents?limit=50&ongoing_only=false` - Incident history

## Configuration

Edit services in `app/config.py`. Environment variables in `.env`:

- `DATABASE_URL` - Database connection (default: SQLite)
- `CHECK_INTERVAL` - Health check interval in seconds (default: 60)
- `TIMEOUT` - HTTP timeout in seconds (default: 10)

## Development

Install dependencies:
```bash
pip install -r app/requirements-dev.txt
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

Available at: https://status.kadenbilyeu.com and https://status.bikatr7.com

## License

GNU Affero General Public License v3.0
