# Demo video storyboard (29 s, limit 30 s)

Built by `scripts/record_demo.py`, which also writes the matching `docs/video_subtitles.srt`
(English, burned in). Cards are plain text rendered from HTML; the chart is Track A's
`results/figures/continuity_texas.png`; the app shots are **real motion** recorded from the running
site (the script draws a box, scrolls, clicks, opens a past fire and downloads the CSV, with a visible
cursor). Every number comes from `results/metrics.json` or from the live app. No AI-generated images or
voices, no NASA logos.

| # | Time | On screen | Subtitle (≤ 8 words) |
|---|---|---|---|
| 1 | 0–3 s | Card from the live app: West Texas, April–July 2011, "11.6× its normal fire activity", 22,578 hotspots, busiest year on record | Texas, 2011: 11.6× normal fire activity. |
| 2 | 3–6 s | Card: NASA plans to end MODIS in 2027; VIIRS reports +660% more hotspots for the same fires (`overall.holdout.raw_viirs.bias_pct`) | MODIS is ending. VIIRS counts don't match. |
| 3 | 6–9.5 s | Track A's Texas continuity chart: the naive record jumps in 2012, the harmonized one doesn't | Raw VIIRS jumps in 2012. Ours doesn't. |
| 4 | 9.5–12 s | Card: on 2019–2026, typical monthly error 971 vs 1,212 for one global ratio | Beats the simple fix on unseen years. |
| 5 | 12–15.5 s | App: a box is drawn on the map; key figures, summary and calendar fill in | Draw any area: 25 years of fire. |
| 6 | 15.5–18.5 s | App: scroll to the burning calendar, switch to "vs normal" | A burning calendar, every month since 2001. |
| 7 | 18.5–21.5 s | App: Now vs history: this month vs the median for the same days, day by day | This month versus the historical median. |
| 8 | 21.5–25 s | App: Fires vs past in northern New Mexico; "Show" on the largest cluster (Hermits Peak / Calf Canyon, 2022) outlines it on the map | The current fire, ranked against every past fire. |
| 9 | 25–27 s | App: the hotspots CSV downloads; the real file name and row count appear | Download every hotspot as CSV. |
| 10 | 27–29 s | Card: FireBridge, site address, "Built on NASA FIRMS MODIS + VIIRS data" | FireBridge. Built on NASA FIRMS data. |

Re-render after deploying, so the end card shows the live address:
`python scripts/record_demo.py --url https://<space>.hf.space --site-url <space>.hf.space`

Optional: a team member can record a voice-over of the subtitle lines (phone mic is fine) and mix it in
with ffmpeg; the video works silently with subtitles as it is.
