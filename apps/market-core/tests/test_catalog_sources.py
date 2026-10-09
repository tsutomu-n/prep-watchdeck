from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
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


@pytest.mark.parametrize("field", ["maxOrderQty", "maxMarketOrderQty", "posLimit"])
def test_bitget_order_limits_keep_semantic_definition_and_full_provenance(field: str) -> None:
    payload = json.loads((FIXTURES / "bitget.json").read_text(encoding="utf-8"))
    original = parse_bitget_catalog(payload, observed_at=OBSERVED_AT).instruments[0]
    changed = replace(original, raw_definition={**original.raw_definition, field: "123"})

    assert changed.definition_sha256() != original.definition_sha256()
    assert changed.semantic_definition_sha256() == original.semantic_definition_sha256()
    assert changed.raw_definition[field] == "123"
    assert original.raw_definition == payload["data"][0]


@pytest.mark.parametrize("field", ["launchTime", "pricePlace", "unknownDefinitionField"])
def test_bitget_listing_price_precision_and_unknown_changes_separate_versions(field: str) -> None:
    payload = json.loads((FIXTURES / "bitget.json").read_text(encoding="utf-8"))
    original = parse_bitget_catalog(payload, observed_at=OBSERVED_AT).instruments[0]
    changed = replace(original, raw_definition={**original.raw_definition, field: "123"})

    assert changed.semantic_definition_sha256() != original.semantic_definition_sha256()


def test_normalized_changes_separate_versions() -> None:
    payload = json.loads((FIXTURES / "bitget.json").read_text(encoding="utf-8"))
    original = parse_bitget_catalog(payload, observed_at=OBSERVED_AT).instruments[0]
    changed_definitions = (
        replace(original, base_asset="OTHER"),
        replace(original, funding_interval_seconds=3_600),
        replace(original, price_tick=Decimal("0.10")),
        replace(original, amount_step=Decimal("1")),
        replace(original, contract_multiplier=Decimal("1000")),
    )
    for changed in changed_definitions:
        assert changed.semantic_definition_sha256() != original.semantic_definition_sha256()


def test_aster_unconfirmed_raw_fields_continue_separating_versions() -> None:
    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    original = parse_aster_catalog(payload, observed_at=OBSERVED_AT).instruments[0]
    changed = replace(original, raw_definition={**original.raw_definition, "imn": "123"})

    assert changed.semantic_definition_sha256() != original.semantic_definition_sha256()


def test_aster_create_time_drift_preserves_identity_only_with_exact_listing_boundary() -> None:
    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    parsed = parse_aster_catalog(payload, observed_at=OBSERVED_AT).instruments[0]
    original = replace(
        parsed,
        raw_definition={
            **parsed.raw_definition,
            "onboardDate": 1_790_751_900_000,
            "createTime": 100,
        },
    )
    changed = replace(original, raw_definition={**original.raw_definition, "createTime": 101})
    assert changed.definition_sha256() != original.definition_sha256()
    assert changed.semantic_definition_sha256() == original.semantic_definition_sha256()
    relisted = replace(
        changed, raw_definition={**changed.raw_definition, "onboardDate": 1_790_751_900_001}
    )
    assert relisted.semantic_definition_sha256() != original.semantic_definition_sha256()
    for invalid in (None, 0, True, "1790751900000"):
        first = replace(
            original, raw_definition={**original.raw_definition, "onboardDate": invalid}
        )
        second = replace(first, raw_definition={**first.raw_definition, "createTime": 101})
        assert first.semantic_definition_sha256() != second.semantic_definition_sha256()


def test_aster_uses_official_v3_hosts() -> None:
    assert ASTER_CATALOG_URL == "https://fapi.asterdex.com/fapi/v3/exchangeInfo"
    assert ASTER_L1_BASE_URL == "https://fapi.asterdex.com"
    assert ASTER_WS_URL == "wss://fstream.asterdex.com/ws"
    assert ASTER_SELECTED_WS_URL == ASTER_WS_URL


@pytest.mark.parametrize(
    "underlying_subtype",
    [[], ["Top"], ["AI"], ["Meme"], ["STORAGE"], ["Top", "Meme"]],
)
def test_aster_accepts_confirmed_crypto_subtypes(underlying_subtype: list[str]) -> None:
    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    row = payload["symbols"][0]
    row["underlyingSubType"] = underlying_subtype

    batch = parse_aster_catalog(payload, observed_at=OBSERVED_AT)

    instrument = next(item for item in batch.instruments if item.source_symbol == "BTCUSDT")
    assert instrument.asset_class == "crypto"


@pytest.mark.parametrize(
    "underlying_subtype",
    [
        ["STOCK"],
        ["ETF"],
        ["Commodities"],
        ["pre-launch", "STOCK"],
        ["AOS2"],
        ["Top", "AOS2"],
        ["Top", "STOCK"],
        None,
        "Top",
        [""],
        [1],
    ],
)
def test_aster_rejects_rwa_synthetic_and_unconfirmed_subtypes(
    underlying_subtype: object,
) -> None:
    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    row = payload["symbols"][0]
    row["underlyingSubType"] = underlying_subtype

    batch = parse_aster_catalog(payload, observed_at=OBSERVED_AT)

    assert all(item.source_symbol != "BTCUSDT" for item in batch.instruments)
    exclusion = next(item for item in batch.exclusions if item.source_symbol == "BTCUSDT")
    assert exclusion.reason == "rwa_or_unconfirmed"
    assert exclusion.raw_definition["underlyingSubType"] == underlying_subtype


