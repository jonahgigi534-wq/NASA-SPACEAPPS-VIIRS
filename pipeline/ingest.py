"""Ingest FIRMS hotspot zips into one clean parquet file per region x sensor.

Reads data/raw/<region>/DL_FIRE_*.zip (each zip holds fire_archive_*.csv and fire_nrt_*.csv),
streams the CSVs in chunks (never the whole file in memory), keeps only vegetation fires
(type 0), puts MODIS and VIIRS into one shared schema and writes
data/processed/fires_<region>_<sensor>.parquet   (sensor = modis | viirs).

NRT files have no `type` column, so for NRT we:
  1. drop rows on or before that satellite's last archive date (the archive wins), and
  2. drop rows on "static-source" cells: 0.01 deg cells that had any type 1/2/3 detection
     (volcano, other static land source, offshore) in the region's archive.

Run from the repo root:   python -m pipeline.ingest            (all regions)
                          python -m pipeline.ingest --region texas
"""
from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed")
REGIONS = ("texas", "amazon", "australia")
CHUNK_ROWS = 1_000_000
STATIC_CELL_DEG = 0.01  # grid used to flag static (non-vegetation) sources for NRT rows

# Zip name prefix -> sensor family.
ZIP_SENSOR = {"M-C61": "modis", "SV-C2": "viirs", "J1V-C2": "viirs", "J2V-C2": "viirs"}

# Raw `satellite` codes seen in FIRMS files -> our names.
SATELLITE_NAMES = {
    "Terra": "Terra", "T": "Terra", "Aqua": "Aqua", "A": "Aqua",
    "SNPP": "S-NPP", "N": "S-NPP", "N20": "NOAA-20", "1": "NOAA-20",
    "N21": "NOAA-21", "2": "NOAA-21",
}
VIIRS_CONFIDENCE = {"l": "low", "n": "nominal", "h": "high"}

KEY_COLUMNS = ["region", "sensor", "satellite", "datetime_utc", "acq_date", "lat", "lon",
               "confidence_class", "daynight"]

SCHEMA = pa.schema([
    ("region", pa.string()),
    ("sensor", pa.string()),
    ("satellite", pa.string()),
    ("datetime_utc", pa.timestamp("us", tz="UTC")),
    ("acq_date", pa.date32()),
    ("lat", pa.float64()),
    ("lon", pa.float64()),
    ("frp", pa.float32()),
    ("confidence_class", pa.string()),
    ("confidence_raw", pa.string()),
    ("daynight", pa.string()),
    ("is_provisional", pa.bool_()),
])

CSV_DTYPES = {
    "latitude": "float64", "longitude": "float64", "acq_date": "string",
    "acq_time": "string", "satellite": "string", "confidence": "string",
    "frp": "float32", "daynight": "string", "type": "Int8",
}


@dataclass
class Stats:
    """Counters collected while ingesting one region (printed and saved as JSON)."""
    type_counts: Counter = field(default_factory=Counter)        # (sensor, type) -> n
    rows: Counter = field(default_factory=Counter)               # (satellite, year) -> n
    dates: dict = field(default_factory=dict)                    # (satellite, source) -> [min, max]
    nrt_dropped_overlap: Counter = field(default_factory=Counter)
    nrt_dropped_static: Counter = field(default_factory=Counter)
    null_rows_dropped: Counter = field(default_factory=Counter)


# ---------------------------------------------------------------- small pure helpers

def map_confidence(raw: pd.Series, sensor: str) -> pd.Series:
    """MODIS 0-100 -> low (<30) / nominal (30-79) / high (>=80); VIIRS l/n/h -> same words."""
    if sensor == "modis":
        pct = pd.to_numeric(raw, errors="coerce")
        out = pd.Series(pd.NA, index=raw.index, dtype="string")
        out[pct < 30] = "low"
        out[(pct >= 30) & (pct < 80)] = "nominal"
        out[pct >= 80] = "high"
        return out
    return raw.str.strip().str.lower().map(VIIRS_CONFIDENCE).astype("string")


def parse_datetime(acq_date: pd.Series, acq_time: pd.Series) -> pd.Series:
    """acq_date 'YYYY-MM-DD' + acq_time 'HHMM' (UTC) -> tz-aware UTC timestamp."""
    hhmm = acq_time.str.strip().str.zfill(4)
    return pd.to_datetime(acq_date.str.strip() + hhmm, format="%Y-%m-%d%H%M", utc=True,
                          errors="coerce")


def static_cell_keys(lat: pd.Series, lon: pd.Series) -> np.ndarray:
    """Integer id of the 0.01 deg cell each point falls in."""
    row = np.floor((lat.to_numpy() + 90) / STATIC_CELL_DEG).astype(np.int64)
    col = np.floor((lon.to_numpy() + 180) / STATIC_CELL_DEG).astype(np.int64)
    return row * 100_000 + col


def map_satellite(raw: pd.Series) -> pd.Series:
    names = raw.str.strip().map(SATELLITE_NAMES)
    unknown = raw[names.isna()].unique()
    if len(unknown):
        raise ValueError(f"Unknown satellite code(s) in FIRMS file: {list(unknown)}")
    return names.astype("string")


