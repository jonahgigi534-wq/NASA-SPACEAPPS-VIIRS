"""pipeline.science_check.Expected reads the live FIRMS files the way app/main.py does:
live rows only for days after a region's main end, live missing days included."""
import json
from datetime import date

import pandas as pd

from pipeline.science_check import Expected


def _cells(rows):
    return pd.DataFrame(rows, columns=["region", "lat", "lon", "date", "mec", "modis_n", "viirs_n"])


def test_expected_adds_live_days_after_main_end(tmp_path):
    d1, d2, d3 = date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1)
    _cells([("texas", 31.0, -100.0, d1, 2.0, 1, 2.0),
            ("texas", 31.0, -100.0, d2, 3.0, 1, 3.0)]).to_parquet(tmp_path / "cells_daily.parquet")
    # live repeats d2 (must be ignored: the main file already has it) and adds d3
    _cells([("texas", 31.0, -100.0, d2, 99.0, 9, 99.0),
            ("texas", 31.0, -100.0, d3, 5.0, 2, 5.0)]).to_parquet(tmp_path / "live_cells_daily.parquet")
    pd.DataFrame({"x": [1]}).to_parquet(tmp_path / "live_hotspots.parquet")
    pd.DataFrame({"region": ["texas"], "date": [d1], "scope": ["modis_only"]}).to_parquet(
        tmp_path / "missing_days.parquet")
    pd.DataFrame({"region": ["texas"], "date": [d3], "scope": ["modis_only"]}).to_parquet(
        tmp_path / "live_missing_days.parquet")
    cov = {"texas": {"start": "2026-10-30", "archive_end": "2026-10-31", "nrt_end": "2026-10-31",
                     "live_end": "2026-10-31", "bbox": [-107, 25, -93, 37]}}
    (tmp_path / "coverage.json").write_text(json.dumps(cov))
    (tmp_path / "live_coverage.json").write_text(json.dumps({"texas": {"live_end": "2026-11-01"}}))

    ex = Expected(tmp_path)
    s = ex.series("texas", [-107, 25, -93, 37])
    assert ex.end == d3
    assert s.tolist() == [2.0, 3.0, 5.0]
    m = ex.series("texas", [-107, 25, -93, 37], "modis_only")
    assert m.isna().tolist() == [True, False, True]
