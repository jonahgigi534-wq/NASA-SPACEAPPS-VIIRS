"""
Live FIRMS feed: fetch the most recent days of hotspots so the app can show "this month so far".

The FIRMS archive zips stop at the end of their near-real-time (NRT) data (nrt_end in
data/app/coverage.json). This script fills the gap from there to yesterday using the FIRMS
area API, for each region and each satellite feed:
    VIIRS_NOAA20_NRT, VIIRS_NOAA21_NRT, MODIS_NRT
and writes, in the same schemas as Track A's files (docs/CONTRACTS.md section 2):
    data/app/live_cells_daily.parquet
    data/app/live_hotspots.parquet
    data/app/live_missing_days.parquet
    data/app/live_coverage.json
Every live row is provisional=true. The API adds these in automatically, only for days after
the main files end, and keeps working if they're missing or the FIRMS API is down.

Run from the repo root (needs FIRMS_MAP_KEY in .env; free key at
https://firms.modaps.eosdis.nasa.gov/api/map_key):
    python -m pipeline.live
    python -m pipeline.live --region texas --max-days 30

Politeness: requests are spaced out (FIRMS allows 5,000 transactions per 10 minutes), retried
with back-off on errors, and cached in data/cache/live/ so re-running only fetches new days.

Harmonization of live data (until Track A documents its coefficients file):
    For each region we take the ratio sum(mec) / sum(viirs_n) over the last 3 years of the
    science-quality VIIRS era in cells_daily. That is exactly how much Track A's harmonization
    scales raw VIIRS counts on average, so live counts land on the same MODIS-equivalent scale.
    Same idea for FRP. If cells_daily has no VIIRS era, one global ratio of 1/3 is used.
De-duplication across VIIRS satellites (placeholder rule, same spirit as CONTRACTS viirs_n):
    per cell and day, viirs_n = the largest count from any single VIIRS satellite, so two
    satellites seeing the same fire aren't counted twice.
"""

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", REPO / "data" / "app"))
CACHE_DIR = REPO / "data" / "cache" / "live"

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCES = {                      # FIRMS source name -> (sensor, satellite)
    "VIIRS_NOAA20_NRT": ("VIIRS", "NOAA-20"),
    "VIIRS_NOAA21_NRT": ("VIIRS", "NOAA-21"),
    "MODIS_NRT": ("MODIS", None),          # Terra or Aqua, read from the 'satellite' column
}
CHUNK_DAYS = 5             # the area API allows at most 5 days per request (Nov 2026; it was 10).
                           # If FIRMS changes this again, run() reads the new limit from the error.
MAX_DAYS = 60              # never reach back further than this
SECONDS_BETWEEN_CALLS = 1.0
RETRIES = 4
FRESH_CACHE_HOURS = 1      # chunks touching the last 2 days are re-fetched after an hour
FALLBACK_VIIRS_RATIO = 3.0

# Same schemas as scripts/make_synthetic_app_data.py / docs/CONTRACTS.md section 2
CELLS_SCHEMA = pa.schema([
    ("region", pa.string()), ("cell_id", pa.int32()), ("lat", pa.float32()), ("lon", pa.float32()),
    ("date", pa.date32()), ("mec", pa.float32()), ("mefrp", pa.float32()),
    ("modis_n", pa.float32()), ("viirs_n", pa.float32()), ("source", pa.string()),
    ("provisional", pa.bool_()),
])
HOTSPOTS_SCHEMA = pa.schema([
    ("region", pa.string()), ("lat", pa.float64()), ("lon", pa.float64()),
    ("datetime_utc", pa.timestamp("us")), ("date", pa.date32()), ("satellite", pa.string()),
    ("sensor", pa.string()), ("frp", pa.float32()), ("confidence_class", pa.string()),
    ("daynight", pa.string()), ("provisional", pa.bool_()), ("weight", pa.float32()),
])
MISSING_SCHEMA = pa.schema([("region", pa.string()), ("date", pa.date32()), ("scope", pa.string())])
HOTSPOT_COLUMNS = [f.name for f in HOTSPOTS_SCHEMA]


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------------------------
# Fetching (with cache, rate limiting and retries)
# ---------------------------------------------------------------------------------------------

class FirmsError(Exception):
    pass


class DayRangeError(FirmsError):
    """FIRMS said 'Invalid day range. Expects [1..N].' -> retry with chunks of N days."""
    def __init__(self, message, max_days):
        super().__init__(message)
        self.max_days = max_days


def redact(text, key):
    return text.replace(key, "<MAP_KEY>") if key else text


