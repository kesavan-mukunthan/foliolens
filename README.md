# FolioLens

Analytics for Indian mutual funds.

The engine has two layers. Layer 1 computes figures of record — NAVs and trailing returns held as `Decimal`, reconciled three ways (own implementation vs a library oracle vs the AMC's published figure). Layer 2 is derived analytics — `float64` return series feeding risk and performance metrics, validated own-vs-oracle. The conventions and tolerances that make this hold are in [`CLAUDE.md`](CLAUDE.md); every one is enforced by a test.

## What's here

Anything investable will be of the type `Investment` with a return series. This can be a stock, a fund, a portfolio of funds.

More on the design in [`ARCHITECTURE.md`](ARCHITECTURE.md); build order in [`SCOPE.md`](SCOPE.md).

## Built on

Python 3.12 with [uv](https://docs.astral.sh/uv/). NAV data comes from AMFI via [mftool]; returns for cross-checking come from AMC factsheets.

## Running it

```bash
uv sync
uv run pytest
uv run mypy src
```

## Roadmap

Have grand plans. Returns on known funds first, then personal portfolios from CAS statements, monitoring, the full fund universe, a screener and recommender, and eventually plain-English queries over the lot.

## Data and licensing

The MIT licence covers the code only, not any data in this repository or fetched by it.

- `fixtures/nav_snapshots/nav.parquet` is a frozen test snapshot of AMFI NAVs (fetched via [mftool]), kept solely so tests are reproducible. It is not a redistributed dataset; get current NAVs from AMFI.
- `fixtures/published_returns.csv` quotes trailing returns from AMC factsheets, each row carrying its source and as-of date, used only as reconciliation targets.
- Sources used in computation but never committed or republished: the IIM-A factor and risk-free library (citation-only; derived from CMIE Prowess and not licensed for redistribution) and benchmark TRI levels (subject to index-provider licensing).

## Notes

A personal project, not investment advice, and not affiliated with any fund house, AMFI, or any data provider named above. Figures are computed, check them against official sources before relying on them.

[mftool]: https://pypi.org/project/mftool/
