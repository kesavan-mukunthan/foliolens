"""One-time snapshot freeze script.

Reads fixtures/funds.csv, fetches each fund's full NAV history via the
mftool client, writes a single frozen parquet (fixtures/nav_snapshots/nav.parquet)
with amfi_code as a column, sorted by (amfi_code, date).

Run once: uv run python scripts/freeze_snapshots.py
Commit the output; thereafter tests read the frozen file and never touch the network.
"""
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNDS_CSV = ROOT / "fixtures" / "funds.csv"
PUBLISHED_CSV = ROOT / "fixtures" / "published_returns.csv"
SNAPSHOTS_DIR = ROOT / "fixtures" / "nav_snapshots"


def main() -> None:
    from foliolens.ingest.mftool_client import NavRecord, get_nav_history
    from foliolens.ingest.land import land
    from foliolens.data_access import DataAccess

    with FUNDS_CSV.open() as f:
        funds = list(csv.DictReader(f))

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Freeze date : {date.today()}")
    print(f"Destination : {SNAPSHOTS_DIR / 'nav.parquet'}")
    print(f"Funds       : {len(funds)}")
    print()

    ok = 0
    all_records: list[NavRecord] = []
    for row in funds:
        amfi_code = row["amfi_code"]
        name = row["fund_name"]
        print(f"  {amfi_code}  {name} ...", end=" ", flush=True)
        try:
            records = get_nav_history(amfi_code)
        except ValueError as e:
            print(f"SKIP  {e}", file=sys.stderr)
            continue
        last_date = records[-1].date
        all_records.extend(records)
        print(f"{len(records)} records  last={last_date}")
        ok += 1

    # One consolidated file per freeze run — amfi_code as a column, sorted.
    land(all_records, SNAPSHOTS_DIR)

    print(f"\nLanded {ok}/{len(funds)} funds.")

    # Verify every factsheet_as_of is covered by the snapshot.
    print("\nVerifying factsheet coverage ...")
    da = DataAccess(SNAPSHOTS_DIR)
    warn = 0
    with PUBLISHED_CSV.open() as f:
        for row in csv.DictReader(f):
            amfi_code = row["amfi_code"]
            as_of = date.fromisoformat(row["factsheet_as_of"])
            try:
                ns = da.load_nav_series(amfi_code)
            except ValueError:
                print(f"  MISSING snapshot: {amfi_code}")
                warn += 1
                continue
            if not ns.data:
                print(f"  EMPTY snapshot: {amfi_code}")
                warn += 1
                continue
            last = ns.data[-1][0]
            status = "OK " if last >= as_of else "WARN"
            if last < as_of:
                warn += 1
            print(f"  {status}  {amfi_code}  last={last}  factsheet_as_of={as_of}")

    if warn:
        print(f"\n{warn} coverage warning(s) — check above.")
        sys.exit(1)
    else:
        print("\nAll funds covered through their factsheet_as_of. Done.")


if __name__ == "__main__":
    main()
