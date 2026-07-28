# conftest.py — loads FROZEN fixtures only. No network.
import socket
from pathlib import Path
import pytest

from foliolens.data_access import DataAccess
from foliolens.model.value_objects import NavSeries
from foliolens.validation.reconcile import (
    Exemption,
    PublishedReturn,
    load_exemptions,
    load_published_returns,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
NAV_SNAPSHOTS = FIXTURES / "nav_snapshots"
PUBLISHED_RETURNS_CSV = FIXTURES / "published_returns.csv"
RECONCILIATION_EXEMPTIONS_CSV = FIXTURES / "reconciliation_exemptions.csv"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Guard the source-of-truth rule: tests never hit a live source."""
    def _blocked(*_a, **_k):
        raise RuntimeError("network access attempted in a test")
    monkeypatch.setattr(socket, "socket", _blocked)


@pytest.fixture(scope="session")
def funds():
    # TODO: parse fixtures/funds.csv -> list of share-class records
    ...


@pytest.fixture(scope="session")
def published_returns() -> list[PublishedReturn]:
    """Every row of the frozen published-returns factsheet fixture."""
    return load_published_returns(PUBLISHED_RETURNS_CSV)


@pytest.fixture(scope="session")
def exemptions() -> list[Exemption]:
    """The reviewable exemption list (empty until a human adjudicates a row)."""
    return load_exemptions(RECONCILIATION_EXEMPTIONS_CSV)


@pytest.fixture(scope="session")
def data_access() -> DataAccess:
    """DataAccess pointed at the FROZEN parquet (fixtures/nav_snapshots/), not data/raw/."""
    return DataAccess(NAV_SNAPSHOTS)


@pytest.fixture(scope="session")
def nav_series(data_access):
    """Callable amfi_code -> Decimal NavSeries, read via the frozen data_access."""
    def _load(amfi_code: str) -> NavSeries:
        return data_access.load_nav_series(amfi_code)

    return _load
