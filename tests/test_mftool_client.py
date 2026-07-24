"""Unit tests for the mftool_client normaliser and fetch semantics.

No network: normalise() tests use hand-built dicts; fetch tests inject a fake
client so no socket is touched. The conftest _no_network fixture guards against
accidental live calls.
"""
import datetime
from decimal import Decimal

import pytest
import requests

from foliolens.ingest import mftool_client
from foliolens.ingest.mftool_client import normalise


CODE = "120586"


def _raw(*entries: tuple[str, str]) -> dict:
    """Build a minimal raw dict in mftool's shape from (date_str, nav_str) pairs."""
    return {"data": [{"date": d, "nav": n} for d, n in entries]}


def test_normalise_sorts_ascending():
    raw = _raw(
        ("15-06-2026", "100.5000"),
        ("13-06-2026", "99.0000"),
        ("14-06-2026", "99.8000"),
    )
    result = normalise(CODE, raw)
    dates = [r.date for r in result]
    assert dates == sorted(dates), "records must be sorted ascending by date"


def test_normalise_drops_duplicate_date():
    raw = _raw(
        ("15-06-2026", "100.5000"),
        ("15-06-2026", "101.0000"),  # duplicate date — second dropped
        ("14-06-2026", "99.8000"),
    )
    result = normalise(CODE, raw)
    date_15 = datetime.date(2026, 6, 15)
    assert len(result) == 2
    assert sum(1 for r in result if r.date == date_15) == 1, \
        "duplicate (amfi_code, date) must be de-duplicated to one row"


def test_normalise_nav_is_decimal():
    raw = _raw(("15-06-2026", "118.70000"))
    result = normalise(CODE, raw)
    assert len(result) == 1
    assert isinstance(result[0].nav, Decimal), "nav must be Decimal, not float"
    assert result[0].nav == Decimal("118.70000")


def test_normalise_amfi_code_is_string():
    raw = _raw(("15-06-2026", "118.70000"))
    result = normalise(CODE, raw)
    assert isinstance(result[0].amfi_code, str)


def test_normalise_date_is_date_object():
    raw = _raw(("15-06-2026", "118.70000"))
    result = normalise(CODE, raw)
    assert isinstance(result[0].date, datetime.date)
    assert result[0].date == datetime.date(2026, 6, 15)


def test_normalise_empty_data():
    result = normalise(CODE, {"data": []})
    assert result == []


def test_normalise_no_forward_fill():
    """Gaps between dates are preserved — no fabricated rows."""
    raw = _raw(
        ("17-06-2026", "102.0000"),
        ("13-06-2026", "99.0000"),  # 14, 15, 16 are absent (weekend/holiday)
    )
    result = normalise(CODE, raw)
    assert len(result) == 2, "only dates present in raw feed should appear"
    assert result[0].date == datetime.date(2026, 6, 13)
    assert result[1].date == datetime.date(2026, 6, 17)


# --- fetch_nav_history: None-vs-exception semantics -------------------------
#
# These guard the incident this module was rewritten to fix: a transient network
# error must NOT be swallowed into None (which the caller records as a dead
# scheme, quarantining live funds forever). None is reserved for a successful
# response that genuinely carries no data.


class _FakeResponse:
    def __init__(self, payload, *, raise_exc=None):
        self._payload = payload
        self._raise_exc = raise_exc

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, *, payload=None, exc=None):
        self._payload = payload
        self._exc = exc

    def get(self, url):
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload)


class _FakeClient:
    _get_scheme_url = "https://api.mfapi.in/mf/"

    def __init__(self, *, payload=None, exc=None):
        self._session = _FakeSession(payload=payload, exc=exc)


def _install_client(monkeypatch, *, payload=None, exc=None):
    monkeypatch.setattr(
        mftool_client, "_get_client", lambda: _FakeClient(payload=payload, exc=exc)
    )


def test_fetch_returns_payload_when_data_present(monkeypatch):
    payload = {"meta": {}, "data": [{"date": "15-06-2026", "nav": "10.0"}], "status": "SUCCESS"}
    _install_client(monkeypatch, payload=payload)
    assert mftool_client.fetch_nav_history(CODE) is payload


def test_fetch_returns_none_for_empty_data(monkeypatch):
    """HTTP 200 with no data rows = genuinely absent scheme → None."""
    _install_client(monkeypatch, payload={"meta": {}, "data": [], "status": "SUCCESS"})
    assert mftool_client.fetch_nav_history(CODE) is None


def test_fetch_propagates_network_error_not_none(monkeypatch):
    """The incident guard: a timeout must raise, never collapse to None.

    A None here would be recorded as 'mftool returned None' and the fund
    permanently quarantined as dead — which is exactly what happened to ~5000
    live funds. The caller's retry ladder only fires on an exception.
    """
    _install_client(monkeypatch, exc=requests.ReadTimeout("read timed out"))
    with pytest.raises(requests.RequestException):
        mftool_client.fetch_nav_history(CODE)


def test_get_client_rejects_implausibly_small_index(monkeypatch):
    """An empty/stub scheme index means the index load failed — refuse to run,
    rather than judge every code invalid and return None for live funds."""
    mftool_client._client = None  # reset the module-level singleton

    class _StubMftool:
        def __init__(self):
            self._session = _FakeSession(payload={})
            self._scheme_codes = {"1", "2", "3"}  # far below _MIN_SCHEME_CODES

    monkeypatch.setattr(mftool_client, "Mftool", _StubMftool)
    monkeypatch.setattr(mftool_client, "_install_timeout", lambda mf: None)
    with pytest.raises(RuntimeError, match="index loaded only"):
        mftool_client._get_client()
    mftool_client._client = None  # leave the singleton clean for other tests
