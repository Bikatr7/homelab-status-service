# Homelab Status Service

Self-hosted service monitoring and uptime tracking for homelab infrastructure. Monitors configured services via HTTP health checks, tracks incidents, and displays a status page.

## Stack

FastAPI + SQLAlchemy + APScheduler + SQLite + Vanilla JS frontend

## API Endpoints

- `GET /api/overview?domain={domain}&hours=720&history=all` - Time-weighted availability, timelines and grouped history (24, 168 or 720 hours)
- `GET /api/services?domain={domain}` - List all services with current status
- `GET /api/services/{id}/history?hours=24` - Service health check history
- `GET /api/services/{id}/stats?hours=24` - Uptime statistics
- `GET /api/incidents?limit=50&ongoing_only=false&days=30` - Incident history
- `GET /api/health` - API health check

## Status page measurements

The homepage uses `/api/overview`. Timelines default to the last 30 days of
checks; the outage archive includes all retained incidents. Use
`history=window` to limit the archive to the selected period.

Only outages longer than 60 seconds count. Longer outages count in full,
including the first minute. A new failure shows as Checking until it passes
that threshold. This changes reporting, not the stored records.

Uptime is based on elapsed time, not sample counts. A check remains valid until
the next sample or three check intervals (at least 180 seconds). Gaps after
that are unknown and excluded from uptime. Green/red timeline bars have equal
height; custom tooltips show exact times, downtime and missing observations.

Overlapping outages are grouped across services. Group duration runs from the
first failure to the last recovery, without implying a shared cause. Archive
rows load 20 at a time with no total display limit.

Timestamps use UTC in the API. The page offers local time and UTC, including
historical daylight-saving offsets. Public responses contain service labels
and hostnames, not diagnostic errors or internal infrastructure details.

Responses are cached for 20 seconds. The browser refreshes each minute and
marks old checks stale if updates fail. Only `frontend/assets/` is served at
`/assets`; repository files and backups are not exposed.

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

The browser regression checks use Playwright and Chromium, with intercepted
fixture responses (no production writes):

```bash
PLAYWRIGHT_MODULE=/path/to/playwright BROWSER_PATH=/path/to/chromium node scripts/check_frontend.cjs
```

They cover public-source privacy, phone/desktop layouts, keyboard navigation,
offline and stale states, timezone/DST conversion, and HTML escaping.

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
