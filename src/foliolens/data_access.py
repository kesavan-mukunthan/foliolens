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

from .benchmark_map import (
    ALTERNATE,
    CATEGORY_YARDSTICK,
    DEFAULT_BENCHMARK_MAP,
    TIER1,
    load_benchmark_map,
)
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

    @property
    def _index_path(self) -> str:
        return str(self._root / "index_nav.parquet")

    @property
    def _scheme_master_path(self) -> str:
        return str(self._root / "scheme_master.parquet")

    def load_scheme_master(
        self, benchmark_map_path: Path | str = DEFAULT_BENCHMARK_MAP
    ) -> pa.Table:
        """Return the canonical fund-metadata surface: scheme_master ⟕ benchmark_map.

        The machine-derived ``scheme_master.parquet`` and the hand-curated
        ``benchmark_map.csv`` are stored separately (distinct provenance); this
        read is the only place they meet. Consumers never see the two files.

        Adds four columns to scheme_master:
        - ``benchmark_code`` — the fund's stated benchmark, tier-1 preferred
          (falls back to the alternate if only that is curated). NULL = mapping
          not yet curated (never a silently-defaulted benchmark).
        - ``benchmark_tier`` — which tier ``benchmark_code`` came from
          (``tier1``/``alternate``); NULL when uncurated.
        - ``benchmark_alternate`` — the alternate stated benchmark code, if
          curated (supports the flexicap page's tier-fallback render rule); else
          NULL.
        - ``category_yardstick`` — the category-level comparison index
          (NIFTY500TRI for ``flexi_cap``); every row in a mapped category
          resolves to it regardless of its stated benchmark (spec-flexicap-page
          §1). NULL for categories without a yardstick.
        """
        master = cast(
            "pa.Table",
            self._con.execute(
                "SELECT * FROM read_parquet(?) ORDER BY amfi_code",
                [self._scheme_master_path],
            ).to_arrow_table(),
        )

        # Collapse the (possibly two-tier) benchmark_map to one entry per fund.
        by_code: dict[str, dict[str, str]] = {}
        for row in load_benchmark_map(benchmark_map_path):
            by_code.setdefault(row.amfi_code, {})[row.tier] = row.benchmark_code

        codes = master.column("amfi_code").to_pylist()
        categories = master.column("sebi_category").to_pylist()
        benchmark_code: list[str | None] = []
        benchmark_tier: list[str | None] = []
        benchmark_alternate: list[str | None] = []
        category_yardstick: list[str | None] = []
        for code, category in zip(codes, categories):
            tiers = by_code.get(code, {})
            if TIER1 in tiers:
                benchmark_code.append(tiers[TIER1])
                benchmark_tier.append(TIER1)
            elif ALTERNATE in tiers:
                benchmark_code.append(tiers[ALTERNATE])
                benchmark_tier.append(ALTERNATE)
            else:
                benchmark_code.append(None)
                benchmark_tier.append(None)
            benchmark_alternate.append(tiers.get(ALTERNATE))
            category_yardstick.append(CATEGORY_YARDSTICK.get(category))

        return (
            master.append_column(
                "benchmark_code", pa.array(benchmark_code, type=pa.string())
            )
            .append_column(
                "benchmark_tier", pa.array(benchmark_tier, type=pa.string())
            )
            .append_column(
                "benchmark_alternate",
                pa.array(benchmark_alternate, type=pa.string()),
            )
            .append_column(
                "category_yardstick",
                pa.array(category_yardstick, type=pa.string()),
            )
        )

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

    def load_index_series(self, index_code: str) -> NavSeries:
        """Return the full daily level series for one benchmark index as a NavSeries.

        NavSeries is reused for index levels (the identifier field carries
        ``index_code``); ``.month_end()`` and ``to_returns`` apply unchanged.
        Reads decimal128 directly; no SQL arithmetic that would cast to DOUBLE.
        Raises ValueError if no data is found for index_code.
        """
        rows: list[Any] = self._con.execute(
            "SELECT date, level FROM read_parquet(?) WHERE index_code = ? ORDER BY date",
            [self._index_path, index_code],
        ).fetchall()

        if not rows:
            raise ValueError(f"no index data for index_code={index_code!r}")

        pairs: list[tuple[date, Decimal]] = []
        for row in rows:
            d = cast(date, row[0])
            level = Decimal(str(row[1]))
            pairs.append((d, level))

        return NavSeries(amfi_code=index_code, data=tuple(pairs))

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
