"""Find the biggest real fire anomalies in the harmonized record -> docs/presets.json.

Anomaly = a month's harmonized hotspot count (mec) as % of the median of the same calendar month
over the app's default baseline 2003-2022 (CLAUDE.md section 5). Only "fire months" count: the
month's median must be at least the region's typical (median) month, so a quiet month going
from 5 to 30 hotspots can't win. Adjacent months that are also >= 200% join the same event.

Selection (reproducible, see `pick`): the biggest event in each region, then the next biggest
event anywhere, ranked by peak-month % of median. At most one event per region-year.

Each preset's bbox is where the extra fire was: 1 deg blocks ranked by excess over their own
median until they hold half the event's excess, boxed, then clipped to the region. The % of
median in "why" is recomputed for exactly that bbox (cells whose centres are inside it, as the
app does) using the same window rule as /api/summary.

Run from the repo root:  python -m pipeline.presets
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from pipeline.build_app_data import region_bboxes
from pipeline.science_check import Expected, same_window, window_total

CELLS = Path("data/app/cells_daily.parquet")
OUT = Path("docs/presets.json")
BASELINE = (2003, 2022)
JOIN_PCT = 200          # adjacent months at/above this join the event
BLOCK = 1.0             # degrees, for locating the anomaly
EXCESS_SHARE = 0.5      # bbox holds the blocks with this share of the event's excess
N_PRESETS = 4
NAMES = {"texas": "Texas", "amazon": "Amazon arc of deforestation", "australia": "Northern Australia"}
NEAR_ZERO = 100         # box median below this: say so, the % alone reads oddly
# Place names + one line of context for events the data picked (keyed by region, first year).
# Only labels: every number in "why" comes from the data. Unknown events get the default name.
CONTEXT = {
    ("texas", 2011): ("West Texas and northern Mexico",
                      "Texas's record 2011 drought fire season."),
    ("texas", 2022): ("Northern New Mexico (Texas region box)",
                      "The box is the Sangre de Cristo mountains, where the Hermits Peak / Calf "
                      "Canyon fire burned in spring 2022."),
    ("amazon", 2023): ("Rondonia / Bolivia border",
                       "Late-season burning during the 2023 Amazon drought."),
    ("australia", 2011): ("Northern Australia savannas",
                          "Heavy grass fuel after the very wet 2010-11 La Nina years."),
}


def _cells() -> str:
    return CELLS.as_posix()


def monthly(con, by_block: bool = False) -> pd.DataFrame:
    block = (f", floor(lat / {BLOCK})::INT AS by, floor(lon / {BLOCK})::INT AS bx"
             if by_block else "")
    # complete months only (the last month of data may be partial)
    return con.execute(f"""
        SELECT region, date_trunc('month', date)::DATE AS mon{block}, sum(mec) AS v
        FROM read_parquet('{_cells()}')
        WHERE date < (SELECT date_trunc('month', max(date)) FROM read_parquet('{_cells()}'))
        GROUP BY ALL""").df()


def with_median(m: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Add the baseline median of the same calendar month (zero-filled: no fire = 0)."""
    m = m.assign(year=pd.to_datetime(m["mon"]).dt.year, cal=pd.to_datetime(m["mon"]).dt.month)
    years = list(range(BASELINE[0], BASELINE[1] + 1))
    base = m[m["year"].between(*BASELINE)].pivot_table(index=keys + ["cal"], columns="year",
                                                         values="v", aggfunc="sum")
    base = base.reindex(columns=years).fillna(0)
    med = base.median(axis=1).rename("med").reset_index()
    return m.merge(med, on=keys + ["cal"], how="left").fillna({"med": 0})


def events(m: pd.DataFrame) -> pd.DataFrame:
    """Peak months -> events (adjacent >= JOIN_PCT months merged), ranked by peak % of median."""
    typical = m.groupby("region")["v"].median()
    m = m.assign(pct=100 * m["v"] / m["med"].where(m["med"] > 0))
    out, used = [], set()
    fire = m[m["med"] >= m["region"].map(typical)]
    for row in fire.sort_values("pct", ascending=False).itertuples():
        if (row.region, row.mon) in used:
            continue
        g = m[m["region"] == row.region].sort_values("mon").reset_index(drop=True)
        i = g.index[g["mon"] == row.mon][0]
        lo = hi = i
        while lo > 0 and g.loc[lo - 1, "pct"] >= JOIN_PCT:
            lo -= 1
        while hi < len(g) - 1 and g.loc[hi + 1, "pct"] >= JOIN_PCT:
            hi += 1
        months = list(g.loc[lo:hi, "mon"])
        used.update((row.region, mo) for mo in months)
        out.append({"region": row.region, "months": months, "peak_pct": row.pct,
                    "year": pd.Timestamp(row.mon).year})
    return pd.DataFrame(out)


