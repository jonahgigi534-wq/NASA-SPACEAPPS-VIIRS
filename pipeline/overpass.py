"""Overpass-time figure: when each satellite actually observed our regions, year by year.

acq_time in FIRMS is UTC. To compare regions on different longitudes we convert it to LOCAL
SOLAR TIME (UTC + longitude / 15 h), the time the satellite orbit is designed around.
Terra and Aqua have been drifting to earlier/later crossing times since ~2020 as their fuel
ran low; S-NPP and NOAA-20 are kept near 13:30 / 01:30. The figure shows that drift.

Output: results/figures/overpass_times.png
Run from the repo root:  python -m pipeline.overpass
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PROCESSED = Path("data/processed")
OUT = Path("results/figures/overpass_times.png")

# Fixed categorical order (colorblind-checked palette, slots 1-4) + distinct markers.
SATELLITES = [("Terra", "#2a78d6", "o"), ("Aqua", "#eb6834", "s"),
              ("S-NPP", "#1baf7a", "^"), ("NOAA-20", "#eda100", "D")]
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3de"
LABEL_NUDGE_PT = {"S-NPP": 7, "NOAA-20": -7}  # VIIRS lines end close together; keep labels apart


def yearly_overpass(processed: Path = PROCESSED):
    """Median and quartiles of local solar time per satellite x year x day/night (all regions)."""
    files = [f.as_posix() for f in sorted(processed.glob("fires_*_*.parquet"))]
    if not files:
        raise FileNotFoundError("Run python -m pipeline.ingest first")
    # Local solar hour; night passes are shifted by +24 h when before noon so 22:00-02:00
    # forms one continuous band instead of wrapping around midnight.
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")  # otherwise hour() uses the laptop's local time zone
    return con.sql(f"""
        WITH t AS (
            SELECT satellite, daynight, year(acq_date) AS year,
                   (hour(datetime_utc) + minute(datetime_utc) / 60.0 + lon / 15.0 + 24) % 24 AS h
            FROM read_parquet({files}) WHERE NOT is_provisional),
        s AS (SELECT *, CASE WHEN daynight = 'N' AND h < 12 THEN h + 24 ELSE h END AS hs FROM t)
        SELECT satellite, daynight, year, count(*) AS n,
               quantile_cont(hs, 0.25) AS q25, median(hs) AS med, quantile_cont(hs, 0.75) AS q75
        FROM s GROUP BY ALL HAVING count(*) >= 200 ORDER BY satellite, daynight, year""").df()


def _hhmm(h: float) -> str:
    h = h % 24
    return f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}"


def draw_panel(ax, df, daynight: str, title: str) -> None:
    for sat, color, marker in SATELLITES:
        d = df[(df["satellite"] == sat) & (df["daynight"] == daynight)]
        if d.empty:
            continue
        ax.fill_between(d["year"], d["q25"], d["q75"], color=color, alpha=0.15, linewidth=0)
        ax.plot(d["year"], d["med"], color=color, linewidth=2, marker=marker, markersize=5,
                markeredgecolor="white", markeredgewidth=0.8, label=sat)
        last = d.iloc[-1]
        ax.annotate(f"{sat} {_hhmm(last['med'])}", (last["year"], last["med"]),
                    xytext=(6, LABEL_NUDGE_PT.get(sat, 0)), textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _hhmm(v)))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_xlim(2000.5, 2029.5)


def main() -> None:
    df = yearly_overpass()
    fig, (ax_d, ax_n) = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True)
    draw_panel(ax_d, df, "D", "Daytime detections")
    draw_panel(ax_n, df, "N", "Night-time detections")
    for ax in (ax_d, ax_n):
        ax.set_ylabel("Local solar time (h:mm)", fontsize=9, color=MUTED)
    ax_n.set_xlabel("Year", fontsize=9, color=MUTED)
    ax_d.legend(loc="upper left", ncols=4, frameon=False, fontsize=9)
    fig.suptitle("When each satellite observes our regions: median overpass time by year",
                 x=0.06, ha="left", fontsize=13, color=INK)
    fig.text(0.06, 0.005, "Line = median local solar time of FIRMS detections (archive, all 3 regions); "
             "band = middle 50%. Local solar time = UTC + longitude/15.", fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, facecolor="white")
    print(f"wrote {OUT}")
    print(df[df["year"].isin([2003, 2012, 2018, 2020, 2022, 2024, 2025, 2026])]
          .assign(med=lambda d: d["med"].map(_hhmm))[["satellite", "daynight", "year", "med", "n"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
