"""Tests for pipeline/grid.py (totals, missing mask) and pipeline/build_app_data.py (contract)."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline import build_app_data, grid
from pipeline.ingest import SCHEMA

DAYS = [date(2012, 2, 1) + timedelta(days=i) for i in range(10)]
MISSING_DAY, QUIET_DAY = DAYS[4], DAYS[5]
MODIS_ERA_DAY = date(2011, 12, 1)

# docs/CONTRACTS.md section 2, column -> arrow type
CONTRACT = {
    "cells_daily": {"region": pa.string(), "cell_id": pa.int32(), "lat": pa.float32(),
                    "lon": pa.float32(), "date": pa.date32(), "mec": pa.float32(),
                    "mefrp": pa.float32(), "modis_n": pa.float32(), "viirs_n": pa.float32(),
                    "source": pa.string(), "provisional": pa.bool_()},
    "missing_days": {"region": pa.string(), "date": pa.date32(), "scope": pa.string()},
    "hotspots": {"region": pa.string(), "lat": pa.float64(), "lon": pa.float64(),
                 "datetime_utc": pa.timestamp("us"), "date": pa.date32(), "satellite": pa.string(),
                 "sensor": pa.string(), "frp": pa.float32(), "confidence_class": pa.string(),
                 "daynight": pa.string(), "provisional": pa.bool_(), "weight": pa.float32()},
}


def _points(day, satellite, n):
    sensor = "MODIS" if satellite in ("Terra", "Aqua") else "VIIRS"
    return [{"region": "texas", "sensor": sensor, "satellite": satellite,
             "datetime_utc": datetime(day.year, day.month, day.day, 19, 30, tzinfo=timezone.utc),
             "acq_date": day, "lat": 30.0 + 0.1 * (i % 5), "lon": -100.0 - 0.3 * (i % 3),
             "frp": 10.0 + i, "confidence_class": "low" if i % 4 == 0 else "nominal",
             "confidence_raw": "n", "daynight": "D", "is_provisional": False} for i in range(n)]


def _day_counts(day):
    if day == MISSING_DAY:
        return {"Terra": 0, "Aqua": 20, "S-NPP": 80}   # Terra had no data: others say ~18 expected
    if day == QUIET_DAY:
        return {"Terra": 0, "Aqua": 2, "S-NPP": 8}     # a real quiet day: Terra 0 is plausible
    return {"Terra": 20, "Aqua": 20, "S-NPP": 80}


@pytest.fixture
def processed(tmp_path):
    rows = _points(MODIS_ERA_DAY, "Terra", 6) + _points(MODIS_ERA_DAY, "Aqua", 4)
    for d in DAYS:
        for sat, n in _day_counts(d).items():
            rows += _points(d, sat, n)
    df = pd.DataFrame(rows)
    for sensor in ("MODIS", "VIIRS"):
        part = df[df["sensor"] == sensor]
        pq.write_table(pa.Table.from_pandas(part, schema=SCHEMA, preserve_index=False),
                       tmp_path / f"fires_texas_{sensor.lower()}.parquet")
    grid.grid_region("texas", processed=tmp_path, missing_csv=tmp_path / "none.csv")
    return tmp_path


# ---------------------------------------------------------------- grid.py

def test_grid_totals_equal_row_counts(processed):
    totals = grid.check_totals("texas", processed)
    assert totals["rows"] == totals["daily_grid"] == totals["monthly_grid"] == totals["daily_sat"]


def test_daily_cell_id_matches_contract(processed):
    g = pd.read_parquet(processed / "grid_daily_texas.parquet")
    expected = ((g["lat"] + 90) * 10).round().astype(int) * 3600 + ((g["lon"] + 180) * 10).round().astype(int)
    assert (g["cell_id"] == expected).all()
    assert (g["n_det_nonlow"] <= g["n_det"]).all()


def test_missing_day_is_nan_not_zero(processed):
    m = pd.read_parquet(processed / "daily_sat_texas.parquet").set_index(["date", "satellite"])
    assert m.loc[(MISSING_DAY, "Terra"), "missing"]
    assert pd.isna(m.loc[(MISSING_DAY, "Terra"), "n_det"])


def test_quiet_day_is_zero_not_missing(processed):
    m = pd.read_parquet(processed / "daily_sat_texas.parquet").set_index(["date", "satellite"])
    assert not m.loc[(QUIET_DAY, "Terra"), "missing"]
    assert m.loc[(QUIET_DAY, "Terra"), "n_det"] == 0


def test_satellite_not_counted_before_it_launched(processed):
    m = pd.read_parquet(processed / "daily_sat_texas.parquet")
    assert m.loc[m["satellite"] == "S-NPP", "date"].min() >= date(2012, 1, 20)


# ---------------------------------------------------------------- build_app_data.py

@pytest.fixture
def app(processed):
    out = processed / "app"
    ratio = build_app_data.build(["texas"], processed=processed, app_dir=out)
    return out, ratio


def test_app_files_match_contract_schema(app):
    out, _ = app
    for name, cols in CONTRACT.items():
        schema = pq.read_schema(out / f"{name}.parquet")
        assert dict(zip(schema.names, schema.types)) == cols, name
    cov = (out / "coverage.json").read_text()
    for key in ("start", "archive_end", "nrt_end", "live_end", "bbox"):
        assert key in cov


def test_placeholder_harmonization(app):
    out, ratio = app
    # S-NPP / (Terra + Aqua) on days all three had data (8 normal days + the quiet day;
    # the day Terra was missing is excluded): (8 x 80 + 8) / (8 x 40 + 2)
    expected = (8 * 80 + 8) / (8 * 40 + 2)
    assert ratio["count"] == pytest.approx(expected)
    cells = pd.read_parquet(out / "cells_daily.parquet")
    modis_era = cells[cells["date"] < date(2012, 1, 20)]
    assert (modis_era["source"] == "MODIS").all() and (modis_era["mec"] == modis_era["modis_n"]).all()
    viirs_era = cells[cells["date"] >= date(2012, 1, 20)]
    assert (viirs_era["source"] == "VIIRS").all()
    assert viirs_era["mec"].to_numpy() == pytest.approx((viirs_era["viirs_n"] / expected).to_numpy(), rel=1e-5)


def test_hotspot_weights_add_up_to_mec(app):
    out, _ = app
    hot = pd.read_parquet(out / "hotspots.parquet")
    cells = pd.read_parquet(out / "cells_daily.parquet")
    assert hot["weight"].sum() == pytest.approx(cells["mec"].sum(), rel=1e-5)


def test_missing_days_scopes(app):
    out, _ = app
    miss = pd.read_parquet(out / "missing_days.parquet")
    assert set(miss.loc[miss["date"] == MISSING_DAY, "scope"]) == {"modis_only"}  # VIIRS had data
    assert QUIET_DAY not in set(miss["date"])


# ---------------------------------------------------------------- real data, when built

REAL_APP = Path("data/app")
REAL_GRIDS = sorted(Path("data/processed").glob("grid_daily_*.parquet"))


@pytest.mark.skipif(not (REAL_APP / "cells_daily.parquet").exists(), reason="run python -m pipeline.build_app_data")
@pytest.mark.parametrize("name", list(CONTRACT))
def test_real_app_data_matches_contract(name):
    schema = pq.read_schema(REAL_APP / f"{name}.parquet")
    assert dict(zip(schema.names, schema.types)) == CONTRACT[name]


@pytest.mark.skipif(not REAL_GRIDS, reason="run python -m pipeline.grid")
@pytest.mark.parametrize("region", [p.stem.removeprefix("grid_daily_") for p in REAL_GRIDS])
def test_real_grid_totals_equal_row_counts(region):
    totals = grid.check_totals(region)
    assert len(set(totals.values())) == 1, totals