def fetch_chunk(client, key, source, bbox, start, days, today):
    """CSV text for one source / box / date chunk, from cache when possible."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    w, s, e, n = bbox
    name = f"{source}_{w}_{s}_{e}_{n}_{start.isoformat()}_{days}.csv"
    path = CACHE_DIR / name
    chunk_end = start + timedelta(days=days - 1)
    if path.exists():
        recent = chunk_end >= today - timedelta(days=2)
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if not recent or age_h < FRESH_CACHE_HOURS:
            return path.read_text(encoding="utf-8")

    url = f"{API}/{key}/{source}/{w},{s},{e},{n}/{days}/{start.isoformat()}"
    wait = 5.0
    for attempt in range(1, RETRIES + 1):
        try:
            r = client.get(url, timeout=90)
            text = r.text
            if r.status_code == 200 and text.lstrip().lower().startswith("latitude"):
                path.write_text(text, encoding="utf-8")
                time.sleep(SECONDS_BETWEEN_CALLS)
                return text
            if r.status_code == 200 and not text.strip():
                path.write_text("", encoding="utf-8")       # no fires at all in this chunk
                time.sleep(SECONDS_BETWEEN_CALLS)
                return ""
            problem = f"HTTP {r.status_code}: {redact(text.strip()[:200], key)}"
            limit = re.search(r"day range.*?\[1\.\.(\d+)\]", text, re.I)
            if limit:
                raise DayRangeError(problem, int(limit.group(1)))
            if r.status_code in (400, 401, 403) or "invalid" in text.lower():
                raise FirmsError(problem)                     # bad key / request: don't retry
        except FirmsError:
            raise
        except Exception as ex:  # network hiccup
            problem = redact(str(ex), key)
        if attempt < RETRIES:
            log(f"    {source} {start}: {problem}; retrying in {wait:.0f} s")
            time.sleep(wait)
            wait *= 2
    raise FirmsError(problem)


def parse_csv(text, source):
    """FIRMS area CSV -> hotspot rows in our schema (without region/weight yet)."""
    if not text.strip():
        return pd.DataFrame(columns=["lat", "lon", "datetime_utc", "date", "satellite", "sensor",
                                     "frp", "confidence_class", "daynight"])
    df = pd.read_csv(io.StringIO(text), dtype={"acq_time": str, "confidence": str,
                                               "satellite": str})
    sensor, sat = SOURCES[source]
    hhmm = df["acq_time"].str.zfill(4)
    dt = pd.to_datetime(df["acq_date"] + " " + hhmm.str[:2] + ":" + hhmm.str[2:],
                        format="%Y-%m-%d %H:%M")
    if sensor == "MODIS":
        satellite = df["satellite"].str.strip().str.upper().str[0].map({"T": "Terra",
                                                                         "A": "Aqua"})
        conf = pd.to_numeric(df["confidence"], errors="coerce")
        conf_class = np.select([conf < 30, conf < 80], ["low", "nominal"], "high")
    else:
        satellite = sat
        conf_class = df["confidence"].str.strip().str.lower().str[0].map(
            {"l": "low", "n": "nominal", "h": "high"}).fillna("nominal")
    return pd.DataFrame({
        "lat": df["latitude"].astype(float), "lon": df["longitude"].astype(float),
        "datetime_utc": dt, "date": dt.dt.date, "satellite": satellite, "sensor": sensor,
        "frp": pd.to_numeric(df["frp"], errors="coerce").fillna(0).astype(np.float32),
        "confidence_class": conf_class, "daynight": df["daynight"].str.strip().str.upper(),
    })


# ---------------------------------------------------------------------------------------------
# Harmonizing + gridding
# ---------------------------------------------------------------------------------------------

def cell_id(lat, lon):
    """Cell id exactly as written in docs/CONTRACTS.md section 2."""
    return (np.round((np.asarray(lat) + 90) * 10).astype(np.int64) * 3600
            + np.round((np.asarray(lon) + 180) * 10).astype(np.int64)).astype(np.int32)


def harmonization_factors(data_dir):
    """{region: (count factor, frp factor)} that turn raw VIIRS into MODIS-equivalent units,
    learned from the main app data (see the module docstring)."""
    import duckdb
    cells = str(Path(data_dir) / "cells_daily.parquet").replace("\\", "/")
    hot = str(Path(data_dir) / "hotspots.parquet").replace("\\", "/")
    con = duckdb.connect()
    out = {}
    try:
        rows = con.execute(f"""
            WITH v AS (SELECT * FROM read_parquet('{cells}')
                       WHERE source = 'VIIRS' AND NOT provisional),
                 last AS (SELECT region, max(date) - INTERVAL 3 YEAR AS since FROM v GROUP BY region)
            SELECT v.region, sum(mec), sum(viirs_n), sum(mefrp)
            FROM v JOIN last USING (region) WHERE v.date >= last.since GROUP BY v.region
        """).fetchall()
        frp = dict(con.execute(f"""
            WITH h AS (SELECT * FROM read_parquet('{hot}')
                       WHERE sensor = 'VIIRS' AND NOT provisional),
                 last AS (SELECT region, max(date) - INTERVAL 3 YEAR AS since FROM h GROUP BY region)
            SELECT h.region, sum(frp) FROM h JOIN last USING (region)
            WHERE h.date >= last.since GROUP BY h.region
        """).fetchall())
    except Exception as ex:
        log(f"  (couldn't read harmonization from {data_dir}: {ex}; using 1/{FALLBACK_VIIRS_RATIO})")
        return out
    for region, mec, viirs_n, mefrp in rows:
        if viirs_n and mec:
            k_frp = (mefrp / frp[region]) if frp.get(region) else 1.0 / FALLBACK_VIIRS_RATIO
            out[region] = (mec / viirs_n, k_frp)
    return out


def static_cells(region):
    """Cells with static heat sources (gas flares, industry), if Track A saved them.
    NRT data has no 'type' column, so this is how non-fire hotspots are removed."""
    p = REPO / "data" / "processed" / "static_cells.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    return set(df.loc[df["region"] == region, "cell_id"].astype(int))


def build_region(region, points, factors, days):
    """Hotspot points of one region -> (cells_daily rows, hotspot rows, missing-day rows)."""
    k_count, k_frp = factors
    if points.empty:
        return (pd.DataFrame(columns=CELLS_SCHEMA.names), pd.DataFrame(columns=HOTSPOT_COLUMNS),
                pd.DataFrame(columns=["region", "date", "scope"]))
    p = points.copy()
    p["region"] = region
    p["cell_id"] = cell_id(p["lat"], p["lon"])
    p["provisional"] = True

    static = static_cells(region)
    if static:
        before = len(p)
        p = p[~p["cell_id"].isin(static)]
        log(f"  [{region}] removed {before - len(p)} detections on static-source cells")

    # per cell-day: MODIS count, VIIRS count = max over single satellites (de-duplication)
    keys = ["cell_id", "date"]
    modis = p[p["sensor"] == "MODIS"].groupby(keys).size().rename("modis_n")
    v = p[p["sensor"] == "VIIRS"]
    per_sat = v.groupby(keys + ["satellite"]).agg(n=("frp", "size"), frp=("frp", "sum"))
    best = per_sat.sort_values("n").groupby(level=[0, 1]).tail(1).droplevel("satellite")
    cells = pd.concat([modis, best.rename(columns={"n": "viirs_n", "frp": "viirs_frp"})],
                      axis=1).fillna(0).reset_index()
    cells["mec"] = cells["viirs_n"] * k_count
    cells["mefrp"] = cells["viirs_frp"] * k_frp
    cells["region"] = region
    cells["lat"] = (cells["cell_id"] // 3600) / 10 - 90
    cells["lon"] = (cells["cell_id"] % 3600) / 10 - 180
    cells["source"] = "VIIRS"
    cells["provisional"] = True

    # each VIIRS point carries its share of the cell-day's harmonized count
    v_all = p["sensor"] == "VIIRS"
    n_points = p[v_all].groupby(keys)["frp"].transform("size")
    cell_mec = p[v_all][keys].merge(cells[keys + ["mec"]], on=keys, how="left")["mec"].to_numpy()
    p["weight"] = 0.0
    p.loc[v_all, "weight"] = cell_mec / n_points.to_numpy()

    # missing data: a sensor with nothing for the whole region while the other sees plenty
    per_day = p.groupby(["date", "sensor"]).size().unstack(fill_value=0)
    rows = []
    for d in days:
        m = int(per_day.at[d, "MODIS"]) if d in per_day.index and "MODIS" in per_day else 0
        vv = int(per_day.at[d, "VIIRS"]) if d in per_day.index and "VIIRS" in per_day else 0
        if vv == 0 and m >= 10:
            rows += [(region, d, "viirs_raw"), (region, d, "harmonized")]
        if m == 0 and vv >= 30:
            rows.append((region, d, "modis_only"))
    missing = pd.DataFrame(rows, columns=["region", "date", "scope"])
    return cells, p, missing


def write_atomic(df, schema, path):
    """Write to a temp file then rename, so the running API never sees half a file."""
    tmp = Path(str(path) + ".tmp")
    table = pa.Table.from_pandas(df[schema.names], schema=schema, preserve_index=False)
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------

def run(key, data_dir=DATA_DIR, regions=None, max_days=MAX_DAYS, client=None, today=None):
    """Fetch, harmonize and write the live files. Returns live_coverage dict."""
    import httpx
    data_dir = Path(data_dir)
    with open(data_dir / "coverage.json") as f:
        coverage = json.load(f)
    today = today or datetime.now(timezone.utc).date()
    last_day = today - timedelta(days=1)          # today is still incomplete
    factors = harmonization_factors(data_dir)
    chunk_days = CHUNK_DAYS
    own_client = client is None
    client = client or httpx.Client(follow_redirects=True)

    all_cells, all_points, all_missing, live_cov = [], [], [], {}
    try:
        for region, cov in coverage.items():
            if regions and region not in regions:
                continue
            main_end = date.fromisoformat(cov.get("nrt_end") or cov["archive_end"])
            first = max(main_end + timedelta(days=1), last_day - timedelta(days=max_days - 1))
            if first > last_day:
                log(f"[{region}] main data already reaches {main_end}; nothing to fetch")
                continue
            bbox = [int(x) if float(x).is_integer() else x for x in cov["bbox"]]
            log(f"[{region}] fetching {first} -> {last_day}")
            frames, fetched_to = [], last_day
            for source in SOURCES:
                d = first
                while d <= last_day:
                    days = min(chunk_days, (last_day - d).days + 1)
                    try:
                        text = fetch_chunk(client, key, source, bbox, d, days, today)
                        frames.append(parse_csv(text, source))
                    except DayRangeError as ex:
                        if ex.max_days < 1 or ex.max_days >= days:
                            log(f"  {source} {d}: FAILED ({ex}).")
                            fetched_to = min(fetched_to, d - timedelta(days=1))
                            break
                        log(f"  FIRMS now allows {ex.max_days} days per request; adjusting.")
                        chunk_days = ex.max_days
                        continue                      # retry the same start date, smaller chunk
                    except FirmsError as ex:
                        log(f"  {source} {d}: FAILED ({ex}). Keeping data only up to {d - timedelta(days=1)}.")
                        fetched_to = min(fetched_to, d - timedelta(days=1))
                        break
                    d += timedelta(days=days)
            if fetched_to < first:
                log(f"[{region}] no usable live data")
                continue
            pts = pd.concat(frames, ignore_index=True) if frames else parse_csv("", "MODIS_NRT")
            pts = pts[(pts["date"] >= first) & (pts["date"] <= fetched_to)]
            w, s, e, n = cov["bbox"]
            pts = pts[(pts["lat"] >= s) & (pts["lat"] <= n) & (pts["lon"] >= w) & (pts["lon"] <= e)]
            f = factors.get(region, (1 / FALLBACK_VIIRS_RATIO, 1 / FALLBACK_VIIRS_RATIO))
            days = [first + timedelta(days=i) for i in range((fetched_to - first).days + 1)]
            cells, points, missing = build_region(region, pts, f, days)
            all_cells.append(cells)
            all_points.append(points)
            all_missing.append(missing)
            live_cov[region] = {"live_start": first.isoformat(), "live_end": fetched_to.isoformat(),
                                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "viirs_count_factor": round(f[0], 4), "sources": list(SOURCES)}
            log(f"[{region}] {len(points):,} hotspots, {len(cells):,} cell-days, "
                f"harmonization factor {f[0]:.3f}, {len(missing)} missing-day rows")
    finally:
        if own_client:
            client.close()

    if not live_cov:
        log("No live data written (existing live files, if any, are left as they were).")
        return live_cov
    cells = pd.concat(all_cells, ignore_index=True).sort_values(["region", "date", "cell_id"])
    points = pd.concat(all_points, ignore_index=True).sort_values(["region", "datetime_utc"])
    missing = pd.concat(all_missing, ignore_index=True)
    write_atomic(cells, CELLS_SCHEMA, data_dir / "live_cells_daily.parquet")
    write_atomic(points, HOTSPOTS_SCHEMA, data_dir / "live_hotspots.parquet")
    write_atomic(missing, MISSING_SCHEMA, data_dir / "live_missing_days.parquet")
    tmp = data_dir / "live_coverage.json.tmp"
    tmp.write_text(json.dumps(live_cov, indent=1))
    os.replace(tmp, data_dir / "live_coverage.json")
    log(f"Wrote live files to {data_dir}")
    return live_cov


def main():
    ap = argparse.ArgumentParser(description="Fetch recent FIRMS hotspots for the app.")
    ap.add_argument("--region", action="append", help="only this region (repeatable)")
    ap.add_argument("--max-days", type=int, default=MAX_DAYS)
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except ImportError:
        pass
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key or key.startswith("<"):
        sys.exit("FIRMS_MAP_KEY is not set. Put FIRMS_MAP_KEY=your_key in .env "
                 "(free key: https://firms.modaps.eosdis.nasa.gov/api/map_key).")
    run(key, args.data_dir, args.region, args.max_days)


if __name__ == "__main__":
    main()
