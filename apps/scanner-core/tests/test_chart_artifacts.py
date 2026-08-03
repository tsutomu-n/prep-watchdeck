from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck.adapters.duckdb import DuckDbSnapshotCache
from prep_watchdeck.adapters.fixture import FixtureProvider
from prep_watchdeck.adapters.local_snapshot import AtomicSnapshotWriter
from prep_watchdeck.application.chart_artifacts import (
    chart_timeframes_from_5m,
    write_chart_files,
)
from prep_watchdeck.application.run_cycle import run_scan_cycle
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.source_mode import SourceMode
from prep_watchdeck.models import CandleBar


def test_detail_chart_bars_are_sorted_deduplicated_and_limited(tmp_path) -> None:
    bars = [_bar(index) for index in reversed(range(130))]
    bars.append(_bar(100, close="9.9"))

    write_chart_files(
        tmp_path,
        snapshot_run_id="normalization-test",
        generated_at_ms=1_781_100_000_000,
        data_as_of_ms=1_781_100_000_000,
        chart_candles_by_symbol={"ALTUSDT": chart_timeframes_from_5m(bars)},
        symbols=["ALTUSDT"],
    )

    payload = json.loads((tmp_path / "ALTUSDT.json").read_text())
    chart_bars = payload["timeframes"]["5m"]
    timestamps = [bar["ts"] for bar in chart_bars]
    assert len(chart_bars) <= 128
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))


def test_detail_chart_cleanup_removes_only_stale_json_files(tmp_path) -> None:
    (tmp_path / "STALEUSDT.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "STALEUSDT.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.txt").write_text("keep\n", encoding="utf-8")

    write_chart_files(
        tmp_path,
        snapshot_run_id="cleanup-test",
        generated_at_ms=1_781_100_000_000,
        data_as_of_ms=1_781_100_000_000,
        chart_candles_by_symbol={"ALTUSDT": chart_timeframes_from_5m([_bar(1)])},
        symbols=["ALTUSDT"],
    )

    assert not (tmp_path / "STALEUSDT.json").exists()
    assert (tmp_path / "ALTUSDT.json").exists()
    assert (tmp_path / "README.txt").exists()


def test_archive_failure_keeps_previous_latest(tmp_path) -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )
    latest = tmp_path / "snapshots" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text('{"runId":"previous"}\n', encoding="utf-8")

    class FailingArchiveWriter(AtomicSnapshotWriter):
        def _write_archive(self, snapshot, payload) -> None:
            raise RuntimeError("archive failure")

    with pytest.raises(RuntimeError, match="archive failure"):
        FailingArchiveWriter(latest).write(snapshot)

    assert json.loads(latest.read_text())["runId"] == "previous"


def test_cache_failure_keeps_previous_latest(tmp_path) -> None:
    provider = FixtureProvider(Path("../../fixtures"))
    latest = tmp_path / "snapshots" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text('{"runId":"previous"}\n', encoding="utf-8")

    class FailingCache:
        def save(self, snapshot) -> None:
            raise RuntimeError("cache failure")

        def save_candles_5m(self, candles_by_symbol) -> None:
            raise AssertionError("fixture scan must not save live candles")

        def latest(self):
            return None

    with pytest.raises(RuntimeError, match="cache failure"):
        run_scan_cycle(
            source=SourceMode.FIXTURE,
            template="balanced",
            fixture_set="basic",
            providers={DataSource.FIXTURE: provider},
            writer=AtomicSnapshotWriter(latest),
            cache=FailingCache(),
        )

    assert json.loads(latest.read_text())["runId"] == "previous"


def test_live_scan_uses_v2_chart_writer_without_changing_existing_archives(tmp_path) -> None:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )
    snapshot = snapshot.model_copy(
        update={
            "run_id": "live-chart-integration",
            "source": snapshot.source.model_copy(update={"data_source": DataSource.LIVE}),
        },
        deep=True,
    )
    bars = [_bar(index) for index in range(10)]

    class LiveProvider:
        def __init__(self) -> None:
            self.latest_candles_by_symbol = {"ALTUSDT": bars}
            self.latest_chart_candles_by_symbol = {
                "ALTUSDT": {
                    "5m": bars,
                    "15m": bars,
                }
            }

        def build_snapshot(self, *, template: str, fixture_set: str | None = None):
            return snapshot

    latest = tmp_path / "snapshots" / "latest.json"
    chart_dir = latest.parent / "charts" / "latest"
    chart_dir.mkdir(parents=True)
    (chart_dir / "ALTUSDT.json").write_text('{"schemaVersion":1}\n', encoding="utf-8")
    (chart_dir / "STALEUSDT.json").write_text('{"schemaVersion":1}\n', encoding="utf-8")
    (chart_dir / "README.txt").write_text("preserve\n", encoding="utf-8")
    legacy_archive = latest.parent / "archive" / "2000-01-01" / "legacy.json"
    legacy_archive.parent.mkdir(parents=True)
    legacy_archive.write_text('{"runId":"legacy"}\n', encoding="utf-8")
    legacy_archive_before = legacy_archive.read_bytes()

    run_scan_cycle(
        source=SourceMode.LIVE,
        template="balanced",
        fixture_set=None,
        providers={DataSource.LIVE: LiveProvider()},
        writer=AtomicSnapshotWriter(latest),
        cache=DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb"),
    )

    latest_payload = json.loads(latest.read_text())
    chart_payload = json.loads((chart_dir / "ALTUSDT.json").read_text())
    assert latest_payload["runId"] == "live-chart-integration"
    assert set(chart_payload) == {
        "schemaVersion",
        "snapshotRunId",
        "symbol",
        "generatedAt",
        "dataAsOf",
        "timeframes",
    }
    assert chart_payload["schemaVersion"] == 2
    assert chart_payload["snapshotRunId"] == latest_payload["runId"]
    assert not (chart_dir / "STALEUSDT.json").exists()
    assert (chart_dir / "README.txt").read_text() == "preserve\n"
    assert legacy_archive.read_bytes() == legacy_archive_before
    assert any(path != legacy_archive for path in (latest.parent / "archive").glob("*/*.json"))


def _bar(index: int, *, close: str = "1.1") -> CandleBar:
    return CandleBar(
        symbol="ALTUSDT",
        ts=1_781_000_000_000 + index * 300_000,
        open=Decimal("1.0"),
        high=Decimal("1.2"),
        low=Decimal("0.9"),
        close=Decimal(close),
        base_vol=Decimal("100"),
        quote_vol=Decimal("1000"),
    )
