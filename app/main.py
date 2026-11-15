"""
FireBridge API: FastAPI + DuckDB over the app data in data/app/ (docs/CONTRACTS.md section 2).

Run from the repo root:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000 (website) or http://127.0.0.1:8000/docs (try every endpoint).

Data folder: env var APP_DATA_DIR (default data/app). If it's empty, make fake data first:
    python scripts/make_synthetic_app_data.py
Deployed: set APP_DATA_URL (Hugging Face dataset URL ending in /resolve/main/) and the 4 data
files are downloaded into APP_DATA_DIR at startup if missing (see "Deploy" below). Set
FIRMS_MAP_KEY and the live FIRMS feed refreshes in the background at most once an hour
(LIVE_REFRESH=0 turns it off; LIVE_CACHE_DIR moves its cache). GET /api/status shows both.

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
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import List, Literal, Optional

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, Response,
                               StreamingResponse)
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
    check_download_status()
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
# Deploy: download the app data at startup (B6)
# =============================================================================================
# On the deployed site the data isn't in the container. Set APP_DATA_URL to the Hugging Face
# dataset's base URL (ending in /resolve/main/) and the 4 files are downloaded by name into
# APP_DATA_DIR when the server starts, if they're missing. The server answers right away;
# until the download finishes, endpoints return 503 "still downloading".

DOWNLOAD_CHUNK = 1 << 20          # write to disk 1 MB at a time (never hold a file in memory)
DOWNLOAD_RETRIES = 3
_download = {"active": False, "file": None, "mb_done": 0.0, "mb_total": None, "error": None}


def _http_client():
    import httpx
    return httpx.Client(follow_redirects=True,
                        timeout=httpx.Timeout(60.0, read=300.0))   # HF redirects to its CDN


def data_base_url(url):
    """The folder URL the 4 files live under. Accepts the folder URL (ending in /resolve/main/)
    or, by mistake, a URL to one of the files (e.g. .../resolve/main/coverage.json)."""
    url = url.strip().split("?")[0]
    last = url.rstrip("/").rsplit("/", 1)[-1]
    if not url.endswith("/") and "." in last:
        url = url[: -len(last)]
    return url if url.endswith("/") else url + "/"


def missing_data_files(data_dir):
    return [f for f in DataStore.REQUIRED if not (Path(data_dir) / f).exists()]


def download_app_data(base_url, data_dir, client=None):
    """Download every missing required file from base_url into data_dir, streaming to disk.
    Each file goes to '<name>.part' first and is renamed only when complete."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    base = data_base_url(base_url)
    own = client is None
    client = client or _http_client()
    try:
        for name in missing_data_files(data_dir):
            dest, part = data_dir / name, data_dir / (name + ".part")
            error = None
            for attempt in range(1, DOWNLOAD_RETRIES + 1):
                try:
                    with client.stream("GET", base + name) as r:
                        r.raise_for_status()
                        size = r.headers.get("content-length")
                        _download.update(file=name, mb_done=0.0,
                                         mb_total=round(int(size) / 1e6) if size else None)
                        with open(part, "wb") as f:
                            for chunk in r.iter_bytes(DOWNLOAD_CHUNK):
                                f.write(chunk)
                                _download["mb_done"] += len(chunk) / 1e6
                    os.replace(part, dest)
                    print(f"[data] downloaded {name} ({dest.stat().st_size / 1e6:.0f} MB)",
                          flush=True)
                    error = None
                    break
                except Exception as ex:
                    error = f"{name}: {ex}"
                    print(f"[data] download attempt {attempt} failed: {error}", flush=True)
                    part.unlink(missing_ok=True)
            if error:
                raise RuntimeError(f"Couldn't download {error}")
    finally:
        if own:
            client.close()


def _download_in_background(base_url, data_dir):
    _download.update(active=True, error=None)
    try:
        download_app_data(base_url, data_dir)
    except Exception as ex:
        _download["error"] = str(ex)
    finally:
        _download["active"] = False


def start_data_download():
    """Called at startup: begin downloading missing data files if APP_DATA_URL is set."""
    url = os.environ.get("APP_DATA_URL", "").strip()
    data_dir = os.environ.get("APP_DATA_DIR", REPO / "data" / "app")
    if not url or not missing_data_files(data_dir):
        return None
    _download["active"] = True       # set before the thread starts so requests see it at once
    t = threading.Thread(target=_download_in_background, args=(url, data_dir), daemon=True,
                         name="app-data-download")
    t.start()
    return t


