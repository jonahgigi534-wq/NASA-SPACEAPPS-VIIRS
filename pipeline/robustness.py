"""Two robustness checks added to results/metrics.json (docs/CONTRACTS.md section 3).

1. leave_one_region_out: can the translation travel to a region it never saw? For each region,
   fit B_qm (and the one-global-ratio baseline) on the OTHER two regions' 2012-2018 S-NPP/Aqua
   pairs, pooled by land cover x day/night, then score the held-out region's test years (2019 on)
   at validate.py's main level (monthly regional totals).
2. drift_vs_modis: harmonized VIIRS vs MODIS Terra + Aqua (the scale the app shows), bias by
   period, from data/app/cells_daily.parquet. Terra and Aqua drift in orbit after about 2022, so a
   change after 2022 is the reference moving, not necessarily the translation.

Runs after `validate` (which writes metrics.json) and `app` (which writes data/app).
Run from the repo root:  python -m pipeline.robustness
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from pipeline import harmonize as hz
from pipeline.validate import TEST_START, scores

METRICS = Path("results/metrics.json")
CELLS = Path("data/app/cells_daily.parquet")
METHOD = "B_qm"
MCOL, VCOL = hz.VARIANTS["all"]
PERIODS = {"2012-2018": (2012, 2018), "2019-2021": (2019, 2021), "2022_on": (2022, 9999)}
POOLED = "pooled"


def monthly_scores(rows: pd.DataFrame, pred: np.ndarray) -> dict:
    """Bias, R2 and normalized RMSE of monthly regional totals (validate.py's main level)."""
    agg = rows.assign(pred=pred).groupby("month")[[MCOL, "pred"]].sum()
    s = scores(agg[MCOL], agg["pred"])
    nrmse = float(np.sqrt(((agg["pred"] - agg[MCOL]) ** 2).mean()) / agg[MCOL].mean())
    return {"bias_pct": s["bias_pct"], "r2": s["r2"], "nrmse": round(nrmse, 4), "months": int(len(agg))}


def leave_one_region_out(pairs: pd.DataFrame, own_models: dict) -> dict:
    train = hz.train_rows(pairs)
    snpp = pairs[(pairs["viirs_sat"] == "S-NPP") & (pairs["month"] >= TEST_START)]
    out = {}
    for region in sorted(pairs["region"].unique()):
        others = train[train["region"] != region].assign(region=POOLED)
        pooled = {METHOD: hz.fit_method(METHOD, others, MCOL, VCOL),
                  "global_ratio": hz.global_ratio(others, MCOL, VCOL)}
        test = snpp[snpp["region"] == region]
        as_pooled = test.assign(region=POOLED)
        out[region] = {
            "fit_on": sorted(set(train["region"]) - {region}),
            "own_region_fit": monthly_scores(test, hz.predict(METHOD, own_models, test, VCOL)),
            "other_regions_fit": monthly_scores(test, hz.predict(METHOD, pooled, as_pooled, VCOL)),
            "other_regions_global_ratio": monthly_scores(
                test, hz.predict("global_ratio", pooled, as_pooled, VCOL)),
        }
    return out


def drift_vs_modis(cells: Path = CELLS) -> dict:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    m = con.execute(f"""
        SELECT region, year(date) AS y, sum(mec) AS mec, sum(modis_n) AS modis,
               count(DISTINCT date_trunc('month', date)) AS months
        FROM read_parquet('{cells.as_posix()}')
        WHERE source = 'VIIRS' AND NOT provisional GROUP BY 1, 2""").df()
    out = {}
    for region, g in m.groupby("region"):
        out[region] = {}
        for name, (y0, y1) in PERIODS.items():
            p = g[g["y"].between(y0, y1)]
            if p.empty or p["modis"].sum() == 0:
                continue
            out[region][name] = {
                "bias_pct": round(float((p["mec"].sum() / p["modis"].sum() - 1) * 100), 2),
                "months": int(p["months"].sum())}
    return out


def main() -> None:
    metrics = json.loads(METRICS.read_text())
    pairs = pd.read_parquet(hz.PAIRS_PATH)
    own = hz.load_models()["all"]
    metrics["leave_one_region_out"] = leave_one_region_out(pairs, own)
    metrics["drift_vs_modis"] = drift_vs_modis()
    METRICS.write_text(json.dumps(metrics, indent=1))
    for region, r in metrics["leave_one_region_out"].items():
        print(f"{region:10s} own   {r['own_region_fit']}\n{'':10s} other {r['other_regions_fit']}\n"
              f"{'':10s} ratio {r['other_regions_global_ratio']}")
    print(json.dumps(metrics["drift_vs_modis"]))
    print(f"updated {METRICS}")


if __name__ == "__main__":
    main()
