from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

import pytest

from prep_watchdeck.composition import build_ticker_runtime_writer
from prep_watchdeck.domain.service_models import TickerLatestRecord
from prep_watchdeck.settings import Settings


def test_collector_deduplicates_symbol_and_rejects_older_timestamps() -> None:
    runtime = _runtime_module()
    collector = runtime.TickerRuntimeCollector(
        [
            _ticker("BTCUSDT", 100, 101.0),
            _ticker("BTCUSDT", 100, 102.0),
            _ticker("ETHUSDT", 100, 51.0),
        ]
    )

    first = collector.publish(as_of_ms=1_000)

    assert first is not None
    assert first.sequence == 1
    assert first.full_updates == [
        ("BTCUSDT", 102.0, 100),
        ("ETHUSDT", 51.0, 100),
    ]
    assert first.delta_updates == first.full_updates

    collector.record([_ticker("BTCUSDT", 99, 999.0)])
    assert collector.publish(as_of_ms=1_100) is None

    collector.record(
        [
            _ticker("BTCUSDT", 101, 103.0),
            _ticker("BTCUSDT", 101, 104.0),
            _ticker("BTCUSDT", 100, 888.0),
        ]
    )
    second = collector.publish(as_of_ms=1_200)

    assert second is not None
    assert second.sequence == 2
    assert second.delta_updates == [("BTCUSDT", 104.0, 101)]
    assert second.full_updates == [
        ("BTCUSDT", 104.0, 101),
        ("ETHUSDT", 51.0, 100),
    ]


def test_collector_excludes_unsupported_symbols() -> None:
    runtime = _runtime_module()
    collector = runtime.TickerRuntimeCollector(
        [
            _ticker("BTCUSDT", 100, 101.0),
            _ticker("龙虾USDT", 100, 1.0),
        ]
    )

    publication = collector.publish(as_of_ms=1_000)

    assert publication is not None
    assert publication.full_updates == [("BTCUSDT", 101.0, 100)]
    assert publication.delta_updates == publication.full_updates


def test_sequence_advances_only_for_dirty_batches() -> None:
    runtime = _runtime_module()
    collector = runtime.TickerRuntimeCollector()

    assert collector.publish(as_of_ms=1_000) is None
    collector.record([_ticker("BTCUSDT", 100, 101.0)])
    first = collector.publish(as_of_ms=1_100)
    assert first is not None
    assert first.sequence == 1
    assert collector.publish(as_of_ms=1_200) is None

    collector.record([_ticker("ETHUSDT", 200, 51.0)])
    second = collector.publish(as_of_ms=1_300)
    assert second is not None
    assert second.sequence == 2


def test_publication_returns_delta_only_for_immediately_previous_sequence() -> None:
    runtime = _runtime_module()
    collector = runtime.TickerRuntimeCollector([_ticker("BTCUSDT", 100, 101.0)])
    first = collector.publish(as_of_ms=1_000)
    assert first is not None
    collector.record([_ticker("BTCUSDT", 200, 102.0), _ticker("ETHUSDT", 200, 51.0)])
    second = collector.publish(as_of_ms=2_000)
    assert second is not None

    assert second.batch_after(2) is None
    assert second.batch_after(1) == {
        "schemaVersion": 1,
        "sequence": 2,
        "asOf": 2_000,
        "full": False,
        "updates": [
            ["BTCUSDT", 102.0, 200],
            ["ETHUSDT", 51.0, 200],
        ],
    }
    assert second.batch_after(0)["full"] is True
    assert second.batch_after(-1)["full"] is True
    assert second.batch_after(3)["full"] is True
    assert second.batch_after(0)["updates"] == [
        ["BTCUSDT", 102.0, 200],
        ["ETHUSDT", 51.0, 200],
    ]


def test_atomic_writer_uses_one_compact_file_without_archive(tmp_path) -> None:
    runtime = _runtime_module()
    collector = runtime.TickerRuntimeCollector([_ticker("BTCUSDT", 100, 101.0)])
    first = collector.publish(as_of_ms=1_000)
    assert first is not None
    runtime_path = tmp_path / "ticker-runtime.json"
    writer = runtime.AtomicTickerRuntimeWriter(runtime_path)

    writer.write(first)
    collector.record([_ticker("BTCUSDT", 200, 102.0)])
    second = collector.publish(as_of_ms=2_000)
    assert second is not None
    writer.write(second)

    raw = runtime_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload == {
        "schemaVersion": 1,
        "sequence": 2,
        "asOf": 2_000,
        "fullUpdates": [["BTCUSDT", 102.0, 200]],
        "deltaUpdates": [["BTCUSDT", 102.0, 200]],
    }
    assert "\n  " not in raw
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [runtime_path]


