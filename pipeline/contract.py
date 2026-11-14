"""Read the app-file schemas straight from docs/CONTRACTS.md section 2, so tests check the
built files against the contract itself (not a hand-copied list that can drift)."""
from __future__ import annotations

import re
from pathlib import Path

import pyarrow as pa

CONTRACTS_MD = Path(__file__).resolve().parents[1] / "docs" / "CONTRACTS.md"
APP_FILES = ("cells_daily", "missing_days", "hotspots")
COVERAGE_KEYS = ("start", "archive_end", "nrt_end", "live_end", "bbox")

# contract type word -> arrow type as written by DuckDB/pyarrow
ARROW = {"string": pa.string(), "int32": pa.int32(), "float32": pa.float32(),
         "float64": pa.float64(), "date": pa.date32(), "bool": pa.bool_(),
         "timestamp": pa.timestamp("us")}

_HEADING = re.compile(r"^### `data/app/(\w+)\.parquet`")
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([a-z0-9]+)")


def _section2(text: str) -> list[str]:
    start = text.index("## 2.")
    end = text.index("\n## 3.", start)
    return text[start:end].splitlines()


def parse_contract(path: Path = CONTRACTS_MD) -> dict[str, list[tuple[str, pa.DataType]]]:
    """{file name: [(column, arrow type), ...]} in contract order."""
    out: dict[str, list[tuple[str, pa.DataType]]] = {}
    current = None
    for line in _section2(path.read_text(encoding="utf-8")):
        head = _HEADING.match(line)
        if head:
            current = out.setdefault(head.group(1), [])
            continue
        row = _ROW.match(line)
        if current is None or not row or row.group(1) in ("column", "---"):
            continue
        names, word = row.group(1), row.group(2)
        if word not in ARROW:
            raise ValueError(f"CONTRACTS.md: unknown type {word!r} for {names!r}")
        current.extend((n.strip(), ARROW[word]) for n in names.split(","))
    missing = set(APP_FILES) - set(out)
    if missing:
        raise ValueError(f"CONTRACTS.md section 2 has no table for {sorted(missing)}")
    return out
