import fastapi
import maxminddb


# Get db
# https://www.iplocate.io/download/ip-to-country.mmdb?apikey=$API_KEY&variant=daily

def get_country(ip: str):
    with maxminddb.open_database('data/ip-to-country.mmdb') as reader:
        # This returns the raw data dictionary directly matching the IP
        data = reader.get(ip)
        return data["country_code"] if data else None

app = fastapi.FastAPI()

@app.get("/ip/{ip}.svg")
def get_flag(ip: str):
    country_code = get_country(ip)
    if not country_code:
        return fastapi.Response(status_code=404, content="IP address not found in database.")

    # Assuming you have SVG files named like 'us.svg', 'gb.svg', etc. in a 'flags' directory
    try:
        with open(f"flags/4x3/{country_code.lower()}.svg", "r") as svg_file:
            svg_content = svg_file.read()
            return fastapi.Response(content=svg_content, media_type="image/svg+xml")
    except FileNotFoundError:
        return fastapi.Response(status_code=404, content="Flag not found for the country code.")

@app.get("/ip/{ip}.png")
def get_flag_png(ip: str):
    country_code = get_country(ip)
    if not country_code:
        return fastapi.Response(status_code=404, content="IP address not found in database.")

    try:
        with open(f"flags/4x3/{country_code.lower()}.svg", "r") as svg_file:
            svg_content = svg_file.read()
            # Convert to png using cairosvg
            import cairosvg
            png_content = cairosvg.svg2png(bytestring=svg_content.encode('utf-8'))
            return fastapi.Response(content=png_content, media_type="image/png")
    except FileNotFoundError:
        return fastapi.Response(status_code=404, content="Flag not found for the country code.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)