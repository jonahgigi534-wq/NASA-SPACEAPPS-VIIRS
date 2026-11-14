"""Build the app data in data/app/ exactly per docs/CONTRACTS.md section 2.

FIRST VERSION (Track A2): Texas by default, PLACEHOLDER harmonization. A3/A4 replace the
placeholder with the winning method from results/metrics.json.

Placeholder harmonization
  * before 2012-01-20 (MODIS era):  mec = modis_n            (Terra + Aqua count)
  * from 2012-01-20  (VIIRS era):   mec = viirs_n / RATIO
      viirs_n = mean count over the VIIRS satellites that had data that day (S-NPP, NOAA-20, ...),
                so overlapping satellites are not double-counted (de-duplication rule)
      RATIO   = ONE global ratio = S-NPP detections / (Terra + Aqua) detections, all regions
                with ingested data, 2012-01-20..2018-12-31, days all three had data. Terra+Aqua
                (not Aqua alone) because modis_n, and so mec before 2012, is Terra+Aqua.
  * mefrp follows the same rule with the FRP ratio (S-NPP FRP sum / Terra+Aqua FRP sum).
  * hotspot weight = how much the point adds to mec: 1 for MODIS-era MODIS points,
    1 / (RATIO x number of VIIRS satellites with data that day) for VIIRS points, 0 otherwise.
    So the weights in a cell-day add up to its mec exactly.

missing_days scopes (from data/processed/daily_sat_<region>.parquet):
  modis_only  any operating MODIS satellite had no data that day (Terra+Aqua sum would be low)
  viirs_raw   VIIRS era and no VIIRS satellite had data that day
  harmonized  modis_only days before 2012-01-20 + viirs_raw days

Run from the repo root:  python -m pipeline.build_app_data [--region texas ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from pipeline.ingest import REGIONS

PROCESSED = Path("data/processed")
APP_DIR = Path("data/app")
REGIONS_DIR = Path("data/regions")
VIIRS_START = "2012-01-20"
RATIO_FIT = ("2012-01-20", "2018-12-31")
VIIRS_SATS = ("S-NPP", "NOAA-20", "NOAA-21")
MODIS_SATS = ("Terra", "Aqua")
GEOJSON_REGION = {"texas": "texas", "amazon_arc": "amazon", "north_australia": "australia"}


def _p(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET memory_limit = '6GB'")
    return con


def _in(names) -> str:
    return "(" + ", ".join(f"'{n}'" for n in names) + ")"


# ---------------------------------------------------------------- placeholder ratio

def global_ratios(con, processed: Path = PROCESSED) -> dict:
    """ONE S-NPP/Aqua ratio for counts and FRP, pooled over every region that has a grid."""
    grids = sorted(processed.glob("grid_daily_*.parquet"))
    masks = sorted(processed.glob("daily_sat_*.parquet"))
    if not grids or not masks:
        raise FileNotFoundError("Run python -m pipeline.grid first")
    g = "[" + ", ".join(f"'{_p(f)}'" for f in grids) + "]"
    m = "[" + ", ".join(f"'{_p(f)}'" for f in masks) + "]"
    n_snpp, n_modis, f_snpp, f_modis = con.execute(f"""
        WITH ok AS (  -- days where Terra, Aqua AND S-NPP all had data
            SELECT region, date FROM read_parquet({m})
            WHERE satellite IN ('Terra', 'Aqua', 'S-NPP') AND NOT missing
              AND date BETWEEN '{RATIO_FIT[0]}' AND '{RATIO_FIT[1]}'
            GROUP BY region, date HAVING count(*) = 3)
        SELECT sum(n_det) FILTER (WHERE satellite = 'S-NPP'), sum(n_det) FILTER (WHERE sensor = 'MODIS'),
               sum(frp_sum) FILTER (WHERE satellite = 'S-NPP'), sum(frp_sum) FILTER (WHERE sensor = 'MODIS')
        FROM read_parquet({g}) JOIN ok USING (region, date)""").fetchone()
    return {"count": n_snpp / n_modis, "frp": f_snpp / f_modis,
            "regions": sorted(f.stem.removeprefix("grid_daily_") for f in grids), "fit": RATIO_FIT}


# ---------------------------------------------------------------- the three parquet files

def viirs_k_sql(mask: str) -> str:
    """Number of VIIRS satellites with data, per region x day (the de-duplication divisor)."""
    return f"""SELECT region, date, count(*) AS k FROM read_parquet('{mask}')
               WHERE satellite IN {_in(VIIRS_SATS)} AND NOT missing GROUP BY region, date"""


def cells_sql(grid: str, mask: str, ratio: dict) -> str:
    return f"""
    WITH c AS (
        SELECT region, cell_id, any_value(lat) AS lat, any_value(lon) AS lon, date,
            coalesce(sum(n_det) FILTER (WHERE sensor = 'MODIS'), 0)     AS modis_n,
            coalesce(sum(n_det) FILTER (WHERE sensor = 'VIIRS'), 0)     AS viirs_sum,
            coalesce(sum(frp_sum) FILTER (WHERE sensor = 'MODIS'), 0)   AS modis_frp,
            coalesce(sum(frp_sum) FILTER (WHERE sensor = 'VIIRS'), 0)   AS viirs_frp,
            coalesce(bool_or(provisional) FILTER (WHERE sensor = 'MODIS'), false) AS modis_prov,
            coalesce(bool_or(provisional) FILTER (WHERE sensor = 'VIIRS'), false) AS viirs_prov
        FROM read_parquet('{grid}') GROUP BY region, cell_id, date),
    j AS (SELECT c.*, coalesce(k.k, 0) AS k, c.date >= DATE '{VIIRS_START}' AS viirs_era
          FROM c LEFT JOIN ({viirs_k_sql(mask)}) k USING (region, date))
    SELECT region, cell_id::INTEGER AS cell_id, lat::FLOAT AS lat, lon::FLOAT AS lon, date,
        (CASE WHEN viirs_era THEN viirs_sum / greatest(k, 1) / {ratio['count']} ELSE modis_n END)::FLOAT AS mec,
        (CASE WHEN viirs_era THEN viirs_frp / greatest(k, 1) / {ratio['frp']} ELSE modis_frp END)::FLOAT AS mefrp,
        modis_n::FLOAT AS modis_n,
        (viirs_sum / greatest(k, 1))::FLOAT AS viirs_n,
        CASE WHEN viirs_era THEN 'VIIRS' ELSE 'MODIS' END AS source,
        CASE WHEN viirs_era THEN viirs_prov ELSE modis_prov END AS provisional
    FROM j ORDER BY region, date, cell_id"""


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


def hotspots_sql(fires: str, mask: str, ratio: dict) -> str:
    return f"""
    SELECT f.region, f.lat, f.lon, f.datetime_utc::TIMESTAMP AS datetime_utc, f.acq_date AS date,
        f.satellite, f.sensor, f.frp, f.confidence_class, f.daynight,
        f.is_provisional AS provisional,
        (CASE WHEN f.sensor = 'MODIS' AND f.acq_date < DATE '{VIIRS_START}' THEN 1.0
              WHEN f.sensor = 'VIIRS' THEN 1.0 / ({ratio['count']} * greatest(coalesce(k.k, 1), 1))
              ELSE 0.0 END)::FLOAT AS weight
    FROM read_parquet({fires}) f
    LEFT JOIN ({viirs_k_sql(mask)}) k ON k.region = f.region AND k.date = f.acq_date
    ORDER BY f.region, f.datetime_utc"""


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

def build(regions, processed: Path = PROCESSED, app_dir: Path = APP_DIR) -> dict:
    con = connect()
    ratio = global_ratios(con, processed)
    app_dir.mkdir(parents=True, exist_ok=True)
    tables = {"cells_daily": [], "missing_days": [], "hotspots": []}
    bboxes, coverage = region_bboxes(), {}
    for region in regions:
        grid = _p(processed / f"grid_daily_{region}.parquet")
        mask = _p(processed / f"daily_sat_{region}.parquet")
        fires = "[" + ", ".join(f"'{_p(f)}'" for f in sorted(processed.glob(f"fires_{region}_*.parquet"))) + "]"
        tables["cells_daily"].append(cells_sql(grid, mask, ratio))
        tables["missing_days"].append(missing_sql(mask))
        tables["hotspots"].append(hotspots_sql(fires, mask, ratio))
        coverage[region] = coverage_entry(con, fires, bboxes[region])
    for name, parts in tables.items():
        copy(con, " UNION ALL ".join(f"({s})" for s in parts), app_dir / f"{name}.parquet")
    write_coverage(coverage, app_dir)
    return ratio


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Build data/app/ (CONTRACTS.md section 2)")
    ap.add_argument("--region", choices=REGIONS, action="append", help="default: texas only (A2)")
    args = ap.parse_args(argv)
    ratio = build(args.region or ["texas"])
    print(f"placeholder global ratio S-NPP/(Terra+Aqua): count {ratio['count']:.3f}, FRP {ratio['frp']:.3f} "
          f"(regions {ratio['regions']}, {ratio['fit'][0]}..{ratio['fit'][1]})")
    for f in sorted(APP_DIR.iterdir()):
        print(f"{f.name:28s} {f.stat().st_size / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
