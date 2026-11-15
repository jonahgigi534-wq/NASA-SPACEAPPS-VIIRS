"""Unit tests for app/analytics.py on small hand-made series (no data files needed).

Run:  pytest tests/test_analytics_math.py -q
"""

import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import analytics as an  # noqa: E402


def daily(start, end, value=0.0):
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(float(value), index=idx)


# ---- z-score and % of median ------------------------------------------------------------------

def test_z_score_and_pct_of_median():
    z, pct = an.anomaly(150.0, median=100.0, mean=120.0, std=15.0)
    assert z == pytest.approx(2.0)
    assert pct == pytest.approx(150.0)


def test_anomaly_undefined_cases_are_none():
    assert an.anomaly(5.0, median=0.0, mean=1.0, std=0.0) == (None, None)
    assert an.anomaly(np.nan, median=10.0, mean=10.0, std=2.0) == (None, None)


# ---- missing data stays missing (NaN), never zero ----------------------------------------------

def test_missing_days_become_nan_not_zero():
    rows = pd.DataFrame({"date": pd.to_datetime(["2020-01-02", "2020-01-04"]),
                         "mec": [3.0, 5.0]})
    s = an.build_daily_series(rows, "mec", date(2020, 1, 1), date(2020, 1, 5),
                              missing_dates={pd.Timestamp("2020-01-03")})
    assert s.loc["2020-01-01"] == 0          # no rows = no fire seen
    assert s.loc["2020-01-02"] == 3
    assert math.isnan(s.loc["2020-01-03"])   # missing = unknown
    assert s.loc["2020-01-04"] == 5


def test_nan_before_sensor_start():
    s = an.build_daily_series(None, "viirs_n", date(2012, 1, 1), date(2012, 1, 31),
                              nan_before=date(2012, 1, 20))
    assert s.loc[:"2012-01-19"].isna().all()
    assert (s.loc["2012-01-20":] == 0).all()


def test_window_value_fills_a_few_missing_days_but_not_many():
    s = daily("2020-01-01", "2020-01-10", 2.0)
    s.iloc[0] = np.nan                                   # 10% missing -> filled with the average
    assert an.window_value(s, "2020-01-01", "2020-01-10") == pytest.approx(20.0)
    s.iloc[1:3] = np.nan                                 # 30% missing -> unknown
    assert math.isnan(an.window_value(s, "2020-01-01", "2020-01-10"))


def test_monthly_table_marks_mostly_missing_month_as_nan():
    s = daily("2020-01-01", "2020-02-29", 1.0)
    s.loc["2020-02-01":"2020-02-15"] = np.nan
    mt = an.monthly_table(s)
    assert mt.loc[pd.Period("2020-01"), "value"] == pytest.approx(31.0)
    assert math.isnan(mt.loc[pd.Period("2020-02"), "value"])


def test_climatology_ignores_missing_days_instead_of_counting_zero():
    s = daily("2001-01-01", "2010-12-31", 4.0)
    s[s.index.year == 2005] = np.nan
    clim = an.doy_climatology(s, (2001, 2010))
    assert clim["mean"].dropna().eq(4.0).all()
    assert clim["median"].dropna().eq(4.0).all()


def test_leap_day_numbering():
    idx = pd.to_datetime(["2001-03-01", "2004-02-29", "2004-03-01", "2001-12-31"])
    assert list(an.leap_doy(idx)) == [61, 60, 61, 366]


# ---- fire season on a synthetic seasonal curve -------------------------------------------------

def gaussian_year(peak_doy, width, n=366):
    d = np.arange(1, n + 1)
    dist = np.minimum(np.abs(d - peak_doy), n - np.abs(d - peak_doy))
    return np.exp(-0.5 * (dist / width) ** 2)


def test_fire_season_window_on_seasonal_curve():
    fs = an.fire_season(gaussian_year(75, 20))
    # 80% of a normal curve lies within +/- 1.28 standard deviations of the peak
    assert fs["peak"] in ("03-15", "03-16")                  # leap day 75 = Mar 15
    start = an.leap_doy(pd.to_datetime(["2000-" + fs["start"]]))[0]
    end = an.leap_doy(pd.to_datetime(["2000-" + fs["end"]]))[0]
    assert abs(start - (75 - 25.6)) <= 2
    assert abs(end - (75 + 25.6)) <= 2
    assert fs["share_of_year"] >= 0.8


