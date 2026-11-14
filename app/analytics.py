"""
FireBridge analytics: all the math from CLAUDE.md section 5, as plain functions.

Nothing here touches files or the web. app/main.py loads the data, adds up the harmonized
hotspots for the user's area into one DAILY SERIES, and hands that series to these functions.

The daily series is a pandas Series:
    index  = every calendar day (no gaps)
    value  = hotspots that day in the area (0 if none were seen)
    NaN    = the satellite had NO DATA that day. Missing data is never treated as zero fire.

Sections:
    1. Area selection      (polygon / bbox / point + radius  ->  0.1 degree cells)
    2. Daily series        (sparse rows -> full daily series with NaN on missing days)
    3. Climatology         (what is "normal" for each day / month, from the baseline years)
    4. Patterns            (month x year grid, years ranked, fire season, high-risk months...)
    5. Comparisons         (a date range or the current month vs the same days in other years)
    6. Plain language      (sentences built ONLY from the computed numbers)
    7. Response builders   (put it together in the exact JSON shapes of docs/CONTRACTS.md)
"""

import json
import math
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box, shape

EARTH_RADIUS_KM = 6371.0088
CELL_DEG = 0.1             # app grid size in degrees
SMOOTH_DAYS = 15           # day-of-year climatology pools +/- 15 days around each day
MAX_MISSING_SHARE = 0.2    # a month/window with more than 20% missing days is reported as missing
FIRE_SEASON_SHARE = 0.8    # fire season = shortest stretch of the year holding 80% of activity
HIGH_RISK_SHARE = 0.2      # high-risk months = the top 20% of months (3 of 12)
UNUSUAL_Z = 1.0            # "unusual month" = more than 1 standard deviation above normal

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
MON = [m[:3] for m in MONTHS]


class AreaError(ValueError):
    """The user's area can't be used. The message is shown to the user as-is."""


# =============================================================================================
# 1. Area selection
# =============================================================================================

class Area:
    """A user-selected area: a shape on the map, or a point with a radius in km."""

    def __init__(self, kind, geom, lat=None, lon=None, radius_km=None):
        self.kind = kind
        self.geom = geom            # shapely geometry in lon/lat (a circle polygon for points)
        self.lat, self.lon, self.radius_km = lat, lon, radius_km
        shapely.prepare(self.geom)

    def contains(self, lat, lon):
        """True for each (lat, lon) inside the area (edges count as inside)."""
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        if self.kind == "point":
            return haversine_km(self.lat, self.lon, lat, lon) <= self.radius_km
        return shapely.intersects_xy(self.geom, lon, lat)


def _num(x, name):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise AreaError(f"'{name}' must be a number.")
    if not math.isfinite(v):
        raise AreaError(f"'{name}' must be a number.")
    return v


def _check_lonlat(lon, lat):
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise AreaError("Coordinates must be longitude -180..180 and latitude -90..90.")


