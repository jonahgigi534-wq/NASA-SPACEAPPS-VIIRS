"""Build the app data in data/app/ exactly per docs/CONTRACTS.md section 2.

Harmonization (CLAUDE.md 4.4) = the winning method in results/metrics.json, fitted by
pipeline.harmonize and validated by pipeline.validate.

  * before 2012-01-20 (MODIS era): mec = modis_n = Terra + Aqua count. Each MODIS point weighs 1.
  * from 2012-01-20 (VIIRS era): every VIIRS detection gets a weight = how many MODIS-scale
    hotspots it stands for. For each satellite x day/night x 0.25 deg cell x month:
        v_eff  = VIIRS count scaled to a full month (count x days in month / days with data),
                 because the fitted curve is defined on whole months
        aqua   = winning model(v_eff)            (Aqua-equivalent count, per land-cover group)
        factor = aqua / v_eff x (Terra+Aqua)/Aqua factor (region, day/night, calendar month)
    De-duplication: on a day when k VIIRS satellites had data (S-NPP, NOAA-20, NOAA-21), each
    detection's weight is factor / k, i.e. the harmonized value is the AVERAGE of what each
    satellite says, so overlapping satellites are never double-counted.
    MODIS points in the VIIRS era weigh 0 (they still count in modis_n for the comparison mode).
  * mec of a 0.1 deg cell-day = sum of its points' weights (so hotspot weights add up to mec).
  * viirs_n = raw VIIRS count averaged over the k satellites (same de-duplication, no scaling).
  * mefrp: MODIS FRP before 2012-01-20; after, VIIRS FRP x one global (Terra+Aqua)/S-NPP FRP
    ratio / k. (FRP is secondary and not separately validated.)
  * provisional: the cell-day includes NRT detections from the sensor in use.

missing_days scopes (from data/processed/daily_sat_<region>.parquet):
  modis_only  any operating MODIS satellite had no data that day (Terra+Aqua sum would be low)
  viirs_raw   VIIRS era and no VIIRS satellite had data that day
  harmonized  modis_only days before 2012-01-20 + viirs_raw days

Run from the repo root:  python -m pipeline.build_app_data [--region texas ...]   (default: all)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

import duckdb
import numpy as np
import pandas as pd

from pipeline import harmonize as hz
from pipeline.ingest import REGIONS

PROCESSED = Path("data/processed")
APP_DIR = Path("data/app")
REGIONS_DIR = Path("data/regions")
METRICS = Path("results/metrics.json")
VIIRS_START = "2012-01-20"
VIIRS_SATS = ("S-NPP", "NOAA-20", "NOAA-21")
MODIS_SATS = ("Terra", "Aqua")
GEOJSON_REGION = {"texas": "texas", "amazon_arc": "amazon", "north_australia": "australia"}

FactorFn = Callable[[pd.DataFrame], np.ndarray]


def _p(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _in(names) -> str:
    return "(" + ", ".join(f"'{n}'" for n in names) + ")"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET memory_limit = '6GB'")
    # ~40 M hotspot rows are sorted when written: let DuckDB spill to disk instead of failing
    con.execute(f"SET temp_directory = '{_p(PROCESSED / 'duckdb_tmp')}'")
    con.execute("SET preserve_insertion_order = false")
    return con


# ---------------------------------------------------------------- per cell-month VIIRS factors

def viirs_cell_months(con, fires: str, mask: str) -> pd.DataFrame:
    """VIIRS counts per satellite x day/night x 0.25 deg cell x month, scaled to a full month."""
    return con.execute(f"""
        WITH v AS (
            SELECT region, satellite, daynight,
                (floor((lat + 90) / 0.25)::INTEGER * 1440 + floor((lon + 180) / 0.25)::INTEGER) AS cell_id,
                date_trunc('month', acq_date)::DATE AS month, count(*) AS v
            FROM read_parquet({fires}) WHERE sensor = 'VIIRS' AND acq_date >= DATE '{VIIRS_START}'
            GROUP BY ALL),
        ok AS (
            SELECT satellite, date_trunc('month', date)::DATE AS month, count(*) AS valid_days
            FROM read_parquet('{mask}') WHERE NOT missing GROUP BY ALL)
        SELECT v.*, ok.valid_days,
               day(last_day(v.month)) AS days_in_month,
               v.v * day(last_day(v.month)) / greatest(ok.valid_days, 1) AS v_eff
        FROM v LEFT JOIN ok USING (satellite, month)""").df()


def winner_factor_fn(method: str, models: dict) -> FactorFn:
    """factor per VIIRS detection = model(v_eff) / v_eff x (Terra+Aqua)/Aqua."""
    def fn(cm: pd.DataFrame) -> np.ndarray:
        rows = hz.attach_landcover(cm.assign(month=pd.to_datetime(cm["month"])))
        aqua = hz.predict(method, models["all"], rows, "v_eff")
        tf = hz.terra_factor(models, rows["region"], rows["daynight"], pd.to_datetime(rows["month"]).dt.month)
        return np.where(rows["v_eff"] > 0, aqua / rows["v_eff"].clip(lower=1e-9) * tf, 0.0)
    return fn


def load_winner() -> tuple[FactorFn, float, str]:
    if not METRICS.exists():
        raise FileNotFoundError("Run python -m pipeline.harmonize and python -m pipeline.validate first")
    method = json.loads(METRICS.read_text())["winner"]
    models = hz.load_models()
    return winner_factor_fn(method, models), models["frp_ratio_modis_per_snpp"], method


# ---------------------------------------------------------------- points -> hotspots + cells

def viirs_k_sql(mask: str) -> str:
    """Number of VIIRS satellites with data, per region x day (the de-duplication divisor)."""
    return f"""SELECT region, date, count(*) AS k FROM read_parquet('{mask}')
               WHERE satellite IN {_in(VIIRS_SATS)} AND NOT missing GROUP BY region, date"""


def points_sql(fires: str, mask: str, frp_ratio: float) -> str:
    k = "greatest(coalesce(k.k, 1), 1)"
    return f"""
    SELECT f.region, f.lat, f.lon, f.datetime_utc::TIMESTAMP AS datetime_utc, f.acq_date AS date,
        f.satellite, f.sensor, f.frp, f.confidence_class, f.daynight, f.is_provisional AS provisional,
        (CASE WHEN f.sensor = 'MODIS' AND f.acq_date < DATE '{VIIRS_START}' THEN 1.0
              WHEN f.sensor = 'VIIRS' THEN coalesce(w.factor, 0) / {k} ELSE 0.0 END)::FLOAT AS weight,
        (CASE WHEN f.sensor = 'MODIS' AND f.acq_date < DATE '{VIIRS_START}' THEN f.frp
              WHEN f.sensor = 'VIIRS' THEN f.frp * {frp_ratio} / {k} ELSE 0.0 END)::DOUBLE AS frp_w,
        (CASE WHEN f.sensor = 'VIIRS' THEN 1.0 / {k} ELSE 0.0 END)::DOUBLE AS viirs_w
    FROM read_parquet({fires}) f
    LEFT JOIN ({viirs_k_sql(mask)}) k ON k.region = f.region AND k.date = f.acq_date
    LEFT JOIN weights w ON w.region = f.region AND w.satellite = f.satellite AND w.daynight = f.daynight
         AND w.month = date_trunc('month', f.acq_date)::DATE
         AND w.cell_id = floor((f.lat + 90) / 0.25)::INTEGER * 1440 + floor((f.lon + 180) / 0.25)::INTEGER"""


HOTSPOT_COLS = ("region, lat, lon, datetime_utc, date, satellite, sensor, frp, confidence_class, "
                "daynight, provisional, weight")


def cells_sql(points: str) -> str:
    return f"""
    WITH p AS (SELECT *, round((lat + 90) * 10)::INTEGER AS r, round((lon + 180) * 10)::INTEGER AS c,
                      CASE WHEN date >= DATE '{VIIRS_START}' THEN 'VIIRS' ELSE 'MODIS' END AS src
               FROM read_parquet('{points}'))
    SELECT region, (r * 3600 + c)::INTEGER AS cell_id, (r / 10.0 - 90)::FLOAT AS lat,
        (c / 10.0 - 180)::FLOAT AS lon, date,
        sum(weight)::FLOAT AS mec, sum(frp_w)::FLOAT AS mefrp,
        (count(*) FILTER (WHERE sensor = 'MODIS'))::FLOAT AS modis_n,
        sum(viirs_w)::FLOAT AS viirs_n, any_value(src) AS source,
        coalesce(bool_or(provisional) FILTER (WHERE sensor = src), false) AS provisional
    FROM p GROUP BY region, r, c, date ORDER BY region, date, cell_id"""


def missing_sql(mask: str) -> str:
    return f"""
    WITH modis AS (
        SELECT DISTINCT region, date FROM read_parquet('{mask}')
        WHERE satellite IN {_in(MODIS_SATS)} AND missing),
    viirs AS (  -- VIIRS-era days with no VIIRS satellite reporting
        SELECT region, date FROM read_parquet('{mask}')
        WHERE satellite IN {_in(VIIRS_SATS)} AND date >= DATE '{VIIRS_START}'
        GROUP BY region, date HAVING bool_and(missing))
    SELECT region, date, 'modis_only' AS scope FROM modis
    UNION ALL SELECT region, date, 'viirs_raw' FROM viirs
    UNION ALL SELECT region, date, 'harmonized' FROM modis WHERE date < DATE '{VIIRS_START}'
    UNION ALL SELECT region, date, 'harmonized' FROM viirs
    ORDER BY region, date, scope"""


def copy(con, sql: str, out: Path) -> None:
    tmp = out.with_suffix(out.suffix + ".tmp")
    con.execute(f"COPY ({sql}) TO '{_p(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
    tmp.replace(out)


# ---------------------------------------------------------------- coverage.json

def region_bboxes(regions_dir: Path = REGIONS_DIR) -> dict:
    out = {}
    for gj in regions_dir.glob("*.geojson"):
        feat = json.loads(gj.read_text())["features"][0]
        ring = feat["geometry"]["coordinates"][0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        out[GEOJSON_REGION.get(feat["properties"]["name"], feat["properties"]["name"])] = \
            [min(xs), min(ys), max(xs), max(ys)]
    return out


def coverage_entry(con, fires: str, bbox: list) -> dict:
    start, archive_end, nrt_end = con.execute(f"""
        SELECT min(acq_date), max(acq_date) FILTER (WHERE sensor = 'VIIRS' AND NOT is_provisional),
               max(acq_date) FROM read_parquet({fires})""").fetchone()
    # live_end = nrt_end here; Track B's pipeline/live.py extends it via live_coverage.json.
    return {"start": str(start), "archive_end": str(archive_end), "nrt_end": str(nrt_end),
            "live_end": str(nrt_end), "bbox": bbox}


def write_coverage(entries: dict, app_dir: Path) -> None:
    path = app_dir / "coverage.json"
    cov = json.loads(path.read_text()) if path.exists() else {}
    cov.update(entries)
    path.write_text(json.dumps(cov, indent=1))


# ---------------------------------------------------------------- driver

def fires_list(region: str, processed: Path) -> str:
    return "[" + ", ".join(f"'{_p(f)}'" for f in sorted(processed.glob(f"fires_{region}_*.parquet"))) + "]"


def build_region_points(con, region: str, processed: Path, factor_fn: FactorFn, frp_ratio: float) -> Path:
    fires, mask = fires_list(region, processed), _p(processed / f"daily_sat_{region}.parquet")
    cm = viirs_cell_months(con, fires, mask)
    weights = cm[["region", "satellite", "daynight", "cell_id", "month"]].assign(factor=factor_fn(cm))
    con.register("weights", weights)
    out = processed / f"points_{region}.parquet"
    copy(con, points_sql(fires, mask, frp_ratio), out)
    con.unregister("weights")
    return out


def build(regions, processed: Path = PROCESSED, app_dir: Path = APP_DIR,
          factor_fn: FactorFn | None = None, frp_ratio: float | None = None) -> str:
    """Write all four app files for `regions`. Returns the harmonization method used."""
    method = "custom"
    if factor_fn is None:
        factor_fn, frp_ratio, method = load_winner()
    con = connect()
    app_dir.mkdir(parents=True, exist_ok=True)
    bboxes, coverage, points, masks = region_bboxes(), {}, [], []
    for region in regions:
        points.append(build_region_points(con, region, processed, factor_fn, frp_ratio))
        masks.append(_p(processed / f"daily_sat_{region}.parquet"))
        coverage[region] = coverage_entry(con, fires_list(region, processed), bboxes[region])
    union = " UNION ALL ".join
    copy(con, union(f"(SELECT {HOTSPOT_COLS} FROM read_parquet('{_p(p)}'))" for p in points)
         + " ORDER BY region, datetime_utc", app_dir / "hotspots.parquet")
    copy(con, union(f"({cells_sql(_p(p))})" for p in points), app_dir / "cells_daily.parquet")
    copy(con, union(f"({missing_sql(m)})" for m in masks), app_dir / "missing_days.parquet")
    write_coverage(coverage, app_dir)
    return method


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Build data/app/ (CONTRACTS.md section 2)")
    ap.add_argument("--region", choices=REGIONS, action="append", help="default: all regions")
    args = ap.parse_args(argv)
    method = build(args.region or list(REGIONS))
    print(f"harmonization: {method}")
    for f in sorted(APP_DIR.iterdir()):
        print(f"{f.name:28s} {f.stat().st_size / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
