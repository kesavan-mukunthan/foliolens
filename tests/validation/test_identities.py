"""B1 identity checker — cross-checks a fund's post-assembly metrics against
their own reported inputs (Sharpe/IR/alpha as a function of return/vol/
tracking-error/beta the *same* row already carries).

``test_old_published_118424_values_violate_all_three_identities`` is the
permanent regression record of the pre-fix site bug (fund 118424, 1Y window):
it must never be deleted or "fixed" by editing the hardcoded numbers.
"""
from __future__ import annotations

from foliolens.validation.identities import _ratio_tolerance, check_identities


def test_old_published_118424_values_violate_all_three_identities() -> None:
    # OLD published values for fund 118424, 1Y window, taken verbatim from
    # the pre-fix site (annualised, %): return 2.18, volatility 15.81,
    # sharpe 0.81, benchmark_return 0.48, beta 0.90, alpha -4.81,
    # tracking_error 2.33, ir -2.08, rf 7.00. Stored below as fractions
    # (the published % ÷ 100) — the units the artifact actually emits and
    # the units the identities.py tolerances are calibrated against; the
    # numbers themselves are unchanged from what was published.
    row = {
        "amfi_code": "118424",
        "metrics": {
            "return_1Y": 2.18 / 100,
            "volatility_1Y": 15.81 / 100,
            "sharpe_1Y": 0.81,
            "benchmark_return_1Y": 0.48 / 100,
            "beta_1Y": 0.90,
            "tracking_error_1Y": 2.33 / 100,
            "information_ratio_1Y": -2.08,
            "rf_1Y": 7.00 / 100,
        },
        "alpha": {"alpha_1Y": {"value": -4.81 / 100}},
    }

    violations = check_identities(row)
    by_identity = {v.identity: v for v in violations}

    assert {"sharpe", "ir", "alpha"} == set(by_identity)
    for v in violations:
        assert v.amfi_code == "118424"
        assert v.window == "1Y"

    # Still fails at the scaled tolerances, not just the old flat ones: the
    # gaps clear _ratio_tolerance computed from this row's own volatility/TE.
    assert by_identity["sharpe"].gap > _ratio_tolerance(15.81 / 100)
    assert by_identity["ir"].gap > _ratio_tolerance(2.33 / 100)
    assert by_identity["alpha"].gap > 0.04  # 4 pp, expressed as a fraction


def test_null_input_is_skipped_never_flagged() -> None:
    # A young fund: fund_return is null for 1Y -> the sharpe/ir/alpha checks
    # for that window are skipped entirely, never reported as a violation.
    row = {
        "amfi_code": "999999",
        "metrics": {
            "return_1Y": None,
            "volatility_1Y": 0.1581,
            "sharpe_1Y": 0.81,
            "benchmark_return_1Y": 0.0048,
            "beta_1Y": 0.90,
            "tracking_error_1Y": 0.0233,
            "information_ratio_1Y": -2.08,
            "rf_1Y": 0.07,
        },
        "alpha": {"alpha_1Y": None},
    }
    assert check_identities(row) == []


def test_low_tracking_error_row_passes_scaled_but_would_fail_flat() -> None:
    # Regression record of the D-run stop: the flat 0.15 IR tolerance
    # aborted a real flexipage build with 59 identity violations, every one
    # a low-tracking-error fund of exactly this shape -- a close
    # benchmark-hugging fund with tracking_error ~= 2%. A ~1pp numerator
    # convention gap (the same class of arithmetic/day-count slack
    # _ALPHA_TOL already budgets for) divides through this small denominator
    # into an IR gap of ~0.5 -- comfortably inside the scaled tolerance
    # (0.03 / 0.02 = 1.5) but well outside the old flat 0.15. This is the
    # shape of fund that the flat tolerance over-flagged in production
    # before the scaled tolerance landed.
    fund_return, rf_return, volatility = 0.10, 0.06, 0.15
    benchmark_return, tracking_error, beta = 0.09, 0.02, 0.95
    sharpe = (fund_return - rf_return) / volatility
    alpha = (fund_return - benchmark_return) + (1.0 - beta) * (benchmark_return - rf_return)
    true_ir = (fund_return - benchmark_return) / tracking_error
    reported_ir = true_ir - (0.01 / tracking_error)  # 1pp numerator convention gap

    row = {
        "amfi_code": "TE0002",
        "metrics": {
            "return_1Y": fund_return,
            "volatility_1Y": volatility,
            "sharpe_1Y": sharpe,
            "benchmark_return_1Y": benchmark_return,
            "beta_1Y": beta,
            "tracking_error_1Y": tracking_error,
            "information_ratio_1Y": reported_ir,
            "rf_1Y": rf_return,
        },
        "alpha": {"alpha_1Y": {"value": alpha}},
    }

    gap = abs(reported_ir - true_ir)
    assert gap > 0.15  # would have failed the old flat IR tolerance
    assert gap < _ratio_tolerance(tracking_error)  # passes the new scaled tolerance
    assert check_identities(row) == []


def test_internally_consistent_row_yields_no_violations() -> None:
    fund_return, rf_return, volatility = 0.10, 0.06, 0.15
    benchmark_return, tracking_error, beta = 0.08, 0.03, 0.95
    sharpe = (fund_return - rf_return) / volatility
    ir = (fund_return - benchmark_return) / tracking_error
    alpha = (fund_return - benchmark_return) + (1.0 - beta) * (benchmark_return - rf_return)

    row = {
        "amfi_code": "AAAA01",
        "metrics": {
            "return_1Y": fund_return,
            "volatility_1Y": volatility,
            "sharpe_1Y": sharpe,
            "benchmark_return_1Y": benchmark_return,
            "beta_1Y": beta,
            "tracking_error_1Y": tracking_error,
            "information_ratio_1Y": ir,
            "rf_1Y": rf_return,
        },
        "alpha": {"alpha_1Y": {"value": alpha}},
    }
    assert check_identities(row) == []
