from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pathlib import Path

from config import settings
from database import init_db, get_db, AsyncSessionLocal, Service
from monitor import run_health_checks, cleanup_old_checks
from routes import router as api_router
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()

    logger.info("Initializing services...")
    await initialize_services()

    logger.info("Starting scheduler...")
    scheduler.add_job(
        run_health_checks,
        trigger=IntervalTrigger(seconds=settings.CHECK_INTERVAL),
        id="health_checks",
        replace_existing=True
    )
    scheduler.add_job(
        cleanup_old_checks,
        trigger=IntervalTrigger(days=1),
        id="cleanup",
        replace_existing=True
    )
    scheduler.start()

    await run_health_checks()

    yield

    logger.info("Shutting down scheduler...")
    scheduler.shutdown()

app = FastAPI(title="Homelab Status Service", lifespan=lifespan)

origins = [
    "https://kadenbilyeu.com",
    "https://status.kadenbilyeu.com",
    "https://status.bikatr7.com",
    "https://bikatr7.com",
    "http://localhost:5173",
    "https://kadenbilyeu-com.pages.dev",
    "https://*.kadenbilyeu-com.pages.dev",
    "https://*.bikatr7.com",
    "https://bikatr7.pages.dev",
    "https://*.bikatr7.pages.dev"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https://([a-z0-9-]\.)?(kadenbilyeu-com\.pages\.dev|bikatr7\.pages\.dev|kadenbilyeu\.com|bikatr7\.com)$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_PREFIX)

@app.get("/api")
async def api_root():
    return {"message": "Homelab Status Service API", "status": "operational"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

# Serve static frontend
static_dir = Path(__file__).parent / "frontend"
if static_dir.exists():
    @app.get("/")
    async def serve_frontend():
        return FileResponse(static_dir / "index.html")

async def initialize_services():
    logger.info("=== INITIALIZE_SERVICES STARTED ===")

    try:
        async with AsyncSessionLocal() as db:
            logger.info(f"Processing {len(settings.SERVICES)} services from config")

            for i, service_config in enumerate(settings.SERVICES):
                # Find existing service by URL (URL is the unique identifier)
                result = await db.execute(
                    select(Service).where(Service.url == service_config["url"])
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing service if name or config has changed
                    updated = False
                    if existing.name != service_config["name"]:
                        old_name = existing.name
                        existing.name = service_config["name"]
                        updated = True
                        logger.info(f"Updated service name: '{old_name}' -> '{service_config['name']}'")
                    if existing.check_type != service_config["check_type"]:
                        existing.check_type = service_config["check_type"]
                        updated = True
                    if existing.expected_status != service_config["expected_status"]:
                        existing.expected_status = service_config["expected_status"]
                        updated = True

                    if updated:
                        logger.info(f"Updated service: {service_config['name']}")
                else:
                    # Create new service
                    service = Service(
                        name=service_config["name"],
                        url=service_config["url"],
                        check_type=service_config["check_type"],
                        expected_status=service_config["expected_status"],
                        enabled=True
                    )
                    db.add(service)
                    logger.info(f"Added service: {service_config['name']}")

            await db.commit()
            logger.info("Service initialization complete")

    except Exception as e:
        logger.error(f"Error in initialize_services: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

    logger.info("=== INITIALIZE_SERVICES FINISHED ===")
