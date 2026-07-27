"""Edge-case and closed-form behaviour for the §3 daily-basis family.

Covers the spec-analytics §3 edges — monotone rise (no drawdown), full-history
drawdown (never recovers), recovery (regains the prior peak) — plus the load-
bearing daily-basis claim: an **intra-month trough is captured** on the daily
series where a month-end series would smooth it away. Drawdown timing is checked
against hand-computed dates; empty inputs fail loud.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from foliolens.analytics.drawdown import (
    cvar,
    drawdown_of,
    max_drawdown,
    max_drawdown_of,
    var_historical,
)
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.convert import to_returns
from foliolens.returns.frequency import Frequency
from fixtures import daily_shareclass

_ABS = 1e-9


# ---------------------------------------------------------------------------
# Monotone rise — never underwater → max drawdown is exactly zero
# ---------------------------------------------------------------------------


def test_monotone_rise_no_drawdown() -> None:
    sc = daily_shareclass([100.0, 101.0, 102.0, 103.0, 104.0])
    dd = drawdown_of(sc)
    assert dd.max_drawdown == 0.0
    # No decline ever begins → the "episode" collapses onto the first date.
    assert dd.peak_date == dd.trough_date == date(2024, 1, 1)


# ---------------------------------------------------------------------------
# Full-history drawdown — monotone decline, never recovers
# ---------------------------------------------------------------------------


def test_full_history_drawdown_never_recovers() -> None:
    # 100 → 80 straight down: peak is the very first (seed) date, trough the last,
    # recovery never happens within the series.
    sc = daily_shareclass([100.0, 95.0, 90.0, 85.0, 80.0])
    dd = drawdown_of(sc)
    assert dd.max_drawdown == pytest.approx(-0.20, abs=_ABS)
    assert dd.peak_date == date(2024, 1, 1)      # the seeded first NAV date
    assert dd.trough_date == date(2024, 1, 5)    # the last date
    assert dd.recovery_date is None
    assert dd.recovery_days is None
    assert dd.underwater_days is None
    assert dd.time_to_trough_days == 4


# ---------------------------------------------------------------------------
# Recovery — dip then regain the prior peak (hand-computed dates)
# ---------------------------------------------------------------------------


def test_recovery_closed_form() -> None:
    # NAV 100,110,90,105,120 on 2024-01-01..05 (base 100, nav[0]=100 → levels=NAV).
    #   running max: 100,110,110,110,120; dd at 90 = (90-110)/110 = -0.181818…
    #   peak = 110 @ 01-02, trough = 90 @ 01-03, recovery = first ≥110 = 120 @ 01-05
    sc = daily_shareclass([100.0, 110.0, 90.0, 105.0, 120.0])
    dd = drawdown_of(sc)
    assert dd.max_drawdown == pytest.approx(-20.0 / 110.0, abs=_ABS)
    assert dd.peak_date == date(2024, 1, 2)
    assert dd.trough_date == date(2024, 1, 3)
    assert dd.recovery_date == date(2024, 1, 5)
    assert dd.time_to_trough_days == 1
    assert dd.recovery_days == 2
    assert dd.underwater_days == 3


# ---------------------------------------------------------------------------
# Intra-month trough — the daily-basis claim (§3 accept)
# ---------------------------------------------------------------------------


def _intra_month_navs() -> list[float]:
    """Rising month-ends hiding a deep mid-February trough.

    Jan 100→130 (rising), Feb 130→104 by the 14th (a −20% dip), then 104→140 by
    the 29th. Month-ends (Jan-31=130, Feb-29=140) are monotone up — a month-end
    series sees no drawdown at all; the daily series sees the −20% trough.
    """
    navs = [100.0 + 30.0 * i / 30 for i in range(31)]          # Jan 1..31 → 100..130
    navs += [130.0 - 26.0 * j / 14 for j in range(1, 15)]      # Feb 1..14 → …104
    navs += [104.0 + 36.0 * j / 15 for j in range(1, 16)]      # Feb 15..29 → …140
    return navs


def test_intra_month_trough_captured_daily_not_month_end() -> None:
    sc = daily_shareclass(_intra_month_navs())  # 60 consecutive days from 2024-01-01

    daily = drawdown_of(sc)
    assert daily.trough_date == date(2024, 2, 14)   # mid-month, not a month-end
    assert daily.max_drawdown == pytest.approx(104.0 / 130.0 - 1.0, abs=_ABS)
    assert daily.peak_date == date(2024, 1, 31)
    assert daily.recovery_date is not None

    # max_drawdown is fixed to the daily convention (spec-analytics): a
    # month-end series is rejected outright rather than silently smoothing
    # away the intra-month trough into a misleading zero drawdown.
    month_end_series = to_returns(sc.source.nav.month_end(), frequency=Frequency.MONTHLY)
    with pytest.raises(ValueError, match="frequency"):
        max_drawdown(month_end_series)
    assert daily.max_drawdown < -0.15


def test_max_drawdown_of_matches_drawdown_of() -> None:
    # The scalar adapter and the detail adapter agree on the same daily NAV.
    sc = daily_shareclass(_intra_month_navs())
    assert max_drawdown_of(sc) == pytest.approx(drawdown_of(sc).max_drawdown, abs=1e-15)


# ---------------------------------------------------------------------------
# Empty inputs fail loud (never a silent 0)
# ---------------------------------------------------------------------------


def _empty() -> ReturnSeries:
    return ReturnSeries(dates=(), values=np.array([], dtype=np.float64), frequency=Frequency.DAILY)


def test_max_drawdown_empty_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        max_drawdown(_empty())


def test_var_historical_empty_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        var_historical(_empty())


def test_cvar_empty_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        cvar(_empty())
