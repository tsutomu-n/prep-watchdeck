from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck_market.candles import CandleParseError
from prep_watchdeck_market.sources.aster_candles import parse_aster_candle
from prep_watchdeck_market.sources.bitget_candles import parse_bitget_finished_candles
from prep_watchdeck_market.sources.hyperliquid_candles import HyperliquidCandleFinalizer

FIXTURES = Path(__file__).parent / "fixtures" / "candles"
OBSERVED_AT = datetime(2026, 8, 14, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize("venue", ["bitget", "aster", "hyperliquid", "malformed"])
def test_candle_finality_table(venue: str) -> None:
    if venue == "bitget":
        payload = _fixture("bitget.json")
        candles = parse_bitget_finished_candles(
            payload,
            source_symbol="BTCUSDT",
            observed_at=OBSERVED_AT,
        )

        assert len(candles) == 5
        assert len({candle.storage_key for candle in candles}) == 5
        assert candles[0].bucket_start == datetime(2026, 8, 14, 9, 56, tzinfo=UTC)
        assert candles[2].close_price == Decimal("104.5")
        assert all(candle.finality == "confirmed" for candle in candles)
        assert all(candle.source_confirmed for candle in candles)
        return

    if venue == "aster":
        payload = _fixture("aster.json")
        candle = parse_aster_candle(payload, observed_at=OBSERVED_AT)

        assert candle is not None
        assert candle.venue_instrument_id == "aster:BTCUSDT"
        assert candle.finality == "confirmed"
        assert candle.source_confirmed is True
        assert candle.volume_notional == Decimal("741")
        assert candle.trade_count == 42
        assert isinstance(payload, dict)
        assert isinstance(payload["data"], dict)
        assert isinstance(payload["data"]["k"], dict)
        payload["data"]["k"]["x"] = False
        assert parse_aster_candle(payload, observed_at=OBSERVED_AT) is None
        return

    if venue == "hyperliquid":
        payload = _fixture("hyperliquid.json")
        assert isinstance(payload, list)
        finalizer = HyperliquidCandleFinalizer()
        finalizer.ingest(payload[0], observed_at=datetime(2026, 8, 14, 10, 0, 30, tzinfo=UTC))
        finalizer.ingest(payload[1], observed_at=datetime(2026, 8, 14, 10, 1, 2, tzinfo=UTC))

        assert finalizer.finalize(now=datetime(2026, 8, 14, 10, 1, 4, tzinfo=UTC)) == ()
        candles = finalizer.finalize(now=datetime(2026, 8, 14, 10, 1, 5, tzinfo=UTC))
        assert len(candles) == 1
        candle = candles[0]
        assert candle.close_price == Decimal("106")
        assert candle.finality == "derived_final"
        assert candle.source_confirmed is False
        assert candle.source_at == datetime(2026, 8, 14, 10, 1, tzinfo=UTC)
        assert finalizer.finalize(now=datetime(2026, 8, 14, 10, 2, tzinfo=UTC)) == ()
        return

    payload = _fixture("aster.json")
    assert isinstance(payload, dict)
    assert isinstance(payload["data"], dict)
    assert isinstance(payload["data"]["k"], dict)
    payload["data"]["k"]["h"] = "100"
    with pytest.raises(CandleParseError):
        parse_aster_candle(payload, observed_at=OBSERVED_AT)


def _fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_hyperliquid_receipt_finalization_and_late_correction_are_separate() -> None:
    from dataclasses import replace
    from datetime import timedelta

    payload = _fixture("hyperliquid.json")
    assert isinstance(payload, list)
    receipt = datetime(2026, 8, 14, 10, 0, 30, tzinfo=UTC)
    decision = datetime(2026, 8, 14, 10, 1, 9, tzinfo=UTC)
    finalizer = HyperliquidCandleFinalizer()
    finalizer.ingest(payload[0], observed_at=receipt)
    assert finalizer.finalize(now=decision - timedelta(seconds=5)) == ()
    candle = finalizer.finalize(now=decision)[0]
    assert candle.observed_at == receipt
    assert candle.finalized_at == decision
    assert not candle.source_confirmed
    assert candle.volume_notional is None
    assert replace(candle, finalized_at=None).finalized_at is None  # Legacy is unknown.
    with pytest.raises(CandleParseError):
        replace(candle, finalized_at=candle.bucket_end - timedelta(seconds=1))

    correction_receipt = decision + timedelta(seconds=11)
    finalizer.ingest(payload[1], observed_at=correction_receipt)
    # A delayed/out-of-order pending receipt cannot overwrite the latest candidate.
    finalizer.ingest(payload[0], observed_at=correction_receipt - timedelta(seconds=1))
    correction = finalizer.finalize(now=correction_receipt + timedelta(seconds=2))[0]
    assert correction.storage_key == candle.storage_key
    assert correction.close_price == Decimal("106")
    assert correction.observed_at == correction_receipt
    assert correction.finalized_at == correction_receipt + timedelta(seconds=2)
    assert correction.finality == "derived_final"
    assert finalizer.finalize(now=correction_receipt + timedelta(minutes=1)) == ()
