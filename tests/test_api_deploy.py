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


# ---- hourly live refresh -----------------------------------------------------------------------

@pytest.fixture
def live_ready_dir(tmp_path, monkeypatch):
    """App data that stops at nrt_end (like Track A's), so the live feed has days to add."""
    import make_synthetic_app_data as synth
    from pipeline import live
    d = tmp_path / "app"
    synth.build(str(d), scale=0.1, end="2026-10-31")
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(live, "SECONDS_BETWEEN_CALLS", 0)
    monkeypatch.setenv("APP_DATA_DIR", str(d))
    monkeypatch.setenv("FIRMS_MAP_KEY", "TESTKEY123")
    main._live.update(active=False, last_ok=None, last_error=None, runs=0)
    yield d
    main._live_stop.set()


def test_refresh_success_shows_up_in_api(live_ready_dir, monkeypatch):
    sys.path.insert(0, str(REPO / "tests"))
    import test_api_live as tl
    from pipeline import live
    real_run = live.run
    monkeypatch.setattr(live, "run", lambda key, data_dir: real_run(
        key, data_dir, client=httpx.Client(transport=httpx.MockTransport(tl.fake_firms([]))),
        today=tl.TODAY))
    client = TestClient(main.app)
    assert client.get("/api/regions").json()["regions"][0]["live_end"] == "2026-10-31"
    main.refresh_live_once(live_ready_dir)
    assert main._live["last_error"] is None and main._live["last_ok"]
    assert client.get("/api/regions").json()["regions"][0]["live_end"] == "2026-11-13"


@pytest.mark.parametrize("boom", [RuntimeError("FIRMS exploded"), SystemExit("bad key")])
def test_failed_refresh_never_takes_the_site_down(live_ready_dir, monkeypatch, boom):
    from pipeline import live

    def fail(key, data_dir):
        raise boom
    monkeypatch.setattr(live, "run", fail)
    client = TestClient(main.app)
    before = client.post("/api/summary", json={"area": {"type": "bbox", "bbox": [-100, 30, -96, 33]}})
    main.refresh_live_once(live_ready_dir)                  # must not raise
    assert "FIRMS exploded" in main._live["last_error"] or "bad key" in main._live["last_error"]
    after = client.post("/api/summary", json={"area": {"type": "bbox", "bbox": [-100, 30, -96, 33]}})
    assert before.status_code == after.status_code == 200
    assert before.json() == after.json()                   # same last-good data
    assert client.get("/api/status").json()["live_refresh"]["last_error"]


def count_runs(monkeypatch):
    runs = []
    monkeypatch.setattr(main, "refresh_live_once", lambda d: runs.append(time.time()))
    return runs


def test_loop_refreshes_on_its_interval(live_ready_dir, monkeypatch):
    runs = count_runs(monkeypatch)
    monkeypatch.setattr(main, "LIVE_REFRESH_SECONDS", 0.2)
    t = main.start_live_refresh()
    time.sleep(0.9)
    main._live_stop.set()
    t.join(2)
    assert 3 <= len(runs) <= 6                            # every 0.2 s, not in a tight loop


def test_loop_runs_once_then_waits_an_hour(live_ready_dir, monkeypatch):
    runs = count_runs(monkeypatch)
    t = main.start_live_refresh()
    time.sleep(0.5)
    main._live_stop.set()
    t.join(2)
    assert len(runs) == 1


def test_quick_restart_does_not_refetch(live_ready_dir, monkeypatch):
    (live_ready_dir / "live_coverage.json").write_text("{}")  # refreshed moments ago
    runs = count_runs(monkeypatch)
    t = main.start_live_refresh()
    time.sleep(0.5)
    main._live_stop.set()
    t.join(2)
    assert runs == []


def test_no_refresh_without_key_or_when_disabled(live_ready_dir, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY")
    assert main.start_live_refresh() is None
    monkeypatch.setenv("FIRMS_MAP_KEY", "x")
    monkeypatch.setenv("LIVE_REFRESH", "0")
    assert main.start_live_refresh() is None


@pytest.mark.parametrize("given", [
    "https://huggingface.co/datasets/team/firebridge-data/resolve/main/",
    "https://huggingface.co/datasets/team/firebridge-data/resolve/main",
    "https://huggingface.co/datasets/team/firebridge-data/resolve/main/coverage.json",
    "https://huggingface.co/datasets/team/firebridge-data/resolve/main/hotspots.parquet?download=true",
])
def test_app_data_url_folder_or_file(given):
    assert main.data_base_url(given) == BASE


def test_status_reports_the_pinned_dataset_revision(source_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(source_dir))
    monkeypatch.setenv("APP_DATA_URL", "https://huggingface.co/datasets/team/firebridge-data/resolve/3e4b6b22/")
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    s = TestClient(main.app).get("/api/status").json()
    assert s["data"]["dataset_revision"] == "3e4b6b22"
