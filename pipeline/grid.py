"""Grid the clean hotspots and build the missing-data mask.

Inputs : data/processed/fires_<region>_<modis|viirs>.parquet   (from pipeline.ingest)
Outputs (all in data/processed/):
  grid_daily_<region>.parquet    0.1 deg cells x day   x satellite x day/night  (app grid)
  grid_monthly_<region>.parquet  0.25 deg cells x month x satellite x day/night (calibration grid)
  daily_sat_<region>.parquet     region-wide detections per satellite per day; n_det is NaN
                                 (never 0) on days that satellite had no data (missing-data mask)

Each grid row has n_det, n_det_nonlow (excluding low confidence, for the sensitivity run),
frp_sum, frp_mean and provisional (any NRT detection in the row). Grids are sparse: only
cell-periods with at least one detection are stored.

0.1 deg cell_id follows docs/CONTRACTS.md: round((lat+90)*10)*3600 + round((lon+180)*10),
i.e. cells are centred on multiples of 0.1 deg. 0.25 deg cells use floor, centred on x.125/x.375/...

Missing-data mask (CLAUDE.md 3.2): if data/raw/missing_dates.csv exists it is used. Otherwise
a satellite-day is flagged missing when, within the satellite's operating period, it has ZERO
detections region-wide although EVERY other operating satellite predicts at least
MIN_EXPECTED (= 10) detections for it that day (its count x the long-run ratio between them).
Days when every satellite is down cannot be detected this way; noted in CLAUDE.md.

Run from the repo root:  python -m pipeline.grid  [--region texas]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from pipeline.ingest import REGIONS

PROCESSED = Path("data/processed")
MISSING_CSV = Path("data/raw/missing_dates.csv")
MIN_EXPECTED = 10   # a zero is "missing" if the other satellites predict >= this many detections
DUCKDB_MEMORY = "6GB"

# Operating periods (first day a satellite can contribute). End = last date in our data.
SATELLITE_START = {"Terra": "2000-11-01", "Aqua": "2002-07-04", "S-NPP": "2012-01-20",
                   "NOAA-20": "2018-04-01", "NOAA-21": "2024-01-17"}


def _sql_path(p: Path) -> str:
    return p.as_posix().replace("'", "''")


def fires_glob(region: str, processed: Path = PROCESSED) -> str:
    files = sorted(processed.glob(f"fires_{region}_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No ingested files for {region}; run python -m pipeline.ingest")
    return "[" + ", ".join(f"'{_sql_path(f)}'" for f in files) + "]"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{DUCKDB_MEMORY}'")
    con.execute("SET TimeZone = 'UTC'")  # timestamps are UTC; never use the laptop's zone
    return con


# ---------------------------------------------------------------- grids

AGGREGATES = """
    count(*)::INTEGER                                   AS n_det,
    count(*) FILTER (WHERE confidence_class <> 'low')::INTEGER AS n_det_nonlow,
    sum(frp)::DOUBLE                                    AS frp_sum,
    avg(frp)::DOUBLE                                    AS frp_mean,
    bool_or(is_provisional)                             AS provisional
