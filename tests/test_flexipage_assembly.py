"""B2 effective-n disclosure — the per-fund ``windows`` block
(``report/flexipage/assembly.py``'s ``_window_disclosure`` / ``build_fund_panel``).

Covers the acceptance surface directly against the assembly layer (not through
the full runner — see ``test_flexipage_runner.py`` for the end-to-end
``metrics.json`` shape, and its own B1 section for why the runner-level path
is exercised separately): for a full/complete window, ``n_overlap_rf`` equals
``n_months`` (Phase A's alignment fix, restated as an ongoing invariant); for
a window whose rf/benchmark panel doesn't fully cover the fund's window, the
disclosed overlap is the reduced count actually available.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from foliolens.ingest.iima import RfExtension
from foliolens.model.investments import SeriesInvestment
from foliolens.report.flexipage.assembly import (
    _window_disclosure,
    _window_refused,
    build_fund_panel,
    build_rf_disclosure,
)
from foliolens.returns.frequency import Frequency
from fixtures import daily_shareclass, returns_series


def _series_investment(rs, id: str) -> SeriesInvestment:  # noqa: A002
    return SeriesInvestment(id=id, returns_series=rs)


# ---------------------------------------------------------------------------
# _window_disclosure — direct unit coverage
# ---------------------------------------------------------------------------


def test_full_overlap_n_overlap_rf_equals_n_months() -> None:
    fund_rs = returns_series(np.full(60, 0.01))
    rf_rs = returns_series(np.full(60, 0.003))
    yardstick_rs = returns_series(np.full(60, 0.008))
    as_of = fund_rs.dates[-1]

    disclosure = _window_disclosure(
        fund_rs, rf_rs, yardstick_rs, 12, as_of, label="1Y", refused_by_metric={}
    )
    assert disclosure["n_months"] == 12
    assert disclosure["n_overlap_rf"] == 12
    assert disclosure["n_overlap_benchmark"] == 12
    assert disclosure["refused"] == {}


def test_truncated_rf_reports_the_reduced_overlap_it_actually_has() -> None:
    fund_rs = returns_series(np.full(60, 0.01))
    as_of = fund_rs.dates[-1]
    # rf only covers the last 6 months of the fund's trailing 12M window —
    # the fund's own window is still fully 12 months long.
    rf_rs = returns_series(np.full(6, 0.003), start_year=fund_rs.dates[-6].year,
                            start_month=fund_rs.dates[-6].month)
    yardstick_rs = returns_series(np.full(60, 0.008))

    disclosure = _window_disclosure(
        fund_rs, rf_rs, yardstick_rs, 12, as_of, label="1Y", refused_by_metric={}
    )
    assert disclosure["n_months"] == 12
    assert disclosure["n_overlap_rf"] == 6
    assert disclosure["n_overlap_benchmark"] == 12


def test_window_absent_reports_zero_counts_not_null() -> None:
    # Only 6 months of fund history -> the 12M window doesn't exist.
    fund_rs = returns_series(np.full(6, 0.01))
    rf_rs = returns_series(np.full(6, 0.003))
    yardstick_rs = returns_series(np.full(6, 0.008))
    as_of = fund_rs.dates[-1]

    disclosure = _window_disclosure(
        fund_rs, rf_rs, yardstick_rs, 12, as_of, label="1Y", refused_by_metric={}
    )
    assert disclosure == {
        "n_months": 0,
        "n_overlap_rf": 0,
        "n_overlap_benchmark": 0,
        "refused": {},
    }


def test_window_refused_strips_the_window_suffix_and_ignores_other_windows() -> None:
    refused_by_metric = {
        "sharpe_1Y": "insufficient_history(required=2, available=0)",
        "downside_deviation_1Y": "insufficient_history(required=1, available=0)",
        "volatility_3Y": "insufficient_history(required=2, available=1)",
        "skew_SI": "insufficient_history(required=3, available=2)",
    }
    assert _window_refused("1Y", refused_by_metric) == {
        "sharpe": "insufficient_history(required=2, available=0)",
        "downside_deviation": "insufficient_history(required=1, available=0)",
    }


# ---------------------------------------------------------------------------
# End-to-end through build_fund_panel: the "windows" block lands in the panel
# ---------------------------------------------------------------------------


def test_build_fund_panel_carries_windows_block_for_a_mature_fund() -> None:
    rng = np.random.default_rng(11)
    n_days = 8 * 365
    fund = daily_shareclass(
        100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.01, n_days)),
        start=date(2016, 1, 1),
        id="FUND01",
    )
    yardstick = daily_shareclass(
        100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.008, n_days)),
        start=date(2016, 1, 1),
        id="YARD01",
    )
    fund_dates = fund.returns(Frequency.MONTHLY).dates
    as_of = fund_dates[-1]
    rf = _series_investment(
        returns_series(np.full(len(fund_dates), 0.003), start_year=fund_dates[0].year,
                        start_month=fund_dates[0].month),
        id="rf",
    )

    panel = build_fund_panel(
        amfi_code="FUND01",
        scheme_name="Test Fund",
        fund_house="Test AMC",
        fund=fund,
        rf=rf,
        yardstick=yardstick,
        stated_code=None,
        stated_tier=None,
        yardstick_code="YARD01",
        tier1_landed=True,
        as_of=as_of,
    )

    assert set(panel.windows) == {"1Y", "3Y", "5Y"}
    for label in ("1Y", "3Y", "5Y"):
        block = panel.windows[label]
        assert set(block) == {"n_months", "n_overlap_rf", "n_overlap_benchmark", "refused"}
        assert block["n_months"] > 0
        assert block["n_overlap_rf"] == block["n_months"]
        assert block["n_overlap_benchmark"] == block["n_months"]


# ---------------------------------------------------------------------------
# build_rf_disclosure — extended sub-block (D2d extension, flexipage-4)
# ---------------------------------------------------------------------------


def test_rf_disclosure_extended_absent_when_no_extension() -> None:
    rf = _series_investment(returns_series(np.full(36, 0.003)), id="rf")
    as_of = rf.returns(Frequency.MONTHLY).dates[-1]

    disclosure = build_rf_disclosure(rf, as_of, None)

    assert disclosure["extended"] is None


def test_rf_disclosure_extended_present_with_correct_fields() -> None:
    rf = _series_investment(returns_series(np.full(36, 0.003)), id="rf")
    as_of = rf.returns(Frequency.MONTHLY).dates[-1]
    extension = RfExtension(
        last_published=date(2025, 12, 31),
        extended_through=date(2026, 3, 31),
        n_extended=3,
        carried_monthly_value=0.003,
    )

    disclosure = build_rf_disclosure(rf, as_of, extension)

    extended = disclosure["extended"]
    assert set(extended) == {"last_published", "extended_through", "n_extended", "basis"}
    assert extended["last_published"] == "2025-12-31"
    assert extended["extended_through"] == "2026-03-31"
    assert extended["n_extended"] == 3
    assert "2025-12-31" in extended["basis"]
    assert "carried forward" in extended["basis"]
    assert "RBI repo" in extended["basis"]
