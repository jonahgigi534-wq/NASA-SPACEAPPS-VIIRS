"""Tests for the live FIRMS feed (pipeline/live.py) and how the API uses it.

No internet and no real MAP_KEY needed: a fake FIRMS server (httpx.MockTransport) answers.

Run:  pytest tests/test_api_live.py -q
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from pipeline import live  # noqa: E402

KEY = "TESTKEY123"
TODAY = date(2026, 11, 14)
VIIRS_GAP_DAY = date(2026, 11, 5)     # fake outage: no VIIRS that day, plenty of MODIS
FIRE = (31.02, -98.03)                # one fire location in Texas, cell center (31.0, -98.0)

MODIS_HEADER = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
                "confidence,version,bright_t31,frp,daynight")
VIIRS_HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
                "confidence,version,bright_ti5,frp,daynight")


def fake_firms(calls):
    """A pretend FIRMS area API. Every day: the same fire seen 12x by MODIS,
    4x by NOAA-20 and 3x by NOAA-21 (the same fire, so VIIRS should count 4, not 7)."""
    def handler(request):
        calls.append(str(request.url))
        parts = request.url.path.split("/")
        key, source, days, start = parts[4], parts[5], int(parts[7]), date.fromisoformat(parts[8])
        if key != KEY:
            return httpx.Response(400, text=f"Invalid MAP_KEY {key}.")
        if "-65" in parts[6] or "120" in parts[6]:
            return httpx.Response(200, text="")      # no fires in the other regions
        lines = [MODIS_HEADER if source == "MODIS_NRT" else VIIRS_HEADER]
        for i in range(days):
            d = start + timedelta(days=i)
            if d >= TODAY:
                continue
            if source == "MODIS_NRT":
                for k in range(12):
                    sat, t = ("Terra", "1630") if k % 2 else ("Aqua", "0745")
                    lines.append(f"{FIRE[0]},{FIRE[1]},320,1,1,{d},{t},{sat},MODIS,"
                                 f"{[20, 50, 90][k % 3]},6.1NRT,290,30.0,D")
            elif d != VIIRS_GAP_DAY:
                n = 4 if source == "VIIRS_NOAA20_NRT" else 3
                for k in range(n):
                    lines.append(f"{FIRE[0]},{FIRE[1]},330,0.4,0.4,{d},1935,N,VIIRS,n,2.0NRT,"
                                 f"295,6.0,D")
        return httpx.Response(200, text="\n".join(lines) + "\n")
    return handler


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    import make_synthetic_app_data as synth
    d = tmp_path / "app"
    synth.build(str(d), scale=0.3, end="2026-10-31")      # main data stops at nrt_end
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(live, "SECONDS_BETWEEN_CALLS", 0)
    return d


def run_live(data_dir, handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return live.run(KEY, data_dir, client=client, today=TODAY, **kw)


def test_live_files_and_harmonization(data_dir, capsys):
    calls = []
    cov = run_live(data_dir, fake_firms(calls))
    assert cov["texas"]["live_start"] == "2026-11-01"
    assert cov["texas"]["live_end"] == "2026-11-13"
    assert cov["texas"]["viirs_count_factor"] == pytest.approx(1 / 3, rel=0.15)
    # 13 days -> 2 chunks of <= 10 days, x 3 sources, x 3 regions
    assert len(calls) == 2 * 3 * 3
    assert KEY not in capsys.readouterr().out
    assert all(KEY not in p.name for p in (live.CACHE_DIR).iterdir())

    cells = pd.read_parquet(data_dir / "live_cells_daily.parquet")
    hot = pd.read_parquet(data_dir / "live_hotspots.parquet")
    assert list(cells.columns) == live.CELLS_SCHEMA.names
    assert list(hot.columns) == live.HOTSPOTS_SCHEMA.names
    assert cells["provisional"].all() and hot["provisional"].all()

    day = cells[cells["date"] == date(2026, 11, 2)].iloc[0]
    assert day["viirs_n"] == 4            # de-duplicated: max single satellite, not 4 + 3
    assert day["modis_n"] == 12
    assert day["mec"] == pytest.approx(4 * cov["texas"]["viirs_count_factor"], rel=1e-3)
    # every cell-day's hotspot weights add up to its harmonized count
    w = hot.groupby("date")["weight"].sum()
    m = cells.set_index("date")["mec"]
    assert (w.reindex(m.index) - m).abs().max() < 1e-3
    assert set(hot.loc[hot["sensor"] == "MODIS", "confidence_class"]) == {"low", "nominal", "high"}

    miss = pd.read_parquet(data_dir / "live_missing_days.parquet")
    assert set(miss.loc[miss["date"] == VIIRS_GAP_DAY, "scope"]) == {"viirs_raw", "harmonized"}


def test_api_uses_live_data(data_dir, monkeypatch):
    from app import main
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    main.reset_store()
    client = TestClient(main.app)
    area = {"type": "point", "lat": FIRE[0], "lon": FIRE[1], "radius_km": 5}
    before = client.post("/api/current", json={"area": area}).json()
    assert before["month"] == "2026-10"                   # no live data yet

    run_live(data_dir, fake_firms([]))
    regions = {r["id"]: r for r in client.get("/api/regions").json()["regions"]}
    assert regions["texas"]["live_end"] == "2026-11-13"   # picked up without a restart

    cur = client.post("/api/current", json={"area": area}).json()
    assert cur["month"] == "2026-11" and cur["days_so_far"] == 13
    assert cur["provisional"] is True
    cal = client.post("/api/calendar", json={"area": area, "granularity": "day",
                                             "start": "2026-11-01", "end": "2026-11-13"}).json()
    by_day = {c["period"]: c for c in cal["cells"]}
    assert by_day["2026-11-05"]["missing"] is True        # VIIRS outage: missing, not zero
    assert by_day["2026-11-02"]["value"] > 0 and by_day["2026-11-02"]["provisional"]
    main.reset_store()


def test_firms_down_keeps_old_files_and_api_works(data_dir, monkeypatch, capsys):
    run_live(data_dir, fake_firms([]))
    before = (data_dir / "live_cells_daily.parquet").read_bytes()

    def down(request):
        raise httpx.ConnectError("FIRMS is down")
    monkeypatch.setattr(live, "RETRIES", 1)
    for p in live.CACHE_DIR.iterdir():                     # force re-fetching
        p.unlink()
    assert run_live(data_dir, down) == {}
    assert (data_dir / "live_cells_daily.parquet").read_bytes() == before

    from app import main
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    main.reset_store()
    assert TestClient(main.app).get("/api/regions").status_code == 200
    main.reset_store()


def test_bad_key_is_reported_without_leaking_it(data_dir, capsys):
    client = httpx.Client(transport=httpx.MockTransport(fake_firms([])))
    assert live.run("WRONGKEY99", data_dir, client=client, today=TODAY) == {}
    out = capsys.readouterr().out
    assert "WRONGKEY99" not in out and "<MAP_KEY>" in out
