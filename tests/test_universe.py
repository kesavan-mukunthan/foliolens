"""Unit tests for the universe NAV landing pipeline.

No network: list_scheme_codes and fetch_nav_history are monkeypatched;
time.sleep is stubbed out. consolidate() is tested against hand-built shards.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from foliolens.ingest.universe import consolidate, land_universe


def _make_shard(path: Path, data: list[dict]) -> None:  # type: ignore[type-arg]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"data": data}, f)


# ---------------------------------------------------------------------------
# shard-exists → skip
# ---------------------------------------------------------------------------


def test_existing_shard_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_shard(
        tmp_path / "raw" / "103340.json.gz",
        [{"date": "01-01-2024", "nav": "100.000"}],
    )

    calls: list[str] = []

    def _fetch(code: str) -> None:
        calls.append(code)

    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr("foliolens.ingest.universe.fetch_nav_history", _fetch)
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path)

    assert calls == []


# ---------------------------------------------------------------------------
# failed codes — exception path
# ---------------------------------------------------------------------------


def test_exception_appended_to_failed_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(code: str) -> None:
        raise RuntimeError("network failure")

    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr("foliolens.ingest.universe.fetch_nav_history", _boom)
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path, max_retries=1)

    text = (tmp_path / "failed_codes.txt").read_text()
    assert "103340" in text
    assert "exception" in text


# ---------------------------------------------------------------------------
# failed codes — None response path
# ---------------------------------------------------------------------------


def test_none_response_appended_to_failed_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr("foliolens.ingest.universe.fetch_nav_history", lambda _: None)
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path)

    text = (tmp_path / "failed_codes.txt").read_text()
    assert "103340" in text
    assert "None" in text


# ---------------------------------------------------------------------------
# consolidate — two hand-built shards → sorted parquet
# ---------------------------------------------------------------------------


def test_consolidate_two_shards(tmp_path: Path) -> None:
    _make_shard(
        tmp_path / "raw" / "103340.json.gz",
        [
            {"date": "02-01-2024", "nav": "101.000"},
            {"date": "01-01-2024", "nav": "100.000"},
        ],
    )
    _make_shard(
        tmp_path / "raw" / "108466.json.gz",
        [{"date": "01-01-2024", "nav": "200.000"}],
    )

    out = consolidate(tmp_path)

    assert out == tmp_path / "nav.parquet"
    tbl = pq.read_table(out)
    assert set(tbl.column("amfi_code").to_pylist()) == {"103340", "108466"}
    assert tbl.num_rows == 3
    codes_in_order = tbl.column("amfi_code").to_pylist()
    assert codes_in_order == sorted(codes_in_order)
