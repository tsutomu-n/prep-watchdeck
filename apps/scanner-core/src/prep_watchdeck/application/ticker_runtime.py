from __future__ import annotations

import asyncio
import json
import math
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from prep_watchdeck.domain.service_models import TickerLatestRecord
from prep_watchdeck.domain.symbols import is_safe_public_symbol

TickerRuntimeUpdate = tuple[str, float, int]


@dataclass(frozen=True)
class TickerRuntimePublication:
    sequence: int
    as_of_ms: int
    full_updates: list[TickerRuntimeUpdate]
    delta_updates: list[TickerRuntimeUpdate]

    def batch_after(self, after_sequence: int) -> dict[str, object] | None:
        if after_sequence == self.sequence:
            return None
        use_delta = after_sequence > 0 and after_sequence == self.sequence - 1
        updates = self.delta_updates if use_delta else self.full_updates
        return {
            "schemaVersion": 1,
            "sequence": self.sequence,
            "asOf": self.as_of_ms,
            "full": not use_delta,
            "updates": [list(update) for update in updates],
        }

    def to_runtime_file(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "sequence": self.sequence,
            "asOf": self.as_of_ms,
            "fullUpdates": [list(update) for update in self.full_updates],
            "deltaUpdates": [list(update) for update in self.delta_updates],
        }


class TickerRuntimeCollector:
    def __init__(self, initial: Iterable[TickerLatestRecord] = ()) -> None:
        self._lock = RLock()
        self._latest: dict[str, TickerRuntimeUpdate] = {}
        self._dirty: dict[str, TickerRuntimeUpdate] = {}
        self._sequence = 0
        self.record(initial)

    def record(self, tickers: Iterable[TickerLatestRecord]) -> None:
        with self._lock:
            for ticker in tickers:
                update = _runtime_update(ticker)
                if update is None:
                    continue
                symbol, _, ts_ms = update
                previous = self._latest.get(symbol)
                if previous is not None and ts_ms < previous[2]:
                    continue
                self._latest[symbol] = update
                self._dirty[symbol] = update

    def publish(self, *, as_of_ms: int | None = None) -> TickerRuntimePublication | None:
        with self._lock:
            if not self._dirty:
                return None
            self._sequence += 1
            publication = TickerRuntimePublication(
                sequence=self._sequence,
                as_of_ms=int(time.time() * 1000) if as_of_ms is None else as_of_ms,
                full_updates=[self._latest[symbol] for symbol in sorted(self._latest)],
                delta_updates=[self._dirty[symbol] for symbol in sorted(self._dirty)],
            )
            self._dirty.clear()
            return publication


class TickerRuntimeWriter(Protocol):
    def write(self, publication: TickerRuntimePublication) -> None:
        """Atomically publish a ticker runtime batch."""


class AtomicTickerRuntimeWriter:
    def __init__(self, runtime_path: Path) -> None:
        self.runtime_path = runtime_path
        self._lock = RLock()
        self._last_sequence = 0

    def write(self, publication: TickerRuntimePublication) -> None:
        with self._lock:
            if publication.sequence <= self._last_sequence:
                return
            self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                publication.to_runtime_file(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            tmp_path = self.runtime_path.with_suffix(f"{self.runtime_path.suffix}.tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.runtime_path)
            self._last_sequence = publication.sequence


def publish_ticker_runtime_once(
    collector: TickerRuntimeCollector,
    writer: TickerRuntimeWriter,
    *,
    as_of_ms: int | None = None,
) -> TickerRuntimePublication | None:
    publication = collector.publish(as_of_ms=as_of_ms)
    if publication is not None:
        writer.write(publication)
    return publication


async def publish_ticker_runtime_periodically(
    collector: TickerRuntimeCollector,
    writer: TickerRuntimeWriter,
    *,
    interval_seconds: float,
    publish_immediately: bool = True,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if publish_immediately:
        await asyncio.to_thread(publish_ticker_runtime_once, collector, writer)
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(publish_ticker_runtime_once, collector, writer)


def _runtime_update(ticker: TickerLatestRecord) -> TickerRuntimeUpdate | None:
    symbol = ticker.symbol.strip().upper()
    last_price = ticker.last_price
    if (
        not is_safe_public_symbol(symbol)
        or last_price is None
        or not math.isfinite(last_price)
        or last_price <= 0
    ):
        return None
    return (symbol, last_price, ticker.ts_ms)
