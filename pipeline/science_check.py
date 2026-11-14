"""Science check of the app (Track A6): compare the API's numbers with direct DuckDB queries.

For 3 presets (one per region) it checks /api/summary, /api/calendar (monthly) and
/api/current, then that missing days come back as missing (null), never 0, and that the
Methods page only quotes numbers that are in results/metrics.json.

Expected values are computed here from data/app/ with the definitions in CLAUDE.md section 5
and docs/CONTRACTS.md, independently of app/analytics.py:
  * area = 0.1 deg cells whose centre is inside the bbox (edges count as inside)
  * daily value = sum of mec; a day listed in missing_days (scope = mode) is missing, not 0
  * a window/month total with <= 20% missing days is scaled up from the days with data;
    more than 20% missing -> unknown
  * "typical" = median of the same window in the baseline years 2003-2022

  python -m pipeline.science_check                    # app in-process on $APP_DATA_DIR
  python -m pipeline.science_check --data-dir PATH    # same, on the data in PATH
  python -m pipeline.science_check --url https://...  # a running app (local or live)
The data folder is --data-dir, else $APP_DATA_DIR (as the app reads it), else data/app. Before
comparing anything, the app's /api/regions must agree with that folder's coverage.json; if not,
the app is serving other data and the check stops (exit 2) instead of reporting false mismatches.
Writes results/science_check.md and exits 1 if anything mismatches.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

APP = Path("data/app")   # default; main() uses --data-dir / $APP_DATA_DIR like the app does
PRESETS = Path("docs/presets.json")
METRICS = Path("results/metrics.json")
OUT = Path("results/science_check.md")
BASELINE = (2003, 2022)
MAX_MISSING = 0.2
VALUE_TOL = 0.11       # API rounds values to 0.1
PCT_TOL = 1            # API rounds % to an integer


# ---------------------------------------------------------------- API access

class ApiFailure(Exception):
    def __init__(self, path, body, status, text):
        super().__init__(f"{path} -> HTTP {status}")
        self.path, self.body, self.status, self.text = path, body, status, text


def api_client(url: str | None):
    if url:
        import httpx
        client = httpx.Client(base_url=url.rstrip("/"), timeout=120)
    else:
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

    def post(path: str, body: dict) -> dict:
        r = client.post(path, json=body)
        if r.status_code != 200:
            raise ApiFailure(path, body, r.status_code, r.text[:200])
        return r.json()

    def get(path: str):
        return client.get(path)
    return post, get


# ---------------------------------------------------------------- expected values (DuckDB)

class Expected:
    def __init__(self, app_dir: Path = APP):
        self.con = duckdb.connect()
        self.cells = (app_dir / "cells_daily.parquet").as_posix()
        self.missing = self.con.execute(
            f"SELECT region, date, scope FROM "
            f"read_parquet('{(app_dir / 'missing_days.parquet').as_posix()}')").df()
        self.missing["date"] = pd.to_datetime(self.missing["date"])
        self.cov = json.loads((app_dir / "coverage.json").read_text())
        last = self.con.execute(f"SELECT max(date) FROM read_parquet('{self.cells}')").fetchone()[0]
        self.end = max([last] + [date.fromisoformat(c["live_end"]) for c in self.cov.values()])

    def series(self, region: str, bbox: list, mode: str = "harmonized") -> pd.Series:
        col = {"harmonized": "mec", "modis_only": "modis_n", "viirs_raw": "viirs_n"}[mode]
        w, s, e, n = bbox
        d = self.con.execute(f"""
            SELECT date, sum({col}) AS v FROM read_parquet('{self.cells}')
            WHERE region = ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            GROUP BY date""", [region, s, n, w, e]).df()
        idx = pd.date_range(self.cov[region]["start"], self.end, freq="D")
        out = pd.Series(0.0, index=idx)
        out.loc[pd.to_datetime(d["date"])] = d["v"].to_numpy(float)
        miss = self.missing[(self.missing["region"] == region) & (self.missing["scope"] == mode)]
        out[out.index.isin(miss["date"])] = np.nan
        if mode == "viirs_raw":
            out[out.index < pd.Timestamp("2012-01-20")] = np.nan
        return out


def window_total(s: pd.Series, a, b) -> float:
    w = s.loc[pd.Timestamp(a):pd.Timestamp(b)]
    if len(w) == 0:
        return np.nan
    gaps = int(w.isna().sum())
    if gaps == 0:
        return float(w.sum())
    return np.nan if gaps / len(w) > MAX_MISSING else float(w.mean() * len(w))


def same_window(s: pd.Series, a, b, years) -> dict[int, float]:
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    out = {}
    for y in years:
        try:
            ay = a.replace(year=y)
        except ValueError:
            ay = a.replace(year=y, day=28)
        by = ay + (b - a)
        if ay < s.index[0] or by > s.index[-1]:
            continue
        v = window_total(s, ay, by)
        if not np.isnan(v):
            out[y] = v
    return out


def pct(value, median):
    if median is None or np.isnan(median) or median <= 0 or np.isnan(value):
        return None
    return 100 * value / median


def monthly(s: pd.Series) -> pd.DataFrame:
    rows = [{"period": p, "value": window_total(g, g.index[0], g.index[-1]),
             "full": len(g) == p.days_in_month}
            for p, g in s.groupby(s.index.to_period("M"))]
    return pd.DataFrame(rows).set_index("period")


# ---------------------------------------------------------------- comparisons

class Report:
    def __init__(self):
        self.rows = []

    def check(self, where: str, field: str, got, want, tol: float = 0):
        if want is None or (isinstance(want, float) and np.isnan(want)):
            ok = got is None
        elif got is None:
            ok = False
        elif isinstance(want, str):
            ok = str(got) == want
        else:
            ok = abs(float(got) - float(want)) <= tol
        self.rows.append({"where": where, "field": field, "app": got,
                          "expected": _fmt(want), "ok": ok})

    @property
    def failures(self):
        return [r for r in self.rows if not r["ok"]]


def _fmt(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(x, 2) if isinstance(x, float) else x


def body(p: dict, **extra) -> dict:
    return {"area": {"type": "bbox", "bbox": p["bbox"]}, "start": p["start"], "end": p["end"],
            "baseline": list(BASELINE), "mode": "harmonized", "metric": "count", **extra}


def check_summary(rep, post, ex, p, s):
    got = post("/api/summary", body(p))
    where = f"POST /api/summary [{p['name']}]"
    kf = got["key_figures"]
    w = s.loc[p["start"]:p["end"]]
    value = window_total(s, p["start"], p["end"])
    typical = list(same_window(s, p["start"], p["end"],
                               range(BASELINE[0], BASELINE[1] + 1)).values())
    med = float(np.median(typical)) if typical else np.nan
    m = monthly(s).loc[pd.Period(p["start"], "M"):pd.Period(p["end"], "M")]
    archive_end = date.fromisoformat(ex.cov[p["region"]]["archive_end"])
    rep.check(where, "key_figures.total_hotspots", kf["total_hotspots"], float(np.nansum(w)), 1)
    rep.check(where, "key_figures.pct_of_median", kf["pct_of_median"], pct(value, med), PCT_TOL)
    # the preset button's "why" text must quote the same % the app then shows. It describes the
    # real data it was built from, so only compare when the app's total matches that data.
    quoted = re.search(r"([\d,]+)% of the 2003-2022 median", p["why"])
    total = re.search(r"([\d,]+) harmonized hotspots", p["why"])
    if quoted and total and abs(float(total.group(1).replace(",", "")) - kf["total_hotspots"]) <= 1:
        rep.check(f"docs/presets.json [{p['name']}]", "why: % of median vs app",
                  kf["pct_of_median"], float(quoted.group(1).replace(",", "")), PCT_TOL)
    busiest = str(m["value"].idxmax()) if m["value"].max() > 0 else None   # no fire: none
    rep.check(where, "key_figures.busiest_month", kf["busiest_month"], busiest)
    rep.check(where, "missing_days", got["missing_days"], int(w.isna().sum()))
    rep.check(where, "provisional_days", got["provisional_days"],
              int((w.index.date > archive_end).sum()))


def check_calendar(rep, post, ex, p, s):
    got = post("/api/calendar", body(p, granularity="month"))
    mt = monthly(s)
    base = mt[(mt.index.year >= BASELINE[0]) & (mt.index.year <= BASELINE[1]) & mt["full"]]
    for cell in got["cells"]:
        per = pd.Period(cell["period"], "M")
        where = f"POST /api/calendar month [{p['name']}] {cell['period']}"
        vals = base.loc[base.index.month == per.month, "value"].dropna()
        med = float(vals.median()) if len(vals) else np.nan
        v = mt.loc[per, "value"]
        rep.check(where, "value", cell["value"], v, VALUE_TOL)
        rep.check(where, "median", cell["median"], med, VALUE_TOL)
        rep.check(where, "pct_of_median", cell["pct_of_median"], pct(v, med), PCT_TOL)
        rep.check(where, "missing", str(cell["missing"]), str(bool(np.isnan(v))))


def check_current(rep, post, ex, p, s, as_of: date | None):
    b = body(p)
    if as_of:
        b["as_of"] = as_of.isoformat()
    got = post("/api/current", b)
    day = pd.Timestamp(as_of or ex.end)
    ms = day.replace(day=1)
    where = f"POST /api/current [{p['name']}] as_of {day.date()}"
    this = window_total(s, ms, day)
    others = same_window(s, ms, day, range(s.index[0].year, day.year))
    base = [v for y, v in others.items() if BASELINE[0] <= y <= BASELINE[1]]
    med = float(np.median(base)) if base else np.nan
    rep.check(where, "month", got["month"], ms.strftime("%Y-%m"))
    rep.check(where, "value_so_far", got["value_so_far"], float(np.nansum(s.loc[ms:day])), VALUE_TOL)
    rep.check(where, "median_same_days", got["median_same_days"], med, VALUE_TOL)
    rep.check(where, "pct_of_median", got["pct_of_median"], pct(this, med), PCT_TOL)
    if not np.isnan(this):
        rep.check(where, "rank_among_years", got["rank_among_years"],
                  1 + sum(v > this for v in others.values()))
        rep.check(where, "of_years", got["of_years"], len(others) + 1)


def check_missing(rep, post, ex, presets):
    """A missing day in each preset's region shows as null + missing (never 0), per mode."""
    for p in presets:
        for mode in ("harmonized", "modis_only"):
            miss = ex.missing[(ex.missing["region"] == p["region"]) & (ex.missing["scope"] == mode)]
            if miss.empty:
                continue
            day = miss["date"].sort_values().iloc[len(miss) // 2]
            start, end = (day - timedelta(days=3)).date(), (day + timedelta(days=3)).date()
            got = post("/api/calendar", {**body(p, granularity="day"), "mode": mode,
                                         "start": start.isoformat(), "end": end.isoformat()})
            cell = next(c for c in got["cells"] if c["period"] == day.strftime("%Y-%m-%d"))
            where = f"POST /api/calendar day, mode {mode} [{p['region']}] {day.date()}"
            rep.check(where, "value on a missing day", cell["value"], None)
            rep.check(where, "missing", str(cell["missing"]), "True")
            summ = post("/api/summary", {**body(p), "mode": mode, "start": start.isoformat(),
                                         "end": end.isoformat()})
            want = int(miss["date"].between(pd.Timestamp(start), pd.Timestamp(end)).sum())
            rep.check(f"POST /api/summary, mode {mode} [{p['region']}] {start}..{end}",
                      "missing_days", summ["missing_days"], want)


def metric_numbers() -> set[str]:
    metrics = json.loads(METRICS.read_text())
    allowed = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            allowed.update({f"{x}", f"{abs(x)}", f"{abs(x):,.0f}", f"{abs(x):.2f}", f"{abs(x):.1f}"})
    walk(metrics)
    for note in metrics["notes"]:
        allowed.update(re.findall(r"\d+\.\d+", note))
    return allowed


def check_methods(rep, get):
    r = get("/methods")
    if r.status_code != 200:
        rep.check("GET /methods", "page exists (Track C builds app/static/methods.html)",
                  f"HTTP {r.status_code}", "HTTP 200")
        return
    text = re.sub(r"<[^>]+>", " ", r.text)
    # identifiers, not results: DOIs, product versions (MCD12Q1.061), "Collection 6.1"
    text = re.sub(r"10\.\d{4,}/\S+|\b[A-Za-z0-9_]+\.\d{3}\b|Collection \d+(?:\.\d+)?", " ", text)
    allowed = metric_numbers()
    for num in sorted(set(re.findall(r"\d{1,3}(?:,\d{3})+|\d+\.\d+", text))):
        rep.check("GET /methods", f"number {num}", num,
                  num if num in allowed else "not in metrics.json")


# ---------------------------------------------------------------- report

def write_report(rep: Report, presets, target: str) -> None:
    lines = [f"# Science check of the app ({target})", "",
             f"{len(rep.rows)} checks, **{len(rep.failures)} mismatches**. Expected values are "
             "direct DuckDB queries on data/app/ (`python -m pipeline.science_check`).", "",
             "Presets checked: " + "; ".join(p["name"] for p in presets) + ".", ""]
    if rep.failures:
        lines += ["## Mismatches (for Track B / C)", "", "| Endpoint | Field | App | Expected |",
                  "|---|---|---|---|"]
        lines += [f"| {r['where']} | {r['field']} | {r['app']} | {r['expected']} |"
                  for r in rep.failures]
        lines.append("")
    lines += ["## All checks", "", "| Endpoint | Field | App | Expected | OK |",
              "|---|---|---|---|---|"]
    lines += [f"| {r['where']} | {r['field']} | {r['app']} | {r['expected']} | "
              f"{'yes' if r['ok'] else '**NO**'} |" for r in rep.rows]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pick_presets(n: int = 3) -> list[dict]:
    """One preset per region (the first listed for each)."""
    seen, out = set(), []
    for p in json.loads(PRESETS.read_text(encoding="utf-8")):
        if p["region"] not in seen:
            seen.add(p["region"])
            out.append(p)
    return out[:n]


def data_dir_from(arg: str | None) -> Path:
    """--data-dir, else $APP_DATA_DIR (what app/main.py reads), else data/app."""
    path = Path(arg or os.environ.get("APP_DATA_DIR") or APP)
    if arg:
        os.environ["APP_DATA_DIR"] = str(path)   # the in-process app reads the same folder
    if not (path / "coverage.json").exists():
        raise SystemExit(f"No app data in {path} (coverage.json missing).")
    return path


def same_data_or_stop(get, ex: Expected, data_dir: Path) -> None:
    """Stop unless the app serves the data we compute from (region list, start, archive_end)."""
    r = get("/api/regions")
    if r.status_code != 200:
        raise SystemExit(f"/api/regions -> HTTP {r.status_code}; is the app running with data?")
    app_regions = {x["id"]: x for x in r.json()["regions"]}
    diffs = [f"{reg}: app {app_regions.get(reg, {}).get(k)} vs {data_dir} {cov[k]}"
             for reg, cov in ex.cov.items() for k in ("start", "archive_end")
             if app_regions.get(reg, {}).get(k) != cov[k]]
    if set(app_regions) != set(ex.cov):
        diffs.append(f"regions: app {sorted(app_regions)} vs {data_dir} {sorted(ex.cov)}")
    if diffs:
        raise SystemExit("The app is serving different data than " + str(data_dir) + ":\n  "
                         + "\n  ".join(diffs) + "\nPoint --data-dir (or APP_DATA_DIR) at the "
                         "folder the app uses, then rerun. Nothing was compared.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="base URL of a running app (default: run it in-process)")
    ap.add_argument("--data-dir", help="app data folder (default: $APP_DATA_DIR, else data/app)")
    args = ap.parse_args(argv)
    data_dir = data_dir_from(args.data_dir)
    post, get = api_client(args.url)
    ex, rep = Expected(data_dir), Report()
    same_data_or_stop(get, ex, data_dir)
    presets = pick_presets()

    def guarded(fn, *a):
        try:
            fn(*a)
        except ApiFailure as e:
            area, rng = e.body.get("area", {}).get("bbox"), (e.body.get("start"), e.body.get("end"))
            rep.check(f"POST {e.path} bbox {area} {rng[0]}..{rng[1]} mode {e.body.get('mode')}",
                      "HTTP status", f"{e.status} ({e.text})", "200")

    for p in presets:
        s = ex.series(p["region"], p["bbox"])
        guarded(check_summary, rep, post, ex, p, s)
        guarded(check_calendar, rep, post, ex, p, s)
        guarded(check_current, rep, post, ex, p, s, None)
        guarded(check_current, rep, post, ex, p, s, date.fromisoformat(p["end"]))
    for p in presets:
        guarded(check_missing, rep, post, ex, [p])
    check_methods(rep, get)
    write_report(rep, presets, args.url or f"local, in-process on {data_dir.as_posix()}")
    print(f"{len(rep.rows)} checks, {len(rep.failures)} mismatches -> {OUT}")
    for r in rep.failures:
        print(f"  MISMATCH {r['where']} | {r['field']}: app {r['app']} vs expected {r['expected']}")
    raise SystemExit(1 if rep.failures else 0)


if __name__ == "__main__":
    main()
