"""Harmonize VIIRS to the MODIS scale (CLAUDE.md section 4), Method B + baselines.

1. Calibration pairs: MODIS Aqua vs one VIIRS satellite, counts per 0.25 deg cell x month x
   day/night, archive only, using ONLY days on which both satellites had data (same day; the
   day/night split keeps the ~13:30 / ~01:30 overpasses apart).
   -> data/processed/harmonize_pairs.parquet  (S-NPP pairs for fitting/testing, NOAA-20 for transfer)
2. Fit on S-NPP 2012-01-20 .. 2018-12-31, per region x land-cover group x day/night:
     B_ols  log1p(Aqua) = a + b * log1p(VIIRS)    (the curve's shape)
     B_qm   quantile mapping: the k-th percentile of VIIRS counts -> k-th percentile of Aqua
   Both then get ONE scale factor per group so that predicted training totals equal observed
   training totals (this undoes the log-transform bias and accounts for MODIS-only cells).
   A group with fewer than MIN_ROWS training cell-months uses its region x day/night model.
   Baselines: raw VIIRS (no change) and ONE global ratio (all S-NPP / all Aqua, all regions).
3. Terra factor: the harmonized record is on the Terra + Aqua scale (that is what MODIS-era
   `mec` counts), so Aqua-equivalent counts are multiplied by (Terra+Aqua)/Aqua per region x
   day/night x calendar month, measured 2003-2018 (before the MODIS orbit drift).
Everything is fitted twice: all confidences ("all") and without low confidence ("nonlow").
   -> data/processed/harmonize_models.json

Run from the repo root:  python -m pipeline.harmonize
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from pipeline.ingest import REGIONS

PROCESSED = Path("data/processed")
MODELS_PATH = PROCESSED / "harmonize_models.json"
PAIRS_PATH = PROCESSED / "harmonize_pairs.parquet"
TRAIN = ("2012-01-20", "2018-12-31")
TERRA_FACTOR_YEARS = (2003, 2018)
MIN_ROWS = 30
LC_YEARS = (2001, 2025)
QUANTILES = np.linspace(0, 1, 101)
METHODS = ("B_ols", "B_qm")
VARIANTS = {"all": ("aqua_n", "viirs_n"), "nonlow": ("aqua_nl", "viirs_nl")}


def _p(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET memory_limit = '6GB'")
    return con


# ---------------------------------------------------------------- 1. calibration pairs

def archive_end(con, fires: str) -> str:
    """Last day both MODIS and VIIRS archives cover (VIIRS archive ends first)."""
    return str(con.execute(f"""SELECT least(max(acq_date) FILTER (WHERE sensor = 'VIIRS'),
                                            max(acq_date) FILTER (WHERE sensor = 'MODIS'))
                               FROM read_parquet({fires}) WHERE NOT is_provisional""").fetchone()[0])


def pairs_sql(region: str, sat: str, fires: str, mask: str, end: str) -> str:
    return f"""
    WITH both_ok AS (
        SELECT date FROM read_parquet('{mask}')
        WHERE satellite IN ('Aqua', '{sat}') AND NOT missing AND date <= DATE '{end}'
        GROUP BY date HAVING count(*) = 2),
    f AS (SELECT * FROM read_parquet({fires})
          WHERE satellite IN ('Aqua', '{sat}') AND NOT is_provisional)
    SELECT '{region}' AS region, '{sat}' AS viirs_sat,
        (floor((lat + 90) / 0.25)::INTEGER * 1440 + floor((lon + 180) / 0.25)::INTEGER) AS cell_id,
        date_trunc('month', acq_date)::DATE AS month, daynight,
        count(*) FILTER (WHERE satellite = 'Aqua')  AS aqua_n,
        count(*) FILTER (WHERE satellite <> 'Aqua') AS viirs_n,
        count(*) FILTER (WHERE satellite = 'Aqua'  AND confidence_class <> 'low') AS aqua_nl,
        count(*) FILTER (WHERE satellite <> 'Aqua' AND confidence_class <> 'low') AS viirs_nl
    FROM f JOIN both_ok ON f.acq_date = both_ok.date
    GROUP BY ALL"""


def attach_landcover(pairs: pd.DataFrame, processed: Path = PROCESSED) -> pd.DataFrame:
    """Add lc_group (majority land cover of the cell that year); 'all' if no land-cover data."""
    out = []
    for region, grp in pairs.groupby("region"):
        path = processed / f"landcover_{region}.parquet"
        if not path.exists():
            out.append(grp.assign(lc_group="all"))
            continue
        lc = pd.read_parquet(path)[["cell_id", "year", "lc_group"]]
        year = pd.to_datetime(grp["month"]).dt.year.clip(*LC_YEARS)
        merged = grp.assign(year=year.to_numpy()).merge(lc, on=["cell_id", "year"], how="left")
        out.append(merged.drop(columns="year").fillna({"lc_group": "other"}))
    return pd.concat(out, ignore_index=True)


def build_pairs(processed: Path = PROCESSED) -> pd.DataFrame:
    con = connect()
    parts = []
    for region in REGIONS:
        fires = "[" + ", ".join(f"'{_p(f)}'" for f in sorted(processed.glob(f"fires_{region}_*.parquet"))) + "]"
        mask, end = _p(processed / f"daily_sat_{region}.parquet"), archive_end(con, fires)
        for sat in ("S-NPP", "NOAA-20"):
            parts.append(con.execute(pairs_sql(region, sat, fires, mask, end)).df())
    pairs = attach_landcover(pd.concat(parts, ignore_index=True))
    pairs["month"] = pd.to_datetime(pairs["month"])
    pairs.to_parquet(PAIRS_PATH, index=False)
    return pairs


# ---------------------------------------------------------------- 2. models

def model_key(region, lc_group, daynight) -> str:
    return f"{region}|{lc_group}|{daynight}"


def ols_curve(v: np.ndarray, m: np.ndarray) -> list[float]:
    b, a = np.polyfit(np.log1p(v), np.log1p(m), 1)
    return [float(a), float(b)]


def qm_curve(v: np.ndarray, m: np.ndarray) -> dict:
    vq, mq = np.quantile(v, QUANTILES), np.quantile(m, QUANTILES)
    # tied VIIRS quantiles (small integer counts) -> one point with the mean Aqua quantile
    tab = pd.DataFrame({"v": vq, "m": mq}).groupby("v", as_index=False)["m"].mean()
    return {"v": tab["v"].round(4).tolist(), "m": tab["m"].round(4).tolist()}


def curve_predict(method: str, curve, v: np.ndarray) -> np.ndarray:
    """Aqua-equivalent count from a VIIRS count, BEFORE the group's scale factor."""
    v = np.asarray(v, dtype=float)
    if method == "B_ols":
        a, b = curve
        return np.clip(np.expm1(a + b * np.log1p(v)), 0, None)
    xv, xm = np.asarray(curve["v"]), np.asarray(curve["m"])
    inside = np.interp(v, xv, xm)
    top_ratio = xm[-1] / xv[-1] if xv[-1] > 0 else 0.0
    return np.where(v > xv[-1], v * top_ratio, inside)  # beyond training range: constant ratio


