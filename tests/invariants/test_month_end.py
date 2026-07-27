"""Month-end + frequency invariants — fixture fund 108466 via DataAccess.

(a) every monthly date is a genuine calendar month-end
(b) 2026-06 is absent (its trading history stops mid-month, on 2026-06-19,
    with no NAV yet published in July 2026 — a still-accumulating month)
(c) adjacent monthly dates are exactly one calendar month apart
(d) aligning two mismatched-frequency ``ReturnSeries`` raises
(e) frequency-entry guards: a DAILY series fed to a monthly-convention metric
    (or a MONTHLY series fed to the daily-basis drawdown family) raises
(f) declared-vs-actual spacing: a panel's declared ``.frequency`` is
    consistent with its actual date spacing

GREEN (this commit): (a)-(c) run over the calendar-derived
``returns/monthly.monthly_returns`` path — the trading calendar (from
``DataAccess.derive_trading_calendar``) resolves the true last trading day
of each month, and a month is only emitted once its next month has begun
publishing. (d) exercises ``series_ops.align_dated``'s ``Frequency`` guard.
(e) exercises ``series_ops.require_frequency`` as called at the entry of
``volatility``/``sharpe``/``sortino``/``rolling_return`` (MONTHLY) and
``max_drawdown`` (DAILY). (f) is a sanity check on the fixture factories and
the frozen DataAccess fixture themselves — never expected to fail, since it
verifies the test data, not the guards.
"""
from __future__ import annotations

import calendar as _calendar_module
import statistics
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from foliolens.analytics.drawdown import max_drawdown
from foliolens.analytics.metrics import sharpe, sortino, volatility
from foliolens.analytics.rolling import rolling_return
from foliolens.analytics.series_ops import align_dated
from foliolens.data_access import DataAccess
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.convert import to_returns
from foliolens.returns.frequency import Frequency
from foliolens.returns.monthly import monthly_returns
from fixtures import daily_nav, returns_series, rf_investment

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "nav_snapshots"
_AMFI_CODE = "108466"


def _monthly_dates() -> tuple[date, ...]:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    cal = da.derive_trading_calendar([_AMFI_CODE])
    return monthly_returns(nav, cal).dates


def _is_calendar_month_end(d: date) -> bool:
    return d.day == _calendar_module.monthrange(d.year, d.month)[1]


def _months_apart(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def test_every_monthly_date_is_a_calendar_month_end() -> None:
    dates = _monthly_dates()
    assert dates, "expected a non-empty monthly panel for fixture fund 108466"
    assert all(_is_calendar_month_end(d) for d in dates)


def test_trailing_partial_month_is_absent() -> None:
    # 2026-06 has NAV only through 2026-06-19 with no July 2026 NAV yet — a
    # still-accumulating month, never emitted.
    dates = _monthly_dates()
    assert not any(d.year == 2026 and d.month == 6 for d in dates)


def test_adjacent_monthly_dates_are_one_month_apart() -> None:
    dates = _monthly_dates()
    assert len(dates) >= 2
    for prev_date, curr_date in zip(dates, dates[1:]):
        assert _months_apart(prev_date, curr_date) == 1


def test_align_dated_rejects_frequency_mismatch() -> None:
    monthly = ReturnSeries(
        dates=(date(2024, 1, 31), date(2024, 2, 29)),
        values=np.array([0.01, 0.02], dtype=np.float64),
        frequency=Frequency.MONTHLY,
    )
    daily = ReturnSeries(
        dates=(date(2024, 1, 31), date(2024, 2, 29)),
        values=np.array([0.001, 0.002], dtype=np.float64),
        frequency=Frequency.DAILY,
    )
    with pytest.raises(ValueError, match="frequency mismatch"):
        align_dated(monthly, daily)


# ---------------------------------------------------------------------------
# (e) Frequency-entry guards
# ---------------------------------------------------------------------------


def _daily_series(n: int = 30) -> ReturnSeries:
    return ReturnSeries(
        dates=tuple(date(2024, 1, 1 + i) for i in range(n)),
        values=np.full(n, 0.001, dtype=np.float64),
        frequency=Frequency.DAILY,
    )


def test_volatility_rejects_daily_series() -> None:
    with pytest.raises(ValueError, match="frequency mismatch"):
        volatility(_daily_series())


def test_sharpe_rejects_daily_series() -> None:
    daily = _daily_series()
    with pytest.raises(ValueError, match="frequency mismatch"):
        sharpe(daily, daily)


def test_sortino_rejects_daily_series() -> None:
    daily = _daily_series()
    with pytest.raises(ValueError, match="frequency mismatch"):
        sortino(daily, daily)


def test_rolling_return_rejects_daily_series() -> None:
    with pytest.raises(ValueError, match="frequency mismatch"):
        rolling_return(_daily_series(), 12)


def test_max_drawdown_rejects_monthly_series() -> None:
    monthly = returns_series([0.01, 0.02, -0.01, 0.03])
    with pytest.raises(ValueError, match="frequency mismatch"):
        max_drawdown(monthly)


# ---------------------------------------------------------------------------
# (f) Declared-vs-actual spacing invariant
# ---------------------------------------------------------------------------


def _median_spacing_days(rs: ReturnSeries) -> float:
    gaps = [(b - a).days for a, b in zip(rs.dates, rs.dates[1:])]
    return statistics.median(gaps)


def _assert_spacing_matches_frequency(rs: ReturnSeries) -> None:
    spacing = _median_spacing_days(rs)
    if rs.frequency is Frequency.DAILY:
        assert spacing <= 4, f"DAILY series has median spacing {spacing} days"
    else:
        assert 28 <= spacing <= 33, f"MONTHLY series has median spacing {spacing} days"


def test_fixture_factory_monthly_panel_spacing() -> None:
    _assert_spacing_matches_frequency(returns_series([0.01, 0.02, 0.03, -0.01, 0.015] * 5))


def test_fixture_factory_daily_panel_spacing() -> None:
    nav = daily_nav([100.0 + i * 0.1 for i in range(60)])
    daily_rs = to_returns(nav, frequency=Frequency.DAILY)
    _assert_spacing_matches_frequency(daily_rs)


def test_fixture_factory_rf_panel_spacing() -> None:
    _assert_spacing_matches_frequency(rf_investment().returns)


def test_data_access_monthly_panel_spacing() -> None:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    cal = da.derive_trading_calendar([_AMFI_CODE])
    _assert_spacing_matches_frequency(monthly_returns(nav, cal))


def test_data_access_daily_panel_spacing() -> None:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    _assert_spacing_matches_frequency(to_returns(nav, frequency=Frequency.DAILY))
