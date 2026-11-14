"""Validate the harmonization (CLAUDE.md 4.5) and write results/metrics.json + figures.

Tests (the VIIRS count is mapped to an Aqua-equivalent count and compared with real Aqua):
  holdout          S-NPP vs Aqua, 2019-01 .. archive end   (model fitted on 2012-2018 only)
  transfer_noaa20  NOAA-20 vs Aqua, 2018-04 .. archive end (NOAA-20 never used in fitting)
Scores, per region and overall, on
  monthly regional totals  (what the app's calendar shows)  -> results/metrics.json
  single 0.25 deg cell-months                                -> results/metrics_detail.json
Metrics: r2 = 1 - SSE/SST against the 1:1 line (not just correlation), bias_pct = 100 x
(sum predicted - sum observed) / sum observed, rmse (hotspots), r = Pearson correlation.
Winner: lowest normalized RMSE (RMSE / mean observed) of monthly regional totals on the
holdout, averaged over regions so the big regions don't drown out Texas.

Run from the repo root:
  python -m pipeline.validate               metrics + scatter/bias figures
  python -m pipeline.validate --continuity  continuity figures from data/app (after build_app_data)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import harmonize as hz
from pipeline.validate_figures import bias_figure, continuity_figures, scatter_figure

RESULTS = Path("results")
TEST_START = pd.Timestamp("2019-01-01")
TRANSFER_START = pd.Timestamp("2018-04-01")
DRIFT_START = pd.Timestamp("2022-01-01")
BASELINES = ("raw_viirs", "global_ratio")
SHOW = (*BASELINES, *hz.METHODS)


def scores(obs, pred) -> dict:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    sse, sst = ((pred - obs) ** 2).sum(), ((obs - obs.mean()) ** 2).sum()
    r = np.corrcoef(obs, pred)[0, 1] if obs.std() > 0 and pred.std() > 0 else float("nan")
    return {"r2": round(float(1 - sse / sst), 4) if sst > 0 else None,
            "bias_pct": round(float(100 * (pred.sum() - obs.sum()) / obs.sum()), 2),
            "rmse": round(float(np.sqrt(sse / len(obs))), 3),
            "r": round(float(r), 4), "n": int(len(obs))}


def with_predictions(rows: pd.DataFrame, models: dict, mcol: str, vcol: str) -> pd.DataFrame:
    out = rows[["region", "cell_id", "month", "daynight"]].copy()
    out["obs"] = rows[mcol].to_numpy(float)
    for m in SHOW:
        out[m] = hz.predict(m, models, rows, vcol)
    return out


def level(df: pd.DataFrame, by) -> pd.DataFrame:
    return df.groupby(by, as_index=False)[["obs", *SHOW]].sum()


def test_scores(pred: pd.DataFrame) -> dict:
    """{level: {region|overall: {method: scores}}} for monthly totals and per cell."""
    out = {}
    for name, by in (("monthly_totals", ["region", "month"]), ("per_cell", ["region", "cell_id", "month"])):
        agg = level(pred, by)
        res = {r: {m: scores(g["obs"], g[m]) for m in SHOW} for r, g in agg.groupby("region")}
        res["overall"] = {m: scores(agg["obs"], agg[m]) for m in SHOW}
        out[name] = res
    return out


def normalized_rmse(pred: pd.DataFrame) -> dict:
    agg = level(pred, ["region", "month"])
    out = {}
    for m in SHOW:
        per_region = {r: float(np.sqrt(((g[m] - g["obs"]) ** 2).mean()) / g["obs"].mean())
                      for r, g in agg.groupby("region")}
        out[m] = {"per_region": {k: round(v, 4) for k, v in per_region.items()},
                  "mean": round(float(np.mean(list(per_region.values()))), 4)}
    return out


def run_variant(pairs: pd.DataFrame, models: dict, variant: str) -> dict:
    mcol, vcol = hz.VARIANTS[variant]
    m = models[variant]
    snpp = pairs[pairs["viirs_sat"] == "S-NPP"]
    noaa = pairs[(pairs["viirs_sat"] == "NOAA-20") & (pairs["month"] >= TRANSFER_START)]
    hold = with_predictions(snpp[snpp["month"] >= TEST_START], m, mcol, vcol)
    trans = with_predictions(noaa, m, mcol, vcol)
    return {
        "holdout": test_scores(hold),
        "holdout_2019_2021": test_scores(hold[hold["month"] < DRIFT_START]),
        "holdout_2022_on": test_scores(hold[hold["month"] >= DRIFT_START]),
        "transfer_noaa20": test_scores(trans),
        "nrmse_holdout": normalized_rmse(hold),
        "nrmse_transfer": normalized_rmse(trans),
        "_frames": {"holdout": hold, "transfer": trans},
    }


def contract_metrics(res: dict, winner: str, test_end: int, notes: list[str]) -> dict:
    """results/metrics.json in exactly the docs/CONTRACTS.md section 3 shape."""
    pick = {"raw_viirs": "raw_viirs", "global_ratio": "global_ratio", "harmonized": winner}

    def block(test, region):
        return {k: {s: res[test]["monthly_totals"][region][m][s] for s in ("r2", "bias_pct", "rmse", "r")}
                for k, m in pick.items()}

    regions = [r for r in res["holdout"]["monthly_totals"] if r != "overall"]
    return {"winner": winner, "baseline_years": [2012, 2018], "test_years": [2019, test_end],
            "overall": {"holdout": block("holdout", "overall"), "transfer_noaa20": block("transfer_noaa20", "overall")},
            "regions": {r: {"holdout": block("holdout", r), "transfer_noaa20": block("transfer_noaa20", r)}
                        for r in regions},
            "notes": notes}


def build_notes(res: dict, winner: str, models: dict) -> list[str]:
    n = res["nrmse_holdout"]
    return [
        "Scores compare monthly regional totals of Aqua-equivalent counts against real MODIS Aqua, "
        "on test data the models never saw (2019 onward), and on NOAA-20, which was never used in fitting.",
        "'overall' pools all region-months; because regions differ a lot in size this inflates r2, "
        "so read the per-region numbers too.",
        f"Winner {winner} chosen by lowest mean normalized RMSE across regions on the holdout "
        f"({n[winner]['mean']:.3f} vs global ratio {n['global_ratio']['mean']:.3f}).",
        "From 2022 Terra and Aqua drift off their original overpass times (results/overpass_times.md), "
        "so the MODIS reference itself changes; holdout scores for 2019-2021 and 2022+ are reported "
        "separately in results/metrics_detail.json.",
        f"Land-cover groups (MCD12Q1) used for: {', '.join(models['landcover_used']) or 'none'}.",
        "The harmonized record is on the Terra+Aqua scale: Aqua-equivalent counts are multiplied by the "
        "2003-2018 (Terra+Aqua)/Aqua ratio per region, day/night and calendar month.",
        "Harmonized FRP (mefrp) uses one global FRP ratio and is not separately validated.",
    ]


def strip_frames(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "_frames"}


def report(main_res: dict, nonlow: dict, winner: str) -> None:
    for test in ("holdout", "holdout_2019_2021", "holdout_2022_on", "transfer_noaa20"):
        print(f"\n=== {test}: monthly regional totals (r2 / bias% / rmse) ===")
        for region, ms in main_res[test]["monthly_totals"].items():
            print(f"{region:10s} " + "  ".join(
                f"{m}: {ms[m]['r2']}/{ms[m]['bias_pct']:+.1f}/{ms[m]['rmse']:.0f}" for m in SHOW))
    for key in ("nrmse_holdout", "nrmse_transfer"):
        print(f"\n{key}:", {m: main_res[key][m] for m in SHOW})
    print("\nno-low-confidence holdout nRMSE:", {m: nonlow["nrmse_holdout"][m]["mean"] for m in SHOW})
    print("per-cell holdout overall:", {m: main_res["holdout"]["per_cell"]["overall"][m] for m in SHOW})
    print(f"\nWINNER: {winner}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--continuity", action="store_true", help="only draw continuity_<region>.png")
    args = ap.parse_args(argv)
    if args.continuity:
        for f in continuity_figures():
            print(f"wrote {f}")
        return
    pairs = pd.read_parquet(hz.PAIRS_PATH)
    models = hz.load_models()
    res = {v: run_variant(pairs, models, v) for v in hz.VARIANTS}
    main_res = res["all"]
    winner = min(hz.METHODS, key=lambda m: main_res["nrmse_holdout"][m]["mean"])
    metrics = contract_metrics(main_res, winner, int(pairs["month"].max().year),
                               build_notes(main_res, winner, models))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, indent=1))
    detail = {"winner": winner, "global_ratio_snpp_per_aqua": models["all"]["global_ratio"],
              "main": strip_frames(main_res), "sensitivity_no_low_confidence": strip_frames(res["nonlow"])}
    (RESULTS / "metrics_detail.json").write_text(json.dumps(detail, indent=1))
    frames = main_res["_frames"]
    print("wrote", scatter_figure(frames["holdout"], winner), bias_figure(main_res, winner))
    report(main_res, res["nonlow"], winner)


if __name__ == "__main__":
    main()