def test_fire_season_wraps_past_new_year():
    fs = an.fire_season(gaussian_year(5, 15))
    assert fs["start"].startswith("12")
    assert fs["end"].startswith("01")


def test_fire_season_none_when_no_fire():
    assert an.fire_season(np.zeros(366)) is None


# ---- patterns ----------------------------------------------------------------------------------

def seasonal_series(years=(2001, 2010), peak_month=3, extreme=None):
    idx = pd.date_range(f"{years[0]}-01-01", f"{years[1]}-12-31", freq="D")
    v = np.where(idx.month == peak_month, 10.0, 1.0)
    v = np.where(idx.month == peak_month + 1, 6.0, v)
    v = np.where(idx.month == peak_month - 1, 5.0, v)
    s = pd.Series(v, index=idx)
    if extreme:
        s[s.index.year == extreme] *= 3
    return s


def test_high_risk_months_are_top_three():
    s = seasonal_series()
    mclim = an.monthly_climatology(an.monthly_table(s), (2001, 2010))
    assert an.high_risk_months(mclim) == [2, 3, 4]


def test_years_ranked_puts_extreme_year_first():
    s = seasonal_series(extreme=2006)
    ranked = an.years_ranked(an.monthly_table(s))
    assert ranked[0]["year"] == 2006 and ranked[0]["rank"] == 1
    assert len(ranked) == 10


def test_chance_unusual_month():
    s = seasonal_series(extreme=2006)
    mt = an.monthly_table(s)
    mclim = an.monthly_climatology(mt, (2001, 2010))
    chance = {c["month"]: c["pct_years_above_normal"] for c in
              an.chance_unusual_month(mt, mclim, (2001, 2010))}
    assert chance[3] == 10     # only 2006, 1 of 10 years


def test_current_month_vs_same_days():
    s = daily("2001-01-01", "2026-11-13", 1.0)
    s.loc["2026-11-01":"2026-11-13"] = 3.0
    out = an.current(s, date(2026, 11, 13), (2003, 2022), date(2026, 8, 31), "hotspots")
    assert out["value_so_far"] == 39
    assert out["median_same_days"] == 13
    assert out["pct_of_median"] == 300
    assert out["rank_among_years"] == 1
    assert out["of_years"] == 26
    assert out["provisional"] is True
    assert "39 hotspots so far this month" in out["summary_text"]


def test_summary_pct_of_median_for_a_range():
    s = seasonal_series((2001, 2012), extreme=2011)
    info = {"area_km2": 100.0, "cells": 1, "region": "texas"}
    out = an.summary(s, date(2011, 1, 1), date(2011, 12, 31), (2001, 2010), date(2030, 1, 1),
                     "hotspots", info)
    assert out["key_figures"]["pct_of_median"] == 300
    assert out["key_figures"]["busiest_month"] == "2011-03"
    assert "3.0 times its normal" in out["summary_text"]


def test_summary_when_whole_range_is_missing_but_median_exists():
    """Regression (Track A science check): MODIS had no data 2020-08-19..25 in N. Australia.
    The median exists, the value doesn't -> pct must be null, not a crash (was HTTP 500)."""
    s = daily("2003-01-01", "2022-12-31", 10.0)
    s.loc["2020-08-19":"2020-08-25"] = np.nan
    info = {"area_km2": 100.0, "cells": 1, "region": "australia"}
    out = an.summary(s, date(2020, 8, 19), date(2020, 8, 25), (2003, 2022), date(2030, 1, 1),
                     "MODIS hotspots", info)
    assert out["key_figures"]["pct_of_median"] is None
    assert out["key_figures"]["total_hotspots"] == 0
    assert out["missing_days"] == 7
    assert out["summary_text"].startswith(an.NO_DATA_SENTENCE)


def test_current_when_month_so_far_is_missing_but_median_exists():
    s = daily("2003-01-01", "2020-08-25", 10.0)
    s.loc["2020-08-01":"2020-08-25"] = np.nan
    out = an.current(s, date(2020, 8, 25), (2003, 2019), date(2030, 1, 1), "MODIS hotspots")
    assert out["pct_of_median"] is None and out["rank_among_years"] is None
    assert out["median_same_days"] == 250
    assert "no satellite data for most of August" in out["summary_text"]


def test_summary_sentence_never_compares_none():
    assert an.summary_sentence(0, 2534.0, None, "in 2020", "hotspots") == an.NO_DATA_SENTENCE


# ---- area selection ----------------------------------------------------------------------------

