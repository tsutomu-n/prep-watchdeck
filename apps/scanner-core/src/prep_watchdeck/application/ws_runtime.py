from __future__ import annotations

from collections.abc import AsyncIterable, Mapping
from dataclasses import dataclass
from typing import Any

from prep_watchdeck.application.ws_ingestion import WsFrameStore, ingest_ws_payload


@dataclass(frozen=True)
class WsStreamIngestResult:
    payload_count: int
    ticker_count: int
    candle_1m_count: int

    @property
    def record_count(self) -> int:
        return self.ticker_count + self.candle_1m_count


async def ingest_ws_payload_stream(
    store: WsFrameStore,
    payloads: AsyncIterable[Mapping[str, Any]],
    *,
    max_records: int | None = None,
) -> WsStreamIngestResult:
    if max_records is not None and max_records < 1:
        raise ValueError("max_records must be positive")

    payload_count = 0
    ticker_count = 0
    candle_1m_count = 0
    async for payload in payloads:
        payload_count += 1
        result = ingest_ws_payload(store, payload)
        ticker_count += result.ticker_count
        candle_1m_count += result.candle_1m_count
        if max_records is not None and ticker_count + candle_1m_count >= max_records:
            break

    return WsStreamIngestResult(
        payload_count=payload_count,
        ticker_count=ticker_count,
        candle_1m_count=candle_1m_count,
    )
