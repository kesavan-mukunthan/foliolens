# conftest.py — loads FROZEN fixtures only. No network.
import socket
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


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
def published_returns():
    # TODO: parse fixtures/published_returns.csv (amfi_code, period, pct, as_of, url)
    ...


@pytest.fixture(scope="session")
def data_access():
    # TODO: DataAccess pointed at fixtures/nav_snapshots/ (frozen parquet), NOT data/raw/
    ...


@pytest.fixture(scope="session")
def nav_series(data_access):
    # TODO: return a callable amfi_code -> Decimal NAV series read via data_access
    ...