def test_point_radius_selects_cells_by_distance():
    a = an.parse_area({"type": "point", "lat": 31.0, "lon": -98.0, "radius_km": 50})
    lats = np.array([31.0, 31.4, 31.5, 31.0])
    lons = np.array([-98.0, -98.0, -98.0, -98.6])   # 0, ~44 km, ~56 km, ~57 km away
    assert list(a.contains(lats, lons)) == [True, True, False, False]


def test_bbox_edges_count_as_inside_and_polygon_selection():
    cells = pd.DataFrame({"region": "texas", "cell_id": [1, 2, 3, 4],
                          "lat": [30.0, 30.5, 31.5, 33.1], "lon": [-100.0, -99.0, -97.0, -98.0]})
    a = an.parse_area({"type": "bbox", "bbox": [-100, 30, -96, 33]})
    assert list(an.select_cells(a, cells, ["texas"])["cell_id"]) == [1, 2, 3]
    tri = an.parse_area({"type": "polygon",
                         "coordinates": [[[-100, 30], [-96, 30], [-100, 33], [-100, 30]]]})
    assert list(an.select_cells(tri, cells, ["texas"])["cell_id"]) == [1, 2]


def test_geojson_feature_from_leaflet_is_accepted():
    f = {"type": "Feature", "properties": {},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[-100, 30], [-96, 30], [-96, 33], [-100, 33], [-100, 30]]]}}
    assert an.parse_area(f).kind == "polygon"


@pytest.mark.parametrize("bad", [
    None, {"type": "circle"}, {"type": "bbox", "bbox": [1, 2, 3]},
    {"type": "bbox", "bbox": [-96, 30, -100, 33]}, {"type": "point", "lat": 31, "lon": -98,
                                                    "radius_km": 0},
    {"type": "polygon", "coordinates": "nope"},
])
def test_bad_areas_give_plain_errors(bad):
    with pytest.raises(an.AreaError):
        an.parse_area(bad)


def test_area_km2_of_one_degree_square_at_equator():
    a = an.parse_area({"type": "bbox", "bbox": [0, 0, 1, 1]})
    assert an.area_km2(a.geom) == pytest.approx(12364, rel=0.01)


def test_polygon_with_too_many_corners_is_refused():
    import numpy as np
    ang = np.linspace(0, 2 * np.pi, an.MAX_POLYGON_POINTS + 50)
    ring = [[float(-98 + np.cos(a)), float(31 + np.sin(a))] for a in ang]
    ring.append(ring[0])
    with pytest.raises(an.AreaError, match="too many corners"):
        an.parse_area({"type": "polygon", "coordinates": [ring]})


# ---- weeks and trend ---------------------------------------------------------------------------

def test_weekly_totals_and_high_risk_weeks():
    s = daily("2003-01-06", "2012-12-30", 1.0)          # starts on a Monday
    iso = s.index.isocalendar()
    s[(iso["week"] >= 10) & (iso["week"] <= 20)] = 9.0   # a spring fire season, weeks 10-20
    wt = an.weekly_table(s)
    assert wt.loc[200310, "value"] == pytest.approx(63.0) and wt.loc[200310, "full"]
    hr = an.high_risk_weeks(an.weekly_climatology(wt, (2003, 2012)))
    assert hr == list(range(10, 21))


def test_week_calendar_cells():
    s = daily("2003-01-06", "2012-12-30", 2.0)
    rows = an.calendar_cells(s, "week", date(2011, 4, 4), date(2011, 4, 17), (2003, 2012),
                             lambda a, b: "MODIS", date(2030, 1, 1))
    assert [r["period"] for r in rows] == ["2011-W14", "2011-W15"]
    assert rows[0]["value"] == 14.0 and rows[0]["pct_of_median"] == 100


def test_trend_rising_and_flat():
    idx = pd.date_range("2001-01-01", "2020-12-31", freq="D")
    rising = pd.Series((idx.year - 2000).astype(float), index=idx)   # grows every year
    t = an.trend(an.monthly_table(rising))
    assert t["direction"] == "rising" and t["pct_per_decade"] > 0 and t["p_value"] < 0.05
    rng = np.random.default_rng(1)
    flat = pd.Series(rng.normal(5, 0.5, len(idx)).clip(0), index=idx)
    t2 = an.trend(an.monthly_table(flat))
    assert t2["direction"] == "none" and "No clear trend" in t2["text"]
    short = an.monthly_table(rising.loc["2015":"2020"])
    assert an.trend(short) is None