# ---- Live FIRMS feed, refreshed in the background at most once an hour -----------------------
# Needs FIRMS_MAP_KEY in the environment (a Space secret). pipeline/live.py writes the live_*
# files atomically and get_store() reloads when they change, so visitors just see fresher data.
# A failed refresh is logged and ignored: the site keeps serving the last good data.

LIVE_REFRESH_SECONDS = 3600
_live = {"active": False, "last_ok": None, "last_error": None, "runs": 0}
_live_stop = threading.Event()


def _firms_key():
    # FIRMS_MAP_KEY is the documented name; FIRMS_MAPKEY is accepted in case the secret is
    # typed without the underscore.
    return (os.environ.get("FIRMS_MAP_KEY") or os.environ.get("FIRMS_MAPKEY") or "").strip()


def _seconds_since_last_refresh(data_dir):
    p = Path(data_dir) / "live_coverage.json"
    if not p.exists():
        return None
    import time
    return time.time() - p.stat().st_mtime


def refresh_live_once(data_dir):
    """Run pipeline/live.py once. Never raises: errors are logged and remembered."""
    from datetime import datetime, timezone
    _live["runs"] += 1
    try:
        from pipeline import live
        live.run(_firms_key(), data_dir)
        _live["last_ok"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _live["last_error"] = None
        print("[live] refresh finished", flush=True)
    except BaseException as ex:          # incl. SystemExit from inside the pipeline
        _live["last_error"] = f"{type(ex).__name__}: {ex}"
        print(f"[live] refresh FAILED, keeping the last good data: {_live['last_error']}",
              flush=True)


def _live_loop(data_dir):
    _live["active"] = True
    try:
        # wait for the startup download, if any
        while (_download["active"] or missing_data_files(data_dir)) and not _live_stop.is_set():
            if _download["error"]:
                print("[live] no app data, so no live refresh", flush=True)
                return
            _live_stop.wait(5)
        # restarted soon after a refresh? wait out the rest of the hour first
        age = _seconds_since_last_refresh(data_dir)
        if age is not None and age < LIVE_REFRESH_SECONDS:
            _live_stop.wait(LIVE_REFRESH_SECONDS - age)
        while not _live_stop.is_set():
            refresh_live_once(data_dir)
            _live_stop.wait(LIVE_REFRESH_SECONDS)
    finally:
        _live["active"] = False


def start_live_refresh():
    """Called at startup: refresh the live feed hourly if a FIRMS key is configured.
    Set LIVE_REFRESH=0 to turn it off (e.g. when running locally)."""
    if not _firms_key() or os.environ.get("LIVE_REFRESH", "1") == "0":
        return None
    data_dir = os.environ.get("APP_DATA_DIR", REPO / "data" / "app")
    _live_stop.clear()
    t = threading.Thread(target=_live_loop, args=(data_dir,), daemon=True, name="live-refresh")
    t.start()
    return t


def check_download_status():
    """Raise DataMissing with a friendly message while data is downloading or if it failed."""
    if _download["active"]:
        done = f"{_download['mb_done']:.0f}"
        total = f" of {_download['mb_total']}" if _download["mb_total"] else ""
        raise DataMissing(f"The fire data is still downloading ({_download['file'] or 'starting'}"
                          f", {done}{total} MB). Try again in a minute.")
    if _download["error"]:
        raise DataMissing(f"The fire data couldn't be downloaded: {_download['error']}. "
                          "Check APP_DATA_URL and restart the app.")


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
    granularity: Optional[Literal["day", "week", "month"]] = None
    as_of: Optional[date] = None      # /api/current: compare a past month instead of this one
    lang: Literal["en", "es"] = "en"   # language of the plain-language sentences (es = beta)


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
        self.outside_share = None
        if whole > 0 and covered / whole < 0.98:
            self.outside_share = covered / whole
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

@asynccontextmanager
async def lifespan(_app):
    start_data_download()          # no-op unless APP_DATA_URL is set and files are missing
    start_live_refresh()           # no-op unless FIRMS_MAP_KEY is set
    yield
    _live_stop.set()


app = FastAPI(title="FireBridge API",
              description="Harmonized MODIS + VIIRS burning activity calendar (NASA Space Apps 2026)",
              lifespan=lifespan)
# The frontend may be served from another port while developing, so allow cross-origin calls.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                   allow_headers=["*"])


@app.middleware("http")
async def _revalidate_website_files(request: Request, call_next):
    """Browsers must re-check website files (cheap: ETag -> 304) so a redeploy shows up at once
    instead of an old cached app.js or style.css."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


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


@app.get("/api/status")
def status():
    """Deploy status: data download progress and the last live-feed refresh (not in the
    contract; for checking the deployed site)."""
    url = os.environ.get("APP_DATA_URL", "")
    rev = url.split("/resolve/", 1)[1].split("/", 1)[0] if "/resolve/" in url else None
    return clean({"download": dict(_download),
                  "data": {"source": data_base_url(url) if url else "local files",
                           "dataset_revision": rev},
                  "live_refresh": {
        **_live, "enabled": bool(_firms_key()) and os.environ.get("LIVE_REFRESH", "1") != "0",
        "every_seconds": LIVE_REFRESH_SECONDS}})


@app.post("/api/summary")
def summary(q: Query):
    """Key figures + a plain-language summary for the area and date range."""
    c = ctx_for(q)
    start, end = c.date_range()
    s = c.series()
    out = an.summary(s, start, end, c.baseline, c.provisional_after, c.unit_word,
                     {"area_km2": c.area_km2, "cells": c.n_cells, "region": c.region,
                      "outside_note": c.outside_note, "outside_share": c.outside_share}, lang=q.lang)
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
    return clean(an.patterns(c.series(), c.baseline, c.provisional_after, lang=q.lang))


@app.post("/api/current")
def current(q: Query):
    """The current month so far vs the same days in previous years."""
    c = ctx_for(q)
    as_of = min(q.as_of or c.data_end, c.data_end)
    if as_of < c.data_start:
        raise ApiError(f"'as_of' must be after {c.data_start}.")
    return clean(an.current(c.series(), as_of, c.baseline, c.provisional_after, c.unit_word, lang=q.lang))


UNUSUAL_MIN_PCT = 300      # this month so far at least 3x the median for the same days...
UNUSUAL_MIN_HOTSPOTS = 50  # ...and at least 50 hotspots, so quiet tiles can't raise false alarms
_unusual_cache = {}


@app.get("/api/unusual")
def unusual_now():
    """'Unusual right now': 1 degree tiles in all regions where this month so far (harmonized)
    is far above the median for the same days of the month in 2003-2022. Not in the original
    contract. Cached per loaded data."""
    store = get_store()
    end = max(r["end"] for r in store.regions.values())
    key = (id(store), end)
    if key in _unusual_cache:
        return _unusual_cache[key]
    y0, y1 = DEFAULT_BASELINE
    cur = store.con.cursor()
    try:
        df = cur.execute(
            "SELECT region, floor(lat) AS tlat, floor(lon) AS tlon, year(date) AS yr, sum(mec) AS v "
            "FROM cells WHERE month(date) = ? AND day(date) <= ? AND (year(date) BETWEEN ? AND ? OR year(date) = ?) "
            "GROUP BY 1, 2, 3, 4", [end.month, end.day, y0, y1, end.year]).df()
    finally:
        cur.close()
    years = list(range(y0, y1 + 1))
    tiles = []
    for (region, tlat, tlon), g in df.groupby(["region", "tlat", "tlon"]):
        now = float(g.loc[g["yr"] == end.year, "v"].sum())
        if now < UNUSUAL_MIN_HOTSPOTS:
            continue
        past = g[g["yr"].isin(years)].set_index("yr")["v"].reindex(years).fillna(0)
        med = float(past.median())
        pct = now / med * 100 if med > 0 else None
        if pct is not None and pct < UNUSUAL_MIN_PCT:
            continue
        rank = 1 + int((past > now).sum())
        tiles.append({"region": region, "region_name": store.regions[region]["name"],
                      "lat": float(tlat) + 0.5, "lon": float(tlon) + 0.5,
                      # box around exactly this tile's cell centers (tlat .. tlat + 0.9), so
                      # clicking it analyzes the same cells this count came from
                      "bbox": [float(tlon) - 0.04, float(tlat) - 0.04, float(tlon) + 0.94, float(tlat) + 0.94],
                      "value": round(now, 1), "median": round(med, 1),
                      "pct_of_median": round(pct) if pct is not None else None,
                      "rank_since_2003": rank, "excess": round(now - med, 1)})
    tiles.sort(key=lambda t: -t["excess"])
    out = {"month": end.strftime("%Y-%m"), "days_so_far": end.day, "as_of": end.isoformat(),
           "baseline": DEFAULT_BASELINE, "min_pct": UNUSUAL_MIN_PCT, "min_hotspots": UNUSUAL_MIN_HOTSPOTS,
           "provisional": end > min(r["archive_end"] for r in store.regions.values()),
           "tiles": tiles[:10], "tiles_total": len(tiles)}
    _unusual_cache.clear()
    _unusual_cache[key] = out
    return out


@app.post("/api/fires")
def fires(q: Query):
    """Fire clusters in the area over the whole record: the most recent ones ranked against
    every earlier cluster, and the largest ones (not in the original contract)."""
    c = ctx_for(q)
    col = MODE_COLUMN[q.mode]
    sel = c.sel[["region", "cell_id"]]
    if sel.empty:
        return clean(an.clusters_response(an.fire_clusters(pd.DataFrame(columns=["cell_id", "lat", "lon", "date", "value", "frp"])),
                                          c.data_end, c.provisional_after, c.unit_word))
    cur = c.store.con.cursor()
    try:
        cur.register("sel", sel)
        join = "FROM cells c JOIN sel s ON c.region = s.region AND c.cell_id = s.cell_id"
        n = cur.execute(f"SELECT count(*) {join} WHERE {col} > 0").fetchone()[0]
        if n > an.MAX_CLUSTER_RECORDS:
            raise ApiError("This area has too many fires to group into clusters quickly. "
                           "Draw a smaller area (for example one state or province).")
        rec = cur.execute(f"SELECT c.cell_id, c.lat, c.lon, c.date, {col} AS value, mefrp AS frp "
                          f"{join} WHERE {col} > 0").df()
    finally:
        cur.close()
    cl = an.fire_clusters(rec)
    return clean(an.clusters_response(cl, c.data_end, c.provisional_after, c.unit_word, lang=q.lang))


MAP_CELL_CAP = 20_000


@app.post("/api/cells")
def map_cells(q: Query):
    """Fire on the map: per 0.1 degree cell in the area, the total for the date range and the
    'normal' for the same calendar dates (median over the baseline years, a year with no
    detections in that cell counting as 0). Not in the original contract (added for the map)."""
    c = ctx_for(q)
    start, end = c.date_range()
    if (end - start).days > 366 * 26:
        raise ApiError("Pick a shorter date range for the map.")
    col = "mefrp" if (q.mode == "harmonized" and q.metric == "frp") else MODE_COLUMN[q.mode]
    sel = c.sel[["region", "cell_id", "lat", "lon"]]
    if sel.empty:
        return {"cells": [], "cell_deg": an.CELL_DEG, "units": c.units, "baseline": c.baseline,
                "truncated": False}
    length = end - start
    windows = []
    for y in an.baseline_years(c.baseline):          # the same calendar window in each baseline year
        sy = pd.Timestamp(an._shift_year(pd.Timestamp(start), y))
        windows.append({"year": y, "ws": sy.date(), "we": (sy + length).date()})
    cur = c.store.con.cursor()
    try:
        cur.register("sel", sel[["region", "cell_id"]])
        now = cur.execute(
            f"SELECT c.region, c.cell_id, sum({col}) AS value FROM cells c JOIN sel s "
            "ON c.region = s.region AND c.cell_id = s.cell_id "
            "WHERE c.date BETWEEN ? AND ? GROUP BY 1, 2", [start, end]).df()
        cur.register("win", pd.DataFrame(windows))
        past = cur.execute(
            f"SELECT c.region, c.cell_id, w.year, sum({col}) AS value FROM cells c JOIN sel s "
            "ON c.region = s.region AND c.cell_id = s.cell_id "
            "JOIN win w ON c.date BETWEEN w.ws AND w.we GROUP BY 1, 2, 3").df()
    finally:
        cur.close()
    years = len(windows)
    if len(past):
        wide = past.pivot_table(index=["region", "cell_id"], columns="year", values="value",
                                aggfunc="sum").reindex(columns=[w["year"] for w in windows]).fillna(0)
        med = wide.median(axis=1).rename("median").reset_index()
    else:
        med = pd.DataFrame(columns=["region", "cell_id", "median"])
    out = sel.merge(now, on=["region", "cell_id"], how="left").merge(med, on=["region", "cell_id"], how="left")
    out[["value", "median"]] = out[["value", "median"]].fillna(0)
    out = out[(out["value"] > 0) | (out["median"] > 0)]
    truncated = len(out) > MAP_CELL_CAP
    out = out.sort_values("value", ascending=False).head(MAP_CELL_CAP)
    cells = [{"lat": round(float(r.lat), 2), "lon": round(float(r.lon), 2),
              "value": round(float(r.value), 1), "median": round(float(r.median), 1)}
             for r in out.itertuples(index=False)]
    return {"cells": cells, "cell_deg": an.CELL_DEG, "units": c.units, "baseline": c.baseline,
            "baseline_years_used": years, "truncated": truncated}


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


HOTSPOT_COLUMNS = ["lat", "lon", "datetime_utc", "satellite", "sensor", "frp", "confidence",
                   "daynight", "provisional", "weight"]
def truncated_note():
    return (f"Only the first {HOTSPOT_ROW_CAP:,} hotspots are included. "
            "Pick a smaller area or a shorter date range to get them all.")


def _hotspot_batches(q: Query):
    """(start, end, generator). The generator yields DataFrames of hotspot rows (HOTSPOT_COLUMNS),
    capped at HOTSPOT_ROW_CAP, then the string "truncated" if the cap was hit.

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

    def batches():
        cur = store.con.cursor()
        try:
            cur.register("sel", sel)
            rel = cur.sql(sql, params=params)
            # DuckDB 2.x: to_arrow_reader(); DuckDB 1.x: fetch_arrow_reader()
            reader = (rel.to_arrow_reader() if hasattr(rel, "to_arrow_reader")
                      else rel.fetch_arrow_reader(50_000))
            sent = 0
            for batch in reader:
                df = batch.to_pandas()
                if sent + len(df) > HOTSPOT_ROW_CAP:
                    yield df.iloc[:HOTSPOT_ROW_CAP - sent]
                    yield "truncated"
                    return
                sent += len(df)
                yield df
        finally:
            cur.close()

    return start, end, batches()


def _file_response(stream, media_type, name):
    return StreamingResponse(stream, media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/export/hotspots.csv")
def export_hotspots(q: Query):
    """The hotspot points in the area and date range as CSV, streamed, capped at 200,000 rows."""
    start, end, batches = _hotspot_batches(q)

    def stream():
        yield ",".join(HOTSPOT_COLUMNS) + "\n"
        for b in batches:
            if isinstance(b, str):
                yield f"# {truncated_note()}\n"
            else:
                yield b.to_csv(index=False, header=False, lineterminator="\n")

    return _file_response(stream(), "text/csv", f"firebridge_hotspots_{start}_{end}.csv")


def _props(r):
    return {"datetime_utc": r.datetime_utc, "satellite": r.satellite, "sensor": r.sensor,
            "frp_mw": r.frp, "confidence": r.confidence, "daynight": r.daynight,
            "provisional": r.provisional == "true", "weight": r.weight}


@app.post("/api/export/hotspots.geojson")
def export_hotspots_geojson(q: Query):
    """The same hotspots as a GeoJSON FeatureCollection (QGIS, ArcGIS, web maps)."""
    start, end, batches = _hotspot_batches(q)

    def stream():
        yield ('{"type":"FeatureCollection","name":"firebridge_hotspots",'
               '"source":"NASA FIRMS MODIS + VIIRS, harmonized by FireBridge","features":[')
        first, truncated = True, False
        for b in batches:
            if isinstance(b, str):
                truncated = True
                continue
            out = []
            for r in b.itertuples(index=False):
                feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                        "properties": _props(r)}
                out.append(("" if first else ",") + json.dumps(feat, separators=(",", ":")))
                first = False
            yield "".join(out)
        yield "]" + (f',"note":{json.dumps(truncated_note())}' if truncated else "") + "}"

    return _file_response(stream(), "application/geo+json", f"firebridge_hotspots_{start}_{end}.geojson")


@app.post("/api/export/hotspots.kml")
def export_hotspots_kml(q: Query):
    """The same hotspots as KML (Google Earth): one placemark per hotspot, with its time."""
    from xml.sax.saxutils import escape
    start, end, batches = _hotspot_batches(q)

    def stream():
        yield ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">'
               f'<Document><name>FireBridge hotspots {start} to {end}</name>'
               '<description>NASA FIRMS MODIS + VIIRS hotspots; weight = MODIS-equivalent hotspots '
               'this point adds to the harmonized count.</description>'
               '<Style id="hs"><IconStyle><color>ff0c59e8</color><scale>0.6</scale><Icon><href>'
               'http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href></Icon></IconStyle></Style>\n')
        for b in batches:
            if isinstance(b, str):
                yield f"<Placemark><name>Note</name><description>{escape(truncated_note())}</description></Placemark>\n"
                continue
            out = []
            for r in b.itertuples(index=False):
                data = "".join(f'<Data name="{k}"><value>{escape(str(v))}</value></Data>'
                               for k, v in _props(r).items())
                out.append(f"<Placemark><name>{escape(r.satellite)} {escape(r.datetime_utc)}</name>"
                           f"<TimeStamp><when>{escape(r.datetime_utc)}</when></TimeStamp>"
                           f"<styleUrl>#hs</styleUrl><ExtendedData>{data}</ExtendedData>"
                           f"<Point><coordinates>{r.lon},{r.lat}</coordinates></Point></Placemark>\n")
            yield "".join(out)
        yield "</Document></kml>\n"

    return _file_response(stream(), "application/vnd.google-earth.kml+xml",
                     f"firebridge_hotspots_{start}_{end}.kml")


