"""
FireBridge API: FastAPI + DuckDB over the app data in data/app/ (docs/CONTRACTS.md section 2).

Run from the repo root:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000 (website) or http://127.0.0.1:8000/docs (try every endpoint).

Data folder: env var APP_DATA_DIR (default data/app). If it's empty, make fake data first:
    python scripts/make_synthetic_app_data.py

How a request works:
  1. parse the area (bbox / polygon / point + radius) and find the 0.1 degree cells inside it
  2. one DuckDB query adds up those cells per day   (cached per area, so tabs switch fast)
  3. app/analytics.py turns that into a daily series (NaN on missing days) and does the math
Every endpoint returns exactly the JSON shapes in docs/CONTRACTS.md section 4.
Errors are HTTP 400 {"error": "plain-English message"}.
"""

import json
import os
import threading
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import List, Literal, Optional

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from app import analytics as an

REPO = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO / "app" / "static"

REGION_NAMES = {"texas": "Texas & southern Plains", "amazon": "Southern Amazon arc",
                "australia": "Northern Australia"}
DEFAULT_BASELINE = [2003, 2022]
MIN_BASELINE_YEARS = 3
HOTSPOT_ROW_CAP = 200_000
DEFAULT_VIIRS_START = date(2012, 1, 20)
NOAA20_START = date(2018, 4, 1)
AREA_CACHE_SIZE = 64

MODE_COLUMN = {"harmonized": "mec", "modis_only": "modis_n", "viirs_raw": "viirs_n"}
UNITS = {
    ("harmonized", "count"): ("hotspots (MODIS scale)", "hotspots"),
    ("harmonized", "frp"): ("fire radiative power, MW (MODIS scale)", "MW of fire power"),
    ("modis_only", "count"): ("MODIS hotspots (raw, not harmonized)", "MODIS hotspots"),
    ("viirs_raw", "count"): ("VIIRS hotspots (raw, not harmonized)", "VIIRS hotspots"),
}


class ApiError(Exception):
    """Shown to the user as HTTP 400 {"error": message}."""


class DataMissing(Exception):
    """The app data files aren't there yet (HTTP 503)."""


# =============================================================================================
# Data store: loads data/app/ once, answers "daily totals for these cells"
# =============================================================================================

def _sql_path(p):
    return str(p).replace("\\", "/").replace("'", "''")


