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
(g) cohort-calendar invariant: 108466's monthly panel under the equity
    cohort's shared calendar is a subset of (or equal to) its panel under a
    calendar derived from 108466 alone — and a month where 108466's own last
    NAV predates the cohort's last trading day is rejected under the cohort
    calendar specifically
(h) on-or-after completeness (tail-match fix): a month whose last in-month
    NAV is dated on-or-after the last trading day (a weekend-dated or
    fiscal-year-end close) is emitted; only a truncated month (last NAV before
    the last trading day) is rejected, and a close-reached-but-no-M+1 month is
    still withheld

GREEN (this commit): (a)-(c) run over the calendar-derived
``returns/monthly.monthly_returns`` path — the trading calendar (from
``DataAccess.derive_trading_calendar``) resolves the true last trading day
of each month, and a month is only emitted once its next month has begun
publishing. (d) exercises ``series_ops.align_dated``'s ``Frequency`` guard.
(e) exercises ``series_ops.require_frequency`` as called at the entry of
``volatility``/``sharpe``/``sortino``/``rolling_return`` (MONTHLY) and
``max_drawdown`` (DAILY). (f) is a sanity check on the fixture factories and
the frozen DataAccess fixture themselves — never expected to fail, since it
verifies the test data, not the guards. (g) is the one test of the
last-trading-day clause in a configuration where it can actually fire — the
frozen fixture's 10 equity codes happen to agree on every month's last
trading day, so the rejection case is constructed by hand (108466's own NAV
dated on the cohort's March 2025 last trading day is dropped).
"""
from __future__ import annotations

import calendar as _calendar_module
import statistics
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from foliolens.analytics.drawdown import max_drawdown
from foliolens.analytics.metrics import sharpe, sortino, volatility
from foliolens.analytics.rolling import rolling_return
from foliolens.analytics.series_ops import align_dated
from foliolens.data_access import DataAccess
from foliolens.model.value_objects import NavSeries, ReturnSeries
from foliolens.returns.calendar import TradingCalendar, calendar_from_dates
from foliolens.returns.convert import to_returns
from foliolens.returns.frequency import Frequency
from foliolens.returns.monthly import month_end, monthly_returns
from fixtures import daily_nav, returns_series, rf_investment

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "nav_snapshots"
_AMFI_CODE = "108466"

# All 13 frozen fixture codes (mirrors tests/test_data_access.py's ALL_CODES);
# 103340/120197/120754 are liquid/short-duration-debt (fixtures/funds.csv) —
# excluded from the equity cohort calendar, never mixed with the equity class.
_ALL_FIXTURE_CODES = {
    "103340", "108466", "114616", "118663", "119018", "120197", "120334",
    "120381", "120586", "120591", "120679", "120754", "122639",
}
_LIQUID_DEBT_CODES = {"103340", "120197", "120754"}
_EQUITY_FIXTURE_CODES = sorted(_ALL_FIXTURE_CODES - _LIQUID_DEBT_CODES)


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
    _assert_spacing_matches_frequency(rf_investment().returns(Frequency.MONTHLY))


def test_data_access_monthly_panel_spacing() -> None:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    cal = da.derive_trading_calendar([_AMFI_CODE])
    _assert_spacing_matches_frequency(monthly_returns(nav, cal))


def test_data_access_daily_panel_spacing() -> None:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    _assert_spacing_matches_frequency(to_returns(nav, frequency=Frequency.DAILY))


# ---------------------------------------------------------------------------
# (g) Cohort-calendar invariant
# ---------------------------------------------------------------------------


def _monthly_year_months(nav: NavSeries, cal: TradingCalendar) -> set[tuple[int, int]]:
    return {(d.year, d.month) for d in monthly_returns(nav, cal).dates}


def test_cohort_calendar_emits_subset_of_single_fund_calendar() -> None:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    cohort_cal = da.derive_trading_calendar(_EQUITY_FIXTURE_CODES)
    single_cal = da.derive_trading_calendar([_AMFI_CODE])

    cohort_months = _monthly_year_months(nav, cohort_cal)
    single_months = _monthly_year_months(nav, single_cal)
    assert cohort_months <= single_months


def test_cohort_calendar_rejects_month_where_fund_lags_cohort_last_trading_day() -> None:
    da = DataAccess(FIXTURES)
    nav = da.load_nav_series(_AMFI_CODE)
    cohort_cal = da.derive_trading_calendar(_EQUITY_FIXTURE_CODES)

    # The frozen fixture's 10 equity codes happen to agree on every month's
    # last trading day (verified against this exact fixture), so there is no
    # naturally-occurring case of "108466's last NAV predates the cohort's
    # last trading day" to observe. Construct one: drop 108466's NAV dated
    # exactly on the cohort's March-2025 last trading day.
    cohort_ltd_march = cohort_cal.last_trading_day(2025, 3)
    assert cohort_ltd_march is not None
    assert any(d == cohort_ltd_march for d, _ in nav.data), (
        "fixture assumption changed: 108466 no longer has a NAV on the "
        "cohort's March 2025 last trading day"
    )
    lagged_data = tuple((d, v) for d, v in nav.data if d != cohort_ltd_march)
    lagged_nav = NavSeries(amfi_code=nav.amfi_code, data=lagged_data)

    # month_end() layer: March disappears from the resampled NAV panel itself
    # (the exact-match check on the cohort's last trading day fails); its
    # immediate neighbours Feb/April, each independently checked against
    # their own last trading day, are untouched and both survive as points.
    resampled_months = {(d.year, d.month) for d, _ in month_end(lagged_nav, cohort_cal).data}
    assert (2025, 3) not in resampled_months
    assert (2025, 2) in resampled_months
    assert (2025, 4) in resampled_months

    # monthly_returns() layer: a cascading consequence of (c) "adjacent months
    # exactly one month apart" — with March gone, Feb and April are 2 months
    # apart in the resampled panel, so *that* pair is also dropped. April's
    # own return (Feb->April) never gets a chance to exist; the next surviving
    # return is April->May, dated May. Neither point is a bug: March is
    # rejected for lagging the cohort, and April's return is rejected for
    # being non-adjacent to its now-nearest resampled neighbour, Feb.
    cohort_months = _monthly_year_months(lagged_nav, cohort_cal)
    assert (2025, 3) not in cohort_months
    assert (2025, 4) not in cohort_months
    assert (2025, 2) in cohort_months
    assert (2025, 5) in cohort_months

    # Re-derived from the lagged series' own dates alone, the single-fund
    # calendar has no such conflict — March survives there, so does its
    # April->onward return chain.
    single_cal_lagged = calendar_from_dates(d for d, _ in lagged_nav.data)
    single_months = _monthly_year_months(lagged_nav, single_cal_lagged)
    assert (2025, 3) in single_months
    assert (2025, 4) in single_months


# ---------------------------------------------------------------------------
# (h) On-or-after completeness (tail-match fix)
#
# A month is complete once the fund's last NAV within it is dated *on or after*
# the cohort's last trading day — reaching the month's close, whether the
# closing NAV is dated exactly on the last trading day, or on a later weekend /
# fiscal-year-end date, proves the month closed. Only a fund whose last NAV
# predates the last trading day (a truncated month) is rejected. These tests
# pin that boundary directly on ``month_end`` / ``monthly_returns`` with
# hand-built synthetic calendars (no fixture round-trip). The two asserting the
# *new* behaviour (weekend close, fiscal-year-end) are RED on main; the two
# guards (truncation still rejected, trailing still withheld) hold either way.
# ---------------------------------------------------------------------------

# A common four-month calendar whose January last trading day (2026-01-30, a
# Friday) precedes the calendar month-end (2026-01-31, a Saturday) — the exact
# 119718 geometry.
_TAIL_CAL_DAYS = (
    date(2025, 11, 28),
    date(2025, 12, 31),
    date(2026, 1, 30),   # last trading day of Jan; before the 31st
    date(2026, 2, 27),
    date(2026, 3, 31),
)


def test_weekend_dated_close_is_emitted_119718_shape() -> None:
    # 119718 (SBI Flexicap) geometry: the cohort's last January trading day is
    # 2026-01-30 (Fri); the fund carries no NAV that day but one dated
    # 2026-01-31 (Sat) — it demonstrably reached January's close. Under the
    # on-or-after completeness rule January is emitted, valued at the
    # weekend-dated NAV, labelled on the calendar month-end, and both returns
    # of the k-1 -> k -> k+1 chain (Dec -> Jan -> Feb) exist.
    cal = calendar_from_dates(_TAIL_CAL_DAYS)
    nav = NavSeries(
        "119718",
        (
            (date(2025, 11, 28), Decimal("100")),
            (date(2025, 12, 31), Decimal("110")),
            (date(2026, 1, 31), Decimal("121")),   # Sat close, one day after 01-30
            (date(2026, 2, 27), Decimal("125")),
            (date(2026, 3, 31), Decimal("130")),
        ),
    )

    resampled = dict(month_end(nav, cal).data)
    jan_end = date(2026, 1, 31)
    assert jan_end in resampled, "January (Sat close, on-or-after 01-30) must be emitted"
    assert resampled[jan_end] == Decimal("121"), "value is the weekend-dated NAV"
    assert _is_calendar_month_end(jan_end), "label is the calendar month-end"

    by_date = dict(zip(monthly_returns(nav, cal).dates, monthly_returns(nav, cal).values))
    assert date(2026, 1, 31) in by_date, "Dec -> Jan return exists"
    assert date(2026, 2, 28) in by_date, "Jan -> Feb return exists"


def test_fiscal_year_end_31march_emitted() -> None:
    # Fiscal-year-end shape: a calendar whose March last trading day is the
    # 28th, with the fund's NAV dated the 31st (year-end close, three days
    # after the last trading day). The 31st is on-or-after the last trading
    # day -> March is emitted, valued and labelled on 2025-03-31.
    cal = calendar_from_dates(
        (date(2025, 2, 27), date(2025, 3, 28), date(2025, 4, 30))
    )
    nav = NavSeries(
        "FYE",
        (
            (date(2025, 2, 27), Decimal("100")),
            (date(2025, 3, 31), Decimal("108")),   # 3 days after the 03-28 close
            (date(2025, 4, 30), Decimal("110")),
        ),
    )
    resampled = dict(month_end(nav, cal).data)
    assert date(2025, 3, 31) in resampled
    assert resampled[date(2025, 3, 31)] == Decimal("108")


def test_truncated_month_still_rejected() -> None:
    # Guard (holds either way): the fund's last January NAV is dated the 20th,
    # ten days before the 01-30 last trading day — the fund did not reach the
    # month's close, so January is a truncated month and stays rejected. By
    # adjacency, February's return (Jan -> Feb) never exists either.
    cal = calendar_from_dates(_TAIL_CAL_DAYS)
    nav = NavSeries(
        "TRUNC",
        (
            (date(2025, 11, 28), Decimal("100")),
            (date(2025, 12, 31), Decimal("110")),
            (date(2026, 1, 20), Decimal("121")),   # truncated: before 01-30
            (date(2026, 2, 27), Decimal("125")),
            (date(2026, 3, 31), Decimal("130")),
        ),
    )
    resampled_months = {(d.year, d.month) for d, _ in month_end(nav, cal).data}
    assert (2026, 1) not in resampled_months
    assert date(2026, 2, 28) not in monthly_returns(nav, cal).dates


def test_trailing_month_withheld_even_when_close_reached() -> None:
    # Guard (holds either way): February's last NAV (2026-02-28) is on-or-after
    # its 02-27 last trading day, so the month reached its close — but no March
    # NAV has been published yet, so completeness condition (b) withholds it.
    # The on-or-after relaxation must not leak a still-trailing month.
    cal = calendar_from_dates((date(2026, 1, 30), date(2026, 2, 27)))
    nav = NavSeries(
        "TRAIL",
        (
            (date(2026, 1, 30), Decimal("100")),
            (date(2026, 2, 28), Decimal("110")),   # close reached, but no March NAV
        ),
    )
    resampled_months = {(d.year, d.month) for d, _ in month_end(nav, cal).data}
    assert (2026, 2) not in resampled_months
    assert (2026, 1) in resampled_months   # January is complete (Feb NAV exists)
