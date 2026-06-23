"""Eyeball return sanity check (not the validation harness).

Fetches all funds from funds.csv, lands NAV to data/raw/, reads back via
DataAccess, computes 1Y/3Y/5Y returns as of 2026-05-31, and writes an Excel
workbook with published vs calculated side by side.
"""
import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 5, 31)
PERIODS = ("1Y", "3Y", "5Y")
OUT_PATH = ROOT / "outputs" / "eyeball_returns.xlsx"


def main() -> None:
    import xlsxwriter

    from foliolens.ingest.mftool_client import get_nav_history
    from foliolens.ingest.land import land
    from foliolens.data_access import DataAccess
    from foliolens.model.sources import PricedSource
    from foliolens.returns.engine import period_return

    # ── fixtures ──────────────────────────────────────────────────────────────
    fund_names: dict[str, str] = {}
    all_codes: list[str] = []
    with (ROOT / "fixtures" / "funds.csv").open() as f:
        for row in csv.DictReader(f):
            code = row["amfi_code"]
            tag = "direct" if row["plan"] == "direct" else "regular"
            fund_names[code] = f"{row['fund_name']} ({tag})"
            all_codes.append(code)

    published: dict[str, dict[str, float]] = {}
    with (ROOT / "fixtures" / "published_returns.csv").open() as f:
        for row in csv.DictReader(f):
            published.setdefault(row["amfi_code"], {})[row["period"]] = float(
                row["published_return_pct"]
            )

    # ── compute ───────────────────────────────────────────────────────────────
    data_dir = ROOT / "data" / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    da = DataAccess(data_dir)

    # rows[i] = {"name": str, "1Y": (pub, calc), "3Y": ..., "5Y": ...}
    rows: list[dict[str, object]] = []
    for code in all_codes:
        print(f"  fetching {code} …", flush=True)
        records = get_nav_history(code)
        land(records, data_dir)
        ns = da.load_nav_series(code)
        source = PricedSource(nav=ns)
        row_data: dict[str, object] = {"name": fund_names.get(code, code)}
        for period in PERIODS:
            pub = published.get(code, {}).get(period)
            try:
                result = period_return(source, period, AS_OF)
                calc: float | None = float(result.value) * 100
            except ValueError:
                calc = None
            row_data[period] = (pub, calc)
        rows.append(row_data)

    # ── Excel ─────────────────────────────────────────────────────────────────
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(OUT_PATH))
    ws = wb.add_worksheet("Returns")

    # formats
    title   = wb.add_format({"bold": True, "font_size": 11, "align": "center",
                              "valign": "vcenter", "bg_color": "#1F497D",
                              "font_color": "#FFFFFF", "border": 1})
    sub     = wb.add_format({"bold": True, "align": "center", "valign": "vcenter",
                              "bg_color": "#DCE6F1", "border": 1})
    fund_fmt = wb.add_format({"align": "left", "valign": "vcenter", "border": 1})
    pct     = wb.add_format({"num_format": "0.00%", "align": "right",
                              "valign": "vcenter", "border": 1})
    pct_hi  = wb.add_format({"num_format": "0.00%", "align": "right",
                              "valign": "vcenter", "border": 1, "bg_color": "#FFF2CC"})
    bps     = wb.add_format({"num_format": "+0.0;-0.0;0.0", "align": "right",
                              "valign": "vcenter", "border": 1})
    bps_hi  = wb.add_format({"num_format": "+0.0;-0.0;0.0", "align": "right",
                              "valign": "vcenter", "border": 1, "bg_color": "#FFF2CC"})
    na_fmt  = wb.add_format({"align": "center", "valign": "vcenter",
                              "font_color": "#999999", "border": 1})

    # column widths: Fund | [Published, Calculated, Δ bps] × 3 periods
    ws.set_column(0, 0, 52)
    for i in range(len(PERIODS)):
        base = 1 + i * 3
        ws.set_column(base,     base,     11)   # Published
        ws.set_column(base + 1, base + 1, 11)   # Calculated
        ws.set_column(base + 2, base + 2,  8)   # Δ bps

    ws.set_row(0, 22)
    ws.set_row(1, 18)

    # row 0 — period group headers (merged across Published / Calculated / Δ bps)
    ws.write(0, 0, f"Fund  (as of {AS_OF})", title)
    for i, period in enumerate(PERIODS):
        base = 1 + i * 3
        ws.merge_range(0, base, 0, base + 2, period, title)

    # row 1 — sub-column headers
    ws.write(1, 0, "", sub)
    for i in range(len(PERIODS)):
        base = 1 + i * 3
        ws.write(1, base,     "Published", sub)
        ws.write(1, base + 1, "Calculated", sub)
        ws.write(1, base + 2, "Δ bps", sub)

    # data rows
    THRESHOLD_BPS = 10
    for r, row_data in enumerate(rows):
        data_row = r + 2
        ws.write(data_row, 0, row_data["name"], fund_fmt)
        for i, period in enumerate(PERIODS):
            base = 1 + i * 3
            pair = row_data[period]
            assert isinstance(pair, tuple)
            pub, calc = pair

            # Published
            if pub is not None:
                ws.write(data_row, base, pub / 100, pct)
            else:
                ws.write(data_row, base, "—", na_fmt)

            # Calculated — highlight if outside 10 bps of published
            if calc is not None:
                delta_bps = (calc - pub) * 100 if pub is not None else None
                outside = delta_bps is not None and abs(delta_bps) > THRESHOLD_BPS
                ws.write(data_row, base + 1, calc / 100, pct_hi if outside else pct)
            else:
                ws.write(data_row, base + 1, "—", na_fmt)

            # Δ bps
            if pub is not None and calc is not None:
                ws.write(data_row, base + 2, round((calc - pub) * 100, 1), bps_hi if outside else bps)  # type: ignore[possibly-undefined]
            else:
                ws.write(data_row, base + 2, "—", na_fmt)

    wb.close()
    print(f"\nWritten → {OUT_PATH}")


if __name__ == "__main__":
    main()