class DataStore:
    REQUIRED = ["cells_daily.parquet", "missing_days.parquet", "hotspots.parquet", "coverage.json"]

    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        absent = [f for f in self.REQUIRED if not (self.dir / f).exists()]
        if absent:
            raise DataMissing(
                f"App data not found in {self.dir} (missing {', '.join(absent)}). Run "
                "'python scripts/make_synthetic_app_data.py' for fake data, or set APP_DATA_DIR "
                "to the folder with Track A's real data.")
        self.con = duckdb.connect()
        with open(self.dir / "coverage.json") as f:
            self.coverage = json.load(f)
        self._load_tables()
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()

    # ---- loading -------------------------------------------------------------------------------
    def _load_tables(self):
        con, d = self.con, self.dir
        cells_pq = _sql_path(d / "cells_daily.parquet")
        hot_pq = _sql_path(d / "hotspots.parquet")
        cols = "region, cell_id, lat, lon, date, mec, mefrp, modis_n, viirs_n, source, provisional"
        main_end = dict(con.execute(
            f"SELECT region, max(date) FROM read_parquet('{cells_pq}') GROUP BY region").fetchall())

        # Live FIRMS data (pipeline/live.py) is added only for days AFTER the main files end,
        # so nothing is ever counted twice. The app works fine without the live files.
        live_cells = d / "live_cells_daily.parquet"
        live_hot = d / "live_hotspots.parquet"
        self.live_end = {}
        cells_sql = f"SELECT {cols} FROM read_parquet('{cells_pq}')"
        hot_sql = f"SELECT * FROM read_parquet('{hot_pq}')"
        if main_end and live_cells.exists() and live_hot.exists():
            after = " OR ".join(f"(region = '{r}' AND date > DATE '{e}')"
                                for r, e in main_end.items())
            cells_sql += (f" UNION ALL SELECT {cols} FROM read_parquet('{_sql_path(live_cells)}')"
                          f" WHERE {after}")
            hot_sql = (f"SELECT * FROM read_parquet('{hot_pq}') UNION ALL BY NAME "
                       f"SELECT * FROM read_parquet('{_sql_path(live_hot)}') WHERE {after}")
            live_cov = d / "live_coverage.json"
            if live_cov.exists():
                with open(live_cov) as f:
                    self.live_end = {r: date.fromisoformat(v["live_end"])
                                     for r, v in json.load(f).items()}
        # cells_daily is small enough to keep in memory (fast); hotspots stay on disk.
        con.execute(f"CREATE TABLE cells AS {cells_sql} ORDER BY region, cell_id, date")
        con.execute(f"CREATE VIEW hotspots AS {hot_sql}")

        self.cells = con.execute(
            "SELECT region, cell_id, any_value(lat) AS lat, any_value(lon) AS lon "
            "FROM cells GROUP BY region, cell_id").df()
        self.viirs_start = {r: pd.Timestamp(v).date() for r, v in con.execute(
            "SELECT region, min(date) FROM cells WHERE source = 'VIIRS' GROUP BY region"
        ).fetchall()}
        data_end = {r: pd.Timestamp(v).date() for r, v in con.execute(
            "SELECT region, max(date) FROM cells GROUP BY region").fetchall()}

        miss_sql = f"SELECT region, date, scope FROM read_parquet('{_sql_path(d / 'missing_days.parquet')}')"
        live_miss = d / "live_missing_days.parquet"
        if self.live_end and live_miss.exists():
            miss_sql += (f" UNION ALL SELECT region, date, scope FROM "
                         f"read_parquet('{_sql_path(live_miss)}')")
        miss = con.execute(miss_sql).df()
        self.missing = {}
        for (region, scope), g in miss.groupby(["region", "scope"]):
            self.missing[(region, scope)] = set(pd.to_datetime(g["date"]).dt.normalize())

        self.regions = {}
        for r, c in self.coverage.items():
            end = c.get("live_end") or c.get("nrt_end") or c.get("archive_end")
            end = max(date.fromisoformat(end), self.live_end.get(r, date.min))
            if r in data_end:
                end = max(end, data_end[r])
            self.regions[r] = {
                "id": r, "name": REGION_NAMES.get(r, r.replace("_", " ").title()),
                "bbox": [float(x) for x in c["bbox"]],
                "start": date.fromisoformat(c["start"]),
                "archive_end": date.fromisoformat(c["archive_end"]),
                "end": end,
            }

    # ---- the one heavy query --------------------------------------------------------------------
    def daily_sums(self, key, sel):
        """Per-day sums of all value columns over the selected cells (cached per area)."""
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        if sel.empty:
            df = pd.DataFrame(columns=["date", "mec", "mefrp", "modis_n", "viirs_n"])
        else:
            cur = self.con.cursor()
            try:
                cur.register("sel", sel[["region", "cell_id"]])
                df = cur.execute(
                    "SELECT c.date, sum(mec) AS mec, sum(mefrp) AS mefrp, "
                    "sum(modis_n) AS modis_n, sum(viirs_n) AS viirs_n "
                    "FROM cells c JOIN sel s ON c.region = s.region AND c.cell_id = s.cell_id "
                    "GROUP BY c.date ORDER BY c.date").df()
            finally:
                cur.close()
        with self._cache_lock:
            self._cache[key] = df
            while len(self._cache) > AREA_CACHE_SIZE:
                self._cache.popitem(last=False)
        return df


_store = None
_store_sig = None
_store_lock = threading.Lock()
WATCHED = DataStore.REQUIRED + ["live_cells_daily.parquet", "live_hotspots.parquet",
                                "live_missing_days.parquet", "live_coverage.json"]


def _signature(data_dir):
    """File sizes + modification times, so we notice when data files are replaced."""
    sig = []
    for f in WATCHED:
        p = Path(data_dir) / f
        st = p.stat() if p.exists() else None
        sig.append((f, st.st_mtime_ns if st else None, st.st_size if st else None))
    return tuple(sig)


def get_store():
    """Load the data on first use (so importing this module never fails), and reload it when
    the files change (e.g. pipeline/live.py wrote fresh live data)."""
    global _store, _store_sig
    data_dir = os.environ.get("APP_DATA_DIR", REPO / "data" / "app")
    sig = _signature(data_dir)
    with _store_lock:
        if _store is None or sig != _store_sig:
            _store = DataStore(data_dir)
            _store_sig = sig
        return _store


def reset_store():
    """Forget the loaded data (tests and the live-feed refresher use this)."""
    global _store, _store_sig
    with _store_lock:
        _store = None
        _store_sig = None


# =============================================================================================
# Request handling
# =============================================================================================

