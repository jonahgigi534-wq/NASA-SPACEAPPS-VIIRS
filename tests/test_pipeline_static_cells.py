"""Static heat-source cells: the selection rule, and that pipeline/live.py drops live detections
on the shipped list (results/static_cells.csv, which deploy_space.py uploads)."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from pipeline import live
from pipeline.static_cells import cell_id, select_static

SHIPPED = Path("results/static_cells.csv")


def test_select_static_needs_share_and_count():
    counts = pd.DataFrame({"cell_id": [1, 2, 3, 4],
                           "static_n": [50, 50, 5, 0],
                           "fire_n": [10, 200, 0, 99]})
    # 1: mostly static -> kept; 2: mostly fire -> kept out; 3: too few; 4: no static
    assert select_static(counts)["cell_id"].tolist() == [1]


def test_cell_id_matches_live():
    lat, lon = pd.Series([31.84, -12.3]), pd.Series([-102.37, 131.05])
    assert cell_id(lat.to_numpy(), lon.to_numpy()).tolist() == live.cell_id(lat, lon).tolist()


@pytest.mark.skipif(not SHIPPED.exists(), reason="run python -m pipeline.static_cells")
def test_live_drops_points_on_static_cells():
    static = live.static_cells("texas")
    assert static, "results/static_cells.csv has no texas cells"
    flare = next(iter(static))
    flat, flon = (flare // 3600) / 10 - 90, (flare % 3600) / 10 - 180
    d = date(2026, 11, 1)
    points = pd.DataFrame({
        "lat": [flat, 30.0], "lon": [flon, -100.0], "sensor": ["VIIRS", "VIIRS"],
        "satellite": ["NOAA-20", "NOAA-20"], "frp": [5.0, 7.0], "date": [d, d],
    })
    factors = {"month": {}, "all": (1.0, 1.0)}
    cells, kept, _ = live.build_region("texas", points, factors, [d])
    assert flare not in set(kept["cell_id"]) and flare not in set(cells["cell_id"])
    assert len(kept) == 1