def test_atomic_writer_does_not_replace_newer_sequence_with_delayed_batch(tmp_path) -> None:
    runtime = _runtime_module()
    runtime_path = tmp_path / "ticker-runtime.json"
    writer = runtime.AtomicTickerRuntimeWriter(runtime_path)
    newer = runtime.TickerRuntimePublication(
        sequence=2,
        as_of_ms=2_000,
        full_updates=[("BTCUSDT", 102.0, 200)],
        delta_updates=[("BTCUSDT", 102.0, 200)],
    )
    delayed = runtime.TickerRuntimePublication(
        sequence=1,
        as_of_ms=1_000,
        full_updates=[("BTCUSDT", 101.0, 100)],
        delta_updates=[("BTCUSDT", 101.0, 100)],
    )

    writer.write(newer)
    writer.write(delayed)

    assert json.loads(runtime_path.read_text(encoding="utf-8"))["sequence"] == 2


def test_atomic_writer_keeps_formal_file_when_partial_tmp_replace_fails(
    tmp_path, monkeypatch
) -> None:
    runtime = _runtime_module()
    runtime_path = tmp_path / "ticker-runtime.json"
    writer = runtime.AtomicTickerRuntimeWriter(runtime_path)
    collector = runtime.TickerRuntimeCollector([_ticker("BTCUSDT", 100, 101.0)])
    first = collector.publish(as_of_ms=1_000)
    assert first is not None
    writer.write(first)
    original = runtime_path.read_bytes()
    collector.record([_ticker("BTCUSDT", 200, 102.0)])
    second = collector.publish(as_of_ms=2_000)
    assert second is not None
    tmp_runtime_path = runtime_path.with_suffix(".json.tmp")

    def partial_then_fail(_source, _destination) -> None:
        tmp_runtime_path.write_text('{"schemaVersion":', encoding="utf-8")
        raise OSError("replace failed")

    with monkeypatch.context() as patch_context:
        patch_context.setattr(runtime.os, "replace", partial_then_fail)
        with pytest.raises(OSError, match="replace failed"):
            writer.write(second)

    assert runtime_path.read_bytes() == original
    assert json.loads(runtime_path.read_text(encoding="utf-8"))["sequence"] == 1
    assert tmp_runtime_path.read_text(encoding="utf-8") == '{"schemaVersion":'

    writer.write(second)

    assert json.loads(runtime_path.read_text(encoding="utf-8"))["sequence"] == 2
    assert not tmp_runtime_path.exists()


async def test_periodic_publisher_stops_updating_after_cancellation(tmp_path) -> None:
    runtime = _runtime_module()
    runtime_path = tmp_path / "ticker-runtime.json"
    writer = runtime.AtomicTickerRuntimeWriter(runtime_path)
    collector = runtime.TickerRuntimeCollector([_ticker("BTCUSDT", 100, 101.0)])
    task = asyncio.create_task(
        runtime.publish_ticker_runtime_periodically(
            collector,
            writer,
            interval_seconds=0.01,
        )
    )
    await _wait_for_sequence(runtime_path, 1)
    collector.record([_ticker("BTCUSDT", 200, 102.0)])
    await _wait_for_sequence(runtime_path, 2)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    stopped_payload = runtime_path.read_bytes()
    collector.record([_ticker("BTCUSDT", 300, 103.0)])
    await asyncio.sleep(0.04)

    assert runtime_path.read_bytes() == stopped_payload
    assert json.loads(stopped_payload)["sequence"] == 2


def test_collector_is_thread_safe_and_keeps_newest_timestamp() -> None:
    runtime = _runtime_module()
    collector = runtime.TickerRuntimeCollector()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda ts_ms: collector.record([_ticker("BTCUSDT", ts_ms, float(ts_ms))]),
                range(1, 101),
            )
        )

    publication = collector.publish(as_of_ms=1_000)

    assert publication is not None
    assert publication.full_updates == [("BTCUSDT", 100.0, 100)]


def test_settings_and_composition_build_runtime_writer_from_environment(
    tmp_path, monkeypatch
) -> None:
    runtime_path = tmp_path / "runtime" / "tickers.json"
    monkeypatch.setenv("PREP_WATCHDECK_TICKER_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("PREP_WATCHDECK_TICKER_PUBLISH_INTERVAL_SECONDS", "1.5")

    settings = Settings()
    writer = build_ticker_runtime_writer(settings)

    assert settings.ticker_runtime_path == runtime_path
    assert settings.ticker_publish_interval_seconds == 1.5
    assert writer.runtime_path == runtime_path


def _runtime_module() -> ModuleType:
    return importlib.import_module("prep_watchdeck.application.ticker_runtime")


def _ticker(symbol: str, ts_ms: int, last_price: float | None) -> TickerLatestRecord:
    return TickerLatestRecord(
        symbol=symbol,
        ts_ms=ts_ms,
        last_price=last_price,
        updated_at_ms=ts_ms,
    )


async def _wait_for_sequence(runtime_path, expected: int) -> None:
    for _ in range(100):
        if runtime_path.exists():
            payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            if payload["sequence"] == expected:
                return
        await asyncio.sleep(0.01)
    raise AssertionError(f"ticker runtime did not reach sequence {expected}")
