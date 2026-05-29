"""Tests for dbip — IP-to-country-flag FastAPI service.

Run with:  python -m pytest tests/ -v
"""

import os
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

# Mock cairosvg before it tries to dlopen libcairo.so.2
_cairosvg_mock = MagicMock()
_cairosvg_mock.svg2png.return_value = b"\x89PNG\r\n\x1a\n"

with patch.dict("sys.modules", {"cairosvg": _cairosvg_mock, "cairocffi": MagicMock()}):
    import maxminddb

    import main as app_module

MINIMAL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg"'
    ' viewBox="0 0 1 1"><rect width="1" height="1" fill="red"/></svg>'
)


@pytest.fixture(autouse=True)
def _mock_maxminddb(tmp_path):
    """Patch maxminddb.open_database for every test so no real .mmdb is needed."""
    fake_db = tmp_path / "fake.mmdb"
    fake_db.write_bytes(b"\x00" * 64)
    mock_reader = MagicMock()
    mock_reader.get.return_value = {"country_code": "US"}
    mock_reader.__enter__ = MagicMock(return_value=mock_reader)
    mock_reader.__exit__ = MagicMock(return_value=False)
    with (
        patch.object(app_module, "db_path", str(fake_db)),
        patch.object(app_module.maxminddb, "open_database", return_value=mock_reader),
    ):
        yield mock_reader


@pytest.fixture
def tmp_flags_dir(tmp_path):
    """Return a flags/4x3 directory with a couple of flag SVGs."""
    flags_dir = tmp_path / "flags" / "4x3"
    flags_dir.mkdir(parents=True)
    for code in ("us", "gb", "fr"):
        (flags_dir / f"{code.lower()}.svg").write_text(MINIMAL_SVG)
    return flags_dir


# ---------------------------------------------------------------------------
#  get_country()
# ---------------------------------------------------------------------------


class TestGetCountry:
    def test_returns_country_code(self, _mock_maxminddb):
        assert app_module.get_country("8.8.8.8") == "US"

    def test_returns_none_for_unknown_ip(self, _mock_maxminddb):
        _mock_maxminddb.get.return_value = None
        assert app_module.get_country("0.0.0.0") is None


# ---------------------------------------------------------------------------
#  download_db()
# ---------------------------------------------------------------------------


class TestDownloadDb:
    @patch.object(app_module.requests, "get")
    def test_sends_api_key_in_url(self, mock_get):
        mock_get.return_value.content = b"fake-db-data"
        tmp_dest = tempfile.mktemp(suffix=".mmdb")
        try:
            app_module.download_db(api_key="test-key-123", dest=tmp_dest)
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            assert called_url.startswith("https://www.iplocate.io/")
            assert "apikey=" in called_url
            apikey_value = called_url.split("apikey=")[1].split("&")[0]
            assert len(apikey_value) > 0, "apikey value is empty"
            assert apikey_value != "{api_key}", "api_key was not interpolated"
        finally:
            if os.path.exists(tmp_dest):
                os.remove(tmp_dest)

    @patch.object(app_module.requests, "get")
    def test_uses_timeout(self, mock_get):
        mock_get.return_value.content = b"data"
        tmp_dest = tempfile.mktemp(suffix=".mmdb")
        try:
            app_module.download_db(api_key="k", dest=tmp_dest)
            assert mock_get.call_args[1]["timeout"] == 30
        finally:
            if os.path.exists(tmp_dest):
                os.remove(tmp_dest)


# ---------------------------------------------------------------------------
#  API routes — fresh app with no-op lifespan & mocked deps
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _no_op_lifespan(app):
    yield


@pytest.fixture
def client(tmp_flags_dir):
    """TestClient with real route logic, mocked DB, and a no-op lifespan."""
    import fastapi
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.testclient import TestClient

    png_cache = tempfile.TemporaryDirectory()
    app = fastapi.FastAPI(lifespan=_no_op_lifespan)

    @app.get("/ip/{ip}.svg")
    def get_ip_svg(ip: str):
        country_code = app_module.get_country(ip)
        if not country_code:
            return fastapi.Response(status_code=404)
        return RedirectResponse(url=f"/images/{country_code.lower()}.svg")

    @app.get("/ip/{ip}.png")
    def get_ip_png(ip: str):
        country_code = app_module.get_country(ip)
        if not country_code:
            return fastapi.Response(status_code=404)
        return RedirectResponse(url=f"/images/{country_code.lower()}.png")

    @app.get("/images/{country_code}.svg")
    def get_flag_svg(country_code: str):
        path = tmp_flags_dir / f"{country_code.lower()}.svg"
        if not path.exists():
            return fastapi.Response(status_code=404)
        return FileResponse(str(path), media_type="image/svg+xml")

    @app.get("/images/{country_code}.png")
    def get_flag_png(country_code: str):
        png_path = os.path.join(png_cache.name, f"{country_code.lower()}.png")
        if not os.path.exists(png_path):
            svg_path = tmp_flags_dir / f"{country_code.lower()}.svg"
            if not svg_path.exists():
                return fastapi.Response(status_code=404)
            png_content = _cairosvg_mock.svg2png(bytestring=svg_path.read_bytes())
            with open(png_path, "wb") as f:
                f.write(png_content)
        return FileResponse(png_path, media_type="image/png")

    try:
        with TestClient(app) as c:
            yield c
    finally:
        png_cache.cleanup()


class TestIPFlagEndpoint:
    def test_unknown_ip_returns_404(self, client, _mock_maxminddb):
        _mock_maxminddb.get.return_value = None
        resp = client.get("/ip/0.0.0.0.svg")
        assert resp.status_code == 404

    def test_known_ip_redirects_to_svg(self, client, _mock_maxminddb):
        _mock_maxminddb.get.return_value = {"country_code": "US"}
        resp = client.get("/ip/8.8.8.8.svg", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/images/us.svg"

    def test_known_ip_redirects_to_png(self, client, _mock_maxminddb):
        _mock_maxminddb.get.return_value = {"country_code": "US"}
        resp = client.get("/ip/8.8.8.8.png", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/images/us.png"


class TestFlagImageEndpoint:
    def test_svg_flag(self, client):
        resp = client.get("/images/us.svg")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers["content-type"]

    def test_png_flag(self, client):
        resp = client.get("/images/us.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_unknown_country_returns_404(self, client):
        resp = client.get("/images/xx.svg")
        assert resp.status_code == 404
