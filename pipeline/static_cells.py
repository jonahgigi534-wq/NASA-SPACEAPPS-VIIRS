"""Static heat-source cells (gas flares, industry, volcanoes, offshore) -> data/processed/static_cells.parquet.

The archive tags every detection with a FIRMS `type` (0 = vegetation fire, 1 = volcano,
2 = other static land source, 3 = offshore). NRT and the app's live feed have no `type`, so
pipeline/live.py drops live detections that fall in cells listed here (columns: region, cell_id
on the 0.1 deg grid of docs/CONTRACTS.md section 2). data/ never reaches the deployed app, so
the same list is also written to results/static_cells.csv (committed; deploy_space.py uploads it).

A 0.1 deg cell is ~11 km wide, much coarser than the 0.01 deg grid ingest uses for NRT rows, so
flagging every cell that ever had one static detection would also delete real fires around it.
Rule: a cell is static when the archive's type 1/2/3 detections there are at least
MIN_STATIC_SHARE of all its detections and at least MIN_STATIC_N in number. The script reports
how many type-0 (fire) detections the chosen cells hold, so the cost of the rule is visible.

Run from the repo root:  python -m pipeline.static_cells
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.ingest import RAW_DIR, csv_name, iter_csv_chunks

OUT = Path("data/processed/static_cells.parquet")
SHIPPED = Path("results/static_cells.csv")   # committed + deployed copy that live.py reads
REPORT = Path("results/static_cells.json")
REGIONS = ("amazon", "australia", "texas")
MIN_STATIC_SHARE = 0.5   # static detections / all detections in the cell
MIN_STATIC_N = 10        # ignore cells with only a handful of static detections


def cell_id(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """0.1 deg cell id exactly as docs/CONTRACTS.md section 2 (same as pipeline.live.cell_id)."""
    return (np.round((lat + 90) * 10).astype(np.int64) * 3600
            + np.round((lon + 180) * 10).astype(np.int64))


def count_chunk(raw: pd.DataFrame) -> pd.DataFrame:
    t = raw["type"]
    return pd.DataFrame({
        "cell_id": cell_id(raw["latitude"].to_numpy(float), raw["longitude"].to_numpy(float)),
        "static_n": t.isin([1, 2, 3]).fillna(False).to_numpy(dtype=np.int64),
        "fire_n": (t == 0).fillna(False).to_numpy(dtype=np.int64),
    }).groupby("cell_id", as_index=False).sum()


def count_region(region: str, raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Per 0.1 deg cell: archive detections that are static (type 1/2/3) and fire (type 0)."""
    parts = []
    for zp in sorted((raw_dir / region).glob("DL_FIRE_*.zip")):
        with zipfile.ZipFile(zp) as zf:
            member = csv_name(zf, "archive")
            if member is None:
                raise FileNotFoundError(f"{zp.name} has no fire_archive_*.csv")
            parts.extend(count_chunk(raw) for raw in iter_csv_chunks(zf, member))
    if not parts:
        raise FileNotFoundError(f"No FIRMS zips in {raw_dir / region}")
    return pd.concat(parts).groupby("cell_id", as_index=False).sum()


def select_static(counts: pd.DataFrame) -> pd.DataFrame:
    total = counts["static_n"] + counts["fire_n"]
    keep = (counts["static_n"] >= MIN_STATIC_N) & (counts["static_n"] >= MIN_STATIC_SHARE * total)
    return counts[keep]


def summarize(counts: pd.DataFrame, chosen: pd.DataFrame) -> dict:
    static_all = int(counts["static_n"].sum())
    fire_all = int(counts["fire_n"].sum())
    return {
        "cells": int(len(chosen)),
        "static_detections_covered_pct":
            round(100 * chosen["static_n"].sum() / static_all, 2) if static_all else None,
        "fire_detections_lost_pct":
            round(100 * chosen["fire_n"].sum() / fire_all, 3) if fire_all else None,
    }


def main() -> None:
    report = {"rule": {"min_static_share": MIN_STATIC_SHARE, "min_static_n": MIN_STATIC_N}}
    rows = []
    for region in REGIONS:
        counts = count_region(region)
        chosen = select_static(counts)
        report[region] = {k: (float(v) if isinstance(v, np.floating) else v)
                          for k, v in summarize(counts, chosen).items()}
        print(region, report[region])
        rows.append(pd.DataFrame({"region": region, "cell_id": chosen["cell_id"].astype("int32")}))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cells = pd.concat(rows, ignore_index=True)
    cells.to_parquet(OUT, index=False)
    cells.to_csv(SHIPPED, index=False)
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}, {SHIPPED} and {REPORT}")


if __name__ == "__main__":
    main()
