"""Published-return reconciliation: engine output vs AMC factsheet figures.

Rides the production pipeline (raw fixture NAV → ``share_class_from_nav`` →
``period_return``) and checks every published row lands within the fixed 10 bps
tolerance. Runs in the standard suite and the CI gate — no skip marker: a
mismatch must surface, never be silenced.

Three checks:
  - parametrised: every non-exempt, computable row must not be a MISMATCH;
  - aggregate: status counts, with a hard assertion of zero mismatch;
  - meta: every exemption corresponds to a live published row and carries a
    non-empty reason (a dead exemption fails).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foliolens.data_access import DataAccess
from foliolens.validation.reconcile import (
    PUBLISHED_TOLERANCE_BPS,
    Status,
    format_table,
    load_exemptions,
    load_published_returns,
    reconcile,
    status_counts,
)

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

# Reconcile once at collection time so the parametrised leg can index per row.
# No network here (frozen parquet only); the conftest network guard is per-test.
_PUBLISHED = load_published_returns(_FIXTURES / "published_returns.csv")
_EXEMPTIONS = load_exemptions(_FIXTURES / "reconciliation_exemptions.csv")
_ROWS = reconcile(
    DataAccess(_FIXTURES / "nav_snapshots"), _PUBLISHED, _EXEMPTIONS
)
_ROWS_BY_KEY = {(r.amfi_code, r.period, r.as_of): r for r in _ROWS}


@pytest.mark.parametrize(
    "pub", _PUBLISHED, ids=[f"{p.amfi_code}-{p.period}" for p in _PUBLISHED]
)
def test_published_row_matches(pub) -> None:
    """Every non-exempt, computable published row must land within tolerance.

    MATCH passes; UNCOMPUTABLE and EXEMPT are acceptable non-outcomes; only a
    MISMATCH fails — loud, with fund / period / delta.
    """
    row = _ROWS_BY_KEY[(pub.amfi_code, pub.period, pub.as_of)]
    assert row.status is not Status.MISMATCH, (
        f"{row.amfi_code} {row.period} @ {row.as_of.isoformat()}: "
        f"computed={row.computed_pct} published={row.published_pct} "
        f"diff={row.diff_bps} bps (tolerance {PUBLISHED_TOLERANCE_BPS} bps)"
    )


def test_zero_mismatch(data_access, published_returns, exemptions) -> None:
    """Aggregate: report status counts, assert zero mismatch.

    On failure the full reconciliation table is printed so the mismatching
    rows are visible without re-running anything.
    """
    rows = reconcile(data_access, published_returns, exemptions)
    counts = status_counts(rows)
    assert counts[Status.MISMATCH] == 0, (
        "reconciliation mismatches present — engine unchanged, awaiting "
        "human adjudication (finding, not a fix):\n" + format_table(rows)
    )


def test_exemptions_are_live_and_reasoned(published_returns, exemptions) -> None:
    """Every exemption must point at a real published row and carry a reason.

    A dead exemption (no matching published row) or a blank reason fails — the
    exemption list stays honest reviewable data, never accumulating cruft.
    """
    published_keys = {
        (p.amfi_code, p.period, p.as_of) for p in published_returns
    }
    for e in exemptions:
        assert (e.amfi_code, e.window, e.as_of) in published_keys, (
            f"dead exemption: {e.amfi_code} {e.window} @ {e.as_of.isoformat()} "
            "matches no published row"
        )
        assert e.reason.strip(), (
            f"exemption {e.amfi_code} {e.window} @ {e.as_of.isoformat()} "
            "carries no reason"
        )
