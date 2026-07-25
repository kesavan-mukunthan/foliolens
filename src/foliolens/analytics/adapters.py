"""§5 Investment adapters for the §2/§4 metrics — ``*_of(investment, …)``.

Thin delegation only: each adapter reads the *materialised* monthly return
series off the Investment (``investment.returns``) and calls the corresponding
pure function. It contains **no computation** of its own — the arithmetic lives
in the pure functions (``metrics``/``rolling``/``distribution``), and the
adapter's single job is the ``.returns`` read (``spec-analytics §5``:
"adapters compute nothing beyond delegation").

rf / MAR are passed as **Investment**s, never as scalar rates (``CLAUDE.md`` →
*Analytics conventions*): the adapter reads ``rf.returns`` and hands the two
series to the pure two-series metric, which aligns them.

The §3 daily-basis adapters (``max_drawdown_of``, ``drawdown_of``,
``var_historical_of``, ``cvar_of``) already live in :mod:`.drawdown` — they read
``investment.source`` (daily NAV) by design, and are re-exported from the
package alongside these. This module adds only the ``.returns`` peers for the
monthly-series metrics.
"""
from __future__ import annotations

from datetime import date

from foliolens.model.investments import Investment
from foliolens.model.value_objects import ReturnSeries

from . import distribution, metrics, relative, rolling
from .relative import AlphaResult

# ---------------------------------------------------------------------------
# §2 pure-core peers — over investment.returns (monthly materialised series)
# ---------------------------------------------------------------------------


def period_return_abs_of(investment: Investment, start: date, end: date) -> float:
    """Absolute compounded return of ``investment.returns`` over ``[start, end]``."""
    return metrics.period_return_abs(investment.returns, start, end)


def volatility_of(investment: Investment) -> float:
    """Annualised volatility of ``investment.returns``."""
    return metrics.volatility(investment.returns)


def downside_deviation_of(investment: Investment, mar: Investment) -> float:
    """Annualised downside deviation of ``investment.returns`` below ``mar.returns``."""
    return metrics.downside_deviation(investment.returns, mar.returns)


def sharpe_of(investment: Investment, rf: Investment) -> float:
    """Annualised Sharpe of ``investment.returns`` against the rf Investment's returns."""
    return metrics.sharpe(investment.returns, rf.returns)


def sortino_of(investment: Investment, rf: Investment) -> float:
    """Annualised Sortino (MAR = rf) of ``investment.returns`` against ``rf.returns``."""
    return metrics.sortino(investment.returns, rf.returns)


def calmar_of(investment: Investment) -> float:
    """Calmar ratio of ``investment.returns`` (return-series drawdown, §2 sense)."""
    return metrics.calmar(investment.returns)


# ---------------------------------------------------------------------------
# §4 rolling + distribution peers — over investment.returns
# ---------------------------------------------------------------------------


def rolling_return_of(investment: Investment, window_months: int) -> ReturnSeries:
    """Rolling annualised return of ``investment.returns`` over a fixed window."""
    return rolling.rolling_return(investment.returns, window_months)


def rolling_returns_of(investment: Investment) -> dict[str, ReturnSeries]:
    """Rolling annualised returns of ``investment.returns`` for all standard windows."""
    return rolling.rolling_returns(investment.returns)


def pct_positive_of(investment: Investment) -> float:
    """Fraction of strictly positive periods in ``investment.returns``."""
    return distribution.pct_positive(investment.returns)


def best_period_of(investment: Investment) -> float:
    """Largest single-period return in ``investment.returns``."""
    return distribution.best_period(investment.returns)


def worst_period_of(investment: Investment) -> float:
    """Smallest (most negative) single-period return in ``investment.returns``."""
    return distribution.worst_period(investment.returns)


def skew_of(investment: Investment) -> float:
    """Sample skewness of ``investment.returns``."""
    return distribution.skew(investment.returns)


def kurtosis_of(investment: Investment) -> float:
    """Sample excess kurtosis of ``investment.returns``."""
    return distribution.kurtosis(investment.returns)


