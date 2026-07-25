"""Fund→benchmark mapping — the hand-curated half of the metadata surface.

No machine-readable fund→benchmark source exists (AMC SIDs/factsheets only), so
``fixtures/benchmark_map.csv`` is hand-built per cohort (flexicap first). Columns:
``amfi_code, benchmark_code, tier`` with ``tier ∈ {tier1, alternate}`` — the
SEBI two-tier mandate. A scheme may carry both a tier-1 and an alternate row;
duplicate ``(amfi_code, tier)`` is rejected (fail loud).

This is a separate artifact from the machine-derived ``scheme_master.parquet``
(distinct provenance, update mechanics, audit trail). Consumers never read this
file directly — ``data_access.load_scheme_master`` joins the two and exposes the
result as one read.

Beyond each fund's *stated* benchmark, the flexicap page (spec-flexicap-page §1)
computes all cross-sectional relative metrics against a single **category
yardstick** so ranks are comparable — NIFTY500TRI for ``flexi_cap``. The
yardstick is a category constant, not a per-fund curation, so it lives here as
``CATEGORY_YARDSTICK`` rather than as rows in the CSV.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

TIER1 = "tier1"
ALTERNATE = "alternate"
VALID_TIERS = frozenset({TIER1, ALTERNATE})

_EXPECTED_HEADER = ("amfi_code", "benchmark_code", "tier")

# Category-level yardstick for cross-sectional comparability (spec-flexicap-page
# §1): every fund in a category is ranked against the same index regardless of
# its stated benchmark. Keyed by ``sebi_category``.
CATEGORY_YARDSTICK: dict[str, str] = {
    "flexi_cap": "NIFTY500TRI",
}

# Repo-root fixture: src/foliolens/benchmark_map.py -> src/foliolens -> src -> root.
DEFAULT_BENCHMARK_MAP = (
    Path(__file__).resolve().parents[2] / "fixtures" / "benchmark_map.csv"
)


@dataclass(frozen=True)
class BenchmarkMapRow:
    amfi_code: str
    benchmark_code: str
    tier: str


def load_benchmark_map(
    path: Path | str = DEFAULT_BENCHMARK_MAP,
) -> tuple[BenchmarkMapRow, ...]:
    """Parse and validate the fund→benchmark mapping fixture.

    Blank lines and ``#`` comment lines are skipped (the file is hand-audited).
    Fails loud on: a header that is not ``amfi_code,benchmark_code,tier``; an
    unknown tier; a blank amfi_code/benchmark_code; or a duplicate
    ``(amfi_code, tier)`` pair.
    """
    rows: list[BenchmarkMapRow] = []
    seen: set[tuple[str, str]] = set()
    with Path(path).open(newline="", encoding="utf-8") as fh:
        lines = [
            ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")
        ]
    reader = csv.reader(lines)
    header = next(reader, None)
    if header is None:
        raise ValueError(f"benchmark_map: empty file {path}")
    if tuple(h.strip() for h in header) != _EXPECTED_HEADER:
        raise ValueError(
            f"benchmark_map: header must be {_EXPECTED_HEADER}; saw {header}"
        )
    for raw in reader:
        if len(raw) != 3:
            raise ValueError(f"benchmark_map: malformed row {raw!r}")
        amfi_code, benchmark_code, tier = (c.strip() for c in raw)
        if not amfi_code or not benchmark_code:
            raise ValueError(f"benchmark_map: blank field in row {raw!r}")
        if tier not in VALID_TIERS:
            raise ValueError(
                f"benchmark_map: tier {tier!r} not in {sorted(VALID_TIERS)} "
                f"(amfi_code={amfi_code})"
            )
        key = (amfi_code, tier)
        if key in seen:
            raise ValueError(
                f"benchmark_map: duplicate (amfi_code, tier) {key}"
            )
        seen.add(key)
        rows.append(BenchmarkMapRow(amfi_code, benchmark_code, tier))
    return tuple(rows)
