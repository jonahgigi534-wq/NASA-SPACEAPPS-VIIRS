"""
Make FAKE app data in exactly the shapes Track A will deliver (docs/CONTRACTS.md section 2).

Why: Track B (the API) and Track C (the website) can't wait for the real NASA data, so we build
against realistic fake data with the same columns and types. When Track A's real data/app/ is
ready we just point APP_DATA_DIR at it.

What makes it realistic:
- every region has its own fire season (Texas: Feb-Apr, Amazon: Aug-Oct, N. Australia: May-Nov)
- a few extreme years (Texas 2011, Amazon 2010/2019/2024, Australia 2019...)
- fires cluster in a few hot areas instead of being spread evenly
- MODIS sees each fire about 1.3 times (Terra + Aqua), VIIRS about 3.9 times (smaller pixels),
  so raw VIIRS counts jump about 3x after VIIRS starts on 2012-01-20
- some days have no data for a sensor (missing, NOT zero fire)
- the last ~2.5 months are "provisional" (near-real-time, not science quality)

Everything is built from individual hotspot POINTS first, then cells_daily is the sum of the
points, so the two tables always agree (sum of point weights = mec in every cell-day).

THIS IS FAKE DATA. Never quote numbers from it.

Run from the repo root:
    python scripts/make_synthetic_app_data.py              # writes data/app/
    python scripts/make_synthetic_app_data.py --out some/folder --scale 0.2
"""

import argparse
import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------

DATA_START = date(2001, 1, 1)
VIIRS_START = date(2012, 1, 20)     # S-NPP: harmonized series switches from MODIS to VIIRS here
AQUA_START = date(2002, 7, 4)       # before this only Terra MODIS exists
NOAA20_START = date(2018, 4, 1)
NOAA21_START = date(2024, 1, 17)
ARCHIVE_END = date(2026, 8, 31)     # after this, data is near-real-time = provisional
NRT_END = date(2026, 10, 31)

# Each MODIS-era fire is seen ~1.3 times by Terra+Aqua; each VIIRS-era fire ~3.9 times by VIIRS.
MODIS_DETECTIONS_PER_FIRE = 1.3
VIIRS_DETECTIONS_PER_FIRE = 3.9

# Region id -> settings. bbox = [W, S, E, N] (same as data/regions/*.geojson).
REGIONS = {
    "texas": {
        "bbox": [-107, 25, -93, 37],
        "fires_per_day": 4.0,
        # fire season: list of (peak day-of-year, width in days, relative strength)
        "season": [(75, 28, 1.0), (205, 30, 0.35)],
        "season_floor": 0.12,
        "extreme_years": {2006: 1.7, 2011: 3.2, 2022: 1.8},
        "clusters": [(-95.5, 31.0), (-98.0, 30.5), (-98.5, 26.5), (-97.5, 35.5), (-104.5, 32.0)],
    },
    "amazon": {
        "bbox": [-65, -15, -45, -5],
        "fires_per_day": 10.0,
        "season": [(245, 25, 1.0)],
        "season_floor": 0.02,
        "extreme_years": {2005: 1.6, 2007: 1.8, 2010: 1.9, 2019: 1.4, 2020: 1.4, 2024: 2.0},
        "clusters": [(-55.0, -10.0), (-62.0, -9.0), (-50.0, -7.0), (-48.0, -12.0), (-58.0, -13.0)],
    },
    "australia": {
        "bbox": [120, -20, 150, -10],
        "fires_per_day": 6.0,
        "season": [(255, 45, 1.0), (150, 30, 0.35)],
        "season_floor": 0.05,
        "extreme_years": {2012: 1.3, 2019: 1.5, 2023: 1.4},
        "clusters": [(132.5, -14.5), (126.0, -16.0), (142.0, -15.0), (136.0, -12.5), (129.0, -18.0)],
    },
}


def cell_id(lat, lon):
    """Cell id exactly as written in docs/CONTRACTS.md section 2."""
    return (np.round((lat + 90) * 10).astype(np.int64) * 3600
            + np.round((lon + 180) * 10).astype(np.int64)).astype(np.int32)


def seasonal_curve(doy, peaks, floor):
    """Relative fire activity for each day-of-year: a few smooth bumps plus a small floor."""
    curve = np.full(doy.shape, floor, dtype=float)
    for peak, width, strength in peaks:
        # circular distance in days, so a December peak wraps into January
        d = np.minimum(np.abs(doy - peak), 365 - np.abs(doy - peak))
        curve += strength * np.exp(-0.5 * (d / width) ** 2)
    return curve / curve.mean()