class Query(BaseModel):
    """The POST body shared by every endpoint (docs/CONTRACTS.md section 4)."""
    model_config = ConfigDict(extra="ignore")
    area: dict
    start: Optional[date] = None
    end: Optional[date] = None
    baseline: Optional[List[int]] = None
    mode: Literal["harmonized", "modis_only", "viirs_raw"] = "harmonized"
    metric: Literal["count", "frp"] = "count"
    granularity: Optional[Literal["day", "month"]] = None
    as_of: Optional[date] = None      # /api/current: compare a past month instead of this one


class Context:
    """Everything one request needs: the area's daily series plus facts about the data."""

    def __init__(self, q: Query, store: DataStore):
        self.q = q
        self.store = store
        self.area = an.parse_area(q.area)
        boxes = {r: v["bbox"] for r, v in store.regions.items()}
        parts = an.overlap_with_regions(self.area, boxes)
        if not parts:
            names = ", ".join(v["name"] for v in store.regions.values())
            raise ApiError(f"That area is outside the regions we have data for ({names}). "
                           "Draw inside one of the outlined boxes.")
        self.regions = list(parts)
        self.region = max(parts, key=lambda r: parts[r].area)
        covered = an.area_km2(shapely_union(parts.values()))
        whole = an.area_km2(self.area.geom)
        self.area_km2 = covered
        self.n_cells = sum(an.count_grid_cells(self.area, r, parts[r], boxes[r]) for r in parts)
        self.outside_note = None
        if whole > 0 and covered / whole < 0.98:
            self.outside_note = (f"Only {round(100 * covered / whole)}% of this area is inside "
                                 "our data regions; the rest is not counted.")

        regs = [store.regions[r] for r in self.regions]
        self.data_start = min(r["start"] for r in regs)
        self.data_end = max(r["end"] for r in regs)
        self.provisional_after = min(r["archive_end"] for r in regs)
        self.viirs_start = min((store.viirs_start.get(r, DEFAULT_VIIRS_START)
                                for r in self.regions), default=DEFAULT_VIIRS_START)
        self.sel = an.select_cells(self.area, store.cells, self.regions)
        self.sums = store.daily_sums((an.area_key(q.area), tuple(self.regions)), self.sel)
        self.units, self.unit_word = self._units(q.mode, q.metric)
        self.baseline = self._baseline(q.baseline)

    def _units(self, mode, metric):
        if (mode, metric) not in UNITS:
            raise ApiError("Fire radiative power (metric 'frp') is only available in "
                           "harmonized mode. Switch the metric to 'count' for raw modes.")
        return UNITS[(mode, metric)]

    def _baseline(self, b):
        b = b or DEFAULT_BASELINE
        if len(b) != 2 or b[0] > b[1]:
            raise ApiError("Baseline must be two years, first <= last, e.g. [2003, 2022].")
        first = self.data_start.year
        last_full = self.data_end.year if self.data_end.month == 12 and self.data_end.day == 31 \
            else self.data_end.year - 1
        y0, y1 = max(b[0], first), min(b[1], last_full)
        if y1 - y0 + 1 < MIN_BASELINE_YEARS:
            raise ApiError(f"Pick at least {MIN_BASELINE_YEARS} baseline years between "
                           f"{first} and {last_full}.")
        return [y0, y1]

    def series(self, mode=None, metric=None):
        """The area's daily series for a mode, with NaN on missing days."""
        mode = mode or self.q.mode
        metric = metric or self.q.metric
        col = "mefrp" if (mode == "harmonized" and metric == "frp") else MODE_COLUMN[mode]
        missing = set()
        for r in self.regions:
            missing |= self.store.missing.get((r, mode), set())
        nan_before = self.viirs_start if mode == "viirs_raw" else None
        return an.build_daily_series(self.sums, col, self.data_start, self.data_end,
                                     missing, nan_before)

    def date_range(self, default_start=None):
        start = self.q.start or default_start or self.data_start
        end = self.q.end or self.data_end
        if start > end:
            raise ApiError("The start date must be on or before the end date.")
        if end < self.data_start or start > self.data_end:
            raise ApiError(f"We have data for this area from {self.data_start} to "
                           f"{self.data_end}. Pick dates in that range.")
        return max(start, self.data_start), min(end, self.data_end)

    def source_of(self, start, end):
        if self.q.mode == "modis_only":
            return "MODIS"
        if self.q.mode == "viirs_raw":
            return "VIIRS"
        mid = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        return "VIIRS" if mid.date() >= self.viirs_start else "MODIS"


