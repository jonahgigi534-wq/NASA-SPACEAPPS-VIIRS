"""docs/presets.json shape (Track C's preset buttons) and docs/methods_text.md numbers vs
results/metrics.json (the Methods page may only quote numbers that are in metrics.json)."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from pipeline.build_app_data import region_bboxes

PRESETS = Path("docs/presets.json")
METHODS = Path("docs/methods_text.md")
METRICS = Path("results/metrics.json")


@pytest.mark.skipif(not PRESETS.exists(), reason="run python -m pipeline.presets")
def test_presets_shape():
    presets = json.loads(PRESETS.read_text(encoding="utf-8"))
    boxes = region_bboxes()
    assert len(presets) == 4
    for p in presets:
        assert list(p) == ["name", "region", "bbox", "start", "end", "why"]
        w, s, e, n = p["bbox"]
        rw, rs, re_, rn = boxes[p["region"]]
        assert rw <= w < e <= re_ and rs <= s < n <= rn, p["name"]
        assert date.fromisoformat(p["start"]) <= date.fromisoformat(p["end"])
        assert "% of the 2003-2022 median" in p["why"]


def _metric_numbers(m: dict) -> set[str]:
    """Every metric value as the Methods text may print it (exact, or rounded with commas)."""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            out.update({f"{x}", f"{abs(x)}", f"{abs(x):,.0f}", f"{abs(x):.2f}"})
    walk(m)
    for note in m["notes"]:
        out.update(re.findall(r"\d+\.\d+", note))
    return out


@pytest.mark.skipif(not (METHODS.exists() and METRICS.exists()), reason="docs not written")
def test_methods_numbers_come_from_metrics():
    text = METHODS.read_text(encoding="utf-8")
    results = text[text.index("## Results"):text.index("## Data sources")]
    limits = text[text.index("## Honest limitations"):text.index("## Use of AI")]
    allowed = _metric_numbers(json.loads(METRICS.read_text()))
    # numbers with a decimal point or a thousands comma are measurements: each must be in metrics
    for section in (results, limits):
        for num in re.findall(r"\d{1,3}(?:,\d{3})+|\d+\.\d+", section):
            assert num in allowed, f"methods_text.md quotes {num}, not found in metrics.json"
