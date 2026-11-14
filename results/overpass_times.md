# Overpass times (`results/figures/overpass_times.png`)

Made by `python -m pipeline.overpass` from the FIRMS archive detections in all three regions,
converted from UTC to local solar time (UTC + longitude / 15).

From 2001 to about 2021 every satellite held its designed crossing time: Terra near 10:30 and
22:35, Aqua near 13:40 and 01:25, and S-NPP and NOAA-20 near 13:30 and 01:15. This is why
**MODIS Aqua and VIIRS S-NPP are the calibration pair**: in 2012–2021 they look at the same
fires within about 10 minutes of each other. From 2022 the two MODIS satellites drift as they
run out of fuel: by 2026 Terra's daytime pass has moved about 1.5 h earlier (08:51) and Aqua's
about 2 h later (15:33), while S-NPP and NOAA-20 stay put. Fire activity follows a strong daily
cycle (peaking mid-afternoon), so a drifting overpass changes how many fires MODIS sees for
reasons that have nothing to do with fire on the ground. For the harmonization this means
(1) the 2012–2018 fit window is unaffected, (2) test-period scores from 2022 onward, especially
2024–2026, mix in this drift and should be reported separately, and (3) after 2022 the VIIRS
record is the steadier reference, which supports switching the harmonized series to VIIRS
from 2012. The 2026 points cover January–August only.
