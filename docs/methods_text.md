# How FireBridge works

FireBridge joins two generations of NASA fire satellites into **one continuous record of fire
activity from 2001 to today**, so you can compare this year's fires with any year since 2001
without the satellite change getting in the way.

## The problem: the satellites changed, so the numbers jumped

Satellites spot fires as **hotspots**: places that are much hotter than their surroundings at
the moment the satellite passes over.

- **2001 to 2011: MODIS** (on the Terra and Aqua satellites) looks at the ground in 1 km pixels.
- **From 2012: VIIRS** (on S-NPP, then NOAA-20 and NOAA-21) uses 375 m pixels. It sees smaller
  and cooler fires, so it reports far more hotspots for the same fires.

If you simply put the two records end to end, fire activity seems to explode in 2012. It didn't;
the camera changed. On our test data, raw VIIRS counts are **+659.69%** higher than MODIS Aqua
counts for the same places and months.

## The fix, in plain English

We translate VIIRS counts into "MODIS-equivalent" counts, so the whole record speaks MODIS.

1. **Learn from the overlap.** From 2012 to 2018, MODIS Aqua and VIIRS S-NPP flew over the same
   places at nearly the same time of day (early afternoon and after midnight). For every
   25 km × 25 km square and every month, we know what both satellites counted.
2. **Learn a translation for each kind of place.** The relationship depends on where you are, so
   we learn a separate translation for each region (Texas, Amazon, Northern Australia), each
   land-cover type (forest, shrubland, savanna, grassland, cropland, other; from the MODIS land
   cover map MCD12Q1), and for day and night.
3. **Quantile mapping.** We line up VIIRS counts and MODIS counts by rank: a square-month at
   VIIRS's 90th percentile is translated to MODIS's 90th percentile, and so on. Small counts and
   big fire months each get their own translation, instead of one fixed ratio for everything.
4. **Match the full MODIS record.** MODIS used two satellites (Terra in the morning, Aqua in the
   afternoon). We scale the translated counts to the Terra + Aqua total using the 2003–2018
   ratio of the two for each region, day/night and calendar month.
5. **Don't count the same fire twice.** On days when two or three VIIRS satellites have data, we
   average what they say instead of adding them up.
6. **Before 2012 nothing changes:** the record *is* MODIS.

Each VIIRS hotspot then carries a **weight**: how many MODIS-equivalent hotspots it stands for.
The map, the calendar and the charts all add up these weights.

## How we tested it

We didn't grade the method on the data it learned from.

- **Learn on 2012–2018, test on 2019 → 2026.** The test years were never used for fitting.
- **Leave one region out.** Refit on two regions, test on the third, to see whether one
  translation could serve everywhere.
- **A second, independent test: NOAA-20.** This VIIRS satellite was **never used in fitting**.
  If the translation also works for it, it's capturing the sensor difference, not quirks of one
  satellite.
- **Two simple alternatives to beat:**
  - **raw VIIRS**: no correction at all;
  - **one global ratio**: divide every VIIRS count by one number. This is the obvious quick fix,
    and the one we have to beat.
- **How we score:** we compare monthly regional totals with real MODIS Aqua counts. R² is how much
  of the month-to-month pattern is reproduced (1 = perfect), bias is how far the total is off
  (0% = perfect), and RMSE is the typical error in hotspots per month (lower is better).
- **How we picked the winner:** the method with the lowest error averaged across the three
  regions on the test years. We also tried log-log regression; quantile mapping won.

## Results

All numbers below come from `results/metrics.json`.

**Overall, on the test years (2019 → 2026)**

| Method | R² | Bias | RMSE (hotspots / month) |
|---|---|---|---|
| Raw VIIRS | −60.32 | +659.69% | 63,146 |
| One global ratio | 0.9774 | −0.86% | 1,212 |
| **FireBridge (quantile mapping)** | **0.9855** | **−0.88%** | **971** |

**NOAA-20, never used in fitting**

| Method | R² | Bias | RMSE |
|---|---|---|---|
| Raw VIIRS | −59.38 | +651.35% | 62,479 |
| One global ratio | 0.9775 | −1.95% | 1,206 |
| **FireBridge** | **0.988** | **−2.83%** | **882** |