def pick(ev: pd.DataFrame, n: int = N_PRESETS) -> pd.DataFrame:
    ev = ev.drop_duplicates(["region", "year"])
    first = ev.groupby("region", sort=False).head(1)
    rest = ev.drop(first.index).head(max(n - len(first), 0))
    return pd.concat([first, rest]).sort_values("peak_pct", ascending=False).head(n)


def event_bbox(blocks: pd.DataFrame, region: str, months: list, region_box: list) -> list[float]:
    b = blocks[(blocks["region"] == region) & (blocks["mon"].isin(months))]
    ex = (b["v"] - b["med"]).groupby([b["by"], b["bx"]]).sum()
    ex = ex[ex > 0].sort_values(ascending=False)
    keep = ex[ex.cumsum().shift(fill_value=0) < EXCESS_SHARE * ex.sum()]
    ys, xs = keep.index.get_level_values(0), keep.index.get_level_values(1)
    box = [xs.min() * BLOCK, ys.min() * BLOCK, (xs.max() + 1) * BLOCK, (ys.max() + 1) * BLOCK]
    w, s, e, n = region_box
    return [float(max(box[0], w)), float(max(box[1], s)), float(min(box[2], e)), float(min(box[3], n))]


def bbox_stats(expected, region: str, bbox: list, months: list) -> dict:
    """Value and "typical" inside bbox for the event window, exactly as /api/summary computes
    them (CLAUDE.md 5.3): typical = median over the baseline years of the SAME window's total,
    with missing days handled the same way (pipeline.science_check checks this vs the app)."""
    first = pd.Timestamp(months[0])
    last = pd.Timestamp(months[-1]) + pd.offsets.MonthEnd(0)
    s = expected.series(region, bbox)
    typical = same_window(s, first, last, range(BASELINE[0], BASELINE[1] + 1)).values()
    return {"value": window_total(s, first, last), "median": float(np.median(list(typical)))}


def span_text(months: list) -> str:
    first, last = pd.Timestamp(months[0]), pd.Timestamp(months[-1])
    if first == last:
        return first.strftime("%B %Y")
    return f"{first.strftime('%B')}-{last.strftime('%B %Y')}"


def describe(months: list, st: dict, peak_pct: float, context: str | None) -> str:
    pct = 100 * st["value"] / st["median"]
    quiet = " (this area normally has almost no fire then)" if st["median"] < NEAR_ZERO else ""
    text = (f"{span_text(months)}: {st['value']:,.0f} harmonized hotspots in this box vs a typical "
            f"{st['median']:,.0f} for the same months, {pct:,.0f}% of the 2003-2022 median{quiet}. "
            f"Across the whole region the peak month was {peak_pct:,.0f}% of median.")
    return f"{text} {context}" if context else text


def build() -> list[dict]:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    boxes = region_bboxes()
    expected = Expected(CELLS.parent)   # always our built data, whatever APP_DATA_DIR says
    regional =with_median(monthly(con), ["region"])
    blocks = with_median(monthly(con, by_block=True), ["region", "by", "bx"])
    presets = []
    for ev in pick(events(regional)).itertuples():
        bbox = event_bbox(blocks, ev.region, ev.months, boxes[ev.region])
        st = bbox_stats(expected, ev.region, bbox, ev.months)
        first, last = pd.Timestamp(ev.months[0]), pd.Timestamp(ev.months[-1])
        months_label = first.strftime("%b") + ("" if first == last else "-" + last.strftime("%b"))
        place, context = CONTEXT.get((ev.region, first.year), (NAMES[ev.region], None))
        presets.append({
            "name": f"{place}, {months_label} {first.year}",
            "region": ev.region,
            "bbox": bbox,
            "start": first.strftime("%Y-%m-%d"),
            "end": (last + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"),
            "why": describe(ev.months, st, ev.peak_pct, context),
        })
    return presets


def main() -> None:
    presets = build()
    OUT.write_text(json.dumps(presets, indent=1) + "\n", encoding="utf-8")
    for p in presets:
        print(f"{p['name']:42s} {p['bbox']}  {p['start']} -> {p['end']}")
        print(f"    {p['why']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