def normalize_chunk(raw: pd.DataFrame, region: str, sensor: str, provisional: bool) -> pd.DataFrame:
    """Turn one raw FIRMS chunk (already type-filtered) into our shared schema."""
    dt = parse_datetime(raw["acq_date"], raw["acq_time"])
    return pd.DataFrame({
        "region": region,
        "sensor": sensor.upper(),
        "satellite": map_satellite(raw["satellite"]),
        "datetime_utc": dt,
        "acq_date": dt.dt.date,
        "lat": raw["latitude"],
        "lon": raw["longitude"],
        "frp": raw["frp"],
        "confidence_class": map_confidence(raw["confidence"], sensor),
        "confidence_raw": raw["confidence"].str.strip(),
        "daynight": raw["daynight"].str.strip().str.upper(),
        "is_provisional": provisional,
    }, index=raw.index)


# ---------------------------------------------------------------- reading the zips

def sensor_of(zip_path: Path) -> str:
    prefix = zip_path.stem.removeprefix("DL_FIRE_").rsplit("_", 1)[0]
    if prefix not in ZIP_SENSOR:
        raise ValueError(f"Can't tell the sensor of {zip_path.name}")
    return ZIP_SENSOR[prefix]


def csv_name(zf: zipfile.ZipFile, kind: str) -> str | None:
    """Name of fire_<kind>_*.csv inside the zip (kind = archive | nrt), or None."""
    names = [n for n in zf.namelist()
             if Path(n).name.startswith(f"fire_{kind}_") and n.endswith(".csv")]
    return names[0] if names else None


def iter_csv_chunks(zf: zipfile.ZipFile, member: str):
    """Stream a CSV out of a zip in chunks, reading only the columns we need."""
    with zf.open(member) as fh:
        header = fh.readline().decode().strip().split(",")
    usecols = [c for c in CSV_DTYPES if c in header]
    dtypes = {c: CSV_DTYPES[c] for c in usecols}
    with zf.open(member) as fh:
        yield from pd.read_csv(fh, usecols=usecols, dtype=dtypes, chunksize=CHUNK_ROWS)


# ---------------------------------------------------------------- per-chunk filters + bookkeeping

def drop_null_keys(df: pd.DataFrame, stats: Stats, label: str) -> pd.DataFrame:
    bad = df[KEY_COLUMNS].isna().any(axis=1)
    if bad.any():
        stats.null_rows_dropped[label] += int(bad.sum())
    return df[~bad]


def record_rows(df: pd.DataFrame, stats: Stats, source: str) -> None:
    years = df["datetime_utc"].dt.year
    for (sat, yr), n in df.groupby([df["satellite"], years]).size().items():
        stats.rows[(sat, int(yr))] += int(n)
    for sat, grp in df.groupby("satellite"):
        lo, hi = grp["acq_date"].min(), grp["acq_date"].max()
        old = stats.dates.get((sat, source))
        stats.dates[(sat, source)] = [min(lo, old[0]), max(hi, old[1])] if old else [lo, hi]


def filter_archive_chunk(raw: pd.DataFrame, sensor: str, stats: Stats, static: set) -> pd.DataFrame:
    """Count types, remember static-source cells, keep type 0 only."""
    for t, n in raw["type"].value_counts(dropna=False).items():
        stats.type_counts[(sensor, "NA" if pd.isna(t) else int(t))] += int(n)
    non_veg = raw["type"].isin([1, 2, 3]).fillna(False).to_numpy(dtype=bool)
    if non_veg.any():
        keys = static_cell_keys(raw.loc[non_veg, "latitude"], raw.loc[non_veg, "longitude"])
        static.update(keys.tolist())
    return raw[(raw["type"] == 0).fillna(False).to_numpy(dtype=bool)]


def filter_nrt_chunk(df: pd.DataFrame, stats: Stats, static: np.ndarray,
                     archive_end: dict) -> pd.DataFrame:
    """Drop NRT rows already covered by the archive, and rows on static-source cells."""
    end = df["satellite"].map(archive_end)
    overlap = (end.notna() & (df["acq_date"] <= end.fillna(df["acq_date"]))).to_numpy(dtype=bool)
    for sat, n in df.loc[overlap, "satellite"].value_counts().items():
        stats.nrt_dropped_overlap[sat] += int(n)
    df = df[~overlap]
    on_static = np.isin(static_cell_keys(df["lat"], df["lon"]), static)
    for sat, n in df.loc[on_static, "satellite"].value_counts().items():
        stats.nrt_dropped_static[sat] += int(n)
    return df[~on_static]


# ---------------------------------------------------------------- one region

def write_chunk(writer: pq.ParquetWriter, df: pd.DataFrame) -> None:
    if len(df):
        writer.write_table(pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False))