# ---------------------------------------------------------------------------
# §6 benchmark-relative peers — over investment.returns vs a benchmark Investment
# ---------------------------------------------------------------------------
#
# Same delegation-only contract: read ``.returns`` off the fund, the benchmark,
# and (for risk-adjusted metrics) the rf Investment, then call the pure function.
# The benchmark and rf are **Investments, never scalars** (``CLAUDE.md`` →
# *Analytics conventions*); the benchmark's TRI-vs-PRI identity is upstream. The
# benchmark defaults to the fund's stored ``investment.benchmark`` and is
# overridable per call ("fund→benchmark is a stored default, overridable") — a
# property read, not arithmetic.


def _benchmark_of(investment: Investment, benchmark: Investment | None) -> Investment:
    """The effective benchmark: the explicit override, else the stored default."""
    effective = benchmark if benchmark is not None else investment.benchmark
    if effective is None:
        raise ValueError(f"no benchmark for {investment.id!r} and none supplied")
    return effective


def excess_return_of(
    investment: Investment, benchmark: Investment | None = None
) -> ReturnSeries:
    """Per-period active return of ``investment`` over its benchmark."""
    return relative.excess_return(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def tracking_error_of(
    investment: Investment, benchmark: Investment | None = None
) -> float:
    """Annualised tracking error of ``investment`` against its benchmark."""
    return relative.tracking_error(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def information_ratio_of(
    investment: Investment, benchmark: Investment | None = None
) -> float:
    """Annualised information ratio of ``investment`` against its benchmark."""
    return relative.information_ratio(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def beta_of(investment: Investment, benchmark: Investment | None = None) -> float:
    """Market beta of ``investment`` against its benchmark."""
    return relative.beta(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def correlation_of(
    investment: Investment, benchmark: Investment | None = None
) -> float:
    """Pearson correlation of ``investment`` with its benchmark."""
    return relative.correlation(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def r_squared_of(investment: Investment, benchmark: Investment | None = None) -> float:
    """R² of the ``investment``-on-benchmark regression."""
    return relative.r_squared(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def jensens_alpha_of(
    investment: Investment, rf: Investment, benchmark: Investment | None = None
) -> AlphaResult:
    """Jensen's alpha (with t-stat and window) of ``investment`` vs its benchmark."""
    return relative.jensens_alpha(
        investment.returns,
        _benchmark_of(investment, benchmark).returns,
        rf.returns,
    )


def treynor_of(
    investment: Investment, rf: Investment, benchmark: Investment | None = None
) -> float:
    """Treynor ratio of ``investment`` (excess over rf per unit of beta)."""
    return relative.treynor(
        investment.returns,
        _benchmark_of(investment, benchmark).returns,
        rf.returns,
    )


def up_capture_of(
    investment: Investment, benchmark: Investment | None = None
) -> float:
    """Up-market capture of ``investment`` against its benchmark."""
    return relative.up_capture(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def down_capture_of(
    investment: Investment, benchmark: Investment | None = None
) -> float:
    """Down-market capture of ``investment`` against its benchmark."""
    return relative.down_capture(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def hit_rate_of(investment: Investment, benchmark: Investment | None = None) -> float:
    """Share of months ``investment`` beat its benchmark."""
    return relative.hit_rate(
        investment.returns, _benchmark_of(investment, benchmark).returns
    )


def rolling_excess_return_of(
    investment: Investment, window_months: int, benchmark: Investment | None = None
) -> ReturnSeries:
    """Rolling annualised active return of ``investment`` over a fixed window."""
    return relative.rolling_excess_return(
        investment.returns, _benchmark_of(investment, benchmark).returns, window_months
    )


def rolling_beta_of(
    investment: Investment, window_months: int, benchmark: Investment | None = None
) -> ReturnSeries:
    """Rolling beta of ``investment`` against its benchmark over a fixed window."""
    return relative.rolling_beta(
        investment.returns, _benchmark_of(investment, benchmark).returns, window_months
    )


def rolling_correlation_of(
    investment: Investment, window_months: int, benchmark: Investment | None = None
) -> ReturnSeries:
    """Rolling correlation of ``investment`` with its benchmark over a fixed window."""
    return relative.rolling_correlation(
        investment.returns, _benchmark_of(investment, benchmark).returns, window_months
    )
