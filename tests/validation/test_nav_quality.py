"""Data-quality invariant on the frozen NAV fixture: no single-step jump > 50%.

A single-session NAV move above 50% is not a real fund return — it is a splice
between two different underlying series stitched under one AMFI code. This guard
was discovered by the published-return reconciliation (FL-DQ-1): fund 103340
carries pre-Nov-2009 history belonging to a different scheme/plan, producing a
+900% step on 2009-11-02 that corrupts its since-inception return.

Making it a parametrised invariant converts a one-off exemption note into a
standing check over the whole fixture universe. 103340 is marked
``xfail(strict=True)`` on FL-DQ-1: it is a known, tracked defect today, so the
day its history is truncated or re-sourced this row xpasses — and strict xfail
turns an unexpected pass into a failure, forcing the guard back to green and the
exemption to be retired. The invariant can never silently regress.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from foliolens.data_access import DataAccess

#: A single-step NAV move above this is a data splice, not a return.
MAX_SINGLE_STEP = Decimal("0.50")

#: Known data-quality defect: pre-Nov-2009 103340 history is a foreign scheme.
_FL_DQ_1 = pytest.mark.xfail(
    strict=True,
    reason=(
        "FL-DQ-1: pre-Nov-2009 103340 history belongs to a different "
        "scheme/plan (+900% step 2009-11-02); truncate/re-source at ingestion, "
        "then this xpasses and the guard goes green"
    ),
)

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

# Every fund present in the frozen parquet (collection-time; no network).
_ALL_CODES = sorted(
    set(
        DataAccess(_FIXTURES / "nav_snapshots")
        .load_nav_panel()
        .column("amfi_code")
        .to_pylist()
    )
)


def _params() -> list:
    return [
        pytest.param(code, marks=[_FL_DQ_1] if code == "103340" else [])
        for code in _ALL_CODES
    ]


@pytest.mark.parametrize("amfi_code", _params())
def test_no_nav_step_exceeds_50pct(data_access, amfi_code: str) -> None:
    """No consecutive-NAV ratio in a fund's series may move more than 50%."""
    nav = data_access.load_nav_series(amfi_code)
    worst_step = Decimal(0)
    worst_from: tuple[object, Decimal] | None = None
    worst_to: tuple[object, Decimal] | None = None
    for (prev_date, prev_nav), (curr_date, curr_nav) in zip(nav.data, nav.data[1:]):
        if prev_nav == 0:
            continue
        step = abs(curr_nav / prev_nav - Decimal(1))
        if step > worst_step:
            worst_step = step
            worst_from = (prev_date, prev_nav)
            worst_to = (curr_date, curr_nav)

    assert worst_step <= MAX_SINGLE_STEP, (
        f"{amfi_code}: single-step NAV move {worst_step:.1%} "
        f"({worst_from} -> {worst_to}) exceeds {MAX_SINGLE_STEP:.0%}"
    )
