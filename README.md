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

The homepage uses `/api/overview`; older endpoints remain compatible. The new
endpoint calculates elapsed time, not the fraction of successful samples. A
check remains valid until the next sample or three check intervals (at least
180 seconds). After that, missing observations count as **downtime**, including
gaps already present in retained history. Uptime uses the entire selected window
as its denominator; missing checks reduce uptime and appear as red timeline bars
and system outages. Tooltips show how much downtime comes from missing checks.
The observation-coverage metric still reports how much time had fresh checks.
Observed failures lasting 60 seconds or less do not count toward downtime, timeline red
bars, or outage history. Longer outages count in full. A fresh failure still
inside this threshold is shown as Checking. Raw check and incident records are
not deleted or rewritten.

Timeline segments summarize equal time intervals. The dark homepage uses uniform,
solid green bars for reachable time and red bars for outages.
Custom tooltips reveal exact bounds and
durations on hover, keyboard focus, or tap; Escape or an outside tap dismisses
them. The default timeline covers the full 30-day check retention window. The
outage archive defaults to all retained incidents, including those older than
the raw checks; `history=window` limits incidents to the selected period.
The archive loads in batches of 20 rows with no fixed total display cap.
Observation gaps can only be reconstructed inside the retained check window.
Near-simultaneous, overlapping incidents from different services are grouped,
without asserting a common cause. A group's duration spans its first failure
to last recovery, not the sum of individual service durations. Missing-check
intervals are outages and are merged with overlapping or adjoining incidents for
the same service so history does not double-count an outage. This policy does
not rewrite raw checks or incident records.

All API timestamps have an explicit UTC `Z` suffix. Display defaults to the
browser's local time zone, with a UTC selector and historical DST-aware offsets.
No internal device names, network details, or raw diagnostic errors are exposed
by the homepage or overview response. Only public service labels and hostnames
should be configured for public display.

The overview response has a bounded, 20-second application cache. The browser
refreshes each minute and marks stale checks offline after the freshness deadline.
A browser/API connection failure still displays an unavailable current status
because it cannot establish whether the server or the client's connection failed.
Static resources live under `frontend/assets/`; only that
directory is mounted at `/assets`, not backups or the repository.

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
