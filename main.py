import os
import re
import tempfile
from datetime import datetime
import logging
from contextlib import asynccontextmanager
from typing import Optional
import argparse

import cairosvg
import fastapi
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
import maxminddb
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import requests

# IPv4 validation regex
_IP_RE = re.compile(r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")

png_cache_dir = tempfile.TemporaryDirectory()
db_path = "data/ip-to-country.mmdb"

API_KEY = os.getenv("IPLOCATE_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_valid_ip(ip: str) -> bool:
    if not _IP_RE.match(ip):
        return False
    return all(0 <= int(part) <= 255 for part in ip.split("."))


def get_country(ip: str) -> Optional[str]:
    with maxminddb.open_database(db_path) as reader:
        data = reader.get(ip)
        return data["country_code"] if data else None


def download_db(api_key: str, dest: str) -> None:
    res = requests.get(
        f"https://www.iplocate.io/download/ip-to-country.mmdb?apikey={api_key}&variant=daily",
        timeout=30,
    )
    with open(dest, "wb") as f:
        f.write(res.content)


# Initialize scheduler
scheduler = AsyncIOScheduler()


async def daily_task() -> None:
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
        logger.warning(
            "IPLOCATE_API_KEY is not set. Database auto-download is disabled. "
            "You can still use the service if you manually place data/ip-to-country.mmdb. "
            "Get a free key at https://iplocate.io or download the DB directly from "
            "https://dev.maxmind.com/geoip/geolite2-free-geolocation-data"
        )

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
            logger.warning(
                "Database not found and IPLOCATE_API_KEY is missing. "
                "The application cannot start. Place data/ip-to-country.mmdb manually "
                "or set the IPLOCATE_API_KEY environment variable."
            )
            raise RuntimeError(
                "Database not found and API key is missing. "
                "Get a key at https://iplocate.io or download from https://dev.maxmind.com/geoip/geolite2-free-geolocation-data"
            )

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


APP_ROOT_PATH = os.getenv("APP_ROOT_PATH", "")
app = fastapi.FastAPI(lifespan=lifespan, root_path=APP_ROOT_PATH)


@app.get("/healthz")
def healthz():
    db_ok = os.path.exists(db_path)
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "database_loaded": db_ok}
    )


def _lookup_ip(ip: str):
    """Shared IP lookup with validation. Returns (country_code, error_response)."""
    if not _is_valid_ip(ip):
        return None, fastapi.Response(
            status_code=400,
            content="Invalid IPv4 address.",
        )
    country_code = get_country(ip)
    if not country_code:
        return None, fastapi.Response(
            status_code=404,
            content="IP address not found in database.",
        )
    return country_code, None


@app.get("/ip/{ip}.svg")
def get_ip_svg(ip: str):
    country_code, err = _lookup_ip(ip)
    if err:
        return err
    return RedirectResponse(url=f"/images/{country_code.lower()}.svg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/ip/{ip}.png")
def get_ip_png(ip: str):
    country_code, err = _lookup_ip(ip)
    if err:
        return err
    return RedirectResponse(url=f"/images/{country_code.lower()}.png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/ip/{ip}.json")
def get_ip_json(ip: str):
    country_code, err = _lookup_ip(ip)
    if err:
        return err
    return {"ip": ip, "country_code": country_code.upper()}


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
