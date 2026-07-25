"""§6 benchmark-relative metrics over aligned ``ReturnSeries`` (no benchmark I/O).

Pure free functions in the shape of §2: they take the fund's monthly
``ReturnSeries`` and the benchmark's (and, where the metric is risk-adjusted,
the rf's), align through :mod:`series_ops`, and never touch NAV. The benchmark
and rf enter as return *series* — the ``Investment`` adapters in
:mod:`.adapters` read ``.returns`` off the benchmark/rf Investments and delegate
here (``CLAUDE.md`` → *Analytics conventions*: rf & benchmark are ``Investment``s,
never scalars; the benchmark return-variant is TRI, never PRI — that is the
benchmark Investment's identity, upstream of this layer).

Oracle pinning (own↔oracle ≤ 1e-6, ``spec-analytics §6``):

* :func:`beta` ≡ ``empyrical.beta`` — ``Cov(rb, r)/Var(rb)`` with population
  moments; rf-independent (empyrical's ``beta`` ignores its ``risk_free`` arg).
* :func:`jensens_alpha` ≡ ``empyrical.alpha`` — the CAPM regression on the
  **excess** series ``(r − rf)`` on ``(rb − rf)``, its periodic intercept
  geometrically annualised ``(1 + α_period)^12 − 1``. With a *constant* rf the
  excess-regression slope equals the raw :func:`beta`, so the reported β and the
  β inside alpha coincide — one β, no contradiction. The result carries the
  intercept's **t-stat and estimation window** (``CLAUDE.md``: any alpha-like
  quantity ships its t-stat and window in the same object — a naked point
  estimate is an invalid artifact); the t-stat is on the periodic intercept and
  matches an OLS fixture (``scipy.stats.linregress`` intercept / stderr).
* :func:`information_ratio` ≡ ``empyrical.excess_sharpe × √12`` — annualised to
  sit beside §2's √12-annualised Sharpe; :func:`tracking_error` is the
  annualised active-risk denominator, reusing §2 :func:`~.metrics.volatility`
  over the excess series (so it inherits that function's own↔oracle pinning).
* :func:`up_capture` / :func:`down_capture` ≡ ``empyrical.up_capture`` /
  ``down_capture`` — the CAGR ratio over benchmark-positive / -negative months.

:func:`treynor`, :func:`r_squared`, :func:`hit_rate` and :func:`excess_return`
have no single empyrical oracle; they are pinned by composition (β / correlation
/ volatility, each already oracle-checked) and hand-computed fixtures.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from foliolens.model.value_objects import ReturnSeries

from .metrics import volatility
from .rolling import rolling_return
from .series_ops import align, align_dated

_MONTHS_PER_YEAR = 12.0
_Array = npt.NDArray[np.float64]


# ---------------------------------------------------------------------------
# Excess return (per period) — a dated series, built on the single join
# ---------------------------------------------------------------------------


def excess_return(fund: ReturnSeries, benchmark: ReturnSeries) -> ReturnSeries:
    """Per-period active return ``r − rb`` as a dated ``ReturnSeries``.

    Aligned on the overlap via :func:`series_ops.align_dated`; only months
    present in *both* series contribute. The fund's ``base`` anchor carries
    through (the excess series is a derived view, not a figure of record).
    Fails loud on an empty overlap — there is no active return to report.
    """
    dates, r, rb = align_dated(fund, benchmark)
    if len(dates) < 1:
        raise ValueError("excess_return needs >= 1 overlapping period")
    return ReturnSeries(dates=dates, values=r - rb, base=fund.base)


# ---------------------------------------------------------------------------
# Tracking error & information ratio — active risk / active return
# ---------------------------------------------------------------------------


def tracking_error(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Annualised tracking error: ``std(r − rb, ddof=1) × √12``.

    The active-risk denominator of the information ratio. Implemented as §2
    :func:`~.metrics.volatility` over the :func:`excess_return` series, so it is
    the *same* √12-annualised sample-std definition (and inherits volatility's
    own↔oracle pinning) rather than a second std implementation.
    """
    return volatility(excess_return(fund, benchmark))


