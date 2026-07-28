"""§3 daily-basis family: drawdown (max + duration + recovery), VaR, CVaR.

The one metric family that reads **daily NAV**, not the monthly analytical
series (``CLAUDE.md`` → *Analytics conventions*: "Drawdown is the only exception
— base = daily NAV via ``.source``"). Tail risk (historical VaR / CVaR at 95%)
shares the daily route and is reported **per-period, never annualised**.

Two layers, per ``spec-analytics §3``:

* **Pure functions** over ``ReturnSeries`` / ``ValueIndex``. The ``ReturnSeries``
  entry points (:func:`max_drawdown`, :func:`var_historical`, :func:`cvar`) fix
  the daily convention and assert ``Frequency.DAILY`` — this family never
  silently accepts a monthly series (``spec-analytics``: no cross-frequency
  series use). :func:`drawdown` / :func:`underwater` take a ``ValueIndex``,
  which carries no frequency tag, so they stay periodicity-agnostic by
  construction; in practice the daily adapters are their only caller.
* **Daily adapters** — ``*_of(investment)`` — that derive the daily series from
  ``investment.source`` and feed the pure functions. This is what makes the
  family "daily-basis": the adapter is what actually chooses daily; the pure
  functions enforce that choice at entry where they can.

Seam discipline (``CLAUDE.md`` → *Money & precision*): the daily NAV converts to
float **once**, through ``returns/convert.py`` (``to_returns`` → ``to_index``);
drawdown is computed on the resulting float levels. There is **no** Decimal→float
cast in this module — the base level is recovered from the float index itself
(``levels[0] / (1 + r[0])``), never by re-casting the Decimal ``base``.

Definitions are pinned to the ``empyrical`` daily oracle so own↔oracle holds at
≤ 1e-6: ``max_drawdown`` seeds a peak *before* the first period (``empyrical``
inserts a ``starting_value`` of 100 before ``cumprod``); ``var_historical`` is
``np.percentile(returns, 5)``; ``cvar`` is the lower-tail partition mean.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from foliolens.model.investments import Investment
from foliolens.model.value_objects import ReturnSeries, ValueIndex

from ..returns.convert import to_index
from ..returns.frequency import Frequency
from .series_ops import InsufficientHistoryError, require_frequency

_VAR_CUTOFF = 0.05  # 95% VaR/CVaR — the spec-analytics §3 confidence level


def _seeded_levels(rs: ReturnSeries) -> np.ndarray:
    """Float level series with a peak seeded *before* the first period.

    Reconstructs ``base·Π(1+r)`` via the ``to_index`` seam, then prepends the
    pre-period base level so a decline from the very first period is measured
    from the start (matching ``empyrical``'s ``starting_value`` insert). The seed
    is recovered from the float index (``levels[0] / (1 + r[0])``) — never by
    casting the Decimal ``base`` here, which would open a second Decimal→float
    seam outside ``returns/convert.py``.
    """
    idx = to_index(rs)
    seed = idx.levels[0] / (1.0 + rs.values[0])
    return np.concatenate(([seed], idx.levels))


@dataclass(frozen=True)
class Drawdown:
    """Max-drawdown episode with its timing: the deepest peak-to-trough decline.

    ``max_drawdown`` is a fraction ≤ 0 (0.0 when the level series never draws
    down). ``recovery_date`` is ``None`` when the level never regains the prior
    peak within the series (an unrecovered drawdown — correct, not an error).
    Durations are exposed as day-count properties over the stored dates.
    """

    max_drawdown: float
    peak_date: date
    trough_date: date
    recovery_date: date | None

    @property
    def time_to_trough_days(self) -> int:
        """Calendar days from the peak to the trough (the decline leg)."""
        return (self.trough_date - self.peak_date).days

    @property
    def recovery_days(self) -> int | None:
        """Calendar days from the trough back to the prior peak; None if unrecovered."""
        if self.recovery_date is None:
            return None
        return (self.recovery_date - self.trough_date).days

    @property
    def underwater_days(self) -> int | None:
        """Calendar days from the peak to full recovery; None if unrecovered."""
        if self.recovery_date is None:
            return None
        return (self.recovery_date - self.peak_date).days


def max_drawdown(rs: ReturnSeries) -> float:
    """Maximum drawdown of ``rs`` as a fraction ≤ 0 (0.0 if never underwater).

    Fixed to the daily convention (asserts ``Frequency.DAILY``) — a monthly
    series would silently smooth away an intra-month trough into a misleading
    shallower (or zero) drawdown, so it is rejected outright rather than
    computed on. Seeds a pre-period peak so a first-period decline counts,
    matching ``empyrical.max_drawdown`` (own↔oracle ≤ 1e-6). Scale-invariant,
    so the base level (100) does not affect the result.
    """
    require_frequency(rs, Frequency.DAILY)
    if len(rs) < 1:
        raise InsufficientHistoryError(1, len(rs), "max_drawdown needs >= 1 return")
    levels = _seeded_levels(rs)
    running_max = np.fmax.accumulate(levels)
    return float(np.min((levels - running_max) / running_max))


def underwater(idx: ValueIndex) -> ReturnSeries:
    """Drawdown-from-peak at every date of ``idx`` (fraction ≤ 0): the running
    decline from the peak-to-date level.

    The same running-max computation :func:`drawdown` uses internally to
    locate its deepest episode, exposed here as the full curve rather than
    reduced to the single trough — the seam a chart wanting the curve itself
    (not just the episode) reads from. Periodicity-agnostic, like
    :func:`drawdown`: the caller's ``idx`` may be daily or month-end.
    """
    if len(idx) < 1:
        raise InsufficientHistoryError(1, len(idx), "underwater needs >= 1 level")
    running_max = np.fmax.accumulate(idx.levels)
    dd = (idx.levels - running_max) / running_max
    return ReturnSeries(dates=idx.dates, values=dd, frequency=Frequency.DAILY)


def drawdown(idx: ValueIndex) -> Drawdown:
    """Deepest drawdown episode of a dated float level series, with its timing.

    Operates on levels **as given** — the caller supplies a complete series whose
    first level is the true starting point (the daily adapter prepends the seed
    level at the first NAV date, so ``peak_date`` can be that first date). The
    peak is the running maximum leading into the trough; recovery is the first
    later level that regains the peak. Returns a zero drawdown anchored at the
    first date when the series never declines.
    """
    if len(idx) < 1:
        raise InsufficientHistoryError(1, len(idx), "drawdown needs >= 1 level")
    levels = idx.levels
    dates = idx.dates
    dd = underwater(idx).values
    trough_i = int(np.argmin(dd))
    max_dd = float(dd[trough_i])
    # The peak that leads into this trough: the highest level on or before it
    # (argmax returns the first occurrence — the start of the decline).
    peak_i = int(np.argmax(levels[: trough_i + 1]))
    peak_level = levels[peak_i]
    # Recovery: the first level after the trough that regains the prior peak.
    recovery_date: date | None = None
    tail = levels[trough_i + 1 :]
    regained = np.nonzero(tail >= peak_level)[0]
    if regained.size:
        recovery_date = dates[trough_i + 1 + int(regained[0])]
    return Drawdown(
        max_drawdown=max_dd,
        peak_date=dates[peak_i],
        trough_date=dates[trough_i],
        recovery_date=recovery_date,
    )


def var_historical(rs: ReturnSeries, cutoff: float = _VAR_CUTOFF) -> float:
    """Historical Value-at-Risk: the ``cutoff`` percentile of returns.

    ``np.percentile(returns, 100·cutoff)`` — the return the series falls below
    only ``cutoff`` of the time (a loss, so typically ≤ 0 at 5%). Reported
    **per-period, never annualised** — the daily adapter feeds daily returns and
    the figure stays a daily quantity. Matches ``empyrical.value_at_risk``.
    """
    require_frequency(rs, Frequency.DAILY)
    if len(rs) < 1:
        raise InsufficientHistoryError(1, len(rs), "var_historical needs >= 1 return")
    return float(np.percentile(rs.values, 100.0 * cutoff))


def cvar(rs: ReturnSeries, cutoff: float = _VAR_CUTOFF) -> float:
    """Conditional VaR (expected shortfall): mean of the lower ``cutoff`` tail.

    The average return over the worst ``cutoff`` of periods — the VaR breach's
    expected depth. Uses ``empyrical``'s partition index
    ``int((n−1)·cutoff)`` (inclusive) so own↔oracle holds at ≤ 1e-6. Per-period,
    never annualised. Matches ``empyrical.conditional_value_at_risk``.
    """
    require_frequency(rs, Frequency.DAILY)
    n = len(rs)
    if n < 1:
        raise InsufficientHistoryError(1, n, "cvar needs >= 1 return")
    cutoff_index = int((n - 1) * cutoff)
    return float(np.mean(np.partition(rs.values, cutoff_index)[: cutoff_index + 1]))


# ---------------------------------------------------------------------------
# Daily adapters — read the investment's eagerly-computed DAILY panel
# ---------------------------------------------------------------------------


def _daily_returns(investment: Investment) -> ReturnSeries:
    """The investment's DAILY panel, already computed by its factory.

    No computation here: the factory (:func:`~foliolens.model.investments.
    share_class_from_nav` / ``benchmark_from_index``) is the sole site that
    calls ``to_returns`` for the daily panel — drawdown/VaR/CVaR read the
    *raw* daily NAV so an intra-month trough is captured, not smoothed to a
    month-end point.
    """
    return investment.returns(Frequency.DAILY)


def _daily_levels(investment: Investment) -> ValueIndex:
    """Dated float level series over daily NAV, seeded at the first NAV date.

    ``to_returns`` drops the first NAV point (it becomes the base of the first
    return); this restores it as the seed level so the level series spans every
    NAV date and ``peak_date`` can legitimately be the first one.
    """
    r = _daily_returns(investment)
    idx = to_index(r)
    seed = float(idx.levels[0] / (1.0 + r.values[0]))
    first_date = investment.source.value_series.data[0][0]
    return ValueIndex(
        dates=(first_date, *idx.dates),
        levels=np.concatenate(([seed], idx.levels)),
    )


def drawdown_of(investment: Investment) -> Drawdown:
    """Drawdown episode over the investment's **daily** NAV (``spec-analytics §3``)."""
    return drawdown(_daily_levels(investment))


def max_drawdown_of(investment: Investment) -> float:
    """Maximum drawdown over the investment's **daily** NAV."""
    return max_drawdown(_daily_returns(investment))


def var_historical_of(investment: Investment, cutoff: float = _VAR_CUTOFF) -> float:
    """Historical VaR over the investment's **daily** returns (per-period)."""
    return var_historical(_daily_returns(investment), cutoff)


def cvar_of(investment: Investment, cutoff: float = _VAR_CUTOFF) -> float:
    """Conditional VaR over the investment's **daily** returns (per-period)."""
    return cvar(_daily_returns(investment), cutoff)
