# Demo video storyboard (27 s, limit 30 s)

Built by `scripts/record_demo.py`: title and number cards are plain text rendered from HTML, the
chart is Track A's `results/figures/continuity_texas.png`, and the app shots are screenshots of
the running site. No AI-generated images, no NASA logos. English subtitles are burned in
(`docs/video_subtitles.srt`). Every number comes from `results/metrics.json` or the live app.

| # | Time | On screen | Subtitle (≤ 8 words) |
|---|---|---|---|
| 1 | 0–4 s | Card: "MODIS has tracked fires since 2000. It shuts down in 2027." / "Its successor, VIIRS, reports +660% more hotspots for the same fires." (bias of raw VIIRS vs MODIS Aqua, test years, `overall.holdout.raw_viirs.bias_pct`) | MODIS is ending. VIIRS counts don't match. |
| 2 | 4–9 s | Track A's continuity chart for Texas: the naive record jumps in 2012, the harmonized one doesn't | Raw VIIRS jumps in 2012. Ours doesn't. |
| 3 | 9–12 s | Card: "On years it never saw (2019–2026): typical monthly error 971 vs 1,212 for one global ratio" (`overall.holdout.harmonized.rmse` vs `global_ratio.rmse`) | Beats the simple fix on unseen years. |
| 4 | 12–15 s | App: the West Texas 2011 preset loaded: map, key figures, summary | Pick any area, any dates. |
| 5 | 15–18 s | App: the burning calendar, 2001 → today | A burning calendar from 2001 to today. |
| 6 | 18–21 s | App: Now vs history: this month vs the median for the same days | This month versus the historical median. |
| 7 | 21–24 s | App: the hotspots CSV download, with the real file name and row count | Download every hotspot as CSV. |
| 8 | 24–27 s | Card: "FireBridge" · site URL · "Built on NASA FIRMS MODIS + VIIRS data" | FireBridge. Built on NASA FIRMS data. |

Re-render after deploying, so the end card shows the live URL:
`python scripts/record_demo.py --url https://<space>.hf.space --site-url <space>.hf.space`