def parse_area(area):
    """Turn the API's `area` object into an Area. Raises AreaError with a plain message.

    Accepted (docs/CONTRACTS.md section 4):
      {"type": "bbox", "bbox": [W, S, E, N]}
      {"type": "polygon", "coordinates": [[[lon, lat], ...]]}     (GeoJSON order)
      {"type": "point", "lat": 31, "lon": -98, "radius_km": 50}
    Also accepted, to make the frontend's life easy: GeoJSON "Polygon"/"MultiPolygon"
    geometries and GeoJSON Features (what Leaflet.draw's toGeoJSON() gives).
    """
    if not isinstance(area, dict):
        raise AreaError("Please choose an area: draw one on the map or type coordinates.")
    if area.get("type", "").lower() == "feature":
        area = area.get("geometry") or {}
    kind = str(area.get("type", "")).lower()

    if kind == "bbox":
        bb = area.get("bbox")
        if not isinstance(bb, (list, tuple)) or len(bb) != 4:
            raise AreaError("A box needs four numbers: west, south, east, north.")
        w, s, e, n = (_num(v, "bbox") for v in bb)
        _check_lonlat(w, s)
        _check_lonlat(e, n)
        if w >= e or s >= n:
            raise AreaError("In a box, west must be less than east and south less than north.")
        return Area("bbox", box(w, s, e, n))

    if kind in ("polygon", "multipolygon"):
        try:
            geom = shape({"type": "Polygon" if kind == "polygon" else "MultiPolygon",
                          "coordinates": area.get("coordinates")})
        except Exception:
            raise AreaError("That polygon couldn't be read. Expected GeoJSON order: "
                            "[[[lon, lat], [lon, lat], ...]].")
        if geom.is_empty:
            raise AreaError("That polygon is empty.")
        minx, miny, maxx, maxy = geom.bounds
        _check_lonlat(minx, miny)
        _check_lonlat(maxx, maxy)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)
        if geom.area <= 0:
            raise AreaError("That polygon has no area. Draw at least three distinct corners.")
        return Area("polygon", geom)

    if kind == "point":
        lat = _num(area.get("lat"), "lat")
        lon = _num(area.get("lon"), "lon")
        r = _num(area.get("radius_km", 25), "radius_km")
        _check_lonlat(lon, lat)
        if not 0 < r <= 1000:
            raise AreaError("The radius must be between 0 and 1000 km.")
        return Area("point", circle_polygon(lat, lon, r), lat=lat, lon=lon, radius_km=r)

    raise AreaError("Area type must be 'bbox', 'polygon' or 'point'.")


def area_key(area):
    """A stable text key for an area dict (used to cache results per area)."""
    def rnd(x):
        if isinstance(x, float):
            return round(x, 6)
        if isinstance(x, list):
            return [rnd(v) for v in x]
        if isinstance(x, dict):
            return {k: rnd(v) for k, v in x.items()}
        return x
    return json.dumps(rnd(area), sort_keys=True)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (works on numpy arrays)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def circle_polygon(lat, lon, radius_km, n=72):
    """A circle of `radius_km` around a point, as a lon/lat polygon (for drawing + clipping)."""
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    d = radius_km / EARTH_RADIUS_KM
    p1, l1 = np.radians(lat), np.radians(lon)
    p2 = np.arcsin(np.sin(p1) * np.cos(d) + np.cos(p1) * np.sin(d) * np.cos(ang))
    l2 = l1 + np.arctan2(np.sin(ang) * np.sin(d) * np.cos(p1), np.cos(d) - np.sin(p1) * np.sin(p2))
    return shapely.Polygon(np.column_stack([np.degrees(l2), np.degrees(p2)]))


def area_km2(geom):
    """Area in km2 using the sinusoidal (equal-area) projection."""
    def sinusoidal(xy):
        lat = np.radians(xy[:, 1])
        return np.column_stack([EARTH_RADIUS_KM * np.radians(xy[:, 0]) * np.cos(lat),
                                EARTH_RADIUS_KM * lat])
    return float(shapely.transform(geom, sinusoidal).area)


def overlap_with_regions(area, region_bboxes):
    """{region: part of the area inside that region's box}, only regions that overlap."""
    out = {}
    for region, (w, s, e, n) in region_bboxes.items():
        part = area.geom.intersection(box(w, s, e, n))
        if not part.is_empty and part.area > 0:
            out[region] = part
    return out


def count_grid_cells(area, region, part, bbox):
    """How many 0.1 degree grid cells (by center) of `region` fall inside the area."""
    minx, miny, maxx, maxy = part.bounds
    lats = np.round(np.arange(math.floor(miny * 10), math.ceil(maxy * 10) + 1) / 10, 1)
    lons = np.round(np.arange(math.floor(minx * 10), math.ceil(maxx * 10) + 1) / 10, 1)
    w, s, e, n = bbox
    lats = lats[(lats >= s) & (lats <= n)]
    lons = lons[(lons >= w) & (lons <= e)]
    if len(lats) == 0 or len(lons) == 0:
        return 0
    lat_g, lon_g = np.meshgrid(lats, lons, indexing="ij")
    return int(area.contains(lat_g.ravel(), lon_g.ravel()).sum())