def ingest_archive(zips, region, writers, stats) -> set:
    static: set = set()
    for zp in zips:
        sensor = sensor_of(zp)
        with zipfile.ZipFile(zp) as zf:
            member = csv_name(zf, "archive")
            if member is None:
                raise FileNotFoundError(f"{zp.name} has no fire_archive_*.csv")
            for raw in iter_csv_chunks(zf, member):
                kept = filter_archive_chunk(raw, sensor, stats, static)
                df = drop_null_keys(normalize_chunk(kept, region, sensor, False), stats,
                                    f"{sensor}/archive")
                record_rows(df, stats, "archive")
                write_chunk(writers[sensor], df)
    return static


def ingest_nrt(zips, region, writers, stats, static: set) -> None:
    static_arr = np.fromiter(static, dtype=np.int64, count=len(static))
    archive_end = {sat: hi for (sat, src), (_, hi) in stats.dates.items() if src == "archive"}
    for zp in zips:
        sensor = sensor_of(zp)
        with zipfile.ZipFile(zp) as zf:
            member = csv_name(zf, "nrt")
            if member is None:
                continue
            for raw in iter_csv_chunks(zf, member):
                if "type" in raw.columns:  # if a future NRT file has `type`, use it directly
                    raw = raw[(raw["type"] == 0).fillna(False).to_numpy(dtype=bool)]
                df = drop_null_keys(normalize_chunk(raw, region, sensor, True), stats,
                                    f"{sensor}/nrt")
                df = filter_nrt_chunk(df, stats, static_arr, archive_end)
                record_rows(df, stats, "nrt")
                write_chunk(writers[sensor], df)


def ingest_region(region: str, raw_dir: Path = RAW_DIR, out_dir: Path = OUT_DIR) -> Stats:
    """Ingest every zip in raw_dir/<region>/; write one parquet per sensor. Idempotent."""
    zips = sorted((raw_dir / region).glob("DL_FIRE_*.zip"))
    if not zips:
        raise FileNotFoundError(f"No FIRMS zips in {raw_dir / region}")
    out_dir.mkdir(parents=True, exist_ok=True)
    sensors = sorted({sensor_of(z) for z in zips})
    tmp = {s: out_dir / f"fires_{region}_{s}.parquet.tmp" for s in sensors}
    writers = {s: pq.ParquetWriter(tmp[s], SCHEMA, compression="zstd") for s in sensors}
    stats = Stats()
    try:
        static = ingest_archive(zips, region, writers, stats)
        ingest_nrt(zips, region, writers, stats, static)
    finally:
        for w in writers.values():
            w.close()
    for s in sensors:  # swap in only after a full successful run
        tmp[s].replace(out_dir / f"fires_{region}_{s}.parquet")
    return stats


# ---------------------------------------------------------------- reporting

def region_summary(st: Stats) -> dict:
    type_share = {}
    for sensor in sorted({s for s, _ in st.type_counts}):
        total = sum(n for (s, _), n in st.type_counts.items() if s == sensor)
        type_share[sensor] = {f"type_{t}": f"{100 * n / total:.2f}% ({n:,})"
                              for (s, t), n in sorted(st.type_counts.items(), key=str) if s == sensor}
    return {
        "archive_type_share (removed = all but type_0)": type_share,
        "date_ranges": {f"{sat}/{src}": [str(lo), str(hi)]
                        for (sat, src), (lo, hi) in sorted(st.dates.items())},
        "nrt_dropped_overlap_with_archive": dict(st.nrt_dropped_overlap),
        "nrt_dropped_static_source_cells": dict(st.nrt_dropped_static),
        "rows_dropped_for_null_keys": dict(st.null_rows_dropped),
    }


def report(all_stats: dict[str, Stats]) -> dict:
    """Print the checks asked for in A1 and return them as a JSON-friendly dict."""
    rows = pd.DataFrame([(r, sat, yr, n) for r, st in all_stats.items()
                         for (sat, yr), n in st.rows.items()],
                        columns=["region", "satellite", "year", "rows"])
    pivot = rows.pivot_table(index="year", columns=["region", "satellite"], values="rows",
                             aggfunc="sum", fill_value=0)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_rows", 60):
        print("\n=== Rows kept by year x region x satellite ===")
        print(pivot)
        print("\n=== Total rows kept per region ===")
        print(rows.groupby("region")["rows"].sum().sort_values(ascending=False))
    summary = {}
    for region, st in all_stats.items():
        summary[region] = region_summary(st)
        print(f"\n--- {region} ---")
        for k, v in summary[region].items():
            print(f"{k}: {v}")
    return summary


def null_check(out_dir: Path = OUT_DIR) -> None:
    """Re-open the written parquet files and count nulls in key columns (expected: all 0)."""
    print("\n=== Nulls in key columns of written parquet ===")
    for f in sorted(out_dir.glob("fires_*.parquet")):
        t = pq.read_table(f, columns=KEY_COLUMNS + ["frp"])
        nulls = {c: t.column(c).null_count for c in t.column_names}
        print(f"{f.name}: rows={t.num_rows:,} nulls={nulls}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", choices=REGIONS, action="append", help="default: all regions")
    args = ap.parse_args(argv)
    all_stats = {}
    for region in args.region or REGIONS:
        print(f"Ingesting {region} ...", flush=True)
        all_stats[region] = ingest_region(region)
    summary = report(all_stats)
    null_check()
    (OUT_DIR / "ingest_report.json").write_text(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
