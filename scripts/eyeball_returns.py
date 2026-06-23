"""Eyeball return sanity check (not the validation harness).

Fetches 3 funds from funds.csv, lands NAV to data/raw/,
reads back via DataAccess, and computes 1Y/3Y/5Y returns as of 2026-05-31.
"""
import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 5, 31)

# Three representative funds: ICICI Large Cap Direct, PPFCF Direct, ICICI Midcap Direct
SAMPLE_CODES = ["120586", "122639", "120381"]


def main() -> None:
    from foliolens.ingest.mftool_client import get_nav_history
    from foliolens.ingest.land import land
    from foliolens.data_access import DataAccess
    from foliolens.model.sources import PricedSource
    from foliolens.returns.engine import period_return

    fund_names: dict[str, str] = {}
    with (ROOT / "fixtures" / "funds.csv").open() as f:
        for row in csv.DictReader(f):
            tag = "direct" if row["plan"] == "direct" else "regular"
            fund_names[row["amfi_code"]] = f"{row['fund_name']} ({tag})"

    data_dir = ROOT / "data" / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)

    da = DataAccess(data_dir)

    print(f"\nEyeball returns — as of {AS_OF}")
    print("=" * 75)
    print(f"{'Fund':<50} {'Period':>5}  {'Return':>9}  {'Method':<8}  {'Days':>5}")
    print("-" * 75)

    for code in SAMPLE_CODES:
        print(f"  [fetching {code}]", flush=True)
        records = get_nav_history(code)
        land(records, data_dir)
        ns = da.load_nav_series(code)
        source = PricedSource(nav=ns)
        name = fund_names.get(code, code)

        for period in ("1Y", "3Y", "5Y"):
            try:
                result = period_return(source, period, AS_OF)
                pct = float(result.value) * 100
                print(
                    f"  {name:<50} {period:>5}  {pct:>8.2f}%  {result.method:<8}  {result.days:>5}"
                )
            except ValueError as exc:
                print(f"  {name:<50} {period:>5}  {'N/A':>9}  ({exc})")

    print("=" * 75)


if __name__ == "__main__":
    main()
