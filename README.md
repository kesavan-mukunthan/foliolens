# FolioLens

Analytics for Indian mutual funds. 

Currently working on getting the NAVs and getting the returns correct.

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

## Notes

A personal project, not investment advice, and not affiliated with any fund house or AMFI. Figures are computed, check them against official sources before relying on them.

[mftool]: https://pypi.org/project/mftool/
