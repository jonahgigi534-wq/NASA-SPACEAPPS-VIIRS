# Track A: Data + Science

**You own:** reading the raw NASA data, the harmonization (the science), the accuracy numbers,
and the final app data that everyone else uses.
**Your laptop needs:** the 9 FIRMS zips, the AppEEARS land-cover files, your MAP_KEY,
16 GB RAM and ~10 GB free disk if possible.
**You hand off to:** Track B (the app data files) and Track C (the accuracy numbers, charts and
Methods-page text).

## How to use this file
1. `git clone https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS` then `cd NASA-SPACEAPPS-VIIRS`
2. Run `claude`, press **Shift+Tab** for plan mode.
3. Paste **A1**. Approve the plan. When it's done and the **check** passes, type `/clear` and
   paste the next prompt. Each prompt says **when** to run it.
4. Post in the team chat at every 📣 handoff.

---

## A1: Data, setup, ingest · start now · target 3:15 pm
Fill in the two blanks, then paste:
```
I'm Track A (Data + Science) of a 3-person team. Read CLAUDE.md, docs/challenge.md,
docs/CONTRACTS.md and tracks/TRACK_A_DATA_SCIENCE.md first. I only edit the files Track A owns
(docs/CONTRACTS.md §1).

Data folder: <PATH TO FOLDER WITH THE 9 FIRMS ZIPS AND APPEEARS FILES>
FIRMS MAP_KEY: <KEY>

1. Copy the FIRMS zips into data/raw/<region>/ by ID (CLAUDE.md §3.1). Verify all 9 open and
   contain fire_archive_*.csv; stop and tell me if any is missing.
2. AppEEARS: if data/raw/appeears/<region>/ is empty, look for .tif files in the data folder and
   sort them by their bounds (rasterio) into the region whose box in data/regions/*.geojson
   contains their center, stripping " (n)" from names. Report counts per region. If none exist,
   tell me to run `python scripts/download_appeears.py` and carry on without them.
3. Write FIRMS_MAP_KEY to .env. Confirm data/raw and .env are gitignored.
4. Make .venv and install pandas pyarrow duckdb numpy scipy statsmodels shapely rasterio
   matplotlib pytest locally (Track B owns requirements.txt; tell me anything B should add).
5. Implement pipeline/ingest.py: stream archive + NRT CSVs from the zips (usecols, dtypes,
   chunked or DuckDB), keep type 0, one schema for MODIS and VIIRS (region, sensor, satellite,
   datetime_utc, acq_date, lat, lon, frp, confidence_class, confidence_raw, daynight,
   is_provisional), write data/processed/fires_<region>_<sensor>.parquet. Print rows by region ×
   satellite × year, share of each type removed, nulls in key columns, archive and NRT date
   ranges. pytest: confidence mapping, schema, type filter, no nulls.
Show the plan and wait for my OK. Then run, test, commit, `git pull --rebase origin main`, push.
Finish by telling me the next prompt from my track file.
```
**Check:** all 9 zips valid, counts look sensible (Amazon biggest, Texas smallest), tests pass.

---

## A2: Grid + Texas sample for the team · after A1 · target 4:30 pm
```
Implement pipeline/grid.py: 0.1° daily and 0.25° monthly aggregates per region × satellite ×
day/night (n_det, frp_sum, frp_mean); missing-data mask (data/raw/missing_dates.csv if present,
else infer per CLAUDE.md §3.2), stored as NaN never 0; pytest that grid totals equal row counts;
results/figures/overpass_times.png (acq_time by year for Terra, Aqua, S-NPP, NOAA-20) with one
paragraph on what it shows.

Then write a FIRST version of pipeline/build_app_data.py that builds data/app/ for TEXAS ONLY in
the exact schemas in docs/CONTRACTS.md §2 (cells_daily, missing_days, hotspots, coverage.json),
using a placeholder harmonization: mec = modis_n before 2012-01-20, and viirs_n divided by one
global ratio after. Tell me the file sizes. Commit code (not data), pull --rebase, push. Tell me
the next prompt.
```
**Check:** totals match, overpass figure looks sensible.
📣 **Handoff:** upload `data/app/` (Texas sample) to the shared Drive, post "Texas sample ready"
for Track B.

