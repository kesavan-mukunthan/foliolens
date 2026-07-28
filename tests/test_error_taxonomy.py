"""B3 error taxonomy — null (``InsufficientHistoryError``) vs refused (everything
else propagates).

RED test (``test_bare_value_error_propagates_uncaught_from_build``): today
``_null_safe`` swallows every ``ValueError`` (and ``NotImplementedError``)
indiscriminately, so a bare ``ValueError`` from a metric's non-length guard
(frequency mismatch) is silently nulled instead of failing loud — this
assertion fails on current main. ``InsufficientHistoryError`` already yields
null today too (it *is* a ``ValueError``, so the current broad catch already
nets it) and must keep doing so once the catch is narrowed.
"""
from __future__ import annotations

import numpy as np
import pytest

from foliolens.analytics.artifact import _null_safe, build_metrics
from foliolens.analytics.series_ops import InsufficientHistoryError
from foliolens.model.value_objects import ReturnSeries
from foliolens.returns.frequency import Frequency
from fixtures import fixed_investment, month_end_dates


class _BadFrequencyRF:
    """A stand-in ``rf`` Investment whose ``.returns`` mislabels its series as
    DAILY regardless of the requested frequency — triggers the genuine
    frequency-mismatch ``ValueError`` inside ``align`` deep in a two-series
    metric (``downside_deviation``/``sharpe``/``sortino``), never an
    ``InsufficientHistoryError`` (this guard concerns declared frequency, not
    point count, so it must never migrate — CLAUDE.md's B3 classification).
    """

    id = "bad-rf"

    def returns(self, freq: Frequency) -> ReturnSeries:  # noqa: ARG002
        return ReturnSeries(
            dates=month_end_dates(60), values=np.zeros(60), frequency=Frequency.DAILY
        )


def test_bare_value_error_propagates_uncaught_from_build() -> None:
    fund = fixed_investment(np.random.default_rng(1).normal(0.01, 0.03, 60).tolist())
    with pytest.raises(ValueError, match="frequency mismatch"):
        build_metrics(fund, _BadFrequencyRF())  # type: ignore[arg-type]


def test_insufficient_history_error_yields_null_via_null_safe() -> None:
    def boom() -> float:
        raise InsufficientHistoryError(required=36, available=14)

    assert _null_safe(boom) is None
