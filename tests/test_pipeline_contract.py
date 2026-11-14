"""Every column name, order and dtype of the real data/app files vs docs/CONTRACTS.md section 2.

The expected schemas are parsed from CONTRACTS.md itself (pipeline/contract.py), so if the
contract changes, this test fails until the build matches it again.
"""
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

from pipeline.contract import APP_FILES, COVERAGE_KEYS, parse_contract
from pipeline.ingest import REGIONS

APP = Path("data/app")
CONTRACT = parse_contract()
needs_app = pytest.mark.skipif(not (APP / "cells_daily.parquet").exists(),
                               reason="run python -m pipeline.build_app_data")


def test_contract_parses_every_app_file():
    assert set(APP_FILES) <= set(CONTRACT)
    assert [c for c, _ in CONTRACT["cells_daily"]][:4] == ["region", "cell_id", "lat", "lon"]
    assert len(CONTRACT["hotspots"]) == 12


@needs_app
@pytest.mark.parametrize("name", APP_FILES)
def test_column_names_and_dtypes(name):
    schema = pq.read_schema(APP / f"{name}.parquet")
    got = list(zip(schema.names, schema.types))
    expected = CONTRACT[name]
    assert [c for c, _ in got] == [c for c, _ in expected], f"{name}: column names/order"
    for (col, typ), (_, want) in zip(got, expected):
        assert typ == want, f"{name}.{col}: {typ} != contract {want}"


@needs_app
def test_coverage_json_has_every_region_and_key():
    cov = json.loads((APP / "coverage.json").read_text())
    assert set(cov) == set(REGIONS)
    for region, entry in cov.items():
        assert set(entry) == set(COVERAGE_KEYS), region
        assert entry["start"] <= entry["archive_end"] <= entry["nrt_end"] <= entry["live_end"]
        assert len(entry["bbox"]) == 4


@needs_app
def test_viirs_rows_after_archive_end_are_provisional():
    """archive_end is the VIIRS archive end; every VIIRS cell-day after it comes from NRT."""
    cov = json.loads((APP / "coverage.json").read_text())
    cells = (APP / "cells_daily.parquet").as_posix()
    con = duckdb.connect()
    for region, entry in cov.items():
        bad = con.execute(f"""SELECT count(*) FROM read_parquet('{cells}')
            WHERE region = ? AND date > ?::DATE AND viirs_n > 0 AND NOT provisional""",
                          [region, entry["archive_end"]]).fetchone()[0]
        assert bad == 0, f"{region}: {bad} VIIRS cell-days after archive_end not provisional"
