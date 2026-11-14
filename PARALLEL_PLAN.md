# Running FireBridge on 3 Claude accounts in parallel

Three people, three laptops, three Claude Code sessions, one repo. Each person owns one
**track** and only edits their own files (see `docs/CONTRACTS.md` §1), so you can all push to
`main` without conflicts. The tracks talk to each other only through the file schemas and API
shapes in `docs/CONTRACTS.md`.

| Track | Who | Builds | Needs on their laptop |
|---|---|---|---|
| **A, Data + Science** | strongest laptop (16 GB RAM, ~10 GB free disk) | ingest, grid, harmonize, validate, app data | all 9 FIRMS zips, AppEEARS files, MAP_KEY |
| **B, Backend** | anyone | analytics math, API, live FIRMS feed | MAP_KEY (data comes from A later) |
| **C, Frontend + Ship** | person who'll present | web UI, Methods page, deploy, video, README | nothing at first |

**Everyone, first 10 minutes:**
1. `git clone https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS` then `cd NASA-SPACEAPPS-VIIRS`
2. `claude` and press Shift+Tab for plan mode.
3. Paste **your track's Prompt 1** below. After each prompt passes its check: `/clear`, next prompt.
4. Before every push: `git pull --rebase origin main`.
5. Use the team chat for the checkpoints in `docs/CONTRACTS.md` §5.

