"""§5 metrics artifact — MetricsResult shape, serialisation, null propagation.

Covers the §5 acceptance surface: the artifact round-trips serialise→deserialise
and re-serialises identically (determinism); ``schema_version`` is present; a
young fund yields explicit nulls (never errors) where history is too short; and
rolling panels are keyed by window-end month-end dates. Figures are checked
against the pure functions so the artifact carries the computed values verbatim.
"""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date

import numpy as np

from foliolens.analytics import (
    SCHEMA_VERSION,
    MetricsResult,
    SeriesPoint,
    build_metrics,
    max_drawdown_of,
    rolling_return,
    sharpe,
    skew,
    volatility,
)
from foliolens.analytics.metrics import period_return_abs
from foliolens.analytics.series_ops import between
from foliolens.model.investments import ShareClass, SeriesInvestment
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.frequency import Frequency
from fixtures import daily_shareclass, returns_series


def _is_month_end(d: date) -> bool:
    return d.day == monthrange(d.year, d.month)[1]


def _healthy_fund() -> ShareClass:
    # 1828 days from 2022-12-31 (the pre-period NAV base date) -> exactly 60
    # monthly RETURN points, 2023-01-31 .. 2027-12-31 -- populates every
    # 1Y/3Y/5Y window. Built via the real factory (daily_shareclass ->
    # share_class_from_nav) so it carries both DAILY and MONTHLY panels, like
    # every production Investment: a hand-rolled SeriesInvestment with only a
    # MONTHLY panel is fixture debt, not a case build_metrics should ever
    # silently null (a missing panel is a construction bug and stays loud --
    # B3 amendment).
    rng = np.random.default_rng(42)
    levels = 100.0 * np.cumprod(1.0 + rng.normal(0.01, 0.04, 1828))
    return daily_shareclass(levels, start=date(2022, 12, 31), id="HEALTHY")


def _rf(n: int = 60) -> SeriesInvestment:
    monthly_r = (1.06) ** (1 / 12) - 1
    return SeriesInvestment(
        id="rf", returns_series=returns_series(np.full(n, monthly_r))
    )


def _rf_for(rs: ReturnSeries) -> SeriesInvestment:
    """rf on exactly ``rs``'s dates — for fixtures not anchored at ``_rf()``'s
    canonical 2023-01 start (e.g. the young fund below)."""
    monthly_r = (1.06) ** (1 / 12) - 1
    return SeriesInvestment(
        id="rf",
        returns_series=ReturnSeries(
            dates=rs.dates, values=np.full(len(rs), monthly_r), frequency=rs.frequency
        ),
    )


def _young_fund() -> ShareClass:
    # 95 days from 2024-01-01 -> exactly 2 monthly RETURN points
    # (2024-02-29, 2024-03-31): short enough that every 1Y/3Y/5Y window and
    # skew/kurtosis (need >= 3 / >= 4) are genuinely absent/insufficient, but
    # a real ShareClass (both panels, via the factory) so the daily-basis
    # family is never a missing-panel construction bug.
    rng = np.random.default_rng(3)
    levels = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.02, 95))
    return daily_shareclass(levels, start=date(2024, 1, 1), id="YOUNG")


# ---------------------------------------------------------------------------
# Shape + schema version
# ---------------------------------------------------------------------------


def test_schema_version_present() -> None:
    mr = build_metrics(_healthy_fund(), _rf())
    assert mr.schema_version == SCHEMA_VERSION
    assert mr.to_dict()["schema_version"] == SCHEMA_VERSION


def test_artifact_top_level_shape() -> None:
    d = build_metrics(_healthy_fund(), _rf()).to_dict()
    assert set(d) == {"schema_version", "metadata", "metrics", "series", "refused"}
    assert d["metadata"]["id"] == "HEALTHY"
    assert d["metadata"]["as_of"] == "2027-12-31"