def fit_group(method: str, rows: pd.DataFrame, mcol: str, vcol: str) -> dict:
    pos = rows[rows[vcol] > 0]
    v, m = pos[vcol].to_numpy(float), pos[mcol].to_numpy(float)
    curve = ols_curve(v, m) if method == "B_ols" else qm_curve(v, m)
    pred_total = curve_predict(method, curve, v).sum()
    scale = float(rows[mcol].sum() / pred_total) if pred_total > 0 else 1.0
    return {"curve": curve, "scale": scale, "n": int(len(pos))}


def fit_method(method: str, train: pd.DataFrame, mcol: str, vcol: str) -> dict:
    """Per region x land-cover x day/night, plus a region x 'all' x day/night fallback."""
    models = {}
    for (region, dn), grp in train.groupby(["region", "daynight"]):
        if (grp[vcol] > 0).sum() >= MIN_ROWS:
            models[model_key(region, "all", dn)] = fit_group(method, grp, mcol, vcol)
        for lc, sub in grp.groupby("lc_group"):
            if lc != "all" and (sub[vcol] > 0).sum() >= MIN_ROWS:
                models[model_key(region, lc, dn)] = fit_group(method, sub, mcol, vcol)
    return models


def global_ratio(train: pd.DataFrame, mcol: str, vcol: str) -> float:
    return float(train[vcol].sum() / train[mcol].sum())


# ---------------------------------------------------------------- prediction (used by validate + build)

