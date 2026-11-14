"""API tests: every endpoint in docs/CONTRACTS.md section 4.

Data: if APP_DATA_DIR is set, the tests run on that folder (use this for Track A's real data);
otherwise fresh synthetic data is generated once into a temp folder.

The expected JSON shapes are read straight out of docs/CONTRACTS.md, so if anyone edits the
contract without updating the API (or the other way round), these tests fail.

Run:  pytest tests/test_api_endpoints.py -q
"""

import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

TEXAS_2011 = {"area": {"type": "bbox", "bbox": [-100, 30, -96, 33]},
              "start": "2011-01-01", "end": "2011-12-31", "baseline": [2003, 2022],
              "mode": "harmonized", "metric": "count"}
TEXAS_WHOLE = {"type": "bbox", "bbox": [-107, 25, -93, 37]}


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    data_dir = os.environ.get("APP_DATA_DIR")
    if not data_dir:
        import make_synthetic_app_data as synth
        data_dir = str(tmp_path_factory.mktemp("app_data"))
        synth.build(data_dir, scale=1.0, end="2026-11-13")
        os.environ["APP_DATA_DIR"] = data_dir
    from app import main
    main.reset_store()
    c = TestClient(main.app)
    c.data_dir = Path(data_dir)
    yield c
    main.reset_store()


