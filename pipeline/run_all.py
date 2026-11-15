"""Run the whole Track A pipeline in order (raw FIRMS zips -> data/app/ + results/).

  python -m pipeline.run_all                  # every step
  python -m pipeline.run_all --from harmonize # that step and everything after it
  python -m pipeline.run_all --only app       # one step
  python -m pipeline.run_all --list           # show the steps
  python -m pipeline.run_all --sizes          # only report data/app file sizes

Each step runs as its own `python -m ...` process (memory is freed between steps) and the run
stops at the first step that fails. The Makefile targets call this script.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path("data/app")

# (name, module args, what it makes)
STEPS = [
    ("ingest", ["pipeline.ingest"], "data/processed/fires_<region>_<sensor>.parquet"),
    ("static", ["pipeline.static_cells"], "results/static_cells.csv (flare cells live.py drops)"),
    ("grid", ["pipeline.grid"], "grids + missing-data mask (data/processed/)"),
    ("overpass", ["pipeline.overpass"], "results/figures/overpass_times.png"),
    ("landcover", ["pipeline.landcover"], "data/processed/landcover_<region>.parquet"),
    ("harmonize", ["pipeline.harmonize"], "data/processed/harmonize_models.json"),
    ("validate", ["pipeline.validate"], "results/metrics.json + scatter/bias figures"),
    ("app", ["pipeline.build_app_data"], "data/app/ (CONTRACTS.md section 2)"),
    ("robustness", ["pipeline.robustness"], "metrics.json: leave_one_region_out + drift_vs_modis"),
    ("continuity", ["pipeline.validate", "--continuity"], "results/figures/continuity_<region>.png"),
    ("presets", ["pipeline.presets"], "docs/presets.json (biggest anomalies)"),
]
NAMES = [s[0] for s in STEPS]


def select(start: str | None, only: str | None) -> list[tuple]:
    if only:
        return [s for s in STEPS if s[0] == only]
    first = NAMES.index(start) if start else 0
    return STEPS[first:]


def run_step(name: str, args: list[str]) -> None:
    print(f"\n=== {name}: python -m {' '.join(args)}", flush=True)
    t0 = time.time()
    result = subprocess.run([sys.executable, "-m", *args])
    if result.returncode != 0:
        raise SystemExit(f"step '{name}' failed (exit {result.returncode}); fix it, then "
                         f"rerun with --from {name}")
    print(f"=== {name} done in {time.time() - t0:.0f} s", flush=True)


def report_sizes(app_dir: Path = APP_DIR) -> int:
    files = sorted(p for p in app_dir.glob("*") if p.is_file()) if app_dir.exists() else []
    if not files:
        print(f"{app_dir}/ is empty: run the 'app' step first")
        return 0
    total = 0
    print(f"\n{app_dir}/ file sizes")
    for f in files:
        size = f.stat().st_size
        total += size
        print(f"  {f.name:26s} {size / 1e6:9.1f} MB")
    print(f"  {'TOTAL':26s} {total / 1e6:9.1f} MB")
    return total


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run the Track A pipeline")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--from", dest="start", choices=NAMES, help="start at this step")
    group.add_argument("--only", choices=NAMES, help="run just this step")
    group.add_argument("--list", action="store_true", help="list the steps and exit")
    group.add_argument("--sizes", action="store_true", help="only report data/app sizes")
    args = ap.parse_args(argv)
    if args.list:
        for name, mod, makes in STEPS:
            print(f"  {name:11s} python -m {' '.join(mod):38s} -> {makes}")
        return
    if not args.sizes:
        for name, mod, _ in select(args.start, args.only):
            run_step(name, mod)
    report_sizes()


if __name__ == "__main__":
    main()