def select_cells(area, cells, regions):
    """Rows of `cells` (columns region, cell_id, lat, lon) whose CENTER is inside the area."""
    c = cells[cells["region"].isin(list(regions))]
    if c.empty:
        return c
    return c[area.contains(c["lat"].to_numpy(), c["lon"].to_numpy())]


# =============================================================================================
# 2. Daily series
# =============================================================================================

def build_daily_series(daily, value_col, start, end, missing_dates=(), nan_before=None):
    """Sparse per-day sums -> a full daily Series from start to end.

    daily:          DataFrame with a 'date' column and `value_col` (days with no rows = 0 fire)
    missing_dates:  days with no satellite data -> NaN (never 0)
    nan_before:     days before this date -> NaN (e.g. raw VIIRS before VIIRS existed)
    """
    idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    s = pd.Series(0.0, index=idx)
    if daily is not None and len(daily):
        d = pd.Series(daily[value_col].to_numpy(dtype=float),
                      index=pd.to_datetime(daily["date"]).dt.normalize())
        d = d.groupby(level=0).sum()
        d = d[(d.index >= idx[0]) & (d.index <= idx[-1])]
        s.loc[d.index] = d.to_numpy()
    if missing_dates:
        s[s.index.isin(pd.DatetimeIndex(pd.to_datetime(list(missing_dates))))] = np.nan
    if nan_before is not None:
        s[s.index < pd.Timestamp(nan_before)] = np.nan
    return s


def leap_doy(index):
    """Day of year 1..366 where Feb 29 is always day 60, so Mar 1 is always day 61."""
    index = pd.DatetimeIndex(index)
    shift = (~index.is_leap_year) & (index.month > 2)
    return index.day_of_year.to_numpy() + np.asarray(shift, dtype=int)


def doy_to_mmdd(doy):
    """Day 1..366 (leap numbering) -> 'MM-DD'."""
    return (date(2000, 1, 1) + timedelta(days=int(doy) - 1)).strftime("%m-%d")


def window_value(s, start, end):
    """Total over [start, end]. Missing days are filled with the window's own daily average;
    if more than 20% of the days are missing the total is NaN (unknown)."""
    w = s.loc[pd.Timestamp(start):pd.Timestamp(end)]
    n = len(w)
    if n == 0:
        return np.nan
    n_nan = int(w.isna().sum())
    if n_nan == 0:
        return float(w.sum())
    if n_nan / n > MAX_MISSING_SHARE:
        return np.nan
    return float(w.mean() * n)


# =============================================================================================
# 3. Climatology ("what is normal")
# =============================================================================================

def _nanstats(a, axis):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean = np.nanmean(a, axis=axis)
        median = np.nanmedian(a, axis=axis)
        n = np.sum(~np.isnan(a), axis=axis)
        std = np.where(n >= 2, np.nanstd(a, axis=axis, ddof=1) if a.size else np.nan, np.nan)
    return mean, median, std


def doy_climatology(s, baseline):
    """Normal activity for each day of the year (1..366), from the baseline years.

    For each day we pool that day +/- 15 days in every baseline year, then take the mean,
    median and standard deviation. Missing days are left out, not counted as zero.
    Returns a DataFrame indexed 1..366 with columns mean, median, std.
    """
    y0, y1 = baseline
    b = s[(s.index.year >= y0) & (s.index.year <= y1)]
    years = np.unique(b.index.year)
    mat = np.full((max(len(years), 1), 366), np.nan)
    if len(years):
        yi = np.searchsorted(years, b.index.year)
        mat[yi, leap_doy(b.index) - 1] = b.to_numpy()
    offsets = np.arange(-SMOOTH_DAYS, SMOOTH_DAYS + 1)
    idx = (np.arange(366)[:, None] + offsets[None, :]) % 366          # 366 x 31, wraps the year
    pooled = mat[:, idx].transpose(1, 0, 2).reshape(366, -1)           # 366 x (years * 31)
    mean, median, std = _nanstats(pooled, axis=1)
    return pd.DataFrame({"mean": mean, "median": median, "std": std}, index=np.arange(1, 367))