def information_ratio(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Annualised information ratio: annualised active return / tracking error.

    ``(mean(r − rb) × 12) / (std(r − rb, ddof=1) × √12)`` over the aligned
    overlap — equivalently ``empyrical.excess_sharpe × √12`` (the per-period
    excess Sharpe scaled to the analytics' √12 convention, matching §2 Sharpe).
    Fails loud when tracking error is zero (a fund that never deviates from its
    benchmark has no defined information ratio — the degenerate zero-TE case).
    """
    r, rb = align(fund, benchmark)
    if len(r) < 2:
        raise ValueError(f"information_ratio needs >= 2 overlapping periods, got {len(r)}")
    active = r - rb
    te = float(np.std(active, ddof=1)) * np.sqrt(_MONTHS_PER_YEAR)
    if te == 0.0:
        raise ValueError("information_ratio undefined: tracking error is zero")
    return float(float(np.mean(active)) * _MONTHS_PER_YEAR / te)


# ---------------------------------------------------------------------------
# Beta, correlation, R² — the regression family
# ---------------------------------------------------------------------------


def _beta(r: _Array, rb: _Array) -> float:
    """Slope of ``r`` on ``rb``: ``Cov(rb, r)/Var(rb)`` (population moments).

    Centres only the independent series (``rb``); ``mean(rb_res) == 0`` makes the
    numerator ``mean(rb_res · r)`` equal the full covariance without centring
    ``r`` — the exact algebra ``empyrical.beta`` uses, so the two agree to
    machine precision. Fails loud when the benchmark has (near-)zero variance:
    beta is undefined against a flat benchmark.
    """
    rb_res = rb - np.mean(rb)
    variance = float(np.mean(rb_res * rb_res))
    if variance < 1.0e-30:
        raise ValueError("beta undefined: benchmark variance is zero")
    covariance = float(np.mean(rb_res * r))
    return covariance / variance


def beta(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Market beta: slope of fund returns regressed on benchmark returns.

    ``Cov(rb, r)/Var(rb)`` over the aligned overlap — the raw-return beta funds
    report, rf-independent (≡ ``empyrical.beta``). Needs ≥ 2 overlapping points.
    """
    r, rb = align(fund, benchmark)
    if len(r) < 2:
        raise ValueError(f"beta needs >= 2 overlapping periods, got {len(r)}")
    return _beta(r, rb)


def correlation(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Pearson correlation of fund and benchmark returns over the overlap."""
    r, rb = align(fund, benchmark)
    if len(r) < 2:
        raise ValueError(f"correlation needs >= 2 overlapping periods, got {len(r)}")
    if np.std(r) == 0.0 or np.std(rb) == 0.0:
        raise ValueError("correlation undefined: a series has zero variance")
    return float(np.corrcoef(r, rb)[0, 1])


def r_squared(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Coefficient of determination of the fund-on-benchmark regression: ``ρ²``.

    The share of the fund's variance explained by the benchmark — the squared
    Pearson correlation, in ``[0, 1]``. Composed on :func:`correlation`, not a
    second regression.
    """
    rho = correlation(fund, benchmark)
    return rho * rho


# ---------------------------------------------------------------------------
# Jensen's alpha — CAPM regression intercept, with t-stat and window
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlphaResult:
    """Jensen's alpha with the uncertainty and window that make it a valid figure.

    ``alpha`` is the geometrically **annualised** CAPM intercept (≡
    ``empyrical.alpha``). ``t_stat`` is the t-statistic of the *periodic*
    intercept ``alpha_periodic`` from the OLS regression of excess fund on excess
    benchmark; ``alpha_periodic`` is carried so the t-stat is reproducible.
    ``n`` / ``start`` / ``end`` are the estimation window. A point estimate
    without its t-stat and window is an invalid artifact (``CLAUDE.md`` →
    *Analytics conventions*), so this object cannot be constructed without them.
    """

    alpha: float
    alpha_periodic: float
    t_stat: float
    n: int
    start: date
    end: date


def jensens_alpha(
    fund: ReturnSeries, benchmark: ReturnSeries, rf: ReturnSeries
) -> AlphaResult:
    """CAPM regression intercept of excess fund on excess benchmark, monthly.

    Regresses ``y = (r − rf)`` on ``x = (rb − rf)`` (OLS) over the aligned
    overlap of all three series. The periodic intercept ``α = ȳ − b·x̄`` is
    annualised geometrically ``(1 + α)^12 − 1`` to match ``empyrical.alpha``
    (which uses the same annualisation; with a constant rf the excess-regression
    slope ``b`` equals :func:`beta`, so empyrical's raw-beta residual and this
    OLS residual coincide). The intercept's t-stat comes from the OLS standard
    error ``SE(α) = s·√(1/n + x̄²/Sxx)`` with ``s = √(SSE/(n−2))`` — needs
    ``n ≥ 3``. rf is a *series* (aligned, never a scalar).
    """
    # Align fund↔benchmark first, then intersect with rf, so all three share dates.
    dates_fb, r_fb, rb_fb = align_dated(fund, benchmark)
    paired = ReturnSeries(dates=dates_fb, values=r_fb, base=fund.base)
    bench_paired = ReturnSeries(dates=dates_fb, values=rb_fb, base=benchmark.base)
    dates, r, f = align_dated(paired, rf)
    _, rb, _ = align_dated(bench_paired, rf)
    n = len(dates)
    if n < 3:
        raise ValueError(f"jensens_alpha needs >= 3 overlapping periods, got {n}")

    y = r - f            # excess fund return
    x = rb - f           # excess benchmark return
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    sxx = float(np.sum((x - x_mean) ** 2))
    if sxx == 0.0:
        raise ValueError("jensens_alpha undefined: excess benchmark has zero variance")
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / sxx)
    alpha_periodic = y_mean - slope * x_mean

    residuals = y - (alpha_periodic + slope * x)
    sse = float(np.sum(residuals ** 2))
    s = np.sqrt(sse / (n - 2))
    se_alpha = s * np.sqrt(1.0 / n + x_mean ** 2 / sxx)
    if se_alpha == 0.0:
        # A perfect fit (zero residual variance) — the intercept is exact; the
        # t-stat is infinite in magnitude (sign of the intercept preserved).
        t_stat = float(np.sign(alpha_periodic) * np.inf) if alpha_periodic != 0.0 else 0.0
    else:
        t_stat = alpha_periodic / se_alpha

    alpha_annual = (1.0 + alpha_periodic) ** _MONTHS_PER_YEAR - 1.0
    return AlphaResult(
        alpha=float(alpha_annual),
        alpha_periodic=float(alpha_periodic),
        t_stat=float(t_stat),
        n=n,
        start=dates[0],
        end=dates[-1],
    )


# ---------------------------------------------------------------------------
# Treynor — excess return per unit of systematic risk
# ---------------------------------------------------------------------------


def treynor(fund: ReturnSeries, benchmark: ReturnSeries, rf: ReturnSeries) -> float:
    """Treynor ratio: annualised excess return over rf, per unit of beta.

    ``(mean(r − rf) × 12) / β`` — the same arithmetic annualisation of the mean
    excess as §2 Sharpe's numerator, divided by the market :func:`beta` (rf
    aligned as a series). Fails loud when beta is zero (no systematic risk to
    normalise by). rf and benchmark align independently, so a fund/benchmark
    overlap that excludes some rf months is handled by :func:`align`.
    """
    r, f = align(fund, rf)
    if len(r) < 2:
        raise ValueError(f"treynor needs >= 2 overlapping rf periods, got {len(r)}")
    b = beta(fund, benchmark)
    if b == 0.0:
        raise ValueError("treynor undefined: beta is zero")
    return float(np.mean(r - f)) * _MONTHS_PER_YEAR / b


# ---------------------------------------------------------------------------
# Up / down capture — CAGR ratio over benchmark up / down months
# ---------------------------------------------------------------------------


def _cagr(values: _Array) -> float:
    """CAGR of a per-period return array: ``(Π(1+v))^(12/n) − 1`` (≡ empyrical)."""
    n = len(values)
    ending = float(np.prod(1.0 + values))
    return float(ending ** (_MONTHS_PER_YEAR / n) - 1.0)


def _capture(r: _Array, rb: _Array) -> float:
    """Capture ratio on a subset: ``CAGR(r)/CAGR(rb)`` (≡ ``empyrical.capture``)."""
    return _cagr(r) / _cagr(rb)


def up_capture(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Up-market capture: CAGR ratio over months the benchmark was positive.

    ≡ ``empyrical.up_capture``: filter to ``rb > 0`` months, then
    ``CAGR(r_up)/CAGR(rb_up)``. Fails loud when the benchmark never rose in the
    overlap (no up-market to capture).
    """
    r, rb = align(fund, benchmark)
    mask = rb > 0.0
    if not mask.any():
        raise ValueError("up_capture undefined: benchmark has no positive months")
    return _capture(r[mask], rb[mask])


def down_capture(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Down-market capture: CAGR ratio over months the benchmark was negative.

    ≡ ``empyrical.down_capture``: filter to ``rb < 0`` months, then
    ``CAGR(r_down)/CAGR(rb_down)``. Fails loud when the benchmark never fell in
    the overlap (no down-market to capture).
    """
    r, rb = align(fund, benchmark)
    mask = rb < 0.0
    if not mask.any():
        raise ValueError("down_capture undefined: benchmark has no negative months")
    return _capture(r[mask], rb[mask])


# ---------------------------------------------------------------------------
# Hit rate — share of months beating the benchmark
# ---------------------------------------------------------------------------


def hit_rate(fund: ReturnSeries, benchmark: ReturnSeries) -> float:
    """Fraction of overlapping months the fund strictly beat the benchmark.

    ``mean(r > rb)`` in ``[0, 1]``. A tie (``r == rb``) is not a beat.
    """
    r, rb = align(fund, benchmark)
    if len(r) < 1:
        raise ValueError("hit_rate needs >= 1 overlapping period")
    return float(np.mean(r > rb))


# ---------------------------------------------------------------------------
# Rolling-relative panels — compositions over §4's windowing machinery
# ---------------------------------------------------------------------------

#: Rolling-relative window labels → length in months. Shorter windows than the
#: §4 return panels (``spec-analytics §6``: monthly step, 1/3y — catches regime
#: shifts a since-inception beta averages away).
RELATIVE_ROLLING_WINDOWS: dict[str, int] = {"1Y": 12, "3Y": 36}


def _rolling_pair(
    fund: ReturnSeries,
    benchmark: ReturnSeries,
    window_months: int,
    fn: Callable[[ReturnSeries, ReturnSeries], float],
) -> ReturnSeries:
    """Two-series analogue of §4 :func:`~.rolling.rolling_return`'s windower.

    Steps a fixed-length window monthly over the fund↔benchmark overlap, applies
    the two-series metric ``fn`` to each paired slice, and stamps the value at the
    window's last date — the *same* stepping, empty-if-short rule, and end-date
    stamping as §4, so rolling-relative panels are not a separate rolling
    implementation, only ``fn`` differs. A window longer than the overlap emits
    an empty panel (the young-fund case, ``spec-analytics §4/§6``).
    """
    if window_months < 1:
        raise ValueError(f"window_months must be >= 1, got {window_months}")
    dates, r, rb = align_dated(fund, benchmark)
    n = len(dates)
    if n < window_months:
        return ReturnSeries(dates=(), values=np.array([], dtype=np.float64), base=fund.base)
    out_dates: list[date] = []
    out_values: list[float] = []
    for end_i in range(window_months - 1, n):
        start_i = end_i - window_months + 1
        window_dates = dates[start_i : end_i + 1]
        f_slice = ReturnSeries(dates=window_dates, values=r[start_i : end_i + 1], base=fund.base)
        b_slice = ReturnSeries(
            dates=window_dates, values=rb[start_i : end_i + 1], base=benchmark.base
        )
        out_dates.append(dates[end_i])
        out_values.append(fn(f_slice, b_slice))
    return ReturnSeries(
        dates=tuple(out_dates), values=np.array(out_values, dtype=np.float64), base=fund.base
    )


def rolling_excess_return(
    fund: ReturnSeries, benchmark: ReturnSeries, window_months: int
) -> ReturnSeries:
    """Rolling annualised active return: §4 :func:`~.rolling.rolling_return` over
    the :func:`excess_return` series.

    The direct "over the excess series" composition (``spec-analytics §6``): build
    the per-period active-return series once, then hand it to the *same* §4 rolling
    machinery used for absolute rolling returns — no bespoke rolling loop. Equal by
    construction to ``rolling.rolling_return(excess_return(fund, benchmark), w)``.
    """
    return rolling_return(excess_return(fund, benchmark), window_months)


def rolling_beta(
    fund: ReturnSeries, benchmark: ReturnSeries, window_months: int
) -> ReturnSeries:
    """Rolling market :func:`beta`, monthly step, over a fixed window."""
    return _rolling_pair(fund, benchmark, window_months, beta)


def rolling_correlation(
    fund: ReturnSeries, benchmark: ReturnSeries, window_months: int
) -> ReturnSeries:
    """Rolling :func:`correlation`, monthly step, over a fixed window."""
    return _rolling_pair(fund, benchmark, window_months, correlation)


def rolling_betas(
    fund: ReturnSeries, benchmark: ReturnSeries
) -> dict[str, ReturnSeries]:
    """Rolling beta for all standard relative windows (1Y/3Y), each empty if young."""
    return {
        label: rolling_beta(fund, benchmark, months)
        for label, months in RELATIVE_ROLLING_WINDOWS.items()
    }


def rolling_correlations(
    fund: ReturnSeries, benchmark: ReturnSeries
) -> dict[str, ReturnSeries]:
    """Rolling correlation for all standard relative windows (1Y/3Y)."""
    return {
        label: rolling_correlation(fund, benchmark, months)
        for label, months in RELATIVE_ROLLING_WINDOWS.items()
    }
