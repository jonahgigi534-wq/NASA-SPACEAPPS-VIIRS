"""Land-cover group of every 0.25 deg calibration cell, per year (optional input).

Reads MCD12Q1.061 LC_Type1 GeoTIFFs from data/raw/appeears/<region>/ (one per year, 500 m,
EPSG:4326) and takes the MAJORITY land-cover group of the pixels inside each 0.25 deg cell:

    forest 1-5 | shrub 6-7 | savanna 8-9 | grassland 10 | cropland 12, 14 | other (11, 13, 15-17)

Output: data/processed/landcover_<region>.parquet  (region, cell_id, year, lc_group)
cell_id is the 0.25 deg id used in pipeline/grid.py: floor((lat+90)/0.25)*1440 + floor((lon+180)/0.25).
If no rasters exist for a region, nothing is written and harmonization runs per region only.

Run from the repo root:  python -m pipeline.landcover
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from pipeline.ingest import REGIONS

APPEEARS = Path("data/raw/appeears")
PROCESSED = Path("data/processed")
CELL_DEG = 0.25
GROUPS = ["forest", "shrub", "savanna", "grassland", "cropland", "other"]
# IGBP class (LC_Type1 value) -> index into GROUPS; anything else (255 = no data) is ignored
CLASS_TO_GROUP = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 1, 7: 1, 8: 2, 9: 2, 10: 3,
                  12: 4, 14: 4, 11: 5, 13: 5, 15: 5, 16: 5, 17: 5}
YEAR = re.compile(r"doy(\d{4})")


def lc_files(region: str, appeears: Path = APPEEARS) -> dict[int, Path]:
    files = sorted((appeears / region).glob("MCD12Q1*LC_Type1*.tif"))
    return {int(YEAR.search(f.name).group(1)): f for f in files}


def class_lookup() -> np.ndarray:
    lut = np.full(256, -1, dtype=np.int8)
    for cls, grp in CLASS_TO_GROUP.items():
        lut[cls] = grp
    return lut


def cell_groups(path: Path) -> pd.DataFrame:
    """Majority group per 0.25 deg cell for one raster."""
    with rasterio.open(path) as ds:
        lc = ds.read(1)
        t = ds.transform
    # pixel-centre coordinates (north-up raster, no rotation)
    lon = t.c + (np.arange(lc.shape[1]) + 0.5) * t.a
    lat = t.f + (np.arange(lc.shape[0]) + 0.5) * t.e
    col = np.floor((lon + 180) / CELL_DEG).astype(np.int64)
    row = np.floor((lat + 90) / CELL_DEG).astype(np.int64)
    cell = (row[:, None] * 1440 + col[None, :]).ravel()
    grp = class_lookup()[lc.ravel()]
    keep = grp >= 0
    counts = pd.DataFrame({"cell_id": cell[keep], "g": grp[keep]}).value_counts().rename("n").reset_index()
    top = counts.sort_values(["cell_id", "n"], ascending=[True, False]).drop_duplicates("cell_id")
    return pd.DataFrame({"cell_id": top["cell_id"].astype("int32").to_numpy(),
                         "lc_group": [GROUPS[g] for g in top["g"]]})


def build_region(region: str) -> pd.DataFrame | None:
    files = lc_files(region)
    if not files:
        print(f"{region}: no MCD12Q1 rasters, harmonization will run per region only")
        return None
    parts = [cell_groups(f).assign(year=yr) for yr, f in files.items()]
    out = pd.concat(parts, ignore_index=True).assign(region=region)[["region", "cell_id", "year", "lc_group"]]
    out.to_parquet(PROCESSED / f"landcover_{region}.parquet", index=False)
    return out


def main() -> None:
    for region in REGIONS:
        out = build_region(region)
        if out is not None:
            last = out["year"].max()
            share = out[out["year"] == last]["lc_group"].value_counts(normalize=True).round(2).to_dict()
            print(f"{region}: {out['year'].min()}-{last}, {out['cell_id'].nunique()} cells; {last} shares {share}")


if __name__ == "__main__":
    main()