FIGURES = [  # (file in results/figures, caption) shown on the Methods page
    ("continuity_texas.png", "Texas, 2001 to now: the naive record jumps when VIIRS starts; the "
                             "harmonized record continues on the MODIS scale."),
    ("continuity_amazon.png", "Amazon, the same comparison."),
    ("continuity_australia.png", "Northern Australia, the same comparison."),
    ("scatter_before_after.png", "Test years, every 25 km square-month: raw VIIRS (left) sits far "
                                 "above MODIS; after harmonizing (right) it follows the 1:1 line."),
    ("bias_before_after.png", "Bias against MODIS Aqua before and after harmonizing, by region."),
    ("overpass_times.png", "When each satellite passes over. Terra and Aqua have drifted in "
                           "recent years, which is one of our stated limitations."),
]


def _methods_html():
    """Methods page body: headline cards from results/metrics.json, Track A's methods text
    (docs/methods_text.md) and the validation figures. Rendered on the server so the numbers
    are in the HTML itself (Track A's science check reads them there)."""
    import html as h
    import markdown
    text = (REPO / "docs" / "methods_text.md").read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables"])
    body = body.replace("<table>", '<table class="results-table">')

    cards = ""
    mp = REPO / "results" / "metrics.json"
    if mp.exists():
        m = json.loads(mp.read_text())["overall"]
        ho, tr = m["holdout"], m["transfer_noaa20"]
        # number formats match results/metrics.json (thousands with commas, bias to 2 decimals)
        sign = lambda x: f"{'+' if x >= 0 else '−'}{abs(x):.2f}%"
        cards = f"""
<div class="metrics-cards">
  <div class="kf"><span class="kf-label">Raw VIIRS vs MODIS</span>
    <span class="kf-value">{sign(ho['raw_viirs']['bias_pct'])}</span>
    <span class="kf-sub">bias before harmonizing (test years)</span></div>
  <div class="kf"><span class="kf-label">After harmonizing</span>
    <span class="kf-value">{sign(ho['harmonized']['bias_pct'])}</span>
    <span class="kf-sub">bias on the test years</span></div>
  <div class="kf"><span class="kf-label">Typical monthly error</span>
    <span class="kf-value">{abs(ho['harmonized']['rmse']):,.0f}</span>
    <span class="kf-sub">hotspots/month, vs {abs(ho['global_ratio']['rmse']):,.0f} for one global
      ratio; NOAA-20 (never used in fitting): {abs(tr['harmonized']['rmse']):,.0f} vs
      {abs(tr['global_ratio']['rmse']):,.0f}</span></div>
</div>"""

    figs = "".join(
        f'<figure><img src="/figures/{f}" alt="{h.escape(c)}" loading="lazy">'
        f"<figcaption>{h.escape(c)}</figcaption></figure>"
        for f, c in FIGURES if (REPO / "results" / "figures" / f).exists())
    if figs:
        figs = "<h2>Validation figures</h2>" + figs
        marker = "<h2>Data sources</h2>"
        body = body.replace(marker, figs + marker, 1) if marker in body else body + figs
    # validation chart (drawn in the browser from /content/metrics.json by methods.html)
    cards += ('<figure class="val-chart"><div class="chart-box"><canvas id="val-chart" role="img" '
              'aria-label="Typical monthly error by region: one global ratio versus FireBridge, on the test years '
              'and on NOAA-20"></canvas></div><figcaption>Typical monthly error (RMSE, hotspots per month; lower is '
              'better) on the test years and on NOAA-20, which was never used in fitting. Raw VIIRS is far off the '
              'chart. Numbers in the tables below.</figcaption></figure>')
    # put the headline cards right after the page title
    first_h2 = body.find("<h2>")
    body = body[:first_h2] + cards + body[first_h2:] if first_h2 > 0 else cards + body
    return body


