"""Figures for the validation (results/figures/). Colors are fixed per series everywhere:
harmonized = blue, raw VIIRS = orange, global ratio = green, MODIS reference = grey
(colorblind-checked palette; every series is also labelled, never color alone)."""
from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FIG_DIR = Path("results/figures")
APP_DIR = Path("data/app")
COLORS = {"harmonized": "#2a78d6", "raw_viirs": "#eb6834", "global_ratio": "#1baf7a", "modis": "#8a8984"}
LABELS = {"harmonized": "Harmonized", "raw_viirs": "Raw VIIRS", "global_ratio": "One global ratio",
          "modis": "MODIS (Terra+Aqua)"}
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3de"
SWITCHES = [("2012-01-20", "VIIRS S-NPP starts"), ("2018-04-01", "NOAA-20 starts")]


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_axisbelow(True)


def _save(fig, name: str) -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return path


# ---------------------------------------------------------------- scatter

def scatter_figure(holdout: pd.DataFrame, winner: str) -> Path:
    """Per 0.25 deg cell-month on the 2019+ holdout: Aqua vs raw VIIRS, Aqua vs harmonized."""
    cells = holdout.groupby(["region", "cell_id", "month"])[["obs", "raw_viirs", winner]].sum()
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), sharex=True, sharey=True)
    top = np.log1p(max(cells["obs"].max(), cells["raw_viirs"].max()))
    ticks = [0, 1, 3, 10, 30, 100, 300, 1000]
    for ax, col, title in ((axes[0], "raw_viirs", "Before: raw VIIRS S-NPP"),
                           (axes[1], winner, f"After: harmonized ({winner})")):
        x, y = np.log1p(cells["obs"]), np.log1p(cells[col])
        hb = ax.hexbin(x, y, gridsize=55, bins="log", cmap="Blues", mincnt=1, linewidths=0)
        ax.plot([0, top], [0, top], color=INK, linewidth=1, linestyle="--")
        ax.text(top * 0.97, top * 0.9, "1:1", ha="right", color=INK, fontsize=9)
        bias = 100 * (cells[col].sum() - cells["obs"].sum()) / cells["obs"].sum()
        ax.set_title(f"{title}\nbias {bias:+.0f}% vs Aqua", loc="left", fontsize=11, color=INK)
        ax.set_xticks(np.log1p(ticks), ticks)
        ax.set_yticks(np.log1p(ticks), ticks)
        ax.set_xlabel("MODIS Aqua hotspots per cell-month", fontsize=9, color=MUTED)
        _style(ax)
    axes[0].set_ylabel("VIIRS-based hotspots per cell-month", fontsize=9, color=MUTED)
    fig.suptitle("Test period 2019+, every 0.25° cell-month in all 3 regions (log axes)",
                 x=0.05, y=0.99, ha="left", fontsize=12, color=INK)
    fig.subplots_adjust(top=0.82, left=0.08, right=0.86, bottom=0.12, wspace=0.12)
    cb = fig.colorbar(hb, cax=fig.add_axes((0.89, 0.15, 0.015, 0.62)))
    cb.set_label("cell-months (log scale)", fontsize=9, color=MUTED)
    return _save(fig, "scatter_before_after.png")


# ---------------------------------------------------------------- bias bars

