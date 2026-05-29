# DBIP

FastAPI microservice that maps an IP address to a country flag image.

## How it works

1. You request `/ip/{ip}.svg` or `/ip/{ip}.png`
2. The service looks up the IP in a MaxMind GeoIP database
3. It returns the corresponding country's flag as an SVG or PNG image

PNG flags are generated on-the-fly from SVGs using Cairo and cached in a temp directory.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /ip/{ip}.svg` | Looks up the IP and redirects to the country's flag SVG |
| `GET /ip/{ip}.png` | Looks up the IP and redirects to the country's flag PNG |
| `GET /images/{country_code}.svg` | Serves a flag SVG by ISO country code (e.g. `us`) |
| `GET /images/{country_code}.png` | Serves a flag PNG by ISO country code |

Responses include appropriate `Cache-Control` headers (1 day for IP lookups, 1 year for static flag assets).

## Setup

### Requirements

- Python 3.11+
- Node.js 18+
- [iplocate.io](https://iplocate.io) API key (for GeoIP database downloads)

### Environment Variables

| Variable | Description |
|---|---|
| `IPLOCATE_API_KEY` | API key for iplocate.io — required for database downloads |

### Local Development

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install flag icon assets
yarn install
# Flags will be copied to ./flags/4x3/ via postinstall script

# Start the server
python main.py --api-key YOUR_API_KEY
```

The service binds to `0.0.0.0:8000` by default. Override with `--host` and `--port`.

### Running with Docker

```bash
docker build -t dbip .
docker run -p 8000:8000 -e IPLOCATE_API_KEY=YOUR_API_KEY dbip
```

The Docker image is a multi-stage build that:
- Installs flag icon SVGs via Node/Yarn
- Installs Python dependencies
- Installs Cairo system libraries for SVG→PNG conversion
- Runs as a non-root user

## Auto-update

The service includes an APScheduler job that downloads the latest IP-to-country database every day at 2:00 AM. Set `IPLOCATE_API_KEY` to enable this.

Without an API key, the service will fail to start if `data/ip-to-country.mmdb` is not already present.

## Project Structure

```
├── main.py              # FastAPI application
├── requirements.txt     # Python dependencies
├── package.json         # Node dependency (flag icons)
├── yarn.lock
├── Dockerfile           # Multi-stage build
└── flags/4x3/           # Flag SVG assets (populated by yarn install)
```

## License

See individual dependency licenses.
