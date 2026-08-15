from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

import aiohttp
import pytest

from prep_watchdeck_market.artifacts import ArtifactPublishResult
from prep_watchdeck_market.market_store import MarketStoreResult
from prep_watchdeck_market.models import (
    CatalogBatch,
    CatalogInstrument,
    CatalogProvenance,
    Venue,
    canonical_json_sha256,
)
from prep_watchdeck_market.service import MarketService


def test_catalog_is_published_only_for_venues_that_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service = MarketService("postgresql://not-used", Path("/not-used"))
        service._session = cast(aiohttp.ClientSession, object())
        old_hyperliquid = _batch("hyperliquid", "OLD")
        service._catalogs["hyperliquid"] = old_hyperliquid
        fetched = {
            "bitget": _batch("bitget", "BTCUSDT"),
            "hyperliquid": _batch("hyperliquid", "BTC"),
            "aster": _batch("aster", "BTCUSDT"),
        }

        async def fetch_bitget(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["bitget"]

        async def fetch_hyperliquid(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["hyperliquid"]

        async def fetch_aster(_session: aiohttp.ClientSession) -> CatalogBatch:
            return fetched["aster"]

        old_visible_during_persist: list[bool] = []

        def fake_persist(
            _database_url: str,
            _changed_batches: Sequence[CatalogBatch],
            _current_batches: Sequence[CatalogBatch],
            _started_at: datetime,
            _source_failures: Sequence[Venue],
        ) -> tuple[Venue, ...]:
            old_visible_during_persist.append(
                service._instruments("hyperliquid")[0].source_symbol == "OLD"
            )
            return ("bitget", "aster")

        monkeypatch.setattr("prep_watchdeck_market.service.fetch_bitget_catalog", fetch_bitget)
        monkeypatch.setattr(
            "prep_watchdeck_market.service.fetch_hyperliquid_catalog", fetch_hyperliquid
        )
        monkeypatch.setattr("prep_watchdeck_market.service.fetch_aster_catalog", fetch_aster)
        monkeypatch.setattr("prep_watchdeck_market.service._persist_catalog_refresh", fake_persist)
        monkeypatch.setattr(
            "prep_watchdeck_market.service._load_current_candle_version_starts_url",
            lambda _database_url: {
                "bitget:BTCUSDT": fetched["bitget"].provenance.observed_at,
                "hyperliquid:OLD": old_hyperliquid.provenance.observed_at,
                "aster:BTCUSDT": fetched["aster"].provenance.observed_at,
            },
        )

        result = await service.refresh_catalog()

        assert old_visible_during_persist == [True]
        assert result.status == "partial"
        assert result.venues_succeeded == ("bitget", "aster")
        assert result.venues_failed == ("hyperliquid",)
        assert service._instruments("bitget")[0].source_symbol == "BTCUSDT"
        assert service._instruments("hyperliquid")[0].source_symbol == "OLD"
        assert service._instruments("aster")[0].source_symbol == "BTCUSDT"

    asyncio.run(scenario())


def test_successful_l1_persistence_triggers_artifact_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = MarketService("postgresql://not-used", tmp_path)
        cycle_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        persisted = _store_result()
        published: list[Path] = []

        def fake_persist(
            _database_url: str,
            _cycle_at: datetime,
            _started_at: datetime,
            _batches: Sequence[object],
        ) -> MarketStoreResult:
            return persisted

        def fake_publish(
            _database_url: str,
            artifact_root: Path,
            _generated_at: datetime,
        ) -> ArtifactPublishResult:
            published.append(artifact_root)
            stop_event.set()
            return ArtifactPublishResult(status="ready", files=())

        monkeypatch.setattr("prep_watchdeck_market.service.persist_market_cycle_url", fake_persist)
        monkeypatch.setattr("prep_watchdeck_market.service._publish_artifacts_url", fake_publish)

        result = await service._persist_l1_cycle(cycle_at, cycle_at, ())
        assert result is persisted

        stop_event = asyncio.Event()
        await service._artifact_loop(stop_event)
        assert published == [tmp_path / "artifacts"]

    asyncio.run(scenario())


def _store_result() -> MarketStoreResult:
    return MarketStoreResult(
        run_id=uuid4(),
        status="succeeded",
        records_received=0,
        records_written=0,
        raw_payloads_written=0,
        unknown_source_rows=0,
        commit_seconds=0.01,
    )


def _batch(venue: Venue, source_symbol: str) -> CatalogBatch:
    observed_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    raw_payload: dict[str, object] = {"venue": venue, "symbol": source_symbol}
    instrument = CatalogInstrument(
        venue=venue,
        source_symbol=source_symbol,
        active=True,
        source_status="active",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset="BTC",
        quote_asset="USDT" if venue != "hyperliquid" else "USD",
        settle_asset="USDT" if venue != "hyperliquid" else "USDC",
        collateral_asset="USDT" if venue != "hyperliquid" else "USDC",
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.1"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=3_600,
        raw_definition=raw_payload,
    )
    return CatalogBatch(
        provenance=CatalogProvenance(
            venue=venue,
            source_kind="native_rest",
            endpoint="https://example.invalid/catalog",
            documentation_url="https://example.invalid/docs",
            observed_at=observed_at,
            source_at=None,
            payload_hash=canonical_json_sha256(raw_payload),
        ),
        instruments=(instrument,),
        exclusions=(),
        capabilities=(),
        raw_payload=raw_payload,
    )
