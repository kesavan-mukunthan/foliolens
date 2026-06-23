"""Holdings edge dataclass and DAG resolver stub.

Holding is a weighted, point-in-time edge in the investment DAG.
resolve_holdings is implemented at step 1+; defined here to keep the contract stable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Holding:
    """Weighted edge: child held by parent at a given point in time."""

    parent_id: str
    child_id: str
    as_of: date
    weight: Decimal


def resolve_holdings(
    investment_id: str,
    as_of: date,
    edges: tuple[Holding, ...],
) -> tuple[tuple[str, Decimal], ...]:
    """Resolve direct children of investment_id at as_of from the edge store.

    Returns (child_id, weight) pairs. Stub — implemented at step 1+.
    """
    raise NotImplementedError
