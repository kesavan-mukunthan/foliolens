"""Unit + delegation behaviour for §6 benchmark-relative metrics.

Two things beyond the oracle suite: (1) every ``*_of`` adapter equals its pure
function over the Investments' ``.returns`` (adapters compute nothing beyond
delegation, ``spec-analytics §5``), including the stored-default-benchmark read;
and (2) the rolling-relative panels are compositions over §4's windowing — equal
by construction to the pure machinery, monthly step, empty when history is short.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from foliolens.analytics import adapters, relative
from foliolens.analytics.rolling import rolling_return
from foliolens.model.holdings import Holding
from foliolens.model.investments import Investment, SeriesInvestment
from foliolens.model.sources import ReturnSource
from foliolens.model.value_objects import ReturnSeries
from fixtures import fixed_investment, rf_investment, returns_series

_FUND_VALUES = [((i % 5) - 1) / 100.0 for i in range(36)]
_BENCH_VALUES = [((i % 5) - 1) / 100.0 * 0.8 + ((i % 4) - 1.5) / 500.0 for i in range(36)]


@dataclass(frozen=True)
class _Fund:
    """Minimal Investment carrying a returns series and a stored benchmark."""

    id: str
    returns: ReturnSeries
    benchmark: Investment | None

    @property
    def holdings(self) -> tuple[Holding, ...]:
        return ()

    @property
    def source(self) -> ReturnSource:
        raise NotImplementedError("_Fund is return-space only")


def _fund_inv() -> SeriesInvestment:
    return fixed_investment(_FUND_VALUES, id="fund")


def _bench_inv() -> SeriesInvestment:
    return fixed_investment(_BENCH_VALUES, id="bench")


# ---------------------------------------------------------------------------
# Delegation equality — adapter(explicit benchmark) == pure(.returns)
# ---------------------------------------------------------------------------


def test_scalar_adapters_delegate_exactly() -> None:
    fund, bench, rf = _fund_inv(), _bench_inv(), rf_investment()
    f, b, rfr = fund.returns, bench.returns, rf.returns

    assert adapters.beta_of(fund, bench) == relative.beta(f, b)
    assert adapters.correlation_of(fund, bench) == relative.correlation(f, b)
    assert adapters.r_squared_of(fund, bench) == relative.r_squared(f, b)
    assert adapters.tracking_error_of(fund, bench) == relative.tracking_error(f, b)
    assert adapters.information_ratio_of(fund, bench) == relative.information_ratio(f, b)
    assert adapters.up_capture_of(fund, bench) == relative.up_capture(f, b)
    assert adapters.down_capture_of(fund, bench) == relative.down_capture(f, b)
    assert adapters.hit_rate_of(fund, bench) == relative.hit_rate(f, b)
    assert adapters.treynor_of(fund, rf, bench) == relative.treynor(f, b, rfr)


def test_alpha_adapter_delegates_exactly() -> None:
    fund, bench, rf = _fund_inv(), _bench_inv(), rf_investment()
    own = adapters.jensens_alpha_of(fund, rf, bench)
    pure = relative.jensens_alpha(fund.returns, bench.returns, rf.returns)
    assert own == pure  # AlphaResult is a frozen dataclass → structural equality


def test_excess_return_adapter_delegates_exactly() -> None:
    fund, bench = _fund_inv(), _bench_inv()
    own = adapters.excess_return_of(fund, bench)
    pure = relative.excess_return(fund.returns, bench.returns)
    assert own.dates == pure.dates
    assert np.array_equal(own.values, pure.values)


# ---------------------------------------------------------------------------
# Stored-default benchmark — fund→benchmark default, overridable per call
# ---------------------------------------------------------------------------


def test_adapter_uses_stored_benchmark_by_default() -> None:
    bench = _bench_inv()
    fund = _Fund(id="fund", returns=returns_series(_FUND_VALUES), benchmark=bench)
    # No explicit benchmark → reads investment.benchmark.
    assert adapters.beta_of(fund) == relative.beta(fund.returns, bench.returns)


def test_adapter_override_beats_stored_benchmark() -> None:
    stored = _bench_inv()
    override = fixed_investment([((i % 3) - 1) / 100.0 for i in range(36)], id="other")
    fund = _Fund(id="fund", returns=returns_series(_FUND_VALUES), benchmark=stored)
    assert adapters.beta_of(fund, override) == relative.beta(fund.returns, override.returns)
    assert adapters.beta_of(fund, override) != adapters.beta_of(fund)


def test_adapter_no_benchmark_raises() -> None:
    fund = _Fund(id="fund", returns=returns_series(_FUND_VALUES), benchmark=None)
    with pytest.raises(ValueError, match="no benchmark"):
        adapters.beta_of(fund)


# ---------------------------------------------------------------------------
# Rolling-relative panels — compositions over §4's windowing machinery
# ---------------------------------------------------------------------------


def test_rolling_excess_return_is_rolling_over_excess_series() -> None:
    fund, bench = returns_series(_FUND_VALUES), returns_series(_BENCH_VALUES)
    composed = relative.rolling_excess_return(fund, bench, 12)
    direct = rolling_return(relative.excess_return(fund, bench), 12)
    assert composed.dates == direct.dates
    assert np.array_equal(composed.values, direct.values)


def test_rolling_beta_monthly_step_and_stamping() -> None:
    fund, bench = returns_series(_FUND_VALUES), returns_series(_BENCH_VALUES)
    panel = relative.rolling_beta(fund, bench, 12)
    # 36 months, 12-month window, monthly step → 25 points, stamped at window ends.
    assert len(panel) == 36 - 12 + 1
    assert panel.dates[-1] == fund.dates[-1]
    # Each point equals beta over its own trailing 12-month slice.
    from foliolens.analytics.series_ops import between

    last = relative.beta(
        between(fund, fund.dates[-12], fund.dates[-1]),
        between(bench, bench.dates[-12], bench.dates[-1]),
    )
    assert panel.values[-1] == pytest.approx(last, abs=1e-12)


def test_rolling_correlation_delegates() -> None:
    fund, bench = _fund_inv(), _bench_inv()
    own = adapters.rolling_correlation_of(fund, 12, bench)
    pure = relative.rolling_correlation(fund.returns, bench.returns, 12)
    assert own.dates == pure.dates
    assert np.array_equal(own.values, pure.values)


def test_rolling_beta_empty_when_window_exceeds_history() -> None:
    # 6-month young fund, 12-month window → empty panel (never padded/partial).
    fund = returns_series(_FUND_VALUES[:6])
    bench = returns_series(_BENCH_VALUES[:6])
    panel = relative.rolling_beta(fund, bench, 12)
    assert len(panel) == 0


def test_rolling_bundles_cover_relative_windows() -> None:
    fund, bench = returns_series(_FUND_VALUES), returns_series(_BENCH_VALUES)
    betas = relative.rolling_betas(fund, bench)
    assert set(betas) == set(relative.RELATIVE_ROLLING_WINDOWS)
    # 36 months: 1Y populated, 3Y populated (exactly one point).
    assert len(betas["1Y"]) == 25
    assert len(betas["3Y"]) == 1


# ---------------------------------------------------------------------------
# Composition identities — Treynor / R² are built from the pinned primitives
# ---------------------------------------------------------------------------


def test_treynor_composition_identity() -> None:
    fund, bench = returns_series(_FUND_VALUES), returns_series(_BENCH_VALUES)
    rf = rf_investment().returns
    from foliolens.analytics.series_ops import align

    r, f = align(fund, rf)
    expected = float(np.mean(r - f)) * 12.0 / relative.beta(fund, bench)
    assert relative.treynor(fund, bench, rf) == pytest.approx(expected, abs=1e-12)


def test_r_squared_is_correlation_squared() -> None:
    fund, bench = returns_series(_FUND_VALUES), returns_series(_BENCH_VALUES)
    rho = relative.correlation(fund, bench)
    assert relative.r_squared(fund, bench) == pytest.approx(rho * rho, abs=1e-15)