@app.get("/judges", include_in_schema=False)
def judges_page():
    page = STATIC_DIR / "judges.html"
    if not page.exists():
        return JSONResponse(status_code=404, content={"error": "judges.html isn't built yet."})
    return FileResponse(page)


@app.get("/methods", include_in_schema=False)
def methods_page():
    page = STATIC_DIR / "methods.html"
    if not page.exists():
        return JSONResponse(status_code=404, content={"error": "methods.html isn't built yet."})
    page_html = page.read_text(encoding="utf-8")
    if "<!--METHODS_CONTENT-->" in page_html and (REPO / "docs" / "methods_text.md").exists():
        page_html = page_html.replace("<!--METHODS_CONTENT-->", _methods_html())
    return HTMLResponse(page_html)


def _checks_html():
    """'More checks' page body from results/extra/extra_checks.json (scripts/extra_checks.py)."""
    import html as h
    p = REPO / "results" / "extra" / "extra_checks.json"
    if not p.exists():
        return "<h1>More checks</h1><p>Not computed yet: run <code>python scripts/extra_checks.py</code>.</p>"
    d = json.loads(p.read_text(encoding="utf-8"))
    names = {"texas": "Texas", "amazon": "Amazon", "australia": "Northern Australia"}
    sg = lambda x: f"{'+' if x >= 0 else '−'}{abs(x):.2f}%"
    live = d["live_harmonization"]
    rows_live = "".join(
        f"<tr><td>{names.get(r, r)}</td><td class='num'>{v['one_factor']['monthly_abs_error_pct']:.1f}%</td>"
        f"<td class='num'><b>{v['factor_by_month']['monthly_abs_error_pct']:.1f}%</b></td>"
        f"<td class='num'>{sg(v['one_factor']['total_bias_pct'])}</td><td class='num'>{sg(v['factor_by_month']['total_bias_pct'])}</td>"
        f"<td class='num'>{v['factor_range'][0]:.3f}–{v['factor_range'][1]:.3f}</td></tr>"
        for r, v in live["regions"].items())
    rows_drift = ""
    for r, periods in d["drift"].items():
        for name, v in periods.items():
            rows_drift += (f"<tr><td>{names.get(r, r)}</td><td>{h.escape(name)}</td><td class='num'>{sg(v['bias_pct'])}</td>"
                           f"<td class='num'>{v['monthly_r']:.3f}</td><td class='num'>{v['daily_r']:.3f}</td></tr>")
    md = d["missing_days"]
    if "error" in md:
        miss = f"<p>{h.escape(md['error'])}</p>"
    else:
        rows_miss = "".join(
            f"<tr><td>{names.get(r, r)}</td><td class='num'>{v['our_modis_missing_days']}</td>"
            f"<td class='num'>{v['official_terra_or_aqua_down_days']}</td><td class='num'>{v['flagged_and_official']}</td>"
            f"<td class='num'>{v['official_not_flagged']}</td><td class='num'>{v['flagged_not_official']}</td></tr>"
            for r, v in md["regions"].items())
        miss = (f"<table class='results-table'><thead><tr><th>Region</th><th class='num'>Days flagged missing (MODIS)</th>"
                f"<th class='num'>FIRMS: Terra or Aqua down</th><th class='num'>Both</th><th class='num'>Only FIRMS</th>"
                f"<th class='num'>Only flagged</th></tr></thead><tbody>{rows_miss}</tbody></table>"
                f"<p>{h.escape(md['reading'])} Source: <a href='{md['source']}'>FIRMS missing-data table</a>.</p>")
    fig = lambda f, c: (f'<figure><img src="/extra-figures/{f}" alt="{h.escape(c)}" loading="lazy">'
                        f"<figcaption>{h.escape(c)}</figcaption></figure>")
    return f"""
<h1>More checks</h1>
<p>Three extra checks that use only the app's own data, run by <code>scripts/extra_checks.py</code>
({h.escape(d['generated'])}). The main validation (temporal holdout and NOAA-20 transfer) is on
<a href="/methods">How it works</a>.</p>

<h2>1. Live data: scaling by month halves the error</h2>
<p>The newest days come from FIRMS's near-real-time feed, after the archive ends. They are scaled to the MODIS
level by how much the harmonization scaled raw VIIRS in the archive. That factor changes with the season, so the
live feed now uses one factor per region and calendar month. Fitted on {live['fit'][0]} to {live['fit'][1]} and
tested on {live['test'][0]} to {live['test'][1]}, which it never saw:</p>
<table class="results-table"><thead><tr><th>Region</th><th class="num">Monthly error, one factor</th>
<th class="num">Monthly error, factor by month</th><th class="num">Total bias, one factor</th>
<th class="num">Total bias, by month</th><th class="num">Factor range</th></tr></thead><tbody>{rows_live}</tbody></table>
{fig("live_factor_by_month.png", "MODIS-equivalent hotspots per raw VIIRS hotspot, by calendar month.")}

<h2>2. Does the record drift as the MODIS satellites age?</h2>
<p>In the years both sensors fly, the harmonized record should stay on the MODIS Terra + Aqua scale. Texas and
Northern Australia match it in the fitting years and drift upward later, Texas most since 2022, when Terra and
Aqua began leaving their orbits. The Amazon sits about 5% low in every period, the fitting years included, so its
gap is a steady offset rather than drift. Bias is total harmonized vs MODIS; r is the correlation of monthly and
daily regional totals.</p>
<table class="results-table"><thead><tr><th>Region</th><th>Years</th><th class="num">Bias vs MODIS</th>
<th class="num">Monthly r</th><th class="num">Daily r</th></tr></thead><tbody>{rows_drift}</tbody></table>
{fig("drift_by_year.png", "Harmonized VIIRS divided by MODIS Terra + Aqua, per whole year; 1.0 means the same scale.")}

<h2>3. Missing days compared with FIRMS's official list</h2>
{miss}
"""


