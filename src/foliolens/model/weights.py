"""Weight policies for blend-based investments.

WeightPolicy base + Fixed/Drift/PIT stubs — implemented at step 2+.
Fixed = constant rebalanced weights; Drift = buy-and-hold; PIT = actual disclosures.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


class WeightPolicy:
    """Base: resolves a child's weight at a given point in time."""

    def weight(self, child_id: str, as_of: date) -> Decimal:
        raise NotImplementedError


class Fixed(WeightPolicy):
    """Constant target weights rebalanced each period. Stub — implemented at step 2+."""

    def weight(self, child_id: str, as_of: date) -> Decimal:
        raise NotImplementedError


class Drift(WeightPolicy):
    """Buy-and-hold; weights drift with returns. Stub — implemented at step 2+."""

    def weight(self, child_id: str, as_of: date) -> Decimal:
        raise NotImplementedError


class PIT(WeightPolicy):
    """Point-in-time weights from actual holdings disclosures. Stub — implemented at step 2+."""

    def weight(self, child_id: str, as_of: date) -> Decimal:
        raise NotImplementedError