def spatial_weights(bbox, clusters, rng):
    """Probability of a fire in each 0.1 degree cell: a few hot clusters plus a thin background."""
    w, s, e, n = bbox
    # Cell centers sit on whole tenths (25.0, 25.1, ...) because the contract's cell_id uses
    # round(): the cell centered on 25.0 covers 24.95 .. 25.05.
    lats = np.round(np.arange(s, n + 1e-9, 0.1), 1)
    lons = np.round(np.arange(w, e + 1e-9, 0.1), 1)
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
    weight = np.full(lat_grid.shape, 0.02)
    for lon_c, lat_c in clusters:
        spread = rng.uniform(0.8, 1.8)  # degrees
        strength = rng.uniform(0.6, 1.4)
        weight += strength * np.exp(-((lat_grid - lat_c) ** 2 + (lon_grid - lon_c) ** 2)
                                    / (2 * spread ** 2))
    # fixed per-cell "fire-proneness" so the same cells burn year after year
    weight *= rng.lognormal(0, 0.8, size=weight.shape)
    weight = weight.ravel()
    return lat_grid.ravel(), lon_grid.ravel(), weight / weight.sum()


def pick_missing_days(dates, rng, per_year, first, gap=None):
    """Random missing days for one sensor (plus an optional multi-day outage)."""
    pool = [d for d in dates if d >= first]
    n = int(per_year * len(pool) / 365.25)
    chosen = set(rng.choice(np.array(pool, dtype=object), size=n, replace=False)) if n else set()
    if gap:
        start, length = gap
        chosen |= {start + timedelta(days=i) for i in range(length)}
    return chosen


def make_region(region, cfg, end, scale, rng):
    """Build the hotspot points for one region, then return (points, missing-day sets)."""
    dates = pd.date_range(DATA_START, end, freq="D")
    doy = dates.day_of_year.to_numpy()
    years = dates.year.to_numpy()

    # ---- how many fires each day ----------------------------------------------------------
    lam = cfg["fires_per_day"] * scale * seasonal_curve(doy, cfg["season"], cfg["season_floor"])
    year_factor = np.array([cfg["extreme_years"].get(y, 1.0) for y in years])
    year_factor *= np.exp(0.012 * (years - 2001))          # slight long-term increase
    lam *= year_factor
    # weather: several-day runs of high or low activity (smoothed random noise)
    noise = pd.Series(rng.normal(0, 0.7, len(dates))).rolling(6, min_periods=1, center=True).mean()
    lam *= np.exp(noise.to_numpy() * 1.6 - 0.25)
    n_fires = rng.poisson(lam)

    # ---- where each fire is --------------------------------------------------------------------
    cell_lat, cell_lon, prob = spatial_weights(cfg["bbox"], cfg["clusters"], rng)
    fire_day = np.repeat(np.arange(len(dates)), n_fires)
    fire_cell = rng.choice(len(prob), size=len(fire_day), p=prob)
    fire_date = dates[fire_day].date

    # ---- MODIS detections (Terra + Aqua) --------------------------------------------------------
    has_aqua = np.array([d >= AQUA_START for d in fire_date])
    modis_rate = np.where(has_aqua, MODIS_DETECTIONS_PER_FIRE, MODIS_DETECTIONS_PER_FIRE * 0.55)
    n_modis = rng.poisson(modis_rate)
    m_fire = np.repeat(np.arange(len(fire_day)), n_modis)
    m_aqua_ok = has_aqua[m_fire]
    m_sat = np.where(m_aqua_ok & (rng.random(len(m_fire)) < 0.55), "Aqua", "Terra")

    # ---- VIIRS detections (de-duplicated across S-NPP / NOAA-20 / NOAA-21) ----------------------
    is_viirs_era = np.array([d >= VIIRS_START for d in fire_date])
    n_viirs = np.where(is_viirs_era, rng.poisson(VIIRS_DETECTIONS_PER_FIRE, len(fire_day)), 0)
    v_fire = np.repeat(np.arange(len(fire_day)), n_viirs)
    v_dates = fire_date[v_fire]
    v_sat = np.full(len(v_fire), "S-NPP", dtype=object)
    r = rng.random(len(v_fire))
    after20 = np.array([d >= NOAA20_START for d in v_dates])
    after21 = np.array([d >= NOAA21_START for d in v_dates])
    v_sat[after20 & (r < 0.5)] = "NOAA-20"
    v_sat[after21 & (r >= 0.5) & (r < 0.7)] = "NOAA-21"

    def build_points(fire_idx, sensor, satellite):
        n = len(fire_idx)
        center_lat = cell_lat[fire_cell[fire_idx]]
        center_lon = cell_lon[fire_cell[fire_idx]]
        # points scatter inside their 0.1 degree cell (5 decimals, like FIRMS), inside the box
        w, s, e, nn = cfg["bbox"]
        lat = np.round(np.clip(center_lat + rng.uniform(-0.0499, 0.0499, n), s, nn), 5)
        lon = np.round(np.clip(center_lon + rng.uniform(-0.0499, 0.0499, n), w, e), 5)
        daynight = np.where(rng.random(n) < 0.8, "D", "N")
        # local solar overpass times: Terra ~10:30 / 22:30, everyone else ~13:30 / 01:30
        local_hour = np.where(satellite == "Terra",
                              np.where(daynight == "D", 10.5, 22.5),
                              np.where(daynight == "D", 13.5, 1.5))
        local_hour = local_hour + rng.normal(0, 0.4, n)
        utc_hours = local_hour - lon / 15.0                      # solar time -> UTC
        base = pd.to_datetime(np.array(fire_date[fire_idx], dtype="datetime64[D]"))
        dt = base + pd.to_timedelta(np.round(utc_hours * 60), unit="min")
        if sensor == "MODIS":
            frp = rng.lognormal(np.log(18), 1.0, n)
            conf = rng.choice(["low", "nominal", "high"], n, p=[0.15, 0.6, 0.25])
        else:
            frp = rng.lognormal(np.log(6), 1.0, n)
            conf = rng.choice(["low", "nominal", "high"], n, p=[0.08, 0.82, 0.10])
        return pd.DataFrame({
            "region": region, "lat": lat, "lon": lon,
            "datetime_utc": dt.floor("min"),
            "satellite": satellite, "sensor": sensor,
            "frp": np.round(frp, 1).astype(np.float32),
            "confidence_class": conf, "daynight": daynight,
        })

    points = pd.concat([build_points(m_fire, "MODIS", m_sat),
                        build_points(v_fire, "VIIRS", v_sat)], ignore_index=True)
    points["date"] = points["datetime_utc"].dt.date   # UTC date, as in the contract

    # ---- missing data: a sensor had nothing for the whole region that day ----------------------
    all_dates = list(dates.date)
    modis_missing = pick_missing_days(all_dates, rng, 3, DATA_START,
                                      gap=(date(2016, 2, 19), 7))
    viirs_missing = pick_missing_days(all_dates, rng, 3, VIIRS_START,
                                      gap=(date(2022, 7, 26), 5))
    drop = ((points["sensor"] == "MODIS") & points["date"].isin(modis_missing)) | \
           ((points["sensor"] == "VIIRS") & points["date"].isin(viirs_missing))
    points = points[~drop].reset_index(drop=True)
    return points, modis_missing, viirs_missing


