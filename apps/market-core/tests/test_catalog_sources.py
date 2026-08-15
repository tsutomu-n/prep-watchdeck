from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck_market.models import CatalogBatch, canonical_json_sha256
from prep_watchdeck_market.sources.aster import ASTER_CATALOG_URL, parse_aster_catalog
from prep_watchdeck_market.sources.aster_candle_stream import ASTER_WS_URL
from prep_watchdeck_market.sources.aster_l1 import ASTER_L1_BASE_URL
from prep_watchdeck_market.sources.bitget import parse_bitget_catalog
from prep_watchdeck_market.sources.hyperliquid import parse_hyperliquid_catalog
from prep_watchdeck_market.sources.selected_streams import ASTER_SELECTED_WS_URL

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
OBSERVED_AT = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


def test_aster_uses_official_v3_hosts() -> None:
    assert ASTER_CATALOG_URL == "https://fapi.asterdex.com/fapi/v3/exchangeInfo"
    assert ASTER_L1_BASE_URL == "https://fapi.asterdex.com"
    assert ASTER_WS_URL == "wss://fstream.asterdex.com/ws"
    assert ASTER_SELECTED_WS_URL == ASTER_WS_URL


@pytest.mark.parametrize(
    (
        "fixture_name",
        "parser",
        "expected_symbols",
        "expected_quote",
        "expected_step",
        "expected_exclusions",
    ),
    [
        (
            "bitget.json",
            parse_bitget_catalog,
            ("BTCUSDT",),
            "USDT",
            Decimal("0.0001"),
            {"rwa_or_unconfirmed", "not_active", "not_perpetual"},
        ),
        (
            "hyperliquid.json",
            parse_hyperliquid_catalog,
            ("BTC", "HYPE"),
            "USDT",
            Decimal("0.00001"),
            {"delisted", "not_default_core"},
        ),
        (
            "aster.json",
            parse_aster_catalog,
            ("BTCUSDT",),
            "USDT",
            Decimal("0.001"),
            {"not_crypto", "not_active", "not_perpetual"},
        ),
    ],
)
def test_catalog_parsers_table(
    fixture_name: str,
    parser: Callable[..., CatalogBatch],
    expected_symbols: tuple[str, ...],
    expected_quote: str,
    expected_step: Decimal,
    expected_exclusions: set[str],
) -> None:
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))

    batch = parser(payload, observed_at=OBSERVED_AT)

    assert tuple(item.source_symbol for item in batch.instruments) == expected_symbols
    first = batch.instruments[0]
    assert first.venue_instrument_id == f"{first.venue}:{first.source_symbol}"
    assert first.active is True
    assert first.asset_class == "crypto"
    assert first.market_type == "linear_perpetual"
    assert first.execution_model == "clob"
    assert first.base_asset == "BTC"
    assert first.quote_asset == expected_quote
    assert first.quantity_unit == "base"
    assert first.contract_multiplier == Decimal("1")
    assert first.amount_step == expected_step
    assert len(first.definition_sha256()) == 64
    assert batch.provenance.observed_at == OBSERVED_AT
    assert batch.provenance.payload_hash == canonical_json_sha256(batch.raw_payload)
    assert {item.reason for item in batch.exclusions} == expected_exclusions
    if fixture_name in {"bitget.json", "aster.json"}:
        changed_envelope = json.loads(json.dumps(payload))
        assert isinstance(changed_envelope, dict)
        timestamp_field = "requestTime" if fixture_name == "bitget.json" else "serverTime"
        changed_envelope[timestamp_field] = 1
        assert (
            parser(changed_envelope, observed_at=OBSERVED_AT).provenance.payload_hash
            == batch.provenance.payload_hash
        )
    assert any(capability.capability == "catalog" for capability in batch.capabilities)
    if first.venue == "hyperliquid":
        assert batch.instruments[1].quote_asset == "USDC"
        assert batch.provenance.source_at is None
    else:
        assert batch.provenance.source_at is not None
    if first.venue == "aster":
        open_interest = next(
            capability
            for capability in batch.capabilities
            if capability.capability == "open_interest"
        )
        assert open_interest.available is False
