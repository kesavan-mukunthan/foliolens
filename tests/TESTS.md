# tests/ — the gate

Green pytest is the acceptance gate for every step. Two tiers:
- `invariants/` — standing correctness laws from `CLAUDE.md`; run every step.
- `step00/` — step-0 reconciliation, bound to the frozen fixtures.

All fixtures load from `fixtures/` only. **No test calls mftool or any live source** — `conftest.py` loads frozen snapshots and guards against network. A test that needs the network is a bug.

## invariants/

### test_decimal.py
- `test_decimal_roundtrip` — `Decimal("23.4567")` written to parquet then read via `DataAccess` returns an equal `Decimal`; stored dtype is `decimal128`, not float. *(Must pass before 0.5.)*
- `test_no_float_in_returns` — engine return values are `Decimal`, not float.

### test_annualization.py
- `test_sub_year_is_absolute` — a 6-month period returns `(end/start − 1)`, not annualised.
- `test_over_year_is_cagr` — a 3Y period returns `(end/start)^(1/years) − 1`.
- `test_one_year_boundary` — a 1Y period uses the ≥1Y path and equals the absolute return at exactly 1Y.
- `test_daycount_is_365` — `years == actual_days / 365`.

### test_twr.py
- `test_twr_equals_point_to_point` — on a cashflow-free series, TWR == point-to-point geometric return.
- `test_chaining_consistency` — cumulative TWR over a span == compound of its sub-period TWRs.

### test_month_end.py
- `test_last_on_or_before` — month-end picks the last NAV on/before calendar month-end.
- `test_weekend_boundary` — when month-end falls on a weekend/holiday, picks the prior business day's NAV.
- `test_no_lookahead` — no selected month-end date exceeds its calendar month-end.

### test_determinism.py
- `test_report_reproducible` — running the pipeline twice on frozen fixtures yields identical metric outputs.

### test_no_live_fetch.py
- `test_no_network_in_analysis` — analysis/compute paths neither import nor call the mftool client.

## step00/

### test_reconciliation.py — parametrised over funds × periods from fixtures
- `test_own_vs_oracle` — `|own − oracle| / |oracle| ≤ 1e-6`; periodicity declared.
- `test_own_vs_published` — `|own − published| ≤ 10 bps` after matching `factsheet_as_of`.
- `test_fails_loud` — an injected out-of-tolerance case raises/flags with fund/period/delta; no silent pass.
- `test_direct_ge_regular` — for the paired fund, direct-growth return ≥ regular-growth over the same window.

### test_categories.py
- `test_all_categories_compute` — every category (incl. FoF, multi-asset, liquid, debt) produces a return without error and within a plausible band.

## conftest.py — skeleton

```python
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
```