def monthly_table(s):
    """One row per calendar month: value (total, gap-filled if <=20% missing, else NaN),
    days in the series, missing days, and whether the month is complete in the series."""
    g = s.groupby(s.index.to_period("M"))
    n = g.size()
    n_nan = s.isna().groupby(s.index.to_period("M")).sum()
    mean = g.mean()
    value = np.where(n_nan / n > MAX_MISSING_SHARE, np.nan, mean * n)
    t = pd.DataFrame({"value": value, "n_days": n, "n_missing": n_nan}, index=n.index)
    t["year"] = t.index.year
    t["month"] = t.index.month
    t["full"] = t["n_days"] == t.index.days_in_month
    return t


def monthly_climatology(mt, baseline):
    """Normal total for each month of the year (1..12) across the baseline years:
    median, mean, std. Only complete, non-missing months count."""
    y0, y1 = baseline
    b = mt[(mt["year"] >= y0) & (mt["year"] <= y1) & mt["full"]]
    rows = []
    for m in range(1, 13):
        v = b.loc[b["month"] == m, "value"].to_numpy(dtype=float)
        mean, median, std = _nanstats(v, axis=0) if len(v) else (np.nan, np.nan, np.nan)
        rows.append({"month": m, "mean": float(mean), "median": float(median),
                     "std": float(std), "n_years": int(np.sum(~np.isnan(v)))})
    return pd.DataFrame(rows).set_index("month")


def anomaly(value, median, mean, std):
    """z-score and % of median for one value (None when they can't be computed)."""
    ok = value is not None and not _isnan(value)
    z = (value - mean) / std if ok and not _isnan(std) and std > 0 and not _isnan(mean) else None
    pct = value / median * 100 if ok and not _isnan(median) and median > 0 else None
    return z, pct


def _isnan(x):
    return x is None or (isinstance(x, (float, np.floating)) and math.isnan(x))


# =============================================================================================
# 4. Patterns and critical periods
# =============================================================================================

def fire_season(clim_mean, share=FIRE_SEASON_SHARE):
    """The shortest stretch of the year (it may wrap past New Year) that holds `share` of the
    typical yearly activity, plus the peak day. Uses the smoothed daily mean."""
    v = np.nan_to_num(np.asarray(clim_mean, dtype=float))
    total = v.sum()
    if total <= 0:
        return None
    n = len(v)
    csum = np.concatenate([[0.0], np.cumsum(np.concatenate([v, v]))])
    best_len, best_start, best_sum = n, 0, -1.0
    for i in range(n):
        j = int(np.searchsorted(csum, csum[i] + share * total - 1e-9, side="left"))
        held = csum[j] - csum[i]
        # shortest window wins; among equally short ones, the one holding the most activity
        if j - i < best_len or (j - i == best_len and held > best_sum):
            best_len, best_start, best_sum = j - i, i, held
    days = (best_start + np.arange(best_len)) % n
    peak = days[np.argmax(v[days])]
    return {"start": doy_to_mmdd(best_start + 1), "peak": doy_to_mmdd(peak + 1),
            "end": doy_to_mmdd(days[-1] + 1),
            "share_of_year": round(float(v[days].sum() / total), 2)}


def high_risk_months(mclim, share=HIGH_RISK_SHARE):
    """The top 20% of months by typical (median) activity, as month numbers in order."""
    k = math.ceil(12 * share)
    m = mclim[(mclim["median"].fillna(0) > 0) | (mclim["mean"].fillna(0) > 0)]
    if m.empty:
        return []
    top = m.sort_values(["median", "mean"], ascending=False).head(k)
    return sorted(int(i) for i in top.index)


