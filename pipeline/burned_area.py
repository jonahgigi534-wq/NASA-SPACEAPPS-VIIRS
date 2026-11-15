"""Independent check against MODIS Burned Area (MCD64A1 v061) -> results/metrics.json + one figure.

Burned area comes from one sensor family (MODIS) for the whole record, so it does not jump in 2012
when hotspots switch from MODIS to VIIRS. If the harmonization works, harmonized hotspots should
relate to burned area the same way before 2012 (MODIS hotspots) and after (harmonized VIIRS):
similar month-to-month correlation and a similar number of hotspots per km2 burned.
Raw VIIRS is shown for contrast.

Burned km2 per month = burned pixels (Burn_Date > 0) x pixel area at the pixel's latitude, over
the whole region box (same box as the hotspot data). Hotspots: data/app/cells_daily.parquet,
non-provisional days only.

Run from the repo root:  python -m pipeline.burned_area
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import rasterio

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

APPEEARS = Path("data/raw/appeears")
CELLS = Path("data/app/cells_daily.parquet")
CACHE = Path("data/processed/burned_area_monthly.parquet")
METRICS = Path("results/metrics.json")
FIGURE = Path("results/figures/burned_area_check.png")
REGIONS = ("texas", "amazon", "australia")
NAMES = {"texas": "Texas", "amazon": "Amazon", "australia": "N. Australia"}
SWITCH_YEAR = 2012
KM_PER_DEG = 111.32
DOY = re.compile(r"_doy(\d{4})(\d{3})")


def file_month(path: Path) -> pd.Timestamp:
    year, doy = DOY.search(path.name).groups()
    day = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=int(doy) - 1)
    return day.replace(day=1)


def burned_km2(path: Path) -> float:
    with rasterio.open(path) as ds:
        burned = ds.read(1) > 0
        res_x, res_y = ds.res
        lat = ds.bounds.top - (np.arange(ds.height) + 0.5) * res_y
    row_km2 = res_x * res_y * KM_PER_DEG ** 2 * np.cos(np.radians(lat))
    return float((burned.sum(axis=1) * row_km2).sum())


def monthly_burned(appeears: Path = APPEEARS) -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    rows = [{"region": region, "month": file_month(f), "burned_km2": burned_km2(f)}
            for region in REGIONS
            for f in sorted((appeears / region).glob("MCD64A1.061_Burn_Date_*.tif"))]
    out = pd.DataFrame(rows)
    out.to_parquet(CACHE, index=False)
    return out


def monthly_hotspots(cells: Path = CELLS) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    d = con.execute(f"""
        SELECT region, date_trunc('month', date)::DATE AS month,
               sum(mec) AS harmonized, sum(viirs_n) AS raw_viirs
        FROM read_parquet('{cells.as_posix()}')
        WHERE NOT provisional GROUP BY 1, 2""").df()
    return d.assign(month=pd.to_datetime(d["month"]))


def period_stats(g: pd.DataFrame) -> dict:
    return {"months": int(len(g)),
            "r_monthly": round(float(np.corrcoef(g["harmonized"], g["burned_km2"])[0, 1]), 3),
            "hotspots_per_km2": round(float(g["harmonized"].sum() / g["burned_km2"].sum()), 3)}


def compare(burned: pd.DataFrame, hot: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    m = burned.merge(hot, on=["region", "month"], how="inner")
    out = {}
    for region, g in m.groupby("region"):
        before, after = g[g["month"].dt.year < SWITCH_YEAR], g[g["month"].dt.year >= SWITCH_YEAR]
        out[region] = {
            "before_2012_modis": period_stats(before),
            "from_2012_harmonized": period_stats(after),
            "from_2012_raw_viirs_per_km2":
                round(float(after["raw_viirs"].sum() / after["burned_km2"].sum()), 3),
        }
    return out, m


def figure(m: pd.DataFrame) -> Path:
    """Hotspots per km2 burned, by year: harmonized should stay level across 2012."""
    y = m.assign(year=m["month"].dt.year).groupby(["region", "year"])[
        ["harmonized", "raw_viirs", "burned_km2"]].sum().reset_index()
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), sharex=True)
    for ax, region in zip(axes, REGIONS):
        g = y[y["region"] == region]
        after = g[g["year"] >= SWITCH_YEAR]
        ax.plot(g["year"], g["harmonized"] / g["burned_km2"], color="#c2410c", lw=2,
                marker="o", ms=4, label="FireBridge (MODIS to 2011, harmonized VIIRS after)")
        ax.plot(after["year"], after["raw_viirs"] / after["burned_km2"], color="#8fa3b8",
                lw=2, ls="--", label="Raw VIIRS")
        ax.axvline(SWITCH_YEAR, color="#999", lw=1)
        ax.set_yscale("log")
        plain = FuncFormatter(lambda v, _: f"{v:g}")
        ax.yaxis.set_major_formatter(plain)
        ax.yaxis.set_minor_formatter(plain)
        ax.tick_params(axis="y", which="minor", labelsize=8)
        ax.set_title(NAMES[region], loc="left", fontsize=11)
        ax.grid(axis="y", color="#e5e5e5", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Hotspots per km² burned (log)")
    axes[0].legend(loc="upper left", fontsize=8, frameon=False)
    fig.suptitle("Hotspots per area burned (MODIS MCD64A1), by year. Grey line: 2012 sensor switch.",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=150)
    plt.close(fig)
    return FIGURE


def main() -> None:
    res, merged = compare(monthly_burned(), monthly_hotspots())
    metrics = json.loads(METRICS.read_text())
    metrics["burned_area_check"] = res
    METRICS.write_text(json.dumps(metrics, indent=1))
    print(json.dumps(res, indent=1))
    print(f"updated {METRICS}, wrote {figure(merged)}")


if __name__ == "__main__":
    main()
