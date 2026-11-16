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
FireBridge is a free website that shows when and where fires have burned, anywhere you choose, from 2001 to today. You draw an area on a map (or type coordinates, or search for a town) and pick your dates. FireBridge then gives you a burning activity calendar of every month since 2001. It also shows the area's usual fire season, its highest-risk months, how this month compares with the 2003-2022 normal, and how the latest fire ranks against every fire there since 2001. A map replays the fire season month by month. Everything can be downloaded as CSV, GeoJSON or KML.

How it works:
The record comes from two satellite instruments. MODIS (on Terra and Aqua, since 2001) is retiring. Its successor, VIIRS (since 2012), has sharper pixels and reports 5 to 9 times more hotspots for the same fires. If you join the two records as they are, fire seems to explode in 2012. That jump is fake.

From 2012 to 2018, MODIS Aqua and VIIRS S-NPP flew almost the same orbit. We use those years to learn how the two instruments relate. The method is quantile mapping, fitted separately for each region, each land-cover type (from NASA's MODIS land cover product) and day or night. Then we translate every VIIRS detection onto the MODIS scale.

We tested it on years the method never saw (2019 onward). The harmonized record lands within 1% of MODIS overall, while raw VIIRS is off by 660%. On NOAA-20, a satellite we never used for fitting, it lands within 3%. An independent check against NASA's MODIS burned-area product shows the 2012 jump is gone. A live NASA FIRMS feed updates the current month every hour. Gas flares and other fixed heat sources are filtered out, and days with no satellite data show up as missing, not as zero fire.

Benefits and impact:
As MODIS retires, fire agencies risk losing their 25-year baseline. FireBridge keeps it. An emergency manager can see in seconds whether this month is unusual. A land manager can plan around the real fire season. A scientist can study trends without a fake jump in 2012. An "unusual right now" list also points to the places furthest above normal this month, which helps with early warning.

Creativity:
The usual shortcut is one global ratio between the two sensors. We match them per region and per land type instead. In two of our three test regions, that cuts the error roughly in half (in the Amazon, one ratio does slightly better). We also group hotspots into fire clusters, so a new fire can be ranked against every past fire, not just past months. The site is map-first, like a weather app. It explains every number in plain language, and it has a beta Spanish interface, since the challenge comes from Argentina's space agency, CONAE.

Tools:
Python (pandas, NumPy, SciPy, DuckDB over Parquet, rasterio) runs the pipeline and the statistics. FastAPI serves the data. The website is plain HTML, CSS and JavaScript, with Leaflet for the map and D3 and Chart.js for the charts. It runs in Docker on Azure Container Apps, with the data hosted on Hugging Face. GitHub Actions runs our tests on every push, and Playwright checks every feature in a real browser. We used no special hardware, only laptops and free cloud tiers. We used Claude Code as a coding assistant, and our team reviewed and ran everything.

Factors we considered:
Scientific honesty came first. We tested on held-out years and on a satellite we never fitted to, and we publish where the method struggles. Texas runs about 6% high, and MODIS itself drifts in orbit after 2022. A fit from one region also does not carry over to another, so each new region needs its own fit. The 2012-2018 overlap exists everywhere, so that is doable worldwide.
Accessibility mattered too: colorblind-safe colors, screen-reader data tables, keyboard navigation and phone layouts.
For everyday use, we added shareable links, a one-page printable briefing and standard GIS file formats.
For reliability, we pinned every library version and the dataset version. 133 automated checks confirm that every number on the site matches the data.

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
