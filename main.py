import os
import tempfile
from datetime import datetime
import logging
from contextlib import asynccontextmanager
import argparse

import cairosvg
import fastapi
from fastapi.responses import FileResponse, RedirectResponse
import maxminddb
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import requests

png_cache_dir = tempfile.TemporaryDirectory()
db_path = "data/ip-to-country.mmdb"

API_KEY = os.getenv("IPLOCATE_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_country(ip: str):
    with maxminddb.open_database('data/ip-to-country.mmdb') as reader:
        # This returns the raw data dictionary directly matching the IP
        data = reader.get(ip)
        return data["country_code"] if data else None

def download_db(api_key: str, dest: str):
    res = requests.get(
        f"https://www.iplocate.io/download/ip-to-country.mmdb?apikey=***&variant=daily",
        timeout=30,
    )
    with open(dest, "wb") as f:
        f.write(res.content)

# Initialize scheduler
scheduler = AsyncIOScheduler()


# Background task - runs once per day (e.g., at 2 AM)
async def daily_task():
    """
    Long-running background task that executes once per day.
    Customize this function with your actual task logic.
    """
    logger.info(f"Daily background task started at {datetime.now()}")
    try:
        if API_KEY:
            logger.info("Downloading latest IP-to-country database...")
            download_db(api_key=API_KEY, dest=db_path)
        logger.info("Daily background task completed successfully")
    except Exception as e:
        logger.error(f"Error in daily background task: {e}")


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    # Verify libcairo2 / cairosvg works (needed for PNG flag conversion)
    try:
        cairosvg.svg2png(bytestring=b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
    except Exception as e:
        raise RuntimeError(
            "libcairo2 runtime is required for PNG flag conversion but is not available. "
            "Inside Docker this is installed automatically; on the host run: "
            "apt-get install -y libcairo2"
        ) from e

    if not API_KEY:
        logger.info("IPLOCATE_API_KEY environment variable is not set. Downloads will be disabled.")

    # Check if database exists, download if not
    if not os.path.exists(db_path):
        if API_KEY:
            logger.info("IP-to-country database not found. Downloading...")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            try:
                download_db(api_key=API_KEY, dest=db_path)
                logger.info("Database downloaded successfully")
            except Exception as e:
                logger.error(f"Failed to download database: {e}")
                raise
        else:
            raise ValueError("Database not found and API key is missing. The application cannot start.")

    # Initialize and start the scheduler
    scheduler.add_job(
        daily_task,
        CronTrigger(hour=2, minute=0),  # Runs at 2:00 AM every day
        id="daily_task",
        name="Daily Background Task",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler started")
    yield
    # Shutdown: Stop the scheduler
    scheduler.shutdown()
    logger.info("Scheduler stopped")

app = fastapi.FastAPI(lifespan=lifespan)

@app.get("/ip/{ip}.svg")
def get_ip_svg(ip: str):
    country_code = get_country(ip)
    if not country_code:
        return fastapi.Response(status_code=404, content="IP address not found in database.")

    return RedirectResponse(url=f"/images/{country_code.lower()}.svg", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/ip/{ip}.png")
def get_ip_png(ip: str):
    country_code = get_country(ip)
    if not country_code:
        return fastapi.Response(status_code=404, content="IP address not found in database.")

    return RedirectResponse(url=f"/images/{country_code.lower()}.png", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/images/{country_code}.svg")
def get_flag_svg(country_code: str):
    return FileResponse(f"flags/4x3/{country_code.lower()}.svg", media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=31536000"})

@app.get("/images/{country_code}.png")
def get_flag_png(country_code: str):
    png_path = os.path.join(png_cache_dir.name, f"{country_code.lower()}.png")

    if not os.path.exists(png_path):
        try:
            with open(f"flags/4x3/{country_code.lower()}.svg", "r") as svg_file:
                svg_content = svg_file.read()
                png_content = cairosvg.svg2png(bytestring=svg_content.encode('utf-8'))
            with open(png_path, "wb") as png_file:
                png_file.write(png_content)
        except FileNotFoundError:
            return fastapi.Response(status_code=404, content="Flag not found for the country code.")

    return FileResponse(png_path, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000"})


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="IP-to-Country FastAPI Server")
    parser.add_argument("--api-key", default=os.getenv("IPLOCATE_API_KEY"), help="API key for iplocate.io")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")

    args = parser.parse_args()

    API_KEY = args.api_key

    uvicorn.run(app, host=args.host, port=args.port)