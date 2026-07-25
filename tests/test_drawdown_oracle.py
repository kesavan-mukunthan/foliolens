"""Own-vs-oracle acceptance for §3 daily-basis metrics — the spec-analytics §3 gate.

Oracle = empyrical-reloaded: ``max_drawdown`` for drawdown, ``value_at_risk`` /
``conditional_value_at_risk`` (cutoff 0.05 → 95%) for tail risk. Tolerance is the
value recorded in spec-analytics §3: own↔oracle relative ≤ 1e-6 on a frozen
fixture. The family is computed on **daily** returns (via the daily adapter and
directly on a daily-derived ``ReturnSeries``); no published or live series enters.

VaR/CVaR are checked per-period — the fixture is daily and the figures stay daily
quantities; nothing here annualises them.
"""
from __future__ import annotations

import empyrical

from foliolens.analytics.drawdown import (
    _daily_returns,
    cvar,
    cvar_of,
    max_drawdown,
    max_drawdown_of,
    var_historical,
    var_historical_of,
)
from fixtures import daily_shareclass

_REL = 1e-6

# 40 daily NAV points with drawdowns of varied depth and one full recovery, so
# max drawdown, the 5% VaR quantile, and the CVaR tail are all non-trivial.
_NAVS = [
    100.0, 101.5, 103.0, 102.2, 99.8, 97.5, 98.9, 101.1, 104.3, 106.0,
    105.2, 103.7, 100.4, 96.1, 94.8, 95.9, 98.2, 100.7, 102.9, 101.0,
    99.3, 97.0, 93.5, 91.2, 92.8, 95.4, 98.1, 100.6, 103.2, 105.9,
    107.1, 106.3, 104.0, 102.5, 104.8, 107.7, 109.2, 108.1, 110.5, 112.0,
]


def _rel_close(own: float, oracle: float) -> bool:
    return abs(own - oracle) <= _REL * abs(oracle)


def test_max_drawdown_vs_oracle() -> None:
    sc = daily_shareclass(_NAVS)
    oracle = empyrical.max_drawdown(_daily_returns(sc).values)
    assert _rel_close(max_drawdown_of(sc), float(oracle))


def test_max_drawdown_pure_vs_oracle() -> None:
    sc = daily_shareclass(_NAVS)
    r = _daily_returns(sc)
    oracle = empyrical.max_drawdown(r.values)
    assert _rel_close(max_drawdown(r), float(oracle))


def test_var_historical_vs_oracle() -> None:
    sc = daily_shareclass(_NAVS)
    r = _daily_returns(sc)
    oracle = empyrical.value_at_risk(r.values, cutoff=0.05)
    assert _rel_close(var_historical_of(sc), float(oracle))
    assert _rel_close(var_historical(r), float(oracle))


def test_cvar_vs_oracle() -> None:
    sc = daily_shareclass(_NAVS)
    r = _daily_returns(sc)
    oracle = empyrical.conditional_value_at_risk(r.values, cutoff=0.05)
    assert _rel_close(cvar_of(sc), float(oracle))
    assert _rel_close(cvar(r), float(oracle))
