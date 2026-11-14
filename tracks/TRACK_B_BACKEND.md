# Track B: Backend

**You own:** the analytics math, the server (API) the website talks to, and the live FIRMS feed.
**Your laptop needs:** a FIRMS MAP_KEY (get your own free one at
firms.modaps.eosdis.nasa.gov/api/map_key so you don't share Track A's rate limit).
No NASA data needed at first: you build on fake data in the exact same format until Track A
delivers.
**You hand off to:** Track C (a working API).

## How to use this file
1. `git clone https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS` then `cd NASA-SPACEAPPS-VIIRS`
2. Run `claude`, press **Shift+Tab** for plan mode.
3. Paste **B1**. Approve the plan. When it's done and the **check** passes, type `/clear` and
   paste the next prompt. Each prompt says **when** to run it.
4. Post in the team chat at every 📣 handoff.

---

## B1: Fake data + analytics · start now · target 4:30 pm
Fill in the blank, then paste:
```
I'm Track B (Backend) of a 3-person team. Read CLAUDE.md, docs/challenge.md, docs/CONTRACTS.md
and tracks/TRACK_B_BACKEND.md first. I only edit the files Track B owns (docs/CONTRACTS.md §1).

FIRMS MAP_KEY: <KEY>  (write it to .env; confirm .env is gitignored)

Track A is still building the real data, so:
1. Write requirements.txt for the whole project (pandas, pyarrow, duckdb, numpy, scipy,
   statsmodels, shapely, rasterio, matplotlib, fastapi, uvicorn, httpx, python-dotenv, pytest,
   playwright) and create .venv.
2. Write scripts/make_synthetic_app_data.py: realistic fake data in EXACTLY the
   docs/CONTRACTS.md §2 schemas for all three regions (a seasonal fire cycle per region, a few
   extreme years like Texas 2011, viirs_n 3x higher than modis_n after 2012-01-20, some missing
   days, provisional rows for the last 2 months, matching hotspot points). A few MB total.
3. Implement app/analytics.py: everything in CLAUDE.md §5 (polygon / bbox / point+radius → cells;
   daily series with 0 where there are no rows and NaN on missing days; median, mean, std
   climatology with ±15-day smoothing; anomalies; month×year grid; years ranked; fire season;
   high-risk months; chance of an unusual month; current month vs median; plain-language
   summary built only from computed numbers).
4. pytest on small hand-made series: z-score, % of median, NaN propagation, fire season on a
   synthetic seasonal curve, point+radius selection.
Show the plan and wait for my OK. Then build, test, commit, `git pull --rebase origin main`,
push. Finish by telling me the next prompt from my track file.
```
**Check:** tests pass; the fake data looks like a real fire record (seasons, a jump in 2012).
📣 **Handoff:** post "requirements.txt is in" so A and C can `pip install -r requirements.txt`.

---

## B2: The API · after B1 · target 6:00 pm
```
Implement app/main.py: FastAPI + DuckDB over data/app/*.parquet (folder from env var
APP_DATA_DIR, default data/app), with every endpoint in docs/CONTRACTS.md §4 returning EXACTLY
those JSON shapes. Serve app/static/ at / and methods.html at /methods. Errors are HTTP 400
{"error": "..."}. Stream the hotspots CSV with the 200,000-row cap.
pytest every endpoint on the synthetic data, including response time under 2 s for a
Texas-size bbox. Save one response per endpoint (Texas 2011 bbox) to /tmp/api_examples/ and
compare each to the examples in docs/CONTRACTS.md; if a field differs, fix the API, not the
contract. Tell me the command to run the server. Commit, pull --rebase, push. Tell me the next
prompt.
```
**Check:** `uvicorn app.main:app --reload` runs, and every endpoint answers fast.
📣 **Handoff:** post "API runs on fake data: `uvicorn app.main:app`" for Track C.

---

## B3: Live FIRMS feed · after B2 · target 8:00 pm
```
Implement pipeline/live.py per CLAUDE.md §3.1: fetch VIIRS_NOAA20_NRT, VIIRS_NOAA21_NRT and
MODIS_NRT for each region from the end of the zips' NRT data to today, in ≤10-day chunks;
cache raw CSVs in data/cache/live/ (gitignored); respect the rate limit and retry politely.
Write data/app/live_cells_daily.parquet and data/app/live_hotspots.parquet in the same schemas
(provisional=true; use the harmonization coefficients from data/processed/ if present, else
one global ratio). Make the API union the live files in automatically and keep working when
they're missing or the FIRMS API is down. Test with my key. Commit, pull --rebase, push. Tell
me the next prompt.
```
**Check:** `/api/current` shows this month's numbers with `provisional: true`.

---

## B4: Switch to the Texas sample · when Track A posts "Texas sample ready" (~4:30 pm)
You can run this between B1–B3 whenever the sample arrives.
```
Track A's Texas sample of the real data is at <PATH>. Run the API and the full test suite with
APP_DATA_DIR pointing there. Fix anything that breaks because real data differs from the fake
data (types, nulls, sizes, edge cases). If real data shows a contract problem, tell me exactly
what so I can agree it with Track A. Then switch back to synthetic data for the other regions.
Commit, pull --rebase, push.
```

## B5: Switch to the full real data · when Track A posts "Real data ready" (~9:00 pm)
```
Track A's full real data/app/ is at <PATH>. Point APP_DATA_DIR at it, run all tests and the
timing test, and fix anything that breaks. If any endpoint takes over 2 s, speed it up (sort the
parquet, pre-aggregate monthly tables, cache climatology per area). Check 3 numbers in
/api/summary against hand-written DuckDB queries. Commit, pull --rebase, push.
```
📣 **Handoff:** post "API on real data" for Track C.

---

## B6: Help deploy · Sunday morning, with Track C
```
Help Track C deploy to Hugging Face Spaces (Docker). Make sure the app reads APP_DATA_DIR and
FIRMS_MAP_KEY from environment variables, loads the data files from APP_DATA_URL at startup if
they're not present, refreshes the live feed in the background at most once an hour, and
answers /api/regions as a health check. Check the memory use with the real data stays well under
the Space's limit. Test the container locally with `docker build` and `docker run`. Commit,
pull --rebase, push.
```

## B7: Fix bugs from reviews · Sunday afternoon and evening
```
Here are the problems Track A / the judge review found in the API: <PASTE LIST>. Fix them in
order of importance, re-run all tests and the timing test, and tell me which you fixed and how.
Commit, pull --rebase, push.
```