def finish(points, modis_missing, viirs_missing, end):
    """Add harmonization weights and build cells_daily + missing_days from the points."""
    viirs_era = points["date"] >= VIIRS_START
    # placeholder harmonization (Track A replaces it): ONE global ratio, VIIRS / MODIS counts
    # over the overlap 2012-01-20 .. 2018-12-31, so the harmonized series stays continuous.
    overlap = viirs_era & (points["date"] <= date(2018, 12, 31))
    ratio = ((points["sensor"] == "VIIRS") & overlap).sum() / \
            max(((points["sensor"] == "MODIS") & overlap).sum(), 1)
    points["weight"] = np.select(
        [(points["sensor"] == "MODIS") & ~viirs_era, points["sensor"] == "VIIRS"],
        [1.0, 1.0 / ratio], default=0.0).astype(np.float32)
    points["provisional"] = points["date"] > ARCHIVE_END
    points["cell_id"] = cell_id(points["lat"].to_numpy(), points["lon"].to_numpy())

    p = points.assign(
        is_modis=(points["sensor"] == "MODIS").astype(np.float32),
        is_viirs=(points["sensor"] == "VIIRS").astype(np.float32),
        w_frp=np.where(points["weight"] > 0, points["frp"], 0).astype(np.float32),
    )
    cells = (p.groupby(["region", "cell_id", "date"], as_index=False)
              .agg(mec=("weight", "sum"), mefrp=("w_frp", "sum"),
                   modis_n=("is_modis", "sum"), viirs_n=("is_viirs", "sum")))
    lat_idx = cells["cell_id"] // 3600
    lon_idx = cells["cell_id"] % 3600
    cells["lat"] = (lat_idx / 10 - 90).astype(np.float32)
    cells["lon"] = (lon_idx / 10 - 180).astype(np.float32)
    cells["source"] = np.where(cells["date"] >= VIIRS_START, "VIIRS", "MODIS")
    cells["provisional"] = cells["date"] > ARCHIVE_END
    cells = cells[["region", "cell_id", "lat", "lon", "date", "mec", "mefrp",
                   "modis_n", "viirs_n", "source", "provisional"]]

    region = points["region"].iloc[0]
    rows = []
    for d in sorted(modis_missing):
        rows.append((region, d, "modis_only"))
        if d < VIIRS_START:
            rows.append((region, d, "harmonized"))
    for d in sorted(viirs_missing):
        rows.append((region, d, "viirs_raw"))
        rows.append((region, d, "harmonized"))
    missing = pd.DataFrame(rows, columns=["region", "date", "scope"])
    missing = missing[missing["date"] <= end]
    return points, cells, missing, ratio


