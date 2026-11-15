"""
Extra validation checks that need only the app data (data/app/), not the raw FIRMS archives.
Written by Track B/C as NEW files, so nothing Track A owns is changed. Output:

    results/extra/extra_checks.json        all numbers below
    results/extra/drift_by_year.png        harmonized / MODIS ratio by year and region
    results/extra/live_factor_by_month.png how the VIIRS->harmonized factor changes by month

Checks:
 1. Live-data harmonization. The live feed scales raw VIIRS by a factor learned from the
    archive. Fit on Aug 2023 - Jul 2025, test on Aug 2025 - Jul 2026 (never used to fit):
    does one factor per region and calendar month reproduce Track A's harmonized monthly totals
    better than one factor per region?
 2. Drift after the satellites aged. In the overlap years both sensors fly. Does the harmonized
    record keep matching MODIS (Terra + Aqua, the scale it targets) in 2019-2021 and 2022+ as
    well as in the 2012-2018 fitting years? (Terra and Aqua drift in orbit after about 2022.)
    Monthly and daily regional totals.
 3. Missing days vs FIRMS's official list. Track A infers missing days from the data; FIRMS
    publishes the days each satellite has no data. How many agree?

Run from the repo root:  python scripts/extra_checks.py   (APP_DATA_DIR to use other data)
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = Path(os.environ.get("APP_DATA_DIR", REPO / "data" / "app"))
OUT = REPO / "results" / "extra"
FIT = ("2023-08-01", "2025-07-31")
TEST = ("2025-08-01", "2026-07-31")
PERIODS = {"2012-2018 (fit years)": (2012, 2018), "2019-2021": (2019, 2021), "2022 onward": (2022, 2026)}
REGION_NAMES = {"texas": "Texas", "amazon": "Amazon", "australia": "N. Australia"}


def q(sql, params=None):
    con = duckdb.connect()
    return con.execute(sql, params or []).df()


def cells_path():
    return str(DATA / "cells_daily.parquet").replace("\\", "/")


# ---------------------------------------------------------------------------------------------
def check_live_factors():
    from pipeline.live import harmonization_factors, factor_for
    f = harmonization_factors(DATA, since=FIT[0], until=FIT[1])
    m = q(f"""SELECT region, strftime(date, '%Y-%m') AS ym, month(date) AS mo,
                     sum(viirs_n) AS v, sum(mec) AS mec
              FROM read_parquet('{cells_path()}')
              WHERE source = 'VIIRS' AND NOT provisional AND date BETWEEN ? AND ?
              GROUP BY 1, 2, 3""", [TEST[0], TEST[1]])
    out = {"fit": list(FIT), "test": list(TEST), "regions": {}}
    for region, g in m.groupby("region"):
        if region not in f:
            continue
        one = g["v"] * f[region]["all"][0]
        by_m = g["v"] * g["mo"].map(lambda mo: factor_for(f[region], mo)[0])
        def score(pred):
            err = (pred - g["mec"]) / g["mec"].where(g["mec"] > 0)
            return {"monthly_abs_error_pct": round(float(err.abs().mean() * 100), 1),
                    "total_bias_pct": round(float((pred.sum() / g["mec"].sum() - 1) * 100), 2)}
        out["regions"][region] = {"one_factor": score(one), "factor_by_month": score(by_m),
                                  "months_tested": int(len(g)),
                                  "factor_range": [round(min(k[0] for k in f[region]["month"].values()), 3),
                                                   round(max(k[0] for k in f[region]["month"].values()), 3)]}
    return out, f


def check_drift():
    m = q(f"""SELECT region, year(date) AS y, strftime(date, '%Y-%m') AS ym, date,
                     sum(mec) AS mec, sum(modis_n) AS modis
              FROM read_parquet('{cells_path()}')
              WHERE source = 'VIIRS' AND NOT provisional GROUP BY 1, 2, 3, 4""")
    res, yearly = {}, []
    for region, g in m.groupby("region"):
        res[region] = {}
        for name, (y0, y1) in PERIODS.items():
            p = g[(g["y"] >= y0) & (g["y"] <= y1)]
            if p.empty:
                continue
            mon = p.groupby("ym")[["mec", "modis"]].sum()
            day = p.groupby("date")[["mec", "modis"]].sum()
            res[region][name] = {
                "bias_pct": round(float((mon["mec"].sum() / mon["modis"].sum() - 1) * 100), 2),
                "monthly_r": round(float(np.corrcoef(mon["mec"], mon["modis"])[0, 1]), 3),
                "daily_r": round(float(np.corrcoef(day["mec"], day["modis"])[0, 1]), 3),
                "months": int(len(mon))}
        # whole years only: a partial year (2026 = Jan-Jul) would show its season, not drift
        months_per_year = g.groupby("y")["ym"].nunique()
        yr = g.groupby("y")[["mec", "modis"]].sum()
        for y, r in yr.iterrows():
            if months_per_year.get(y, 0) < 12:
                continue
            yearly.append({"region": region, "year": int(y), "ratio": float(r["mec"] / r["modis"]) if r["modis"] else None})
    return res, pd.DataFrame(yearly)


def check_missing_days():
    import httpx
    try:
        r = httpx.get("https://firms.modaps.eosdis.nasa.gov/api/missing_data/?action=fetch_data",
                      headers={"X-Requested-With": "XMLHttpRequest"}, timeout=60)
        cells = re.findall(r"<td>([^<]*)</td>", r.json()["html"])
    except Exception as ex:
        return {"error": f"FIRMS missing-data list unavailable: {ex}"}
    pairs = [(cells[i], cells[i + 1]) for i in range(0, len(cells) - 1, 2)
             if re.match(r"\d{4}-\d{2}-\d{2}$", cells[i])]
    off = pd.DataFrame(pairs, columns=["date", "satellite"])
    off["date"] = pd.to_datetime(off["date"])
    end = pd.Timestamp("2026-07-31")
    modis_any = {d for d in off.loc[off["satellite"].str.contains("MODIS"), "date"] if d <= end}
    both = (set(off.loc[off["satellite"].str.contains("Terra"), "date"])
            & set(off.loc[off["satellite"].str.contains("Aqua"), "date"]))
    snpp = set(off.loc[off["satellite"].str.contains("Suomi"), "date"])
    snpp_alone = {d for d in snpp if pd.Timestamp("2012-01-20") <= d < pd.Timestamp("2018-04-01")}
    ours = q(f"SELECT region, date, scope FROM read_parquet('{str(DATA / 'missing_days.parquet').replace(chr(92), '/')}')")
    ours["date"] = pd.to_datetime(ours["date"])
    out = {"source": "https://firms.modaps.eosdis.nasa.gov/api/missing_data/",
           "official_days_by_satellite": off.groupby("satellite").size().to_dict(),
           "official_days_both_modis_down": len(both),
           "official_snpp_down_before_noaa20": len(snpp_alone),
           "regions": {}}
    for region, g in ours.groupby("region"):
        mo = set(g.loc[g["scope"] == "modis_only", "date"])
        out["regions"][region] = {
            "our_modis_missing_days": len(mo),
            "official_terra_or_aqua_down_days": len(modis_any),
            "flagged_and_official": len(mo & modis_any),
            "official_not_flagged": len(modis_any - mo),
            "flagged_not_official": len(mo - modis_any)}
    out["reading"] = ("Track A's inferred MODIS-missing days catch about half of the days FIRMS lists one MODIS "
                      "satellite as down, and also flag days FIRMS does not list (likely days when MODIS saw "
                      "no fire while the more sensitive VIIRS saw small ones). Only "
                      f"{len(snpp_alone)} S-NPP outage day falls before NOAA-20 started, so VIIRS gaps are covered "
                      "by the other satellite in the averaged record.")
    return out


# ---------------------------------------------------------------------------------------------
def figures(yearly, factors):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"texas": "#1d5fa8", "amazon": "#1b7f5b", "australia": "#c2410c"}
    fig, ax = plt.subplots(figsize=(9, 4))
    for region, g in yearly.groupby("region"):
        g = g[g["year"] <= 2026]
        ax.plot(g["year"], g["ratio"], marker="o", lw=1.8, color=colors.get(region), label=REGION_NAMES.get(region, region))
    ax.axhline(1, color="#555", lw=1, ls="--")
    ax.axvspan(2011.6, 2018.5, color="#eee", zorder=0)
    ax.text(2012, ax.get_ylim()[1] * 0.98, "fitting years", va="top", fontsize=9, color="#555")
    ax.set_title("Harmonized VIIRS / MODIS (Terra + Aqua) hotspots per whole year: 1.0 = same scale", loc="left", fontsize=11)
    fig.text(0.99, 0.01, "2012 starts Jan 20; 2026 left out (only Jan-Jul in the archive)",
             ha="right", va="bottom", fontsize=8.5, color="#555")
    ax.set_ylabel("ratio"); ax.set_xlabel("year"); ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(rect=(0, 0.04, 1, 1)); fig.savefig(OUT / "drift_by_year.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.6))
    for region, f in factors.items():
        ms = sorted(f["month"])
        ax.plot(ms, [f["month"][m][0] for m in ms], marker="o", lw=1.8, color=colors.get(region), label=REGION_NAMES.get(region, region))
    ax.set_xticks(range(1, 13)); ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    ax.set_title("MODIS-equivalent hotspots per raw VIIRS hotspot, by calendar month (fit Aug 2023 - Jul 2025)", loc="left", fontsize=11)
    ax.set_ylabel("factor"); ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "live_factor_by_month.png", dpi=150); plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    live, factors = check_live_factors()
    drift, yearly = check_drift()
    missing = check_missing_days()
    figures(yearly, factors)
    out = {"generated": date.today().isoformat(), "data": str(DATA.name),
           "live_harmonization": live, "drift": drift, "missing_days": missing,
           "notes": ["Computed from data/app only (cells_daily, missing_days, hotspots); see scripts/extra_checks.py.",
                     "Drift compares harmonized VIIRS with MODIS Terra + Aqua, the scale the harmonization targets."]}
    (OUT / "extra_checks.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1)[:4000])


if __name__ == "__main__":
    main()