Revised schedule (we're starting at ~2 pm Saturday): A finishes the science by ~9 pm Saturday,
B and C build against fake data until then, everything joins up Saturday night, Sunday is polish,
deploy, video and **submit by 10 pm Sunday**.

---

## Track A: Data + Science

### A1: data, setup, ingest (target 15:15)
```
I'm Track A (Data + Science) of a 3-person team. Read CLAUDE.md, docs/challenge.md,
docs/CONTRACTS.md and PARALLEL_PLAN.md first. I only edit the files Track A owns.

Data folder: <PATH>
FIRMS MAP_KEY: <KEY>

1. Copy the FIRMS zips into data/raw/<region>/ by ID (CLAUDE.md §3.1); verify all 9 open and
   contain fire_archive_*.csv. AppEEARS: if data/raw/appeears/<region>/ isn't already filled by
   scripts/download_appeears.py, sort any .tif files by their bounds (rasterio) into the right
   region; report counts per region. Write FIRMS_MAP_KEY to .env. Confirm data/raw and .env are
   gitignored.
2. Create .venv; install pandas pyarrow duckdb numpy scipy statsmodels shapely rasterio
   matplotlib pytest (B owns requirements.txt; just install locally, and tell me if B needs to add
   anything).
3. Implement pipeline/ingest.py per CLAUDE.md §3 and Prompt 1 in KICKOFF_PROMPTS.md (stream from
   zips, keep type 0, unified schema, parquet per region × sensor, counts table, pytest).
Show the plan first and wait for my OK. Then run, test, commit, pull --rebase, push.
```

### A2: grid + Texas sample for the team (target 16:30)
```
Implement pipeline/grid.py per KICKOFF_PROMPTS.md Prompt 2 (0.1° daily, 0.25° monthly, missing
mask as NaN, totals check, overpass_times.png).
Then, as an early hand-off to Track B, write a FIRST version of pipeline/build_app_data.py that
produces data/app/ for TEXAS ONLY in the exact schemas in docs/CONTRACTS.md §2, using
mec = modis_n before 2012-01-20 and mec = viirs_n / (one global ratio) after, as a placeholder
until harmonization is done. Tell me the file sizes so I can upload them to our shared Drive.
Commit and push (code only, not data).
```

### A3: harmonize + validate (target 19:30, the most important step; plan mode)
Paste **KICKOFF_PROMPTS.md Prompt 3** as written, then add:
```
Also: lead every summary with harmonized vs the GLOBAL RATIO baseline (not vs raw VIIRS); that's
the comparison that proves our method adds something. Write results/metrics.json in the exact
shape in docs/CONTRACTS.md §3. Commit results/metrics.json and results/figures/*.png.
```

### A4: final app data (target 21:00)
```
Finish pipeline/build_app_data.py for all three regions using the winning harmonization from
results/metrics.json, exactly per docs/CONTRACTS.md §2: cells_daily.parquet, missing_days.parquet,
hotspots.parquet, coverage.json. NRT rows flagged provisional. Validate the schema with a pytest
that checks every column name and dtype against CONTRACTS.md. Report each file's size.
Also add pipeline/run_all.py and a Makefile target `all`. Commit code and push.
```
Then upload `data/app/` to the shared Drive and tell B and C. After that, A becomes the
**science reviewer**: check B's numbers in the app against `results/metrics.json`, write the
Methods-page text (hand it to C), and help with the Sunday judge review.

---

## Track B: Backend

### B1: synthetic data + analytics (target 16:30)
```
I'm Track B (Backend) of a 3-person team. Read CLAUDE.md, docs/challenge.md, docs/CONTRACTS.md
and PARALLEL_PLAN.md first. I only edit the files Track B owns.

FIRMS MAP_KEY: <KEY>  (write it to .env; confirm .env is gitignored)

Track A is still building the real data. So:
1. Write requirements.txt for the whole project (pandas, pyarrow, duckdb, numpy, scipy,
   statsmodels, shapely, rasterio, matplotlib, fastapi, uvicorn, httpx, python-dotenv, pytest,
   playwright) and create .venv.
2. Write scripts/make_synthetic_app_data.py: realistic fake data in EXACTLY the
   docs/CONTRACTS.md §2 schemas for all three regions (seasonal fire cycle per region, a few
   extreme years like Texas 2011, a 3x jump in viirs_n after 2012-01-20, some missing days,
   provisional rows for the last 2 months, matching hotspots points). Small (a few MB).
3. Implement app/analytics.py: everything in CLAUDE.md §5 (polygon/bbox/point → cells; daily
   series with 0 where no rows and NaN on missing days; climatology median/mean/std with ±15-day
   smoothing; anomalies; month×year grid; years ranked; fire season; high-risk months; chance of
   an unusual month; current month vs median; plain-language summary from computed numbers only).
4. pytest for all of it on small hand-made series (z-score, % of median, NaN propagation, fire
   season on a synthetic seasonal curve, point+radius selection).
Show the plan first and wait for my OK. Then build, test, commit, pull --rebase, push.
```

### B2: API (target 18:00)
```
Implement app/main.py (FastAPI + DuckDB over data/app/*.parquet; path configurable by env var
APP_DATA_DIR, default data/app) with every endpoint in docs/CONTRACTS.md §4, returning EXACTLY
those JSON shapes. Serve app/static/ at / and /methods. Errors as HTTP 400 {"error": ...}.
Stream the hotspots CSV with the 200,000-row cap.
pytest every endpoint against the synthetic data, including response time < 2 s for a
Texas-size bbox. Then save one real response per endpoint (Texas 2011 bbox) to
/tmp/api_examples/ and tell me whether they match the mock JSON in docs/CONTRACTS.md; if any field
differs, fix the API, not the contract. Commit and push.
```

### B3: live FIRMS feed (target 20:00)
```
Implement pipeline/live.py per CLAUDE.md §3.1: fetch VIIRS_NOAA20_NRT, VIIRS_NOAA21_NRT and MODIS_NRT
for each region from the end of the zips' NRT data to today in ≤10-day chunks, cache raw CSVs to
data/cache/live/ (gitignored), respect the rate limit, retry politely, and write
data/app/live_cells_daily.parquet + data/app/live_hotspots.parquet in the same schemas
(provisional=true; apply the harmonization coefficients from data/processed/ if present, else the
global ratio). Make the API union live files in automatically, and keep working if they're
missing. Add a `make live` target note for Track A. Test with my key. Commit and push.
```

### B4: switch to real data (when A delivers, target 22:30)
```
Track A's real data/app/ is now at <PATH>. Point APP_DATA_DIR at it, run the full test suite and
the endpoint timing test, and fix anything that breaks (performance: add DuckDB indexes/sorting or
pre-aggregated monthly tables if any endpoint is over 2 s). Check 3 numbers in /api/summary
against a hand calculation in DuckDB. Commit and push.
```
After that, B pairs with C on deployment (the API + data on Hugging Face Spaces).

---

## Track C: Frontend + Ship

### C1: UI on mock data (target 18:00)
```
I'm Track C (Frontend + Ship) of a 3-person team. Read CLAUDE.md, docs/challenge.md,
docs/CONTRACTS.md and PARALLEL_PLAN.md first. I only edit the files Track C owns.
The backend isn't ready, so build against mock data.

1. Create app/static/mock/*.json from the example responses in docs/CONTRACTS.md §4, made
   realistic and bigger: full month×year grid 2001→2026 for a Texas box with a seasonal cycle and
   2011 as an extreme year, 12-month medians, ranked years, a daily calendar for one month, a
   timeseries showing a 3x jump in viirs_raw after 2012 that harmonized doesn't have.
2. Build app/static/index.html, methods.html, js/, css/ per CLAUDE.md §6 (plain HTML/JS, Leaflet +
   Leaflet.draw, D3, Chart.js from a CDN; no build step). One api.js module: if the URL has
   ?mock=1 it loads mock JSON, otherwise it calls the real /api endpoints. Use the
   frontend-design skill if available. Accessible colors (viridis/cividis sequential, a
   colorblind-safe diverging ramp), keyboard navigation, ARIA labels, works on a phone.
3. Open it with a simple local static server and check every tab, toggle and export works on
   mock data. Screenshot each view to docs/screenshots/.
Show the plan first and wait for my OK. Then build, commit, pull --rebase, push.
```

### C2: deploy skeleton now, not Sunday (target 18:30)
```
Set up deployment early so Sunday has no surprises. Target Hugging Face Spaces (Docker type,
free CPU tier) as the primary host. Write a Dockerfile (python:3.11-slim, installs
requirements.txt, copies app/, downloads data/app/ at build or start from a URL in env var
APP_DATA_URL, serves uvicorn app.main:app on port 7860) and .dockerignore. Until B's API exists,
make the container serve app/static with ?mock=1 working. Give me click-by-click steps to create
the Space, set secrets (FIRMS_MAP_KEY, APP_DATA_URL), and push. Get a public URL live today.
Commit and push.
```

### C3: wire to the real API (when B is ready, target 22:30)
```
Track B's API is running (locally at <URL> / on the Space). Switch the UI to the real API
(?mock=0 default), test the full flow with Playwright: draw, lat/lon box, point+radius, presets,
date range, baseline, all three tabs, mode toggle, both CSV exports, PNG exports, Methods page
loading results/metrics.json. Fix UI bugs; report API mismatches to me so I can pass them to B.
Then go through docs/challenge.md R1–R18 and tell me where each is visible. Commit and push.
```

### C4: Sunday: deploy, video, submission
Use **KICKOFF_PROMPTS.md Prompts 6, 7 and 8** in order (deploy, video + README + submission text,
fresh-eyes review). Presets: ask Track A which events are the real biggest anomalies.
Methods page text: from Track A. All numbers: from `results/metrics.json` only.

---

## If something goes wrong
- **A is late:** B and C keep going on synthetic/mock data. The app can ship on A's Texas sample
  plus metrics if the full build slips; cut Australia first (CLAUDE.md §8 cut order).
- **A contract needs to change:** the person who needs it posts in team chat, the owner updates
  `docs/CONTRACTS.md` and the mock/synthetic data in the same commit.
- **Push rejected:** `git pull --rebase origin main`, then push again. If there's a conflict in a
  file you don't own, take the other version (`git checkout --theirs <file>`) and tell its owner.
- **Recovery prompts** for stuck sessions are at the bottom of KICKOFF_PROMPTS.md.
