from __future__ import annotations

from itertools import pairwise
from typing import Any

from prep_watchdeck.bitget.candles import fetch_recent_history_candles
from prep_watchdeck.models import CandleBar


async def test_fetch_recent_history_candles_paginates_beyond_legacy_attempt_cap(
    monkeypatch,
) -> None:
    monkeypatch.setattr("prep_watchdeck.bitget.candles.time.time", lambda: 1_781_000_000.0)
    client: Any = FakeHistoryClient()

    bars = await fetch_recent_history_candles(
        client,
        "BTCUSDT",
        "USDT-FUTURES",
        granularity="1m",
        limit=2500,
    )

    assert len(bars) == 2500
    assert len(client.calls) == 13
    assert client.calls[1]["endTime"] == client.calls[0]["startTime"]
    assert bars == sorted(bars, key=lambda bar: bar.ts)
    assert _gap_minutes(bars) == []


class FakeHistoryClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        assert path == "/api/v2/mix/market/history-candles"
        self.calls.append(params)
        limit = int(params["limit"])
        end_ms = int(params["endTime"])
        start_ms = end_ms - limit * 60_000
        return {
            "data": [
                [
                    str(start_ms + index * 60_000),
                    "100.0",
                    "101.0",
                    "99.0",
                    "100.5",
                    "10.0",
                    "1005.0",
                ]
                for index in range(limit)
            ]
        }


def _gap_minutes(bars: list[CandleBar]) -> list[int]:
    timestamps = sorted(bar.ts for bar in bars)
    return [
        (current - previous) // 60_000
        for previous, current in pairwise(timestamps)
        if current - previous != 60_000
    ]
