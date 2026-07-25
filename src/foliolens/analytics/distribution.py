"""§4 distribution statistics over ``ReturnSeries`` — % positive, best/worst,
skew, kurtosis.

Pure and periodicity-agnostic over the monthly analytical series, mirroring
§2. Skew and kurtosis use the bias-corrected (sample) estimators — the
Fisher-Pearson adjusted skewness and Fisher's adjusted excess kurtosis — which
match ``pandas.Series.skew()`` / ``.kurt()`` and
``scipy.stats.skew(..., bias=False)`` / ``scipy.stats.kurtosis(..., bias=False)``
to within the analytics 1e-6 tolerance. Kurtosis is reported as *excess*
kurtosis (0 for a normal distribution), the standard financial convention.
"""
from __future__ import annotations

import numpy as np

from foliolens.model.value_objects import ReturnSeries


def pct_positive(rs: ReturnSeries) -> float:
    """Fraction of periods with a strictly positive return, in ``[0, 1]``.

    A zero return does not count as positive (it is not a gain).
    """
    if len(rs) < 1:
        raise ValueError("pct_positive needs >= 1 return")
    return float(np.mean(rs.values > 0.0))


def best_period(rs: ReturnSeries) -> float:
    """The single largest per-period return in the series."""
    if len(rs) < 1:
        raise ValueError("best_period needs >= 1 return")
    return float(np.max(rs.values))


def worst_period(rs: ReturnSeries) -> float:
    """The single smallest (most negative) per-period return in the series."""
    if len(rs) < 1:
        raise ValueError("worst_period needs >= 1 return")
    return float(np.min(rs.values))


def skew(rs: ReturnSeries) -> float:
    """Sample skewness (bias-corrected Fisher-Pearson ``G1``).

    ``G1 = sqrt(n(n-1))/(n-2) · m3/m2^1.5`` where ``m2``/``m3`` are the 2nd/3rd
    central moments about the mean (population, denominator ``n``). Matches
    ``pandas.Series.skew()`` / ``scipy.stats.skew(bias=False)``. Requires
    ``n >= 3`` (the ``n-2`` denominator is undefined below that).
    """
    n = len(rs)
    if n < 3:
        raise ValueError(f"skew needs >= 3 returns, got {n}")
    values = rs.values
    deviations = values - np.mean(values)
    m2 = float(np.mean(deviations**2))
    m3 = float(np.mean(deviations**3))
    g1 = m3 / m2**1.5
    return float(np.sqrt(n * (n - 1)) / (n - 2) * g1)


def kurtosis(rs: ReturnSeries) -> float:
    """Sample excess kurtosis (bias-corrected Fisher's ``G2``).

    ``g2 = m4/m2^2 − 3`` (population excess kurtosis), then bias-corrected —
    ``G2 = (n-1)/((n-2)(n-3)) · ((n+1)·g2 + 6)``. Matches
    ``pandas.Series.kurt()`` / ``scipy.stats.kurtosis(fisher=True, bias=False)``.
    Requires ``n >= 4`` (the ``(n-2)(n-3)`` denominator is undefined below that).
    """
    n = len(rs)
    if n < 4:
        raise ValueError(f"kurtosis needs >= 4 returns, got {n}")
    values = rs.values
    deviations = values - np.mean(values)
    m2 = float(np.mean(deviations**2))
    m4 = float(np.mean(deviations**4))
    g2 = m4 / m2**2 - 3.0
    return float((n - 1) / ((n - 2) * (n - 3)) * ((n + 1) * g2 + 6.0))