def shapely_union(geoms):
    import shapely
    return shapely.union_all(list(geoms))


def clean(obj):
    """Make a result JSON-safe: NaN/inf -> null, numpy numbers -> plain numbers."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else float(obj)
    return obj


def ctx_for(q: Query):
    return Context(q, get_store())


# =============================================================================================
# The app
# =============================================================================================

app = FastAPI(title="FireBridge API",
              description="Harmonized MODIS + VIIRS burning activity calendar (NASA Space Apps 2026)")
# The frontend may be served from another port while developing, so allow cross-origin calls.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                   allow_headers=["*"])


@app.exception_handler(ApiError)
@app.exception_handler(an.AreaError)
async def _bad_request(request: Request, exc: Exception):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(DataMissing)
async def _no_data(request: Request, exc: DataMissing):
    return JSONResponse(status_code=503, content={"error": str(exc)})


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError):
    err = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in err.get("loc", []) if x != "body") or "request"
    if field == "area" and err.get("type") == "missing":
        msg = "Please choose an area: draw one on the map or type coordinates."
    else:
        msg = f"Problem with '{field}': {err.get('msg', 'invalid value')}."
    return JSONResponse(status_code=400, content={"error": msg})


@app.get("/api/regions")
def regions():
    """Regions we have data for, with their date coverage. Also the health check."""
    s = get_store()
    return {"regions": [{"id": r["id"], "name": r["name"], "bbox": r["bbox"],
                         "start": r["start"].isoformat(),
                         "archive_end": r["archive_end"].isoformat(),
                         "live_end": r["end"].isoformat()} for r in s.regions.values()]}


@app.post("/api/summary")
def summary(q: Query):
    """Key figures + a plain-language summary for the area and date range."""
    c = ctx_for(q)
    start, end = c.date_range()
    s = c.series()
    out = an.summary(s, start, end, c.baseline, c.provisional_after, c.unit_word,
                     {"area_km2": c.area_km2, "cells": c.n_cells, "region": c.region,
                      "outside_note": c.outside_note})
    return clean(out)


@app.post("/api/calendar")
def calendar(q: Query):
    """Burning calendar values + anomalies, per month (default) or per day."""
    c = ctx_for(q)
    gran = q.granularity or "month"
    start, end = c.date_range()
    if gran == "day" and (end - start).days > 3 * 366:
        raise ApiError("Daily view is limited to 3 years. Pick a shorter date range "
                       "or use granularity 'month'.")
    cells = an.calendar_cells(c.series(), gran, start, end, c.baseline, c.source_of,
                              c.provisional_after)
    return clean({"granularity": gran, "mode": q.mode, "metric": q.metric, "units": c.units,
                  "cells": cells})


@app.post("/api/patterns")
def patterns(q: Query):
    """Month x year grid (2001 -> now), years ranked, fire season, high-risk months."""
    c = ctx_for(q)
    return clean(an.patterns(c.series(), c.baseline, c.provisional_after))


@app.post("/api/current")
def current(q: Query):
    """The current month so far vs the same days in previous years."""
    c = ctx_for(q)
    as_of = min(q.as_of or c.data_end, c.data_end)
    if as_of < c.data_start:
        raise ApiError(f"'as_of' must be after {c.data_start}.")
    return clean(an.current(c.series(), as_of, c.baseline, c.provisional_after, c.unit_word))


@app.post("/api/timeseries")
def timeseries(q: Query):
    """Monthly totals 2001 -> now in all three modes, to show the 2012 jump disappear."""
    c = ctx_for(q)
    metric = q.metric
    h = an.monthly_values(c.series("harmonized", metric))
    if metric == "count":
        m = an.monthly_values(c.series("modis_only", "count"))
        v = an.monthly_values(c.series("viirs_raw", "count"))
    else:
        m = v = {}
    series = [{"month": k, "harmonized": h[k], "modis_only": m.get(k), "viirs_raw": v.get(k)}
              for k in h]
    switches = [{"date": c.viirs_start.isoformat(), "label": "VIIRS S-NPP starts"}]
    if c.data_end >= NOAA20_START:
        switches.append({"date": NOAA20_START.isoformat(), "label": "NOAA-20 starts"})
    return clean({"series": series, "sensor_switches": switches})


@app.post("/api/export/series.csv")
def export_series(q: Query):
    """The analytics table as CSV (daily by default; granularity 'month' for monthly)."""
    c = ctx_for(q)
    gran = q.granularity or "day"
    start, end = c.date_range()
    rows = an.calendar_cells(c.series(), gran, start, end, c.baseline, c.source_of,
                             c.provisional_after)
    df = pd.DataFrame(rows).rename(columns={"period": "date", "source": "source_sensor",
                                            "provisional": "provisional_flag",
                                            "missing": "missing_flag"})
    cols = ["date", "value", "median", "mean", "std", "z", "pct_of_median", "source_sensor",
            "provisional_flag", "missing_flag"]
    df = df.reindex(columns=cols)
    for col in ("provisional_flag", "missing_flag"):
        df[col] = df[col].map({True: "true", False: "false"})
    for col in ("pct_of_median",):
        df[col] = df[col].astype("Int64")
    name = f"firebridge_series_{q.mode}_{start}_{end}.csv"
    return Response(df.to_csv(index=False, lineterminator="\n"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/export/hotspots.csv")
def export_hotspots(q: Query):
    """The hotspot points in the area and date range, streamed, capped at 200,000 rows.

    A point is included if its 0.1 degree cell is in the area (the same rule the analytics
    use), so the 'weight' column adds up to the harmonized total."""
    c = ctx_for(q)
    start, end = c.date_range()
    sel = c.sel[["region", "cell_id"]].copy()
    w, s, e, n = c.area.geom.bounds
    pad = an.CELL_DEG
    sensor = {"modis_only": "MODIS", "viirs_raw": "VIIRS"}.get(q.mode)
    regions_sql = ", ".join(f"'{r}'" for r in c.regions)
    sql = f"""
        SELECT round(h.lat, 5) AS lat, round(h.lon, 5) AS lon,
               strftime(h.datetime_utc, '%Y-%m-%dT%H:%M:%SZ') AS datetime_utc,
               h.satellite, h.sensor, round(CAST(h.frp AS DOUBLE), 1) AS frp,
               h.confidence_class AS confidence, h.daynight,
               CASE WHEN h.provisional THEN 'true' ELSE 'false' END AS provisional,
               round(CAST(h.weight AS DOUBLE), 4) AS weight
        FROM hotspots h
        JOIN sel ON h.region = sel.region
             AND CAST(round((h.lat + 90) * 10) AS BIGINT) * 3600
                 + CAST(round((h.lon + 180) * 10) AS BIGINT) = sel.cell_id
        WHERE h.region IN ({regions_sql})
          AND h.date BETWEEN ? AND ?
          AND h.lat BETWEEN ? AND ? AND h.lon BETWEEN ? AND ?
          {"AND h.sensor = ?" if sensor else ""}
        ORDER BY h.datetime_utc
        LIMIT {HOTSPOT_ROW_CAP + 1}
    """
    params = [start, end, s - pad, n + pad, w - pad, e + pad] + ([sensor] if sensor else [])
    store = c.store

    def stream():
        cur = store.con.cursor()
        try:
            cur.register("sel", sel)
            rel = cur.sql(sql, params=params)
            # DuckDB 2.x: to_arrow_reader(); DuckDB 1.x: fetch_arrow_reader()
            reader = (rel.to_arrow_reader() if hasattr(rel, "to_arrow_reader")
                      else rel.fetch_arrow_reader(50_000))
            sent, header = 0, True
            for batch in reader:
                df = batch.to_pandas()
                if sent + len(df) > HOTSPOT_ROW_CAP:
                    df = df.iloc[:HOTSPOT_ROW_CAP - sent]
                    yield df.to_csv(index=False, header=header, lineterminator="\n")
                    yield (f"# Only the first {HOTSPOT_ROW_CAP:,} hotspots are included. "
                           "Pick a smaller area or a shorter date range to get them all.\n")
                    return
                sent += len(df)
                yield df.to_csv(index=False, header=header, lineterminator="\n")
                header = False
            if header:   # no rows at all: still send the header line
                yield "lat,lon,datetime_utc,satellite,sensor,frp,confidence,daynight,provisional,weight\n"
        finally:
            cur.close()

    name = f"firebridge_hotspots_{start}_{end}.csv"
    return StreamingResponse(stream(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/methods", include_in_schema=False)
def methods_page():
    page = STATIC_DIR / "methods.html"
    if not page.exists():
        return JSONResponse(status_code=404, content={"error": "methods.html isn't built yet."})
    return FileResponse(page)


# Website (Track C's files). Registered last so the /api routes above always win.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    @app.get("/", include_in_schema=False)
    def no_website_yet():
        return {"message": "FireBridge API is running. The website (app/static/) isn't built "
                           "yet; try /docs to explore the API."}