def years_ranked(mt):
    """Yearly totals for every COMPLETE year (all 12 months present), busiest first."""
    full = mt[mt["full"]]
    rows = []
    for y, g in full.groupby("year"):
        if len(g) == 12 and not g["value"].isna().any():
            rows.append({"year": int(y), "total": float(g["value"].sum())})
    rows.sort(key=lambda r: -r["total"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def chance_unusual_month(mt, mclim, baseline):
    """For each month: % of baseline years in which it was well above normal (z > 1).
    A historical frequency, not a forecast."""
    y0, y1 = baseline
    b = mt[(mt["year"] >= y0) & (mt["year"] <= y1) & mt["full"]]
    out = []
    for m in range(1, 13):
        v = b.loc[b["month"] == m, "value"].dropna().to_numpy(dtype=float)
        mean, std = mclim.loc[m, "mean"], mclim.loc[m, "std"]
        if len(v) == 0 or _isnan(std):
            pct = None
        elif std == 0:
            pct = 0
        else:
            pct = int(round(100 * np.mean((v - mean) / std > UNUSUAL_Z)))
        out.append({"month": m, "pct_years_above_normal": pct})
    return out


# =============================================================================================
# 5. Comparisons with other years
# =============================================================================================

def _shift_year(d, year):
    try:
        return d.replace(year=year)
    except ValueError:            # Feb 29 in a non-leap year
        return d.replace(year=year, day=28)


def same_window_values(s, start, end, years):
    """{year: total over the same calendar window in that year}. Windows that don't fit
    fully inside the series are skipped."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    length = end - start
    out = {}
    for y in years:
        sy = _shift_year(start, int(y))
        ey = sy + length
        if sy < s.index[0] or ey > s.index[-1]:
            continue
        v = window_value(s, sy, ey)
        if not _isnan(v):
            out[int(y)] = v
    return out


def baseline_years(baseline):
    return range(baseline[0], baseline[1] + 1)


# =============================================================================================
# 6. Plain language (only computed numbers go in)
# =============================================================================================

def fmt_int(x):
    return f"{int(round(x)):,}"


def count_words(x, unit_word):
    """'1 hotspot', '2,140 hotspots' (unit words ending in 'hotspots' get singular at 1)."""
    if int(round(x)) == 1 and unit_word.endswith("hotspots"):
        unit_word = unit_word[:-1]
    return f"{fmt_int(x)} {unit_word}"


def fmt_date(d):
    d = pd.Timestamp(d)
    return f"{MON[d.month - 1]} {d.day}, {d.year}"


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def describe_range(start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31:
        return f"in {start.year}" if start.year == end.year else f"in {start.year}-{end.year}"
    if start.day == 1 and end == start + pd.offsets.MonthEnd(0):
        return f"in {MONTHS[start.month - 1]} {start.year}"
    return f"between {fmt_date(start)} and {fmt_date(end)}"


def describe_season(fs):
    """'Fire season here usually runs February to April, peaking in mid-March.'"""
    if not fs:
        return ""
    sm, em = int(fs["start"][:2]), int(fs["end"][:2])
    pm, pd_ = int(fs["peak"][:2]), int(fs["peak"][3:])
    part = "early" if pd_ <= 10 else ("mid" if pd_ <= 20 else "late")
    runs = (f"is concentrated in {MONTHS[sm - 1]}" if sm == em
            else f"usually runs {MONTHS[sm - 1]} to {MONTHS[em - 1]}")
    return f"Fire season here {runs}, peaking in {part}-{MONTHS[pm - 1]}."


def summary_sentence(total, median, pct, when, unit_word):
    if median is None or _isnan(median) or median <= 0:
        return (f"There are usually almost no {unit_word} here at this time of year; "
                f"this area had {count_words(total, unit_word)} {when}.")
    vs = f"({count_words(total, unit_word)} vs a typical {fmt_int(median)})"
    if pct >= 150:
        return f"This area had {pct / 100:.1f} times its normal fire activity {when} {vs}."
    if pct <= 67:
        return f"Fire activity here was below normal {when}: {round(pct)}% of the median {vs}."
    return f"Fire activity here was close to normal {when}: {round(pct)}% of the median {vs}."


# =============================================================================================
# 7. Response builders (exact shapes from docs/CONTRACTS.md section 4)
# =============================================================================================

def r1(x):
    return None if _isnan(x) else round(float(x), 1)


def r2(x):
    return None if _isnan(x) else round(float(x), 2)


def rint(x):
    return None if _isnan(x) else int(round(float(x)))


def calendar_cells(s, granularity, start, end, baseline, source_of, provisional_after):
    """Rows for /api/calendar and /api/export/series.csv."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    if granularity == "day":
        clim = doy_climatology(s, baseline)
        w = s.loc[start:end]
        stats = clim.loc[leap_doy(w.index)]
        for d, v, med, mean, std in zip(w.index, w.to_numpy(), stats["median"].to_numpy(),
                                        stats["mean"].to_numpy(), stats["std"].to_numpy()):
            z, pct = anomaly(v, med, mean, std)
            rows.append({"period": d.strftime("%Y-%m-%d"), "value": r1(v), "median": r1(med),
                         "mean": r1(mean), "std": r1(std), "z": r2(z),
                         "pct_of_median": rint(pct), "missing": bool(np.isnan(v)),
                         "provisional": bool(d.date() > provisional_after),
                         "source": source_of(d, d)})
        return rows

    mt = monthly_table(s)
    mclim = monthly_climatology(mt, baseline)
    last = mt.index[-1]
    sel = mt.loc[start.to_period("M"):end.to_period("M")]
    for p, row in sel.iterrows():
        if p == last and not row["full"]:
            # month still in progress: compare with the SAME days of that month in other years
            ms, me = p.start_time, s.index[-1]
            vals = list(same_window_values(s, ms, me, baseline_years(baseline)).values())
            med = float(np.median(vals)) if vals else np.nan
            mean = float(np.mean(vals)) if vals else np.nan
            std = float(np.std(vals, ddof=1)) if len(vals) >= 2 else np.nan
        else:
            med, mean, std = (mclim.loc[p.month, k] for k in ("median", "mean", "std"))
        v = row["value"]
        z, pct = anomaly(v, med, mean, std)
        rows.append({"period": str(p), "value": r1(v), "median": r1(med), "mean": r1(mean),
                     "std": r1(std), "z": r2(z), "pct_of_median": rint(pct),
                     "missing": bool(np.isnan(v)),
                     "provisional": bool(p.end_time.date() > provisional_after),
                     "source": source_of(p.start_time, p.end_time.normalize())})
    return rows


def patterns(s, baseline, provisional_after):
    """Body of /api/patterns."""
    mt = monthly_table(s)
    mclim = monthly_climatology(mt, baseline)
    clim = doy_climatology(s, baseline)
    grid = [{"year": int(r.year), "month": int(r.month), "value": r1(r.value),
             "missing": bool(np.isnan(r.value)),
             "provisional": bool(p.end_time.date() > provisional_after)}
            for p, r in mt.iterrows()]
    return {
        "grid": grid,
        "monthly_median": [{"month": int(m), "median": r1(r["median"]), "mean": r1(r["mean"])}
                           for m, r in mclim.iterrows()],
        "years_ranked": [{**y, "total": r1(y["total"])} for y in years_ranked(mt)],
        "fire_season": fire_season(clim["mean"].to_numpy()),
        "high_risk_months": high_risk_months(mclim),
        "chance_unusual_month": chance_unusual_month(mt, mclim, baseline),
    }


def summary(s, start, end, baseline, provisional_after, unit_word, area_info):
    """Body of /api/summary. area_info: area_km2, cells, region, outside_note."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    w = s.loc[start:end]
    total = float(np.nansum(w.to_numpy()))
    value = window_value(s, start, end)
    typical = list(same_window_values(s, start, end, baseline_years(baseline)).values())
    median = float(np.median(typical)) if typical else np.nan
    _, pct = anomaly(value, median, np.nan, np.nan)

    mt = monthly_table(s)
    in_range = mt.loc[start.to_period("M"):end.to_period("M")]
    busiest_month = (str(in_range["value"].idxmax())
                     if in_range["value"].notna().any() and in_range["value"].max() > 0 else None)
    if end.year > start.year:
        yearly = w.groupby(w.index.year).sum(min_count=1)
        busiest_year = int(yearly.idxmax()) if yearly.notna().any() and yearly.max() > 0 else None
    else:
        ranked = years_ranked(mt)        # range inside one year: busiest year on record
        busiest_year = ranked[0]["year"] if ranked and ranked[0]["total"] > 0 else None
    fs = fire_season(doy_climatology(s, baseline)["mean"].to_numpy())

    missing_days = int(w.isna().sum())
    provisional_days = int((w.index.date > provisional_after).sum())
    parts = [summary_sentence(total, median, pct, describe_range(start, end), unit_word)]
    if fs:
        parts.append(describe_season(fs))
    if busiest_year and end.year == start.year:
        parts.append(f"The busiest year on record here was {busiest_year}.")
    if missing_days:
        parts.append(f"{missing_days} day{'s' if missing_days != 1 else ''} had no satellite "
                     f"data and {'are' if missing_days != 1 else 'is'} left out, "
                     "not counted as zero.")
    if provisional_days:
        parts.append(f"Data after {fmt_date(provisional_after)} is provisional "
                     "(near-real-time).")
    if area_info.get("outside_note"):
        parts.append(area_info["outside_note"])

    return {
        "area_km2": rint(area_info["area_km2"]), "cells": area_info["cells"],
        "region": area_info["region"],
        "range": {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")},
        "key_figures": {
            "total_hotspots": rint(total), "pct_of_median": rint(pct),
            "busiest_month": busiest_month, "busiest_year": busiest_year,
            "fire_season": ({k: fs[k] for k in ("start", "peak", "end")} if fs else None),
        },
        "summary_text": " ".join(parts),
        "provisional_days": provisional_days, "missing_days": missing_days,
    }


def current(s, as_of, baseline, provisional_after, unit_word):
    """Body of /api/current: this month so far vs the same days in other years."""
    as_of = pd.Timestamp(as_of)
    ms = as_of.replace(day=1)
    w = s.loc[ms:as_of]
    value_so_far = float(np.nansum(w.to_numpy()))
    this = window_value(s, ms, as_of)
    first_year = s.index[0].year
    others = same_window_values(s, ms, as_of, range(first_year, as_of.year))
    in_base = [v for y, v in others.items() if baseline[0] <= y <= baseline[1]]
    median = float(np.median(in_base)) if in_base else np.nan
    _, pct = anomaly(this, median, np.nan, np.nan)
    rank = None
    of_years = len(others) + (0 if _isnan(this) else 1)
    if not _isnan(this):
        rank = 1 + sum(v > this for v in others.values())
    since = min(others) if others else as_of.year

    month_name = MONTHS[as_of.month - 1]
    days = f"{MON[as_of.month - 1]} 1-{as_of.day}"
    if _isnan(median) or median <= 0:
        text = (f"{count_words(value_so_far, unit_word)} so far in {month_name} ({days}); "
                "there are usually almost none on these days.")
    else:
        text = (f"{count_words(value_so_far, unit_word)} so far this month ({days}) vs a typical "
                f"{fmt_int(median)} ({round(pct)}% of median)")
        if rank:
            text += (", the highest" if rank == 1 else f", the {ordinal(rank)} highest") + \
                    f" since {since}."
        else:
            text += "."
    n_missing = int(w.isna().sum())
    if n_missing:
        text += f" {n_missing} day{'s' if n_missing != 1 else ''} had no satellite data."
    return {
        "month": ms.strftime("%Y-%m"), "days_so_far": int(as_of.day),
        "value_so_far": r1(value_so_far), "median_same_days": r1(median),
        "pct_of_median": rint(pct), "rank_among_years": rank, "of_years": of_years,
        "provisional": bool(as_of.date() > provisional_after), "summary_text": text,
    }


def monthly_values(s):
    """{'YYYY-MM': monthly total or None} for the long-term chart."""
    mt = monthly_table(s)
    return {str(p): r1(v) for p, v in mt["value"].items()}
