# Contracts between the three tracks

All three tracks build against these shapes. **Don't change a contract without telling the other
two tracks** (and updating this file in the same commit). Everything else is yours to decide.

## 1. File ownership (prevents merge conflicts)

| Track | Owns (only this track edits these) |
|---|---|
| **A, Data + Science** | `pipeline/` (except `pipeline/live.py`), `tests/test_pipeline_*.py`, `results/`, `data/app/` (built files), `CLAUDE.md`, `Makefile` |
| **B, Backend** | `app/main.py`, `app/analytics.py`, `app/__init__.py`, `pipeline/live.py`, `scripts/make_synthetic_app_data.py`, `tests/test_api_*.py`, `tests/test_analytics_*.py`, `requirements.txt` |
| **C, Frontend + Ship** | `app/static/**` (incl. `app/static/mock/`), `Dockerfile`, `docs/` (except this file and `challenge.md`), `README.md`, `scripts/record_demo.py`, `.dockerignore` |

Shared, edit with care and tell the others: `docs/CONTRACTS.md`, `docs/challenge.md`, `.gitignore`.

Git: everyone works on `main`, commits small and often, and runs `git pull --rebase origin main`
before every `git push`. Because ownership doesn't overlap, conflicts should be rare.

## 2. App data files (built by A, read by B)

Raw data never goes in git. Built app data over 50 MB doesn't either: A uploads `data/app/` to the
team's shared Drive folder (and later the deploy host). B uses synthetic data with the **exact same
schema** until then.

### `data/app/cells_daily.parquet`
One row per **region × 0.1° cell × day that has at least one detection** (sparse; no zero rows).

| column | type | meaning |
|---|---|---|
| region | string | `texas` / `amazon` / `australia` |
| cell_id | int32 | unique per region: `round((lat+90)*10)*3600 + round((lon+180)*10)` |
| lat, lon | float32 | cell center |
| date | date | UTC date |
| mec | float32 | harmonized hotspot count (MODIS-equivalent) |
| mefrp | float32 | harmonized FRP sum, MW |
| modis_n | float32 | raw MODIS (Terra+Aqua) count, NaN-free (0 if none) |
| viirs_n | float32 | raw VIIRS count (de-duplicated across satellites) |
| source | string | `MODIS` (before VIIRS era) or `VIIRS` |
| provisional | bool | from NRT or live, not science-quality archive |

### `data/app/missing_days.parquet`
Days a sensor had no data for a whole region. **These days are NaN in every series, never 0.**

| column | type | meaning |
|---|---|---|
| region | string | |
| date | date | |
| scope | string | `harmonized`, `modis_only` or `viirs_raw`: which mode is missing that day |

### `data/app/hotspots.parquet` (for the hotspots CSV export)
| column | type |
|---|---|
| region | string |
| lat, lon | float64 |
| datetime_utc | timestamp |
| date | date |
| satellite | string (`Terra`, `Aqua`, `S-NPP`, `NOAA-20`, `NOAA-21`) |
| sensor | string (`MODIS` / `VIIRS`) |
| frp | float32 |
| confidence_class | string (`low` / `nominal` / `high`) |
| daynight | string (`D` / `N`) |
| provisional | bool |
| weight | float32: how much this point adds to `mec` (1.0 for MODIS era) |

### `data/app/coverage.json`
```json
{"texas": {"start": "2001-01-01", "archive_end": "2026-08-31", "nrt_end": "2026-10-31",
           "live_end": "2026-11-13", "bbox": [-107, 25, -93, 37]},
 "amazon": {...}, "australia": {...}}
```

## 3. Results (built by A, read by C for the Methods page)
- `results/metrics.json` (committed). Shape:
```json
{"winner": "B_ols", "baseline_years": [2012, 2018], "test_years": [2019, 2026],
 "overall": {"holdout": {"raw_viirs": {"r2": 0, "bias_pct": 0, "rmse": 0, "r": 0},
                         "global_ratio": {...}, "harmonized": {...}},
             "transfer_noaa20": {"raw_viirs": {...}, "global_ratio": {...}, "harmonized": {...}}},
 "regions": {"texas": {"holdout": {...}, "transfer_noaa20": {...}}, "amazon": {...}, "australia": {...}},
 "notes": ["plain-English caveats"]}
```
- `results/figures/*.png` (committed): at least `continuity_<region>.png`, `scatter_before_after.png`,
  `bias_before_after.png`, `overpass_times.png`.

## 4. API (built by B, used by C)