def contract_examples():
    """{'/api/summary': {...example JSON...}, ...} from docs/CONTRACTS.md section 4."""
    text = (REPO / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    found = re.findall(r"`(?:GET|POST) (/api/\w+)`[^\n]*\n```json\n(.*?)```", text, re.S)
    return {path: json.loads(body) for path, body in found}


def assert_same_shape(got, expected, where="response"):
    """Same keys at every level (lists: compare the first item). Values may differ."""
    if isinstance(expected, dict):
        assert isinstance(got, dict), f"{where}: expected an object"
        assert set(got) == set(expected), \
            f"{where}: keys differ. extra={set(got) - set(expected)} missing={set(expected) - set(got)}"
        for k in expected:
            if got[k] is not None and expected[k] is not None:
                assert_same_shape(got[k], expected[k], f"{where}.{k}")
    elif isinstance(expected, list):
        assert isinstance(got, list), f"{where}: expected a list"
        if expected and got and isinstance(expected[0], (dict, list)):
            assert_same_shape(got[0], expected[0], f"{where}[0]")


def test_contract_has_every_example():
    ex = contract_examples()
    for path in ["/api/regions", "/api/summary", "/api/calendar", "/api/patterns",
                 "/api/current", "/api/timeseries"]:
        assert path in ex, f"{path} example missing from docs/CONTRACTS.md"


@pytest.mark.parametrize("path", ["/api/summary", "/api/calendar", "/api/patterns",
                                  "/api/current", "/api/timeseries"])
def test_post_endpoints_match_contract_shape(client, path):
    r = client.post(path, json=TEXAS_2011)
    assert r.status_code == 200, r.text
    assert_same_shape(r.json(), contract_examples()[path], path)


def test_regions_matches_contract(client):
    r = client.get("/api/regions")
    assert r.status_code == 200
    assert_same_shape(r.json(), contract_examples()["/api/regions"], "/api/regions")
    ids = {x["id"] for x in r.json()["regions"]}
    assert "texas" in ids


def test_calendar_daily_and_modes(client):
    for mode in ["harmonized", "modis_only", "viirs_raw"]:
        body = {**TEXAS_2011, "mode": mode, "granularity": "day",
                "start": "2011-04-01", "end": "2011-04-30"}
        r = client.post("/api/calendar", json=body)
        assert r.status_code == 200, r.text
        cells = r.json()["cells"]
        assert len(cells) == 30 and cells[0]["period"] == "2011-04-01"
        if mode == "viirs_raw":   # VIIRS didn't exist in 2011: missing, not zero
            assert all(c["missing"] and c["value"] is None for c in cells)


def test_missing_day_shows_as_missing_not_zero(client):
    miss = pd.read_parquet(client.data_dir / "missing_days.parquet")
    m = miss[(miss["region"] == "texas") & (miss["scope"] == "harmonized")]
    day = str(pd.Timestamp(m["date"].iloc[0]).date())
    body = {**TEXAS_2011, "area": TEXAS_WHOLE, "granularity": "day", "start": day, "end": day}
    cell = client.post("/api/calendar", json=body).json()["cells"][0]
    assert cell["missing"] is True and cell["value"] is None


def test_harmonized_removes_the_2012_jump(client):
    series = client.post("/api/timeseries", json={**TEXAS_2011, "area": TEXAS_WHOLE}).json()["series"]
    df = pd.DataFrame(series).set_index("month")

    # In the overlap years both sensors fly. On the MODIS scale, harmonized should match MODIS;
    # raw VIIRS should not (that mismatch is the 2012 jump).
    ov = df.loc["2013-01":"2018-12"].dropna()
    raw_ratio = ov["viirs_raw"].sum() / ov["modis_only"].sum()
    harm_ratio = ov["harmonized"].sum() / ov["modis_only"].sum()
    assert raw_ratio > 1.5                                       # VIIRS sees far more hotspots
    assert abs(math.log(harm_ratio)) < abs(math.log(raw_ratio))  # harmonized is much closer to 1


def test_point_radius_and_polygon_areas(client):
    for area in [{"type": "point", "lat": 31, "lon": -98, "radius_km": 50},
                 {"type": "polygon", "coordinates": [[[-100, 30], [-96, 30], [-98, 33],
                                                      [-100, 30]]]}]:
        r = client.post("/api/summary", json={**TEXAS_2011, "area": area})
        assert r.status_code == 200, r.text
        assert r.json()["cells"] > 0


@pytest.mark.parametrize("body,needle", [
    ({**TEXAS_2011, "area": {"type": "bbox", "bbox": [0, 40, 10, 50]}}, "outside"),
    ({**TEXAS_2011, "mode": "nope"}, "mode"),
    ({**TEXAS_2011, "mode": "viirs_raw", "metric": "frp"}, "harmonized"),
    ({**TEXAS_2011, "start": "2012-01-01", "end": "2011-01-01"}, "start date"),
    ({k: v for k, v in TEXAS_2011.items() if k != "area"}, "area"),
    ({**TEXAS_2011, "area": {"type": "bbox", "bbox": [-96, 30, -100, 33]}}, "west"),
])
def test_errors_are_plain_400s(client, body, needle):
    r = client.post("/api/summary", json=body)
    assert r.status_code == 400
    assert needle in r.json()["error"]


def test_series_csv_columns(client):
    r = client.post("/api/export/series.csv", json=TEXAS_2011)
    assert r.status_code == 200
    df = pd.read_csv(io.StringIO(r.text))
    assert list(df.columns) == ["date", "value", "median", "mean", "std", "z", "pct_of_median",
                                "source_sensor", "provisional_flag", "missing_flag"]
    assert len(df) == 365


def test_hotspots_csv_columns_and_weights_add_up(client):
    body = {**TEXAS_2011, "start": "2011-03-01", "end": "2011-03-31"}
    r = client.post("/api/export/hotspots.csv", json=body)
    assert r.status_code == 200
    df = pd.read_csv(io.StringIO(r.text), comment="#")
    assert list(df.columns) == ["lat", "lon", "datetime_utc", "satellite", "sensor", "frp",
                                "confidence", "daynight", "provisional", "weight"]
    assert len(df) > 0
    total = client.post("/api/summary", json=body).json()["key_figures"]["total_hotspots"]
    assert df["weight"].sum() == pytest.approx(total, abs=max(2, 0.01 * total))


def test_hotspots_csv_cap(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "HOTSPOT_ROW_CAP", 10)
    r = client.post("/api/export/hotspots.csv", json=TEXAS_2011)
    lines = r.text.strip().split("\n")
    assert len(lines) == 12 and lines[-1].startswith("# Only the first 10")


def test_texas_size_area_is_fast(client):
    """Every endpoint under 2 s for a Texas-size area, on the first (uncached) request."""
    client.get("/api/regions")   # data loading happens once at startup, not per request
    area = {"type": "bbox", "bbox": [-106.9, 25.1, -93.1, 36.9]}
    for path in ["/api/summary", "/api/calendar", "/api/patterns", "/api/current",
                 "/api/timeseries", "/api/export/series.csv"]:
        t = time.perf_counter()
        r = client.post(path, json={**TEXAS_2011, "area": area})
        dt = time.perf_counter() - t
        assert r.status_code == 200, r.text
        assert dt < 2.0, f"{path} took {dt:.2f} s"
