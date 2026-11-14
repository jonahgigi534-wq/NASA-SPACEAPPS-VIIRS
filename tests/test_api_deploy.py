"""Deploy tests (B6): the app downloads its data from APP_DATA_URL at startup.

A fake Hugging Face server (httpx.MockTransport) serves the 4 files: like the real one,
/resolve/main/<file> redirects to a CDN URL. No internet needed.

Run:  pytest tests/test_api_deploy.py -q
"""

import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from app import main  # noqa: E402

BASE = "https://huggingface.co/datasets/team/firebridge-data/resolve/main/"
FILES = ["cells_daily.parquet", "missing_days.parquet", "hotspots.parquet", "coverage.json"]


@pytest.fixture(scope="module")
def source_dir(tmp_path_factory):
    import make_synthetic_app_data as synth
    d = tmp_path_factory.mktemp("hf_source")
    synth.build(str(d), scale=0.1, end="2026-11-13")
    return d


def fake_hf(source_dir, requested, broken=()):
    def handler(request):
        url = str(request.url)
        if url.startswith(BASE):
            name = url[len(BASE):]
            requested.append(name)
            if name in broken:
                return httpx.Response(404, text="Entry not found")
            return httpx.Response(302, headers={"location": f"https://cdn.test/{name}"})
        if url.startswith("https://cdn.test/"):
            name = url.rsplit("/", 1)[1]
            return httpx.Response(200, content=(source_dir / name).read_bytes())
        return httpx.Response(404)
    return handler


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    main._download.update(active=False, file=None, mb_done=0.0, mb_total=None, error=None)
    main.reset_store()
    yield
    main._download.update(active=False, file=None, mb_done=0.0, mb_total=None, error=None)
    main.reset_store()


def test_downloads_missing_files_and_skips_existing(source_dir, tmp_path):
    dest = tmp_path / "app"
    dest.mkdir()
    (dest / "coverage.json").write_bytes((source_dir / "coverage.json").read_bytes())
    requested = []
    main.download_app_data(BASE.rstrip("/"), dest, client=mock_client(fake_hf(source_dir, requested)))
    assert sorted(requested) == sorted(FILES[:3])          # coverage.json already there
    for f in FILES:
        assert (dest / f).read_bytes() == (source_dir / f).read_bytes()
    assert not list(dest.glob("*.part"))


def test_failed_download_leaves_no_partial_file(source_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DOWNLOAD_RETRIES", 1)
    dest = tmp_path / "app"
    handler = fake_hf(source_dir, [], broken=("hotspots.parquet",))
    with pytest.raises(RuntimeError, match="hotspots.parquet"):
        main.download_app_data(BASE, dest, client=mock_client(handler))
    assert not (dest / "hotspots.parquet").exists()
    assert not list(dest.glob("*.part"))


def test_requests_get_a_friendly_503_while_downloading(source_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(source_dir))
    main._download.update(active=True, file="hotspots.parquet", mb_done=120.4, mb_total=471)
    r = TestClient(main.app).get("/api/regions")
    assert r.status_code == 503
    assert "still downloading (hotspots.parquet, 120 of 471 MB)" in r.json()["error"]


def test_startup_downloads_then_api_works(source_dir, tmp_path, monkeypatch):
    dest = tmp_path / "empty_app_dir"
    monkeypatch.setenv("APP_DATA_URL", BASE)
    monkeypatch.setenv("APP_DATA_DIR", str(dest))
    monkeypatch.setattr(main, "_http_client", lambda: mock_client(fake_hf(source_dir, [])))
    with TestClient(main.app) as client:                  # 'with' runs the startup hook
        deadline = time.time() + 60
        while main._download["active"] and time.time() < deadline:
            time.sleep(0.05)
        assert main._download["error"] is None
        r = client.get("/api/regions")
        assert r.status_code == 200, r.text
        assert {x["id"] for x in r.json()["regions"]} == {"texas", "amazon", "australia"}


def test_no_download_without_app_data_url(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_DATA_URL", raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "nothing"))
    assert main.start_data_download() is None
    r = TestClient(main.app).get("/api/regions")
    assert r.status_code == 503 and "App data not found" in r.json()["error"]