All POST bodies share this shape. Dates are `YYYY-MM-DD`.
```json
{"area": {"type": "bbox", "bbox": [-100, 30, -96, 33]},
 "start": "2011-01-01", "end": "2011-12-31",
 "baseline": [2003, 2022], "mode": "harmonized", "metric": "count"}
```
`area` can be `{"type":"polygon","coordinates":[[[lon,lat],...]]}` (GeoJSON order),
`{"type":"bbox","bbox":[W,S,E,N]}` or `{"type":"point","lat":31,"lon":-98,"radius_km":50}`.
`mode`: `harmonized` | `modis_only` | `viirs_raw`. `metric`: `count` | `frp`.
Errors: HTTP 400 with `{"error": "plain-English message"}` (e.g. area outside our regions).

Example responses (C builds the UI from these; B must match them). Copies live in
`app/static/mock/*.json` so the frontend runs with `?mock=1` before the backend is ready.

`GET /api/regions`
```json
{"regions": [{"id": "texas", "name": "Texas & southern Plains", "bbox": [-107, 25, -93, 37],
              "start": "2001-01-01", "archive_end": "2026-08-31", "live_end": "2026-11-13"}]}
```

`POST /api/summary`
```json
{"area_km2": 112000, "cells": 1120, "region": "texas",
 "range": {"start": "2011-01-01", "end": "2011-12-31"},
 "key_figures": {"total_hotspots": 18432, "pct_of_median": 312, "busiest_month": "2011-04",
                 "busiest_year": 2011, "fire_season": {"start": "02-01", "peak": "03-15", "end": "04-30"}},
 "summary_text": "This area had 3.1 times its normal fire activity in 2011. Fire season here usually runs February to April, peaking in mid-March.",
 "provisional_days": 0, "missing_days": 2}
```

`POST /api/calendar` (granularity `month` or `day`)
```json
{"granularity": "month", "mode": "harmonized", "metric": "count", "units": "hotspots (MODIS scale)",
 "cells": [{"period": "2011-04", "value": 6120.5, "median": 1400, "mean": 1650, "std": 900,
            "z": 4.97, "pct_of_median": 437, "missing": false, "provisional": false, "source": "MODIS"}]}
```

`POST /api/patterns`
```json
{"grid": [{"year": 2011, "month": 4, "value": 6120.5, "missing": false, "provisional": false}],
 "monthly_median": [{"month": 1, "median": 300, "mean": 340}],
 "years_ranked": [{"year": 2011, "total": 18432, "rank": 1}],
 "fire_season": {"start": "02-01", "peak": "03-15", "end": "04-30", "share_of_year": 0.8},
 "high_risk_months": [2, 3, 4],
 "chance_unusual_month": [{"month": 1, "pct_years_above_normal": 15}]}
```

`POST /api/current`
```json
{"month": "2026-11", "days_so_far": 13, "value_so_far": 210, "median_same_days": 95,
 "pct_of_median": 221, "rank_among_years": 2, "of_years": 26, "provisional": true,
 "summary_text": "210 hotspots so far this month vs a typical 95 (221% of median), the 2nd highest since 2001."}
```

`POST /api/timeseries`
```json
{"series": [{"month": "2012-01", "harmonized": 410.2, "modis_only": 395, "viirs_raw": 1630}],
 "sensor_switches": [{"date": "2012-01-20", "label": "VIIRS S-NPP starts"},
                     {"date": "2018-04-01", "label": "NOAA-20 starts"}]}
```

`POST /api/export/series.csv`: columns `date,value,median,mean,std,z,pct_of_median,source_sensor,provisional_flag,missing_flag`

`POST /api/export/hotspots.csv`: columns `lat,lon,datetime_utc,satellite,sensor,frp,confidence,daynight,provisional,weight`.
Streamed. If over 200,000 rows, returns the first 200,000 plus a final comment line saying so.

## 5. Integration checkpoints (Central time)

| When | What | Who |
|---|---|---|
| Sat 14:15 | Everyone has cloned, read CLAUDE.md + this file, started their track | all |
| Sat 16:30 | A pushes a **Texas-only** `data/app/` sample to Drive (real schema) | A → B |
| Sat 18:00 | B's API runs on synthetic data; C's UI runs on mock JSON; C has a "hello" deploy live | B, C |
| Sat 21:00 | A delivers full `data/app/` + `results/metrics.json` | A → B, C |
| Sat 22:30 | B's API on real data; C points UI at real API (`?mock=0`) | B, C |
| Sun 11:00 | Full app works end to end locally | all |
| Sun 14:00 | Full deploy live | C (+B) |
| Sun 18:00 | Video + README + submission text | C (+A for numbers) |
| Sun 20:00 | Fresh-eyes judge review + fixes | all |
| **Sun 22:00** | **Submit** (deadline 23:59) | C |
