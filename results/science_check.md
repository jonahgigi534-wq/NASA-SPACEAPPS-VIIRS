# Science check of the app (local, in-process on data/app)

133 checks, **0 mismatches**. Expected values are direct DuckDB queries on data/app/ (`python -m pipeline.science_check`).

Presets checked: West Texas and northern Mexico, Apr-Jul 2011; Rondonia / Bolivia border, Nov-Dec 2023; Northern Australia savannas, Aug-Sep 2011.

## All checks

| Endpoint | Field | App | Expected | OK |
|---|---|---|---|---|
| POST /api/summary [West Texas and northern Mexico, Apr-Jul 2011] | key_figures.total_hotspots | 22578 | 22578.0 | yes |
| POST /api/summary [West Texas and northern Mexico, Apr-Jul 2011] | key_figures.pct_of_median | 1155 | 1155.35 | yes |
| docs/presets.json [West Texas and northern Mexico, Apr-Jul 2011] | why: % of median vs app | 1155 | 1155.0 | yes |
| POST /api/summary [West Texas and northern Mexico, Apr-Jul 2011] | key_figures.busiest_month | 2011-04 | 2011-04 | yes |
| POST /api/summary [West Texas and northern Mexico, Apr-Jul 2011] | missing_days | 0 | 0 | yes |
| POST /api/summary [West Texas and northern Mexico, Apr-Jul 2011] | provisional_days | 0 | 0 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-04 | value | 11329.0 | 11329.0 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-04 | median | 433.0 | 433.04 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-04 | pct_of_median | 2616 | 2616.15 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-04 | missing | False | False | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-05 | value | 4896.0 | 4896.0 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-05 | median | 706.5 | 706.48 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-05 | pct_of_median | 693 | 693.01 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-05 | missing | False | False | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-06 | value | 5164.0 | 5164.0 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-06 | median | 599.7 | 599.66 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-06 | pct_of_median | 861 | 861.16 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-06 | missing | False | False | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-07 | value | 1189.0 | 1189.0 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-07 | median | 153.8 | 153.8 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-07 | pct_of_median | 773 | 773.08 | yes |
| POST /api/calendar month [West Texas and northern Mexico, Apr-Jul 2011] 2011-07 | missing | False | False | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2026-11-01 | month | 2026-11 | 2026-11 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2026-11-01 | value_so_far | 0.1 | 0.06 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2026-11-01 | median_same_days | 2.3 | 2.26 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2026-11-01 | pct_of_median | 3 | 2.56 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2026-11-01 | rank_among_years | 21 | 21 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2026-11-01 | of_years | 26 | 26 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2011-07-31 | month | 2011-07 | 2011-07 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2011-07-31 | value_so_far | 1189.0 | 1189.0 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2011-07-31 | median_same_days | 115.0 | 115.0 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2011-07-31 | pct_of_median | 1034 | 1033.91 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2011-07-31 | rank_among_years | 1 | 1 | yes |
| POST /api/current [West Texas and northern Mexico, Apr-Jul 2011] as_of 2011-07-31 | of_years | 11 | 11 | yes |
| POST /api/summary [Rondonia / Bolivia border, Nov-Dec 2023] | key_figures.total_hotspots | 7707 | 7707.01 | yes |
| POST /api/summary [Rondonia / Bolivia border, Nov-Dec 2023] | key_figures.pct_of_median | 5348 | 5348.41 | yes |
| docs/presets.json [Rondonia / Bolivia border, Nov-Dec 2023] | why: % of median vs app | 5348 | 5348.0 | yes |
| POST /api/summary [Rondonia / Bolivia border, Nov-Dec 2023] | key_figures.busiest_month | 2023-11 | 2023-11 | yes |
| POST /api/summary [Rondonia / Bolivia border, Nov-Dec 2023] | missing_days | 0 | 0 | yes |
| POST /api/summary [Rondonia / Bolivia border, Nov-Dec 2023] | provisional_days | 0 | 0 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-11 | value | 7444.4 | 7444.41 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-11 | median | 111.4 | 111.39 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-11 | pct_of_median | 6683 | 6683.41 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-11 | missing | False | False | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-12 | value | 262.6 | 262.6 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-12 | median | 14.0 | 14.0 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-12 | pct_of_median | 1876 | 1875.7 | yes |
| POST /api/calendar month [Rondonia / Bolivia border, Nov-Dec 2023] 2023-12 | missing | False | False | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2026-11-01 | month | 2026-11 | 2026-11 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2026-11-01 | value_so_far | 4.5 | 4.46 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2026-11-01 | median_same_days | 2.1 | 2.12 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2026-11-01 | pct_of_median | 210 | 210.16 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2026-11-01 | rank_among_years | 12 | 12 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2026-11-01 | of_years | 26 | 26 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2023-12-31 | month | 2023-12 | 2023-12 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2023-12-31 | value_so_far | 262.6 | 262.6 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2023-12-31 | median_same_days | 14.0 | 14.0 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2023-12-31 | pct_of_median | 1876 | 1875.7 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2023-12-31 | rank_among_years | 2 | 2 | yes |
| POST /api/current [Rondonia / Bolivia border, Nov-Dec 2023] as_of 2023-12-31 | of_years | 22 | 22 | yes |
| POST /api/summary [Northern Australia savannas, Aug-Sep 2011] | key_figures.total_hotspots | 73415 | 73415.0 | yes |
| POST /api/summary [Northern Australia savannas, Aug-Sep 2011] | key_figures.pct_of_median | 334 | 334.02 | yes |
| docs/presets.json [Northern Australia savannas, Aug-Sep 2011] | why: % of median vs app | 334 | 334.0 | yes |
| POST /api/summary [Northern Australia savannas, Aug-Sep 2011] | key_figures.busiest_month | 2011-09 | 2011-09 | yes |
| POST /api/summary [Northern Australia savannas, Aug-Sep 2011] | missing_days | 0 | 0 | yes |
| POST /api/summary [Northern Australia savannas, Aug-Sep 2011] | provisional_days | 0 | 0 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-08 | value | 26190.0 | 26190.0 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-08 | median | 10422.5 | 10422.52 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-08 | pct_of_median | 251 | 251.28 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-08 | missing | False | False | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-09 | value | 47225.0 | 47225.0 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-09 | median | 11960.0 | 11960.02 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-09 | pct_of_median | 395 | 394.86 | yes |
| POST /api/calendar month [Northern Australia savannas, Aug-Sep 2011] 2011-09 | missing | False | False | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2026-11-01 | month | 2026-11 | 2026-11 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2026-11-01 | value_so_far | 497.9 | 497.88 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2026-11-01 | median_same_days | 697.2 | 697.18 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2026-11-01 | pct_of_median | 71 | 71.41 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2026-11-01 | rank_among_years | 19 | 19 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2026-11-01 | of_years | 26 | 26 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2011-09-30 | month | 2011-09 | 2011-09 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2011-09-30 | value_so_far | 47225.0 | 47225.0 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2011-09-30 | median_same_days | 11126.5 | 11126.5 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2011-09-30 | pct_of_median | 424 | 424.44 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2011-09-30 | rank_among_years | 1 | 1 | yes |
| POST /api/current [Northern Australia savannas, Aug-Sep 2011] as_of 2011-09-30 | of_years | 11 | 11 | yes |
| POST /api/calendar day, mode harmonized [texas] 2004-11-10 | value on a missing day | None | None | yes |
| POST /api/calendar day, mode harmonized [texas] 2004-11-10 | missing | True | True | yes |
| POST /api/summary, mode harmonized [texas] 2004-11-07..2004-11-13 | missing_days | 1 | 1 | yes |
| POST /api/calendar day, mode modis_only [texas] 2011-01-19 | value on a missing day | None | None | yes |
| POST /api/calendar day, mode modis_only [texas] 2011-01-19 | missing | True | True | yes |
| POST /api/summary, mode modis_only [texas] 2011-01-16..2011-01-22 | missing_days | 1 | 1 | yes |
| POST /api/calendar day, mode harmonized [amazon] 2004-12-30 | value on a missing day | None | None | yes |
| POST /api/calendar day, mode harmonized [amazon] 2004-12-30 | missing | True | True | yes |
| POST /api/summary, mode harmonized [amazon] 2004-12-27..2005-01-02 | missing_days | 1 | 1 | yes |
| POST /api/calendar day, mode modis_only [amazon] 2011-01-27 | value on a missing day | None | None | yes |
| POST /api/calendar day, mode modis_only [amazon] 2011-01-27 | missing | True | True | yes |
| POST /api/summary, mode modis_only [amazon] 2011-01-24..2011-01-30 | missing_days | 1 | 1 | yes |
| POST /api/calendar day, mode harmonized [australia] 2004-12-25 | value on a missing day | None | None | yes |
| POST /api/calendar day, mode harmonized [australia] 2004-12-25 | missing | True | True | yes |
| POST /api/summary, mode harmonized [australia] 2004-12-22..2004-12-28 | missing_days | 1 | 1 | yes |
| POST /api/calendar day, mode modis_only [australia] 2020-08-22 | value on a missing day | None | None | yes |
| POST /api/calendar day, mode modis_only [australia] 2020-08-22 | missing | True | True | yes |
| POST /api/summary, mode modis_only [australia] 2020-08-19..2020-08-25 | missing_days | 7 | 7 | yes |
| GET /methods | number 0.86 | 0.86 | 0.86 | yes |
| GET /methods | number 0.88 | 0.88 | 0.88 | yes |
| GET /methods | number 0.9774 | 0.9774 | 0.9774 | yes |
| GET /methods | number 0.9775 | 0.9775 | 0.9775 | yes |
| GET /methods | number 0.9855 | 0.9855 | 0.9855 | yes |
| GET /methods | number 1,206 | 1,206 | 1,206 | yes |
| GET /methods | number 1,212 | 1,212 | 1,212 | yes |
| GET /methods | number 1,316 | 1,316 | 1,316 | yes |
| GET /methods | number 1,389 | 1,389 | 1,389 | yes |
| GET /methods | number 1,494 | 1,494 | 1,494 | yes |
| GET /methods | number 1,540 | 1,540 | 1,540 | yes |
| GET /methods | number 1,551 | 1,551 | 1,551 | yes |
| GET /methods | number 1.18 | 1.18 | 1.18 | yes |
| GET /methods | number 1.33 | 1.33 | 1.33 | yes |
| GET /methods | number 1.79 | 1.79 | 1.79 | yes |
| GET /methods | number 1.95 | 1.95 | 1.95 | yes |
| GET /methods | number 2.83 | 2.83 | 2.83 | yes |
| GET /methods | number 5.97 | 5.97 | 5.97 | yes |
| GET /methods | number 589.93 | 589.93 | 589.93 | yes |
| GET /methods | number 59.38 | 59.38 | 59.38 | yes |
| GET /methods | number 60.32 | 60.32 | 60.32 | yes |
| GET /methods | number 62,479 | 62,479 | 62,479 | yes |
| GET /methods | number 63,146 | 63,146 | 63,146 | yes |
| GET /methods | number 651.35 | 651.35 | 651.35 | yes |
| GET /methods | number 659.69 | 659.69 | 659.69 | yes |
| GET /methods | number 680.0 | 680.0 | 680.0 | yes |
| GET /methods | number 738.73 | 738.73 | 738.73 | yes |
| GET /methods | number 9.46 | 9.46 | 9.46 | yes |
| GET /methods | number 9.96 | 9.96 | 9.96 | yes |
