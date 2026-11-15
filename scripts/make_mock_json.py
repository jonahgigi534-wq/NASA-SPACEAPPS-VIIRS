"""
Regenerate app/static/mock/ (the sample responses used by the website's ?mock=1 mode) from the
real API, for the first preset in docs/presets.json. Run from the repo root after API changes:

    python scripts/make_mock_json.py                 # uses APP_DATA_DIR or data/app
"""

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT = REPO / "app" / "static" / "mock"


def main():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    OUT.mkdir(parents=True, exist_ok=True)
    p = json.loads((REPO / "docs" / "presets.json").read_text(encoding="utf-8"))[0]
    b = {"area": {"type": "bbox", "bbox": p["bbox"]}, "start": p["start"], "end": p["end"],
         "baseline": [2003, 2022], "mode": "harmonized", "metric": "count"}
    reg = c.get("/api/regions").json()
    start = min(r["start"] for r in reg["regions"])
    end = max(r["live_end"] for r in reg["regions"])
    month = p["start"][:7]

    def save(name, data):
        (OUT / name).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    def ok(r):
        assert r.status_code == 200, r.text
        return r

    save("regions.json", reg)
    shutil.copy(REPO / "docs" / "presets.json", OUT / "presets.json")
    save("summary.json", ok(c.post("/api/summary", json=b)).json())
    save("calendar.json", ok(c.post("/api/calendar", json={**b, "start": start, "end": end, "granularity": "month"})).json())
    save("calendar_week.json", ok(c.post("/api/calendar", json={**b, "start": start, "end": end, "granularity": "week"})).json())
    save("calendar_day.json", ok(c.post("/api/calendar", json={**b, "start": f"{month}-01", "end": f"{month}-30", "granularity": "day"})).json())
    save("patterns.json", ok(c.post("/api/patterns", json=b)).json())
    save("current.json", ok(c.post("/api/current", json=b)).json())
    save("timeseries.json", ok(c.post("/api/timeseries", json=b)).json())
    save("cells.json", ok(c.post("/api/cells", json=b)).json())
    (OUT / "series.csv").write_text(ok(c.post("/api/export/series.csv", json={**b, "granularity": "day"})).text,
                                    encoding="utf-8", newline="")
    few = {**b, "start": p["start"], "end": p["start"]}
    lines = ok(c.post("/api/export/hotspots.csv", json=few)).text.split("\n")
    (OUT / "hotspots.csv").write_text("\n".join(lines[:201]) + "\n# Sample: first 200 rows only.\n",
                                      encoding="utf-8", newline="")
    gj = ok(c.post("/api/export/hotspots.geojson", json=few)).json()
    gj["features"] = gj["features"][:200]
    gj["note"] = "Sample: first 200 hotspots only."
    save("hotspots.geojson", gj)
    (OUT / "hotspots.kml").write_text(ok(c.post("/api/export/hotspots.kml", json=few)).text, encoding="utf-8")
    print(f"Wrote {len(list(OUT.iterdir()))} sample files to {OUT}")


if __name__ == "__main__":
    main()