Averaged across the regions (each region's error scaled to its own size), FireBridge's error is
0.169 against 0.259 for one global ratio, **about 35% lower**.

**By region, test years (RMSE in hotspots per month, bias in brackets)**

| Region | FireBridge | One global ratio | Raw VIIRS bias |
|---|---|---|---|
| Northern Australia | 759 (−1.33%) | 1,551 (+9.46%) | +738.73% |
| Texas | 144 (+5.97%) | 265 (+1.79%) | +680.0% |
| Amazon | 1,494 (−1.18%) | 1,389 (−9.96%) | +589.93% |

**Is the MODIS reference itself moving?** Harmonized VIIRS vs MODIS Terra + Aqua, total bias by
period. In the years the translation learned from, all three regions sit within a few percent.
After 2022, when Terra and Aqua drift in orbit, **Texas jumps to +11.75%** while the Amazon and
Northern Australia barely move. Part of Texas's test-year bias is MODIS changing, not VIIRS.

| Region | 2012–2018 (learning years) | 2019–2021 | 2022 on |
|---|---|---|---|
| Texas | −1.52% | +0.59% | **+11.75%** |
| Northern Australia | +0.58% | +3.95% | +4.85% |
| Amazon | −4.98% | −5.77% | −5.57% |

**Would it work in a region it never saw?** For each region we refit the translation on the
*other two* regions only and scored the test years again (bias of the total; error scaled to the
region's size in brackets).

| Region | Learned on its own data | Learned on the other two | One global ratio from the other two |
|---|---|---|---|
| Texas | +5.97% (0.1925) | −34.83% (0.4481) | +1.45% (0.3543) |
| Northern Australia | −1.33% (0.1169) | +28.82% (0.4036) | +22.59% (0.3887) |
| Amazon | −1.18% (0.1972) | −15.73% (0.298) | −18.37% (0.2959) |

It doesn't travel: fire behaves differently in each landscape, so FireBridge needs each
region's own 2012–2018 overlap years. That is fine for any place on Earth, because VIIRS and MODIS
overlap everywhere from 2012, but it means a new region must be fitted, not borrowed.

## Data sources

- **NASA FIRMS, MODIS Collection 6.1 active fires** (Terra and Aqua, 1 km).
  Standard archive MCD14ML, doi:10.5067/FIRMS/MODIS/MCD14ML; near-real-time MCD14DL,
  doi:10.5067/FIRMS/MODIS/MCD14DL.NRT.0061.
- **NASA FIRMS, VIIRS 375 m active fires, Collection 2:**
  - S-NPP (VNP14IMGT), doi:10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002
  - NOAA-20 (VJ114IMGT), doi:10.5067/FIRMS/VIIRS/VJ114IMGT_NRT.002
  - NOAA-21 (VJ214IMG), doi:10.5067/VIIRS/VJ214IMG_NRT.002. NOAA-21 enters only through the
    live near-real-time feed; it is not part of the archive used for fitting or testing.
- **MODIS Land Cover Type, MCD12Q1 v061** (yearly, IGBP classes), via NASA AppEEARS,
  doi:10.5067/MODIS/MCD12Q1.061. Used to group places by land cover.
- MODIS Burned Area (MCD64A1 v061) was downloaded but **not used** in this version.
- Algorithms: Giglio, Schroeder & Justice (2016), *Remote Sensing of Environment* 178, 31–41
  (MODIS C6); Schroeder et al. (2014), *Remote Sensing of Environment* 143, 85–96 (VIIRS 375 m).

## Honest limitations

- **The Amazon is the hard case.** There, FireBridge's typical monthly error (1,494) is *higher*
  than one global ratio's (1,389), even though its total is much closer (−1.18% vs −9.96%). Our
  best explanation: some test-year fire seasons were bigger than most of 2012–2018, so the
  translation has to stretch beyond what it learned. It does better on NOAA-20 in the Amazon
  (1,316 vs 1,540).
- **Texas is slightly high:** +5.97% vs MODIS on the test years. Texas has few night fires, so its
  night translation rests on little data.
- **The MODIS reference itself is drifting.** Since about 2022, Terra and Aqua have been slowly
  leaving their original orbits, so they pass over at different times of day than before.
  MODIS counts from those years aren't strictly comparable with earlier MODIS counts either. In
  Texas the harmonized record went from −1.52% vs MODIS in the learning years to +11.75% from 2022.
- **Each region needs its own fit.** A translation borrowed from the other two regions missed
  Texas's total by −34.83% and Northern Australia's by +28.82% (see Results).
- **Hotspots are not burned area.** They count detections of active fire at the moment of an
  overpass. Clouds, smoke and the time of day all affect what is seen.
- **Recent data is provisional.** Near-real-time detections (marked provisional) may change when
  the final archive replaces them.
- **Fire intensity (FRP) uses one simple conversion** and was not separately validated.
- **Missing days are shown as gaps, never as zero.** A satellite-day counts as missing when it
  reports nothing while the other satellites say there should be at least 10 hotspots.
- The "overall" R² looks very high partly because the three regions differ so much in size; the
  per-region numbers are the fairer test.
- The Texas study box is a rectangle, so it also covers parts of New Mexico and northern Mexico.

## Use of AI

The team used Claude (Anthropic) as a coding assistant to write the data pipeline, the app and
the drafts of this text. The team reviewed everything. Every number in the app and on this page
is computed by the pipeline from the NASA data; none were written by hand or generated by AI.