def test_metadata_merge_is_caller_authoritative() -> None:
    mr = build_metrics(
        _healthy_fund(), _rf(), metadata={"scheme_name": "Test Flexi Cap"}
    )
    assert mr.metadata["scheme_name"] == "Test Flexi Cap"
    assert mr.metadata["id"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Values carried verbatim from the pure functions
# ---------------------------------------------------------------------------


def test_metrics_carry_computed_values() -> None:
    fund, rf = _healthy_fund(), _rf()
    rs = fund.returns(Frequency.MONTHLY)
    mr = build_metrics(fund, rf)
    assert mr.metrics["volatility_SI"] == volatility(rs)
    assert mr.metrics["sharpe_SI"] == sharpe(rs, rf.returns(Frequency.MONTHLY))
    assert mr.metrics["skew_SI"] == skew(rs)
    # Windowed metric == the pure function on the trailing slice.
    last12 = ReturnSeries(
        dates=rs.dates[-12:], values=rs.values[-12:], frequency=rs.frequency, base=rs.base
    )
    assert mr.metrics["volatility_1Y"] == volatility(last12)


def test_figures_of_record_merged_verbatim() -> None:
    # Trailing CAGRs (figures of record) are referenced, not recomputed: the
    # caller's values land in the flat metrics map unchanged.
    fof = {"return_1Y": 0.1834, "return_3Y": 0.2015, "return_5Y": None}
    mr = build_metrics(_healthy_fund(), _rf(), figures_of_record=fof)
    assert mr.metrics["return_1Y"] == 0.1834
    assert mr.metrics["return_3Y"] == 0.2015
    assert mr.metrics["return_5Y"] is None


def test_return_ytd_matches_between_window() -> None:
    fund = _healthy_fund()
    rs = fund.returns(Frequency.MONTHLY)
    mr = build_metrics(fund, _rf())
    ytd_window = between(rs, date(2027, 1, 1), date(2027, 12, 31))
    assert mr.metrics["return_YTD"] == period_return_abs(
        ytd_window, ytd_window.dates[0], ytd_window.dates[-1]
    )


# ---------------------------------------------------------------------------
# Rolling series keyed by window-end month-end dates
# ---------------------------------------------------------------------------


def test_rolling_series_keyed_by_month_end() -> None:
    fund = _healthy_fund()
    rs = fund.returns(Frequency.MONTHLY)
    mr = build_metrics(fund, _rf())
    panel = mr.series["rolling_return_1Y"]
    want = rolling_return(rs, 12)
    assert tuple(p.date for p in panel) == want.dates
    assert all(_is_month_end(p.date) for p in panel)
    assert [p.value for p in panel] == list(want.values)


def test_rolling_series_all_windows_present() -> None:
    mr = build_metrics(_healthy_fund(), _rf())
    for label in ("1Y", "3Y", "5Y"):
        assert f"rolling_return_{label}" in mr.series


# ---------------------------------------------------------------------------
# Round-trip + determinism
# ---------------------------------------------------------------------------


def test_dict_round_trip_equal() -> None:
    mr = build_metrics(_healthy_fund(), _rf(), metadata={"fund_house": "ACME"})
    assert MetricsResult.from_dict(mr.to_dict()) == mr


def test_json_round_trip_equal() -> None:
    mr = build_metrics(_healthy_fund(), _rf())
    # allow_nan stays False: non-finite metrics are already mapped to null.
    text = json.dumps(mr.to_dict(), allow_nan=False)
    assert MetricsResult.from_dict(json.loads(text)) == mr


def test_serialisation_is_deterministic() -> None:
    fund, rf = _healthy_fund(), _rf()
    assert build_metrics(fund, rf).to_dict() == build_metrics(fund, rf).to_dict()


def test_series_point_round_trip() -> None:
    p = SeriesPoint(date=date(2025, 6, 30), value=0.1234)
    assert SeriesPoint.from_dict(p.to_dict()) == p


# ---------------------------------------------------------------------------
# Null propagation — young fund yields nulls, never errors
# ---------------------------------------------------------------------------


def test_young_fund_nulls_not_errors() -> None:
    # Two monthly points only: 1Y/3Y/5Y windows and skew/kurtosis null.
    young = _young_fund()
    rs = young.returns(Frequency.MONTHLY)
    mr = build_metrics(young, _rf_for(rs))
    m = mr.metrics
    # Windows longer than history → null.
    for label in ("1Y", "3Y", "5Y"):
        assert m[f"volatility_{label}"] is None
        assert m[f"sharpe_{label}"] is None
    # Statistics needing more points than exist → null.
    assert m["skew_SI"] is None       # needs >= 3
    assert m["kurtosis_SI"] is None   # needs >= 4
    # Sub-year windows longer than history → null.
    assert m["return_3M"] is None
    assert m["return_6M"] is None
    # Daily-basis family reads the fund's real (if short) daily NAV -- a
    # young fund still has *some* daily history, so these populate rather
    # than null (null-propagation is history-specific, never a blanket
    # "young == null everywhere"; a genuinely source-less investment is
    # fixture debt per _healthy_fund's docstring, not a case this family
    # nulls in production, where every Investment carries both panels).
    assert m["max_drawdown_SI"] is not None
    assert m["var95_SI"] is not None
    assert m["cvar95_SI"] is not None
    # What IS computable stays populated (not nulled indiscriminately).
    assert m["volatility_SI"] is not None   # 2 points is enough for volatility
    assert m["return_1M"] is not None


def test_refused_populated_for_insufficient_history_metrics() -> None:
    # Only 2 monthly points -> skew (needs >= 3) / kurtosis (needs >= 4) and
    # every 1Y/3Y/5Y window (needs 12/36/60) raise InsufficientHistoryError.
    young = _young_fund()
    rs = young.returns(Frequency.MONTHLY)
    mr = build_metrics(young, _rf_for(rs))

    assert mr.metrics["skew_SI"] is None
    assert mr.metrics["kurtosis_SI"] is None
    assert mr.refused["skew_SI"] == "insufficient_history(required=3, available=2)"
    assert mr.refused["kurtosis_SI"] == "insufficient_history(required=4, available=2)"
    # A metric nulled for a different reason (window absent, never even
    # calling the metric function) carries no refused entry.
    assert mr.metrics["volatility_1Y"] is None
    assert "volatility_1Y" not in mr.refused


def test_young_fund_rolling_panels_empty() -> None:
    young = _young_fund()
    mr = build_metrics(young, _rf_for(young.returns(Frequency.MONTHLY)))
    for label in ("1Y", "3Y", "5Y"):
        assert mr.series[f"rolling_return_{label}"] == ()


def test_source_backed_daily_metrics_populate() -> None:
    # A NAV-priced investment (has .source) → the daily-basis family is computed,
    # not nulled: null-propagation is absence-specific, not blanket.
    rng = np.random.default_rng(7)
    levels = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 200))
    sc = daily_shareclass(levels)
    mr = build_metrics(sc, _rf())
    assert mr.metrics["max_drawdown_SI"] == max_drawdown_of(sc)
    assert mr.metrics["var95_SI"] is not None
    assert mr.metrics["cvar95_SI"] is not None


def test_young_fund_round_trips() -> None:
    young = _young_fund()
    mr = build_metrics(young, _rf_for(young.returns(Frequency.MONTHLY)))
    text = json.dumps(mr.to_dict(), allow_nan=False)
    assert MetricsResult.from_dict(json.loads(text)) == mr
