# Space Apps submission text (one section per form field)

Fill in the remaining TBD (video link) and the team names before submitting. All numbers come from `results/metrics.json`.

## Project name
FireBridge

## Short summary (one or two sentences)
FireBridge joins NASA's MODIS and VIIRS fire satellites into one consistent record of fire
activity from 2001 to today, and turns it into a burning activity calendar for any area you
draw on a map: fire seasons, unusual years, this month versus the historical median, and a CSV
of every hotspot.

## Project Details (form field)
FireBridge is a free website that turns 25 years of NASA satellite fire detections into one consistent fire history for any place on Earth's surface that you choose. You draw an area on a map (or type coordinates, or search a town), pick dates, and get a burning activity calendar of every month since 2001, the area's usual fire season and high-risk months, how this month compares with the 2003-2022 normal, and how the latest fire ranks against every fire there since 2001. A map replays the fire season month by month, and everything downloads as CSV, GeoJSON or KML.

**How it works.** The record comes from two instruments. MODIS (Terra and Aqua, 2001 onward) is retiring; its successor VIIRS (from 2012) has sharper pixels and reports 5 to 9 times more hotspots for the same fires, so joining the two as-is makes fire seem to explode in 2012. We learn how the two relate during 2012-2018, when MODIS Aqua and VIIRS S-NPP flew nearly the same orbit, using quantile mapping fitted separately for each region, land-cover type (from NASA's MODIS land cover product) and day or night. Then we translate every VIIRS detection onto the MODIS scale. On years the method never saw (2019 onward) the harmonized record is within 1% of MODIS overall (raw VIIRS: +660%), and within 3% on NOAA-20, a satellite we never used for fitting. An independent check against NASA's MODIS burned-area product shows the 2012 jump is gone. A live NASA FIRMS feed refreshes the current month every hour, gas flares and other static heat sources are filtered out, and days with no satellite data are shown as missing, never as zero fire.

**Benefits and intended impact.** As MODIS retires, fire agencies risk losing their 25-year baseline. FireBridge keeps it: an emergency manager can see in seconds whether this month is unusual, a land manager can plan around the real fire season, and a scientist can study trends without a fake jump in 2012. An "unusual right now" list points to the places furthest above normal this month, which supports early warning.

**Creativity.** Most comparisons use one global ratio between sensors. We match them per region and per land type, which roughly halves the error in two of our three test regions (in the Amazon, one ratio does slightly better), and we group hotspots into fire clusters so a new fire can be ranked against every past fire, not just past months. The site is map-first like a weather app, explains every number in plain language, and offers a beta Spanish interface (the challenge comes from Argentina's space agency, CONAE).

**Tools.** Python (pandas, NumPy, SciPy, DuckDB over Parquet, rasterio) for the pipeline and statistics. FastAPI for the web API. Plain HTML, CSS and JavaScript with Leaflet (maps), D3 and Chart.js (charts) for the website. Docker on Azure Container Apps for hosting, the data on Hugging Face, GitHub Actions for tests on every push, and Playwright for an automated browser check of every feature. No special hardware: laptops and free cloud tiers. We used Claude Code as a coding assistant; the team reviewed and ran everything.

**Factors we considered.**
- *Scientific honesty:* we validate on held-out years and an unused satellite, and publish where it struggles: Texas runs about 6% high, and MODIS's own orbit drift after 2022. A fit from one region does not carry over to another, so each new region gets its own fit; the 2012-2018 overlap exists everywhere, so this is feasible worldwide.
- *Accessibility:* colorblind-safe color ramps, screen-reader data tables, keyboard navigation, phone layouts.
- *Real-world use:* shareable links, a one-page printable briefing, standard GIS file formats.
- *Reliability:* pinned library versions, a pinned dataset version, 133 automated checks that every number on the site matches the data.

## NASA data used
- NASA FIRMS MODIS Collection 6.1 active fires (Terra, Aqua): MCD14ML archive
  (doi:10.5067/FIRMS/MODIS/MCD14ML) and MCD14DL near-real-time
  (doi:10.5067/FIRMS/MODIS/MCD14DL.NRT.0061)
- NASA FIRMS VIIRS 375 m active fires, Collection 2: S-NPP (doi:10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002),
  NOAA-20 (doi:10.5067/FIRMS/VIIRS/VJ114IMGT_NRT.002), NOAA-21 (doi:10.5067/VIIRS/VJ214IMG_NRT.002),
  plus the FIRMS area API for the latest days
- MODIS Land Cover Type MCD12Q1 v061 via NASA AppEEARS (doi:10.5067/MODIS/MCD12Q1.061)

The data shaped the project: the size of the MODIS-to-VIIRS jump made a correction necessary,
the 2012–2018 overlap made it learnable, the land-cover data showed one ratio doesn't fit every
landscape, and FIRMS missing-data days led us to treat gaps as unknown rather than zero.

## Use of AI
We used Claude Code (Anthropic) as a coding assistant for the data pipeline, the API, the
website, tests, the deploy and video scripts, and drafts of the documentation. The team
reviewed and ran everything. All numbers come from the pipeline's outputs on NASA data; no
images or video were generated by AI. Details: docs/AI_USE.md in the repository.

## Links
- Project (live site): https://firebridge.graycliff-49f97f4e.northcentralus.azurecontainerapps.io
- Demo video (30 s, English subtitles): TBD
- Code: https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS

## Uploading the video to YouTube (unlisted)
1. youtube.com → **Create** (camera icon) → **Upload video** → choose `docs/demo.mp4`.
2. Title: "FireBridge – NASA Space Apps 2026". Audience: **No, it's not made for kids**.
3. **Subtitles**: the English subtitles are already burned into the video. Optionally also add
   `docs/video_subtitles.srt` under **Subtitles → Add language → English → Upload file → With timing**.
4. **Visibility: Unlisted** → **Save**. Copy the link into the form and into README.md.
5. Open the link in an incognito window to check it plays without logging in.
