"""B1 identity checker — post-assembly self-consistency cross-checks.

Verifies that a fund's already-written per-window metrics are internally
consistent with their own reported inputs: Sharpe/IR/alpha as a function of
the return/volatility/tracking-error/beta figures the *same* row already
carries. This is the class of bug the pre-fix site shipped once already
(fund 118424: a published Sharpe/IR/alpha that could not have come from the
published return/vol/beta/tracking-error alongside it) — ``check_identities``
is a permanent regression guard against it recurring silently, wired into the
flexipage runner (``report/flexipage/runner.py``) so a future assembly bug
fails the build rather than reaching a rendered page.

Not a numerical-accuracy re-derivation: the tolerances below are deliberately
loose (CLAUDE.md — arithmetic-vs-geometric compounding slack, per-metric
overlap differences), tuned to catch percentage-point-scale breaks, never
rounding. Never tightened or loosened at runtime to make a check pass or fail.

Not a null check either: a window whose inputs include a ``None`` is skipped
outright, never reported as a violation — an absent input is
``InsufficientHistoryError``'s business (``analytics/series_ops.py``), not
this module's.

Field values are read as the artifact actually stores them (fractions, e.g.
``0.0218`` for 2.18%) — ``excess`` is always derived here as
``fund_return - benchmark_return`` rather than trusted off a separately
stored excess field, so the identity cross-checks the artifact's storage of
``benchmark_return``/``fund_return`` too, not just its arithmetic.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Trailing windows the identity checks run over (mirrors spec-flexicap-page's
#: 1Y/3Y/5Y relative-metric windows).
_WINDOWS: tuple[str, ...] = ("1Y", "3Y", "5Y")

#: Fixed tolerances (CLAUDE.md validation discipline: never loosened at
#: runtime). Sharpe/IR are dimensionless ratios; alpha's is expressed as a
#: fraction (the same units as the return-like fields it combines).
_SHARPE_TOL = 0.15
_IR_TOL = 0.15
#: simulation-calibrated: CAGR-vs-arithmetic convention slack p90 ≈ 2.2pp at
#: 1Y; guarded defect class ≥ 5pp (site regression, fund 118424).
_ALPHA_TOL = 0.03


@dataclass(frozen=True)
class IdentityViolation:
    """One identity that failed to reconcile, for one fund/window."""

    amfi_code: str
    window: str  # "1Y", "3Y", "5Y"
    identity: str  # "sharpe", "alpha", "ir"
    lhs: float  # the reported value
    rhs: float  # the value predicted from the row's other reported fields
    gap: float  # abs(lhs - rhs)


def _metric(row: Mapping[str, Any], key: str) -> float | None:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _alpha_value(row: Mapping[str, Any], window: str) -> float | None:
    alpha = row.get("alpha")
    if not isinstance(alpha, Mapping):
        return None
    entry = alpha.get(f"alpha_{window}")
    if not isinstance(entry, Mapping):
        return None
    value = entry.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def check_identities(row: Mapping[str, Any]) -> list[IdentityViolation]:
    """Check the sharpe/ir/alpha identities for one fund's assembled row.

    ``row`` is one entry of the flexipage artifact's ``funds`` list (the
    shape ``report.flexipage.assembly.assemble_universe`` writes): a mapping
    carrying ``amfi_code``, a flat ``metrics`` map (``return_1Y``,
    ``volatility_1Y``, ``benchmark_return_1Y``, ``rf_1Y``, ... per window),
    and an ``alpha`` map of per-window ``{"value": ..., "t_stat": ..., ...}``
    objects. Any window where a needed field is absent/``None`` is skipped
    for that identity — never flagged.
    """
    amfi_code = str(row.get("amfi_code", ""))
    violations: list[IdentityViolation] = []

    for window in _WINDOWS:
        fund_return = _metric(row, f"return_{window}")
        volatility = _metric(row, f"volatility_{window}")
        sharpe_reported = _metric(row, f"sharpe_{window}")
        benchmark_return = _metric(row, f"benchmark_return_{window}")
        beta = _metric(row, f"beta_{window}")
        tracking_error = _metric(row, f"tracking_error_{window}")
        ir_reported = _metric(row, f"information_ratio_{window}")
        rf_return = _metric(row, f"rf_{window}")
        alpha_reported = _alpha_value(row, window)

        if (
            fund_return is not None
            and rf_return is not None
            and volatility is not None
            and sharpe_reported is not None
            and volatility != 0.0
        ):
            predicted = (fund_return - rf_return) / volatility
            gap = abs(sharpe_reported - predicted)
            if gap > _SHARPE_TOL:
                violations.append(
                    IdentityViolation(
                        amfi_code, window, "sharpe", sharpe_reported, predicted, gap
                    )
                )

        if (
            fund_return is not None
            and benchmark_return is not None
            and tracking_error is not None
            and ir_reported is not None
            and tracking_error != 0.0
        ):
            predicted = (fund_return - benchmark_return) / tracking_error
            gap = abs(ir_reported - predicted)
            if gap > _IR_TOL:
                violations.append(
                    IdentityViolation(amfi_code, window, "ir", ir_reported, predicted, gap)
                )

        if (
            fund_return is not None
            and benchmark_return is not None
            and beta is not None
            and rf_return is not None
            and alpha_reported is not None
        ):
            excess = fund_return - benchmark_return
            predicted = excess + (1.0 - beta) * (benchmark_return - rf_return)
            gap = abs(alpha_reported - predicted)
            if gap > _ALPHA_TOL:
                violations.append(
                    IdentityViolation(
                        amfi_code, window, "alpha", alpha_reported, predicted, gap
                    )
                )

    return violations