"""


def daily_grid_sql(files: str) -> str:
    """0.1 deg x day, cell ids exactly as in docs/CONTRACTS.md section 2."""
    return f"""
    WITH f AS (
        SELECT *, round((lat + 90) * 10)::INTEGER AS r, round((lon + 180) * 10)::INTEGER AS c
        FROM read_parquet({files}))
    SELECT region, (r * 3600 + c)::INTEGER AS cell_id,
           (r / 10.0 - 90)::FLOAT AS lat, (c / 10.0 - 180)::FLOAT AS lon,
           acq_date AS date, satellite, sensor, daynight, {AGGREGATES}
    FROM f GROUP BY region, r, c, acq_date, satellite, sensor, daynight
    ORDER BY date, cell_id, satellite, daynight"""


def monthly_grid_sql(files: str) -> str:
    """0.25 deg x calendar month (calibration grid, CLAUDE.md 4.1)."""
    return f"""
    WITH f AS (
        SELECT *, floor((lat + 90) / 0.25)::INTEGER AS r, floor((lon + 180) / 0.25)::INTEGER AS c
        FROM read_parquet({files}))
    SELECT region, (r * 1440 + c)::INTEGER AS cell_id,
           (r * 0.25 - 90 + 0.125)::FLOAT AS lat, (c * 0.25 - 180 + 0.125)::FLOAT AS lon,
           date_trunc('month', acq_date)::DATE AS month, satellite, sensor, daynight, {AGGREGATES}
    FROM f GROUP BY region, r, c, month, satellite, sensor, daynight
    ORDER BY month, cell_id, satellite, daynight"""


def write_query(con, sql: str, out: Path) -> int:
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"COPY ({sql}) TO '{_sql_path(tmp)}' (FORMAT parquet, COMPRESSION zstd)")
    tmp.replace(out)
    return con.execute(f"SELECT count(*) FROM read_parquet('{_sql_path(out)}')").fetchone()[0]


# ---------------------------------------------------------------- missing-data mask

def daily_counts(con, files: str) -> pd.DataFrame:
    """Region-wide detections per satellite per day (only days with >= 1 detection)."""
    return con.execute(f"""
        SELECT region, acq_date AS date, satellite, count(*) AS n
        FROM read_parquet({files}) GROUP BY ALL""").df()


def complete_days(counts: pd.DataFrame) -> pd.DataFrame:
    """One row per satellite per day of its operating period, 0 where nothing was detected."""
    counts = counts.assign(date=pd.to_datetime(counts["date"]))
    end = counts["date"].max()
    frames = []
    for sat, grp in counts.groupby("satellite"):
        start = max(pd.Timestamp(SATELLITE_START.get(sat, grp["date"].min())), grp["date"].min())
        days = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
        frames.append(days.merge(grp[["date", "n"]], on="date", how="left")
                      .fillna({"n": 0}).assign(satellite=sat))
    out = pd.concat(frames, ignore_index=True)
    out["region"] = counts["region"].iloc[0]
    return out


def expected_from_others(wide: pd.DataFrame, sat: str) -> pd.Series:
    """Detections we'd expect from `sat` each day, predicted from every other satellite.

    For each other satellite: its count that day x (long-run ratio sat/other over days both
    were operating). We keep the SMALLEST prediction across the operating satellites, so a day
    is only flagged when every other satellite agrees it should have been busy (conservative).
    """
    preds = []
    for other in wide.columns.drop(sat):
        both = wide[sat].notna() & wide[other].notna()
        total_other = wide.loc[both, other].sum()
        if total_other > 0:
            preds.append(wide[other] * (wide.loc[both, sat].sum() / total_other))
    if not preds:
        return pd.Series(0.0, index=wide.index)
    return pd.concat(preds, axis=1).min(axis=1).fillna(0.0)  # min skips non-operating (NaN)


def infer_missing(days: pd.DataFrame) -> np.ndarray:
    """True where a satellite saw nothing although the others predict >= MIN_EXPECTED detections.

    Under a Poisson model the chance of a real zero with 10 expected is ~0.005%, so such a
    zero almost certainly means 'no data', not 'no fire'.
    """
    wide = days.pivot(index="date", columns="satellite", values="n")  # NaN = not operating
    flags = {sat: (wide[sat] == 0) & (expected_from_others(wide, sat) >= MIN_EXPECTED)
             for sat in wide.columns}
    flag_long = (pd.DataFrame(flags).rename_axis(index="date", columns="satellite")
                 .stack().rename("missing").reset_index())
    merged = days.merge(flag_long, on=["date", "satellite"], how="left")
    return merged["missing"].fillna(False).astype(bool).to_numpy()


def missing_from_csv(days: pd.DataFrame, path: Path) -> np.ndarray:
    """Use the official FIRMS missing-dates file when present (columns: date, satellite)."""
    official = pd.read_csv(path, parse_dates=["date"])
    key = set(zip(official["date"].dt.normalize(), official["satellite"]))
    return np.array([(d, s) in key for d, s in zip(days["date"], days["satellite"])], dtype=bool)


def missing_mask(con, files: str, missing_csv: Path = MISSING_CSV) -> pd.DataFrame:
    days = complete_days(daily_counts(con, files))
    days["missing"] = missing_from_csv(days, missing_csv) if missing_csv.exists() else infer_missing(days)
    days["n_det"] = days["n"].where(~days["missing"], np.nan)   # missing -> NaN, never 0
    days["date"] = days["date"].dt.date
    return days[["region", "date", "satellite", "n_det", "missing"]]


# ---------------------------------------------------------------- driver

def grid_region(region: str, processed: Path = PROCESSED, missing_csv: Path = MISSING_CSV) -> dict:
    con = connect()
    files = fires_glob(region, processed)
    out = {
        "daily_rows": write_query(con, daily_grid_sql(files), processed / f"grid_daily_{region}.parquet"),
        "monthly_rows": write_query(con, monthly_grid_sql(files), processed / f"grid_monthly_{region}.parquet"),
    }
    mask = missing_mask(con, files, missing_csv)
    mask.to_parquet(processed / f"daily_sat_{region}.parquet", index=False)
    out["missing_days_by_satellite"] = mask[mask["missing"]].groupby("satellite").size().to_dict()
    out["mask_source"] = str(missing_csv) if missing_csv.exists() else "inferred"
    return out


def check_totals(region: str, processed: Path = PROCESSED) -> dict:
    """Detections in = detections out, for both grids and the daily mask."""
    con = connect()

    def q(sql):
        return con.execute(sql).fetchone()[0]

    def p(name):
        return f"read_parquet('{_sql_path(processed / name)}')"

    return {
        "rows": q(f"SELECT count(*) FROM read_parquet({fires_glob(region, processed)})"),
        "daily_grid": q(f"SELECT sum(n_det) FROM {p(f'grid_daily_{region}.parquet')}"),
        "monthly_grid": q(f"SELECT sum(n_det) FROM {p(f'grid_monthly_{region}.parquet')}"),
        "daily_sat": int(q(f"SELECT sum(n_det) FROM {p(f'daily_sat_{region}.parquet')}")),
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Grid hotspots + missing-data mask")
    ap.add_argument("--region", choices=REGIONS, action="append")
    args = ap.parse_args(argv)
    for region in args.region or REGIONS:
        print(f"\n=== {region} ===", flush=True)
        for k, v in grid_region(region).items():
            print(f"{k}: {v}")
        totals = check_totals(region)
        print("totals:", totals, "OK" if len(set(totals.values())) == 1 else "MISMATCH")


if __name__ == "__main__":
    main()