---

## A3: Harmonize + validate · after A2 · target 7:30 pm · the most important prompt
```
Implement pipeline/harmonize.py, pipeline/validate.py and (if AppEEARS data exists)
pipeline/landcover.py, exactly per CLAUDE.md §4:
- Calibrate MODIS Aqua vs VIIRS S-NPP, same day and overpass, on 0.25° monthly cells.
- Method B first (log-log OLS and quantile mapping, per region × land-cover group × day/night).
  Then Method A (FRP detection-limit matching) only if time allows; it's optional.
- Baselines: raw VIIRS and ONE global ratio.
- Fit 2012–2018, test 2019 → archive end. Transfer test on NOAA-20 (never used in fitting).
- Sensitivity run without low-confidence detections.
- Pick the winner by test-set score; save coefficients to data/processed/.
- Build the final harmonized record per CLAUDE.md §4.4 and document the de-duplication rule.
- results/metrics.json in EXACTLY the shape in docs/CONTRACTS.md §3.
- Figures: continuity_<region>.png (2001 → now, raw vs harmonized, switch dates marked),
  scatter_before_after.png, bias_before_after.png, optional burned-area check.
Show the plan first. After it runs, give me a plain-English summary that leads with
harmonized vs the GLOBAL RATIO (not vs raw VIIRS): which method won, by how much, where it
struggles and why, and the 3 numbers we should put in the video. If it doesn't beat the global
ratio somewhere, say so honestly and propose a fix. Commit metrics.json and figures, pull
--rebase, push. Tell me the next prompt.
```
**Check:** open the continuity plots: the 2012 jump should be gone in the harmonized line.
Read the summary yourself.
📣 **Handoff:** post the 3 headline numbers for Track C (video and README).

---

## A4: Final app data · after A3 · target 9:00 pm
```
Finish pipeline/build_app_data.py for all three regions with the winning harmonization from
results/metrics.json, exactly per docs/CONTRACTS.md §2 (cells_daily, missing_days, hotspots,
coverage.json). NRT rows are provisional. Add a pytest that checks every column name and dtype
against CONTRACTS.md. Add pipeline/run_all.py and Makefile targets for each step plus `all`.
Report each file's size. Commit code, pull --rebase, push. Tell me the next prompt.
```
**Check:** schema test passes; total `data/app/` size reported.
📣 **Handoff:** upload the full `data/app/` to the shared Drive, post "Real data ready" for
Tracks B and C.

---

## A5: Presets + Methods text · after A4 · target 10:00 pm
```
Using the harmonized data, find the 4 biggest real fire anomalies across our regions (region,
bounding box, month or date range, % of median). Write them to docs/presets.json as
[{"name", "region", "bbox", "start", "end", "why"}] for Track C's preset buttons.
Then write docs/methods_text.md for the Methods page: how the harmonization works in plain
English (for a judge who isn't a scientist), the validation design, the key results quoted only
from results/metrics.json, the data sources with DOIs (FIRMS MODIS C6.1, VIIRS S-NPP/NOAA-20/
NOAA-21, MCD12Q1, MCD64A1 if used), and honest limitations. Commit, pull --rebase, push.
```
📣 **Handoff:** tell Track C that `docs/presets.json` and `docs/methods_text.md` are ready.

---

## A6: Science check of the app · Sunday morning, once the app runs on real data
```
Act as the science reviewer. Start the app locally on the real data (or use the live URL:
<URL>). For 3 presets, compare the app's numbers (summary, calendar, current month) with direct
DuckDB queries on data/app/. List any mismatch with the endpoint and the expected value, so I can
pass it to Track B. Also check that missing days show as missing, not zero, and that every number
on the Methods page matches results/metrics.json.
```

## A7: Fresh-eyes judge review · Sunday ~8:00 pm (with the whole team)
Use **KICKOFF_PROMPTS.md Prompt 8** with the live URL. Share the findings with B and C.