def test_aster_rejects_missing_underlying_subtype() -> None:
    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    row = payload["symbols"][0]
    del row["underlyingSubType"]

    batch = parse_aster_catalog(payload, observed_at=OBSERVED_AT)

    assert all(item.source_symbol != "BTCUSDT" for item in batch.instruments)
    exclusion = next(item for item in batch.exclusions if item.source_symbol == "BTCUSDT")
    assert exclusion.reason == "rwa_or_unconfirmed"
    assert "underlyingSubType" not in exclusion.raw_definition


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
    funding_history = next(
        capability
        for capability in batch.capabilities
        if capability.capability == "funding_history"
    )
    assert funding_history.available is True
    assert funding_history.details == {"capture": "settled_events", "catchupHours": 48}
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


def test_aster_funding_config_units_missing_changes_and_timestamp_provenance() -> None:
    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    config = [{"symbol": "BTCUSDT", "fundingIntervalHours": 8, "time": 1786701600000}]
    batch = parse_aster_catalog(payload, observed_at=OBSERVED_AT, funding_payload=config)
    original = batch.instruments[0]
    assert original.funding_interval_seconds == 28800
    assert original.raw_definition["fundingIntervalConfig"] == {
        "endpoint": "/fapi/v3/fundingInfo",
        "definition": {"symbol": "BTCUSDT", "fundingIntervalHours": 8},
    }
    assert batch.provenance.payload_hash == canonical_json_sha256(batch.raw_payload)
    assert isinstance(batch.raw_payload, dict)
    retained_config = batch.raw_payload["fundingInfo"]
    assert isinstance(retained_config, list)
    assert retained_config[0]["time"] == 1786701600000
    config[0]["time"] += 1
    refreshed = parse_aster_catalog(payload, observed_at=OBSERVED_AT, funding_payload=config)
    assert refreshed.provenance.payload_hash != batch.provenance.payload_hash
    assert refreshed.instruments[0].definition_sha256() == original.definition_sha256()
    config[0]["fundingIntervalHours"] = 4
    changed = parse_aster_catalog(payload, observed_at=OBSERVED_AT, funding_payload=config)
    assert changed.instruments[0].funding_interval_seconds == 14400
    assert changed.instruments[0].semantic_definition_sha256() != (
        original.semantic_definition_sha256()
    )
    assert original.funding_interval_seconds == 28800
    for missing in ([], [{"symbol": "BTCUSDT"}]):
        unknown = parse_aster_catalog(payload, observed_at=OBSERVED_AT, funding_payload=missing)
        assert unknown.instruments[0].funding_interval_seconds is None
        assert unknown.instruments[0].definition_sha256() != original.definition_sha256()


@pytest.mark.parametrize("hours", [True, False, 0, -1, 1.5, "8", "", 3600.0])
def test_aster_rejects_invalid_funding_hour_units(hours: object) -> None:
    from prep_watchdeck_market.sources.common import CatalogSourceError

    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))
    with pytest.raises(CatalogSourceError) as caught:
        parse_aster_catalog(
            payload,
            observed_at=OBSERVED_AT,
            funding_payload=[{"symbol": "BTCUSDT", "fundingIntervalHours": hours}],
        )
    assert caught.value.error_code == "invalid_source_payload"


def test_aster_fetch_joins_funding_config_and_fails_closed_on_transport_error() -> None:
    import asyncio
    from typing import cast

    import aiohttp

    from prep_watchdeck_market.sources.aster import ASTER_FUNDING_CONFIG_URL, fetch_aster_catalog
    from prep_watchdeck_market.sources.common import CatalogSourceError

    payload = json.loads((FIXTURES / "aster.json").read_text(encoding="utf-8"))

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def json(self, **kwargs):
            return [{"symbol": "BTCUSDT", "fundingIntervalHours": 1}]

    class CatalogResponse(Response):
        async def json(self, **kwargs):
            return payload

    class Session:
        def __init__(self, fail=False):
            self.calls = []
            self.fail = fail

        def get(self, url, **kwargs):
            self.calls.append(url)
            if url == ASTER_CATALOG_URL:
                return CatalogResponse()
            if self.fail:
                raise aiohttp.ClientError("private-secret-response")
            return Response()

    session = Session()
    batch = asyncio.run(
        fetch_aster_catalog(cast(aiohttp.ClientSession, session), observed_at=OBSERVED_AT)
    )
    assert session.calls == [ASTER_CATALOG_URL, ASTER_FUNDING_CONFIG_URL]
    assert batch.instruments[0].funding_interval_seconds == 3600
    with pytest.raises(CatalogSourceError) as caught:
        asyncio.run(fetch_aster_catalog(cast(aiohttp.ClientSession, Session(fail=True))))
    assert "private-secret-response" not in str(caught.value)
    assert caught.value.__cause__ is None
