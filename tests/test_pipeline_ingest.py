"""Tests for pipeline/ingest.py using tiny synthetic FIRMS zips (plus a check on real output if present)."""
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from pipeline import ingest

# FIRMS MODIS and VIIRS CSVs use the same column names (verified on the real zips).
HEADER = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
          "confidence,version,bright_t31,frp,daynight")


def _zip(path: Path, archive_rows: list[str], nrt_rows: list[str]) -> None:
    """Write a FIRMS-like zip: archive has a `type` column, NRT does not (like the real files)."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"fire_archive_{path.stem}.csv", "\n".join([HEADER + ",type", *archive_rows]) + "\n")
        zf.writestr(f"fire_nrt_{path.stem}.csv", "\n".join([HEADER, *nrt_rows]) + "\n")


@pytest.fixture
def region_out(tmp_path):
    raw = tmp_path / "raw" / "texas"
    raw.mkdir(parents=True)
    _zip(raw / "DL_FIRE_M-C61_1.zip",
         archive_rows=[
             "30.0,-100.0,310,1,1,2020-01-01,0130,Terra,MODIS,29,6.03,290,5.5,N,0",
             "30.1,-100.1,310,1,1,2020-01-02,1905,Aqua,MODIS,30,6.03,290,6.5,D,0",
             "30.205,-100.205,310,1,1,2020-01-03,1905,Aqua,MODIS,80,6.03,290,7.5,D,2",  # static -> dropped
             "30.3,-100.3,310,1,1,2020-01-04,1905,Aqua,MODIS,79,6.03,290,8.5,D,1",   # volcano -> dropped
         ],
         nrt_rows=[
             "30.4,-100.4,310,1,1,2020-01-04,0500,Terra,MODIS,90,6.1NRT,290,9.5,N",   # after archive end
             "30.0,-100.0,310,1,1,2020-01-01,0100,Terra,MODIS,90,6.1NRT,290,9.5,N",   # overlaps archive
         ])
    _zip(raw / "DL_FIRE_SV-C2_2.zip",
         archive_rows=[
             "31.0,-99.0,330,0.4,0.4,2020-01-01,0815,SNPP,VIIRS,l,2,290,1.0,N,0",
             "31.1,-99.1,330,0.4,0.4,2020-01-02,2010,SNPP,VIIRS,n,2,290,2.0,D,0",
             "31.2,-99.2,330,0.4,0.4,2020-01-03,2010,SNPP,VIIRS,h,2,290,3.0,D,3",   # offshore -> dropped
         ],
         nrt_rows=[
             "31.3,-99.3,330,0.4,0.4,2020-01-05,0815,N20,VIIRS,h,2.0NRT,290,4.0,N",
             "30.2051,-100.2049,330,0.4,0.4,2020-01-05,0815,SNPP,VIIRS,n,2.0NRT,290,5.0,N",  # static cell
         ])
    out = tmp_path / "processed"
    stats = ingest.ingest_region("texas", raw_dir=tmp_path / "raw", out_dir=out)
    return out, stats


def _read(out: Path, sensor: str) -> pd.DataFrame:
    return pq.read_table(out / f"fires_texas_{sensor}.parquet").to_pandas()


def test_modis_confidence_boundaries():
    raw = pd.Series(["0", "29", "30", "79", "80", "100"], dtype="string")
    assert ingest.map_confidence(raw, "modis").tolist() == ["low", "low", "nominal", "nominal", "high", "high"]


def test_viirs_confidence_letters():
    raw = pd.Series(["l", "n", "h", " H "], dtype="string")
    assert ingest.map_confidence(raw, "viirs").tolist() == ["low", "nominal", "high", "high"]


def test_datetime_parses_short_acq_time_as_utc():
    dt = ingest.parse_datetime(pd.Series(["2020-01-01"], dtype="string"), pd.Series(["130"], dtype="string"))
    assert dt.iloc[0] == pd.Timestamp("2020-01-01 01:30", tz="UTC")


def test_unknown_satellite_code_raises():
    with pytest.raises(ValueError):
        ingest.map_satellite(pd.Series(["XYZ"], dtype="string"))


def test_output_schema_is_identical_for_modis_and_viirs(region_out):
    out, _ = region_out
    for sensor in ("modis", "viirs"):
        schema = pq.read_schema(out / f"fires_texas_{sensor}.parquet")
        assert schema.remove_metadata().equals(ingest.SCHEMA), sensor


def test_type_filter_keeps_only_vegetation_fires(region_out):
    out, stats = region_out
    modis, viirs = _read(out, "modis"), _read(out, "viirs")
    assert sorted(modis[~modis["is_provisional"]]["frp"].round(1)) == [5.5, 6.5]  # type 1, 2 removed
    assert sorted(viirs[~viirs["is_provisional"]]["frp"].round(1)) == [1.0, 2.0]  # type 3 removed
    assert stats.type_counts[("modis", 2)] == 1 and stats.type_counts[("viirs", 3)] == 1


def test_nrt_overlap_and_static_cells_dropped(region_out):
    out, stats = region_out
    modis, viirs = _read(out, "modis"), _read(out, "viirs")
    assert modis[modis["is_provisional"]]["frp"].round(1).tolist() == [9.5]  # overlap row dropped
    assert viirs[viirs["is_provisional"]]["satellite"].tolist() == ["NOAA-20"]  # static-cell row dropped
    assert stats.nrt_dropped_overlap["Terra"] == 1
    assert stats.nrt_dropped_static["S-NPP"] == 1


def test_values_are_mapped(region_out):
    out, _ = region_out
    modis, viirs = _read(out, "modis"), _read(out, "viirs")
    assert set(modis["satellite"]) == {"Terra", "Aqua"} and set(modis["sensor"]) == {"MODIS"}
    assert set(viirs["satellite"]) == {"S-NPP", "NOAA-20"} and set(viirs["sensor"]) == {"VIIRS"}
    first = modis.sort_values("datetime_utc").iloc[0]
    assert first["confidence_class"] == "low" and first["confidence_raw"] == "29"
    assert first["daynight"] == "N" and str(first["acq_date"]) == "2020-01-01"


def test_no_nulls_in_key_columns(region_out):
    out, _ = region_out
    for sensor in ("modis", "viirs"):
        df = _read(out, sensor)
        assert not df[ingest.KEY_COLUMNS + ["frp"]].isna().any().any(), sensor


def test_missing_archive_csv_raises(tmp_path):
    raw = tmp_path / "raw" / "texas"
    raw.mkdir(parents=True)
    with zipfile.ZipFile(raw / "DL_FIRE_M-C61_9.zip", "w") as zf:
        zf.writestr("Readme.txt", "nothing here")
    with pytest.raises(FileNotFoundError):
        ingest.ingest_region("texas", raw_dir=tmp_path / "raw", out_dir=tmp_path / "out")


REAL_FILES = sorted(Path("data/processed").glob("fires_*_*.parquet"))


@pytest.mark.skipif(not REAL_FILES, reason="run `python -m pipeline.ingest` first")
@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_real_output_schema_and_no_nulls(path):
    assert pq.read_schema(path).remove_metadata().equals(ingest.SCHEMA)
    t = pq.read_table(path, columns=ingest.KEY_COLUMNS + ["frp"])
    assert all(t.column(c).null_count == 0 for c in t.column_names)
