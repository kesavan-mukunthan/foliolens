"""Single read seam for NAV parquet data.

All parquet reads go through this module — no other module opens parquet paths directly.
Path root is local (data/raw/) for step 0; swap to gs:// at step 4.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import duckdb
import pyarrow as pa

from .model.value_objects import NavSeries


class DataAccess:
    """Read NAV series from decimal128 parquet via DuckDB.

    raw_root: directory containing the consolidated nav.parquet
              (amfi_code as an ordinary column, sorted by (amfi_code, date)).
    """

    def __init__(self, raw_root: Path | str) -> None:
        self._root = Path(raw_root)
        self._con: Any = duckdb.connect()

    @property
    def _nav_path(self) -> str:
        return str(self._root / "nav.parquet")

    def load_nav_series(self, amfi_code: str) -> NavSeries:
        """Return the full daily NAV series for one fund from parquet.

        The per-fund figure-of-record read. Reads decimal128 directly; no SQL
        arithmetic that would cast to DOUBLE.
        Raises ValueError if no data is found for amfi_code.
        """
        rows: list[Any] = self._con.execute(
            "SELECT date, nav FROM read_parquet(?) WHERE amfi_code = ? ORDER BY date",
            [self._nav_path, amfi_code],
        ).fetchall()

        if not rows:
            raise ValueError(f"no NAV data for amfi_code={amfi_code!r}")

        pairs: list[tuple[date, Decimal]] = []
        for row in rows:
            d = cast(date, row[0])
            nav = Decimal(str(row[1]))
            pairs.append((d, nav))

        return NavSeries(amfi_code=amfi_code, data=tuple(pairs))

    def load_nav_panel(self, amfi_codes: Sequence[str] | None = None) -> pa.Table:
        """Return (amfi_code, date, nav) for many funds as an Arrow table.

        The path-of-scale bulk read for panel materialisation; per-fund figures
        of record go through load_nav_series. Filtering and ordering happen
        inside DuckDB (no fetchall + Python row loop); nav stays decimal128 in
        the Arrow schema — never cast to DOUBLE.

        amfi_codes=None reads all funds; a sequence reads only those codes.
        """
        if amfi_codes is None:
            result = self._con.execute(
                "SELECT amfi_code, date, nav FROM read_parquet(?) "
                "ORDER BY amfi_code, date",
                [self._nav_path],
            )
        else:
            codes = list(amfi_codes)
            if not codes:
                result = self._con.execute(
                    "SELECT amfi_code, date, nav FROM read_parquet(?) "
                    "WHERE 1 = 0",
                    [self._nav_path],
                )
            else:
                placeholders = ", ".join("?" for _ in codes)
                result = self._con.execute(
                    "SELECT amfi_code, date, nav FROM read_parquet(?) "
                    f"WHERE amfi_code IN ({placeholders}) "
                    "ORDER BY amfi_code, date",
                    [self._nav_path, *codes],
                )

        return cast("pa.Table", result.to_arrow_table())