@app.get("/checks", include_in_schema=False)
def checks_page():
    page = STATIC_DIR / "checks.html"
    if not page.exists():
        return JSONResponse(status_code=404, content={"error": "checks.html isn't built yet."})
    return HTMLResponse(page.read_text(encoding="utf-8").replace("<!--CHECKS_CONTENT-->", _checks_html()))


if (REPO / "results" / "extra").is_dir():
    app.mount("/extra-figures", StaticFiles(directory=REPO / "results" / "extra"), name="extra-figures")


# Track A's files the website shows, served straight from where Track A keeps them, so the
# site never has stale copies: presets, Methods text, metrics.json and validation figures.
CONTENT_FILES = {"presets.json": REPO / "docs" / "presets.json",
                 "methods_text.md": REPO / "docs" / "methods_text.md",
                 "metrics.json": REPO / "results" / "metrics.json"}


@app.get("/content/{name}", include_in_schema=False)
def content_file(name: str):
    path = CONTENT_FILES.get(name)
    if path is None or not path.exists():
        return JSONResponse(status_code=404, content={"error": f"{name} not found."})
    return FileResponse(path)


if (REPO / "results" / "figures").is_dir():
    app.mount("/figures", StaticFiles(directory=REPO / "results" / "figures"), name="figures")


# Website (Track C's files). Registered last so the /api routes above always win.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def no_website_yet():
        return {"message": "FireBridge API is running. The website (app/static/) isn't built "
                           "yet; try /docs to explore the API."}
