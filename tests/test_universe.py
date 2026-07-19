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


def test_none_response_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A None return gets one cheap retry — not zero, and not the full ladder.

    Zero retries loses genuinely flaky responses; the full exception ladder
    costs 42s per wound-up scheme, and roughly half the universe is wound up.
    """
    calls: list[str] = []

    def _always_none(code: str) -> None:
        calls.append(code)
        return None

    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr("foliolens.ingest.universe.fetch_nav_history", _always_none)
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path, max_retries=3)

    assert len(calls) == 2, f"expected 1 initial + 1 retry, got {len(calls)}"


def test_transient_none_then_success_is_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fund that returns None once and then succeeds lands, and is not failed."""
    attempts = iter([None, {"data": [{"date": "01-01-2020", "nav": "10.0"}]}])

    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr(
        "foliolens.ingest.universe.fetch_nav_history", lambda _: next(attempts)
    )
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path, max_retries=3)

    assert (tmp_path / "raw" / "103340.json.gz").exists()
    assert not (tmp_path / "failed_codes.txt").exists()


def test_previously_failed_codes_are_skipped_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """failed_codes.txt is resume state: those codes are not re-fetched."""
    (tmp_path / "failed_codes.txt").write_text("103340\tmftool returned None\n")
    calls: list[str] = []

    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr(
        "foliolens.ingest.universe.fetch_nav_history",
        lambda c: calls.append(c) or None,
    )
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path)

    assert calls == [], "previously-failed code should not be re-fetched"


def test_retry_failed_forces_reattempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """retry_failed=True overrides the skip, so a recovered scheme can land."""
    (tmp_path / "failed_codes.txt").write_text("103340\tmftool returned None\n")

    monkeypatch.setattr("foliolens.ingest.universe.list_scheme_codes", lambda: ["103340"])
    monkeypatch.setattr(
        "foliolens.ingest.universe.fetch_nav_history",
        lambda _: {"data": [{"date": "01-01-2020", "nav": "10.0"}]},
    )
    monkeypatch.setattr("time.sleep", lambda _: None)

    land_universe(tmp_path, retry_failed=True)

    assert (tmp_path / "raw" / "103340.json.gz").exists()


# ---------------------------------------------------------------------------
# shard partition — worker i of N takes every N-th code, disjoint coverage
# ---------------------------------------------------------------------------


def test_shard_partitions_disjoint_and_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    all_codes = [str(c) for c in range(100, 110)]  # 10 codes
    monkeypatch.setattr(
        "foliolens.ingest.universe.list_scheme_codes", lambda: all_codes
    )
    monkeypatch.setattr("time.sleep", lambda _: None)

    fetched: dict[int, list[str]] = {}

    def _run_worker(worker: int) -> None:
        seen: list[str] = []
        monkeypatch.setattr(
            "foliolens.ingest.universe.fetch_nav_history",
            lambda code: seen.append(code) or {"data": []},
        )
        land_universe(tmp_path, shard=(worker, 4))
        fetched[worker] = seen

    for w in range(4):
        _run_worker(w)

    covered = [c for w in range(4) for c in fetched[w]]
    # Disjoint (no code fetched twice) and complete (every code covered once).
    assert sorted(covered) == sorted(all_codes)
    assert len(covered) == len(set(covered))


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
