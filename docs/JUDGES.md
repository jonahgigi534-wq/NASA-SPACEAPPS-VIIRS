# Two-minute tour for judges

The same tour is a page on the live site, **`/judges`**, where every item below is one click into a
prepared view of the app. On any screen, **Copy link** (next to the area name) shares exactly that
view.

| The brief asks for | Where to look in the app |
|---|---|
| Harmonize MODIS and VIIRS so "the sensor of origin no longer matters" | Switch **Satellite record** between Raw VIIRS and Harmonized: the 2012 jump in the long-term chart disappears. Method and tests on **How it works** (`/methods`) and **More checks** (`/checks`). |
| Select a region: draw on a map, or enter latitude and longitude | Draw a rectangle, polygon or circle; **Type coordinates instead** (box or point + radius); search a place; or pick a big fire event. |
| A specific date range | **Dates and settings**: date pickers, quick ranges, adjustable "normal" years. |
| A burning calendar: hotspots from the early 2000s to the present | **Burning calendar** tab: every month (or week) since 2001; click a square for its days. Grey = no data, hatched = provisional. |
| Which periods of the year see more fires | **Patterns & critical periods**: fire season, highest-risk months and weeks, chance of an unusually busy month. |
| Which years had more burning activity | Same tab: yearly totals (busiest three highlighted) and the long-term trend. |
| How a current fire compares with previous ones | **Fires vs past** tab: fire clusters, the latest ranked against all since 2001 (northern New Mexico: Hermits Peak / Calf Canyon 2022). |
| The current month against the historical median | **Now vs history** tab, with live FIRMS data refreshed hourly; **Unusual right now** in the left panel. |
| Anomalies against multi-year averages | Calendar **vs normal** view and **Fire on the map → vs normal**; z-scores in the analytics CSV. |
| Number of fires detected | Key figures strip; **Measure** switches to fire power (MW). |
| Accessible color ramps | Viridis and purple–orange (colorblind-safe), legends with units, keyboard navigation, screen-reader data tables; axe-core audit with no serious issues. |
| Download analytics and visualizations | **Download** panel: analytics CSV, one-page briefing; ⤓ on every chart for PNG. |
| A CSV of the hotspots detected during a search | **Hotspots in this area (CSV)**, plus GeoJSON and KML. |
| Early warning, responders, scientists, land managers, firefighters | Plain-language summaries, the unusual-now list, shareable links, phone layout. |
