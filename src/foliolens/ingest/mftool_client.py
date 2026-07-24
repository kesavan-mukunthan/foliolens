"""mftool client — all mftool calls are isolated here.

Fetches full NAV history by amfi_code and normalises to
(amfi_code, date, nav) with nav as Decimal. Distinguishes holidays/weekends
from missing data; no forward-fill in the raw layer.

Real mftool response shape (verified against live API):
  {
    'fund_house': str,
    'scheme_code': int,
    'scheme_name': str,
    ...
    'data': [{'date': 'DD-MM-YYYY', 'nav': 'NNN.NNNNN'}, ...],  # newest-first
  }
  Returns None for an unknown scheme code.
"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from mftool import Mftool  # isolated here; no other module imports mftool

_DATE_FMT = "%d-%m-%Y"

# (connect, read) seconds. mftool passes no timeout, so requests defaults to
# timeout=None — a blocking read that never returns when a connection is dropped
# mid-response. That hung the universe backfill silently (no exception, so the
# caller's retry ladder never fired). We inject a default via the session so any
# hang surfaces as requests.Timeout and the caller can back off and move on.
_TIMEOUT_S: tuple[float, float] = (5.0, 30.0)

# mftool's get_scheme_historical_nav gates the real fetch on is_valid_code, which
# checks membership in the scheme-code index it downloads at construction. If that
# index load fails or returns empty, EVERY code is judged invalid and the function
# returns None with no error — indistinguishable, to the caller, from a genuinely
# dead scheme. That conflation quarantined ~5000 live funds. Guard: load the index
# once, reuse the instance, and refuse to operate on an implausibly small index.
_MIN_SCHEME_CODES = 10_000

_client_lock = threading.Lock()
_client: Mftool | None = None


def _install_timeout(mf: Mftool) -> None:
    """Wrap the session so every request carries a default timeout.

    Reaches into mftool's private ``_session`` — the one place in the codebase
    allowed to know mftool internals. If a future mftool upgrade renames it, this
    raises loudly here rather than silently reverting to the no-timeout hang.
    """
    session = mf._session  # noqa: SLF001 — deliberate; see module docstring
    original_request = session.request

    def request_with_timeout(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", _TIMEOUT_S)
        return original_request(*args, **kwargs)

    session.request = request_with_timeout


def _get_client() -> Mftool:
    """Return a shared Mftool with a request timeout and a validated index.

    Instantiating Mftool per call rebuilt the session and re-downloaded the full
    scheme-code dump every time — doubling requests and discarding the index cache.
    A single guarded instance loads the index once and fails loud if it is empty.
    """
    global _client
    with _client_lock:
        if _client is None:
            mf = Mftool()
            _install_timeout(mf)
            n = len(mf._scheme_codes)  # noqa: SLF001
            if n < _MIN_SCHEME_CODES:
                raise RuntimeError(
                    f"mftool scheme-code index loaded only {n} codes "
                    f"(< {_MIN_SCHEME_CODES}); refusing to run — a None response now "
                    "would mean 'index failed to load', not 'scheme is dead'."
                )
            _client = mf
        return _client


@dataclass(frozen=True)
class NavRecord:
    amfi_code: str
    date: datetime.date
    nav: Decimal


def fetch_scheme_codes() -> list[str]:
    """Return sorted, de-duplicated AMFI scheme codes via mftool.

    AMFI's dump carries a ``Scheme Code`` header row that mftool passes through
    as a literal code; it is not a fund and 400s on fetch. Every real AMFI code
    is all-digits, so filter to numeric codes to keep junk out of the universe.
    """
    mf = _get_client()
    return sorted({str(k) for k in mf.get_scheme_codes() if str(k).isdigit()})


def fetch_nav_history(amfi_code: str) -> dict[str, Any] | None:
    """Fetch a fund's raw NAV-history response, or None if the scheme is absent.

    Deliberately does NOT call mftool's get_scheme_historical_nav: that method
    wraps its fetch in ``except Exception: return None``, so a timeout or network
    error is indistinguishable from a genuinely dead scheme. That conflation is
    exactly what quarantined ~5000 live funds. Here, network/timeout errors
    PROPAGATE so the caller's retry ladder fires; None is returned only for a
    successful response that carries no data — the sole true "scheme is absent"
    signal. The response shape ({'meta', 'data', 'status'}, data newest-first with
    'date'/'nav') is what normalise() consumes.
    """
    mf = _get_client()
    url = mf._get_scheme_url + str(amfi_code)  # noqa: SLF001 — sole mftool boundary
    response = mf._session.get(url)  # noqa: SLF001 — timeout injected by _install_timeout
    response.raise_for_status()  # non-2xx propagates; caller retries, never marks dead
    payload = cast(dict[str, Any], response.json())
    if not payload.get("data"):
        return None  # HTTP 200 but empty data → genuinely absent scheme
    return payload


def normalise(amfi_code: str, raw: dict[str, Any]) -> list[NavRecord]:
    """Convert a raw mftool response dict to a sorted, de-duplicated NavRecord list.

    Pure function — no network calls. Safe to call in unit tests with
    hand-built dicts.

    Rules applied:
    - date parsed from 'DD-MM-YYYY' to datetime.date
    - nav converted from string to Decimal (no float intermediate)
    - sorted ascending by date
    - duplicate (amfi_code, date) pairs dropped; first occurrence in the raw
      feed is kept (raw is newest-first, so 'first' means the newest nav for
      that date — conservative choice; in practice duplicates are rare)
    - no forward-fill: only dates present in the raw feed appear in output
    """
    seen: set[datetime.date] = set()
    records: list[NavRecord] = []

    for item in raw.get("data", []):
        d = datetime.datetime.strptime(item["date"], _DATE_FMT).date()
        if d in seen:
            continue
        seen.add(d)
        records.append(
            NavRecord(
                amfi_code=str(amfi_code),
                date=d,
                nav=Decimal(item["nav"]),
            )
        )

    records.sort(key=lambda r: r.date)
    return records


def get_nav_history(amfi_code: str) -> list[NavRecord]:
    """Fetch and normalise the full NAV history for one fund.

    Raises ValueError if mftool returns no data for the given code.
    """
    raw = fetch_nav_history(amfi_code)
    if raw is None:
        raise ValueError(f"mftool returned no data for amfi_code={amfi_code!r}")
    return normalise(str(amfi_code), raw)
