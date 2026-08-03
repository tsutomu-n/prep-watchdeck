from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from prep_watchdeck.application.ws_frames import parse_ws_frame
from prep_watchdeck.domain.service_models import Candle1mRecord, TickerLatestRecord


class WsFrameStore(Protocol):
    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        """Persist latest ticker rows."""

    def upsert_candles_1m(self, candles: list[Candle1mRecord]) -> None:
        """Persist 1m candle rows."""


class TickerRuntimeSink(Protocol):
    def record(self, tickers: list[TickerLatestRecord]) -> None:
        """Record persisted ticker rows for runtime publication."""


@dataclass(frozen=True)
class WsIngestResult:
    ticker_count: int
    candle_1m_count: int


@dataclass
class WsBatchBuffer:
    tickers: list[TickerLatestRecord]
    candles_1m: list[Candle1mRecord]

    @classmethod
    def empty(cls) -> WsBatchBuffer:
        return cls(tickers=[], candles_1m=[])

    @property
    def record_count(self) -> int:
        return len(self.tickers) + len(self.candles_1m)

    def add_payload(self, payload: Mapping[str, Any]) -> WsIngestResult:
        parsed = parse_ws_frame(payload)
        self.tickers.extend(parsed.tickers)
        self.candles_1m.extend(parsed.candles_1m)
        return WsIngestResult(
            ticker_count=len(parsed.tickers),
            candle_1m_count=len(parsed.candles_1m),
        )

    def flush(
        self,
        store: WsFrameStore,
        *,
        ticker_sink: TickerRuntimeSink | None = None,
    ) -> None:
        if self.tickers:
            store.upsert_ticker_latest(self.tickers)
        if self.candles_1m:
            store.upsert_candles_1m(self.candles_1m)
        if ticker_sink is not None and self.tickers:
            ticker_sink.record(self.tickers)
        self.tickers = []
        self.candles_1m = []


def ingest_ws_payload(store: WsFrameStore, payload: Mapping[str, Any]) -> WsIngestResult:
    batch = WsBatchBuffer.empty()
    result = batch.add_payload(payload)
    batch.flush(store)
    return result