def bias_figure(res: dict, winner: str, clip: float = 150) -> Path:
    """Bias % of monthly regional totals, per region, for raw / global ratio / harmonized."""
    series = [("raw_viirs", "raw_viirs"), ("global_ratio", "global_ratio"), ("harmonized", winner)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
    for ax, test, title in ((axes[0], "holdout", "Holdout: S-NPP vs Aqua, 2019+"),
                            (axes[1], "transfer_noaa20", "Transfer: NOAA-20 vs Aqua (never fitted)")):
        tot = res[test]["monthly_totals"]
        regions = [r for r in tot if r != "overall"] + ["overall"]
        y = np.arange(len(regions))
        for i, (key, method) in enumerate(series):
            vals = np.array([tot[r][method]["bias_pct"] for r in regions])
            pos = y + (i - 1) * 0.26
            ax.barh(pos, np.clip(vals, -clip, clip), height=0.24, color=COLORS[key], label=LABELS[key])
            for p, v in zip(pos, vals):
                ax.text(min(max(v, -clip), clip) + (3 if v >= 0 else -3), p, f"{v:+.0f}%",
                        va="center", ha="left" if v >= 0 else "right", fontsize=8, color=INK)
        ax.axvline(0, color=INK, linewidth=0.8)
        ax.set_yticks(y, [r.title() for r in regions])
        ax.set_xlim(-clip * 0.6, clip * 1.25)
        ax.set_xlabel(f"Bias of monthly totals vs MODIS Aqua (%), bars clipped at ±{clip:.0f}%",
                      fontsize=9, color=MUTED)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        _style(ax)
    axes[0].invert_yaxis()
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncols=3, frameon=False, fontsize=9)
    fig.suptitle("How far each method is from MODIS (0% = perfect agreement)",
                 x=0.05, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    return _save(fig, "bias_before_after.png")


# ---------------------------------------------------------------- continuity

def monthly_series(app_dir: Path = APP_DIR) -> pd.DataFrame:
    con = duckdb.connect()
    return con.execute(f"""
        SELECT region, date_trunc('month', date)::DATE AS month,
            sum(mec) AS harmonized, sum(modis_n) AS modis,
            sum(CASE WHEN source = 'MODIS' THEN modis_n ELSE viirs_n END) AS naive,
            bool_or(provisional) AS provisional, max(date) AS last_day
        FROM read_parquet('{(app_dir / "cells_daily.parquet").as_posix()}') GROUP BY ALL
        ORDER BY region, month""").df()


def continuity_figure(df: pd.DataFrame, region: str) -> Path:
    d = df[df["region"] == region].copy()
    d["month"] = pd.to_datetime(d["month"])
    full = pd.to_datetime(d["last_day"]) >= d["month"] + pd.offsets.MonthEnd(0)
    d = d[full | (d["month"] < d["month"].max())]   # drop a final partial month
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(d["month"], d["naive"], color=COLORS["raw_viirs"], linewidth=1.4,
            label="Naive record: MODIS, then raw VIIRS")
    ax.plot(d["month"], d["harmonized"], color=COLORS["harmonized"], linewidth=2.2,
            label="Harmonized record (MODIS scale)")
    # drawn last and dotted so it stays visible where it overlaps the harmonized line
    ax.plot(d["month"], d["modis"], color="#3d3d3a", linewidth=0.9, linestyle=":",
            label="MODIS Terra+Aqua (reference, all years)")
    ymax = d[["naive", "harmonized", "modis"]].max().max()
    for when, label in SWITCHES:
        ax.axvline(pd.Timestamp(when), color=INK, linewidth=0.8, linestyle="--")
        ax.text(pd.Timestamp(when), ymax * 1.02, f" {label}", fontsize=8, color=INK, va="bottom")
    prov = d[d["provisional"]]
    if len(prov):
        ax.axvspan(prov["month"].min(), d["month"].max() + pd.offsets.MonthEnd(0), color=GRID, alpha=0.7, linewidth=0)
        ax.text(prov["month"].min(), ymax * 0.92, " provisional\n (NRT)", fontsize=8, color=MUTED)
    ax.set_ylim(0, ymax * 1.12)
    ax.set_ylabel("Hotspots per month", fontsize=9, color=MUTED)
    ax.set_title(f"{region.title()}: monthly hotspots 2001 → now. The naive record jumps when VIIRS "
                 "starts; the harmonized one continues on the MODIS scale",
                 loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    _style(ax)
    fig.tight_layout()
    return _save(fig, f"continuity_{region}.png")


def continuity_figures(app_dir: Path = APP_DIR) -> list[Path]:
    df = monthly_series(app_dir)
    paths = []
    for region in sorted(df["region"].unique()):
        paths.append(continuity_figure(df, region))
        d = df[(df["region"] == region) & (pd.to_datetime(df["month"]).dt.year.between(2012, 2021))]
        print(f"{region}: 2012-2021 harmonized / MODIS = {d['harmonized'].sum() / d['modis'].sum():.3f}, "
              f"naive / MODIS = {d['naive'].sum() / d['modis'].sum():.3f}")
    return paths