# Exact arrow schemas from docs/CONTRACTS.md section 2
CELLS_SCHEMA = pa.schema([
    ("region", pa.string()), ("cell_id", pa.int32()), ("lat", pa.float32()), ("lon", pa.float32()),
    ("date", pa.date32()), ("mec", pa.float32()), ("mefrp", pa.float32()),
    ("modis_n", pa.float32()), ("viirs_n", pa.float32()), ("source", pa.string()),
    ("provisional", pa.bool_()),
])
MISSING_SCHEMA = pa.schema([("region", pa.string()), ("date", pa.date32()), ("scope", pa.string())])
HOTSPOTS_SCHEMA = pa.schema([
    ("region", pa.string()), ("lat", pa.float64()), ("lon", pa.float64()),
    ("datetime_utc", pa.timestamp("us")), ("date", pa.date32()), ("satellite", pa.string()),
    ("sensor", pa.string()), ("frp", pa.float32()), ("confidence_class", pa.string()),
    ("daynight", pa.string()), ("provisional", pa.bool_()), ("weight", pa.float32()),
])


def write(df, schema, path):
    table = pa.Table.from_pandas(df[schema.names], schema=schema, preserve_index=False)
    pq.write_table(table, path, compression="zstd")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default=os.path.join("data", "app"))
    ap.add_argument("--scale", type=float, default=1.0, help="fewer/more fires (tests use 0.3)")
    ap.add_argument("--end", default=None, help="last date of data, default yesterday (UTC)")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    build(args.out, args.scale, args.end, args.seed, verbose=True)


def build(out, scale=1.0, end=None, seed=2026, verbose=False):
    """Write all four app data files to `out`. Used by main() and by the tests."""
    end = date.fromisoformat(end) if end else date.today() - timedelta(days=1)
    rng = np.random.default_rng(seed)
    os.makedirs(out, exist_ok=True)

    all_points, all_cells, all_missing, coverage = [], [], [], {}
    for region, cfg in REGIONS.items():
        points, mm, vm = make_region(region, cfg, end, scale, rng)
        points, cells, missing, ratio = finish(points, mm, vm, end)
        all_points.append(points)
        all_cells.append(cells)
        all_missing.append(missing)
        coverage[region] = {"start": DATA_START.isoformat(), "archive_end": ARCHIVE_END.isoformat(),
                            "nrt_end": min(NRT_END, end).isoformat(), "live_end": end.isoformat(),
                            "bbox": cfg["bbox"]}
        if verbose:
            print(f"[{region}] {len(points):,} hotspots, {len(cells):,} cell-days, "
                  f"{len(missing)} missing-day rows, global VIIRS/MODIS ratio {ratio:.2f}")

    cells = pd.concat(all_cells, ignore_index=True).sort_values(["region", "date", "cell_id"])
    points = pd.concat(all_points, ignore_index=True).sort_values(["region", "datetime_utc"])
    missing = pd.concat(all_missing, ignore_index=True).sort_values(["region", "date", "scope"])

    write(cells, CELLS_SCHEMA, os.path.join(out, "cells_daily.parquet"))
    write(missing, MISSING_SCHEMA, os.path.join(out, "missing_days.parquet"))
    write(points, HOTSPOTS_SCHEMA, os.path.join(out, "hotspots.parquet"))
    with open(os.path.join(out, "coverage.json"), "w") as f:
        json.dump(coverage, f, indent=1)

    if verbose:
        for name in ["cells_daily.parquet", "missing_days.parquet", "hotspots.parquet",
                     "coverage.json"]:
            size = os.path.getsize(os.path.join(out, name)) / 1e6
            print(f"  {name:24s} {size:6.2f} MB")
        print(f"Wrote FAKE data to {out} (data through {end}). Never quote these numbers.")


if __name__ == "__main__":
    main()
