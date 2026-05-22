import os
import tempfile

import cairosvg
import fastapi
from fastapi.responses import FileResponse, RedirectResponse
import maxminddb


# Get db
# https://www.iplocate.io/download/ip-to-country.mmdb?apikey=$API_KEY&variant=daily

def get_country(ip: str):
    with maxminddb.open_database('data/ip-to-country.mmdb') as reader:
        # This returns the raw data dictionary directly matching the IP
        data = reader.get(ip)
        return data["country_code"] if data else None

app = fastapi.FastAPI()

png_cache_dir = tempfile.TemporaryDirectory()

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
    uvicorn.run(app, host="0.0.0.0", port=8000)