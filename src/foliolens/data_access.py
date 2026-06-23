"""Single read seam for NAV parquet data.

All parquet reads go through this module — no other module opens parquet paths directly.
Path root is local (data/raw/) for step 0; swap to gs:// at step 4.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import duckdb

from .model.value_objects import NavSeries


class DataAccess:
    """Read NAV series from decimal128 parquet via DuckDB.

    raw_root: directory containing Hive-partitioned parquet
              (amfi_code=<code>/data.parquet).
    """

    def __init__(self, raw_root: Path | str) -> None:
        self._root = Path(raw_root)
        self._con: Any = duckdb.connect()

    def load_nav_series(self, amfi_code: str) -> NavSeries:
        """Return the full daily NAV series for one fund from parquet.

        Reads decimal128 directly; no SQL arithmetic that would cast to DOUBLE.
        Raises ValueError if no data is found for amfi_code.
        """
        pattern = str(self._root / f"amfi_code={amfi_code}" / "*.parquet")
        rows: list[Any] = self._con.execute(
            "SELECT date, nav FROM read_parquet(?) ORDER BY date",
            [pattern],
        ).fetchall()

        if not rows:
            raise ValueError(f"no NAV data for amfi_code={amfi_code!r}")

        pairs: list[tuple[date, Decimal]] = []
        for row in rows:
            d = cast(date, row[0])
            nav = Decimal(str(row[1]))
            pairs.append((d, nav))

        return NavSeries(amfi_code=amfi_code, data=tuple(pairs))