def predict(method: str, models: dict, df: pd.DataFrame, vcol: str) -> np.ndarray:
    """Aqua-equivalent counts for rows with region, lc_group, daynight and a VIIRS count column."""
    v = df[vcol].to_numpy(float)
    if method == "raw_viirs":
        return v
    if method == "global_ratio":
        return v / models["global_ratio"]
    fitted = models[method]
    out = np.zeros(len(df))
    keys = (df["region"] + "|" + df["lc_group"] + "|" + df["daynight"]).to_numpy()
    fallback = (df["region"] + "|all|" + df["daynight"]).to_numpy()
    use = np.where(np.isin(keys, list(fitted)), keys, fallback)
    for key in np.unique(use):
        idx = use == key
        if key not in fitted:
            out[idx] = v[idx] / models["global_ratio"]   # no model at all: global ratio
            continue
        g = fitted[key]
        out[idx] = curve_predict(method, g["curve"], v[idx]) * g["scale"]
    return out


# ---------------------------------------------------------------- 3. Terra factor + FRP ratio

def terra_and_frp(con, processed: Path = PROCESSED) -> tuple[dict, float]:
    grids = "[" + ", ".join(f"'{_p(f)}'" for f in sorted(processed.glob("grid_monthly_*.parquet"))) + "]"
    tf = con.execute(f"""
        SELECT region, daynight, month(month) AS cal_month,
               sum(n_det) FILTER (WHERE satellite IN ('Terra', 'Aqua')) /
               nullif(sum(n_det) FILTER (WHERE satellite = 'Aqua'), 0) AS k
        FROM read_parquet({grids})
        WHERE year(month) BETWEEN {TERRA_FACTOR_YEARS[0]} AND {TERRA_FACTOR_YEARS[1]}
        GROUP BY ALL""").df().dropna()
    frp = con.execute(f"""
        SELECT sum(frp_sum) FILTER (WHERE satellite IN ('Terra', 'Aqua')) /
               sum(frp_sum) FILTER (WHERE satellite = 'S-NPP')
        FROM read_parquet({grids}) WHERE month BETWEEN DATE '2012-02-01' AND DATE '{TRAIN[1]}'""").fetchone()[0]
    factors = {f"{r.region}|{r.daynight}|{int(r.cal_month)}": round(float(r.k), 4) for r in tf.itertuples()}
    return factors, float(frp)


def terra_factor(models: dict, region, daynight, cal_month) -> np.ndarray:
    """(Terra+Aqua)/Aqua for each row; 1.0 if not measurable."""
    tf = models["terra_factor"]
    keys = [f"{r}|{d}|{int(m)}" for r, d, m in zip(region, daynight, cal_month)]
    return np.array([tf.get(k, 1.0) for k in keys])


# ---------------------------------------------------------------- driver

def train_rows(pairs: pd.DataFrame) -> pd.DataFrame:
    t = pairs[pairs["viirs_sat"] == "S-NPP"]
    return t[(t["month"] >= pd.Timestamp("2012-01-01")) & (t["month"] <= pd.Timestamp(TRAIN[1]))]


def fit_all(pairs: pd.DataFrame, con) -> dict:
    train = train_rows(pairs)
    tf, frp_ratio = terra_and_frp(con)
    out = {"train": TRAIN, "min_rows": MIN_ROWS, "terra_factor": tf, "frp_ratio_modis_per_snpp": frp_ratio,
           "landcover_used": sorted(pairs.loc[pairs["lc_group"] != "all", "region"].unique().tolist())}
    for variant, (mcol, vcol) in VARIANTS.items():
        v = {"global_ratio": global_ratio(train, mcol, vcol)}
        for method in METHODS:
            v[method] = fit_method(method, train, mcol, vcol)
        out[variant] = v
    return out


def load_models(path: Path = MODELS_PATH) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    con = connect()
    pairs = build_pairs()
    print(f"pairs: {len(pairs):,} cell-month-daynight rows ({pairs.groupby('viirs_sat').size().to_dict()})")
    models = fit_all(pairs, con)
    MODELS_PATH.write_text(json.dumps(models, indent=1))
    a = models["all"]
    print(f"global ratio S-NPP/Aqua (train): {a['global_ratio']:.3f}; nonlow: {models['nonlow']['global_ratio']:.3f}")
    for method in METHODS:
        groups = [k for k in a[method] if "|all|" not in k]
        print(f"{method}: {len(a[method])} models ({len(groups)} land-cover groups)")
    for k, g in sorted(a["B_ols"].items()):
        print(f"  B_ols {k:28s} a={g['curve'][0]:+.3f} b={g['curve'][1]:.3f} scale={g['scale']:.3f} n={g['n']}")
    print(f"wrote {MODELS_PATH}")


if __name__ == "__main__":
    main()
