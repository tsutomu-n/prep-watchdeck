from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import aiohttp
import pytest

import prep_watchdeck_market.funding_runtime as funding_runtime_module
from prep_watchdeck_market.funding_runtime import (
    FUNDING_LOOKBACK,
    FundingRuntime,
    funding_request_window,
)
from prep_watchdeck_market.funding_store import FundingStoreResult
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.funding import (
    FundingBatch,
    FundingEvent,
    FundingSourceError,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def test_request_window_is_bounded_and_skips_known_not_due_event() -> None:
    instrument = _instrument("bitget", "BTCUSDT", 28_800)
    version_start = NOW - timedelta(days=4)

    initial = funding_request_window(
        instrument,
        version_start=version_start,
        latest_funding_at=None,
        now=NOW,
    )
    assert initial is not None
    assert initial.start_at == NOW - FUNDING_LOOKBACK
    assert initial.end_at == NOW

    assert (
        funding_request_window(
            instrument,
            version_start=version_start,
            latest_funding_at=NOW - timedelta(hours=7, minutes=58),
            now=NOW,
        )
        is None
    )

    due = funding_request_window(
        instrument,
        version_start=version_start,
        latest_funding_at=NOW - timedelta(hours=9),
        now=NOW,
    )
    assert due is not None
    assert due.start_at == NOW - timedelta(hours=9) + timedelta(milliseconds=1)


def test_one_sweep_isolates_source_failure_and_persists_successes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        instruments = (
            _instrument("bitget", "BTCUSDT", 28_800),
            _instrument("hyperliquid", "BTC", 3_600),
            _instrument("aster", "BTCUSDT", None),
        )
        version_starts = {
            item.venue_instrument_id: NOW - timedelta(hours=2) for item in instruments
        }
        persisted: dict[str, object] = {}

        def fake_latest(_database_url: str) -> dict[str, datetime]:
            return {}

        async def fake_fetch(
            _session: aiohttp.ClientSession,
            instrument: CatalogInstrument,
            *,
            start_at: datetime,
            end_at: datetime,
        ) -> FundingBatch:
            if instrument.venue == "hyperliquid":
                raise FundingSourceError("temporary failure", error_code="source_unavailable")
            event = FundingEvent(
                venue=instrument.venue,
                source_symbol=instrument.source_symbol,
                funding_at=NOW - timedelta(hours=1),
                funding_rate_raw=Decimal("0.0001"),
                observed_at=NOW,
                raw_payload={"symbol": instrument.source_symbol},
            )
            raw = [{"symbol": instrument.source_symbol, "start": start_at.isoformat()}]
            return FundingBatch(
                venue=instrument.venue,
                source_symbol=instrument.source_symbol,
                endpoint="/funding",
                observed_at=NOW,
                payload_hash=_hash(raw),
                events=(event,),
                raw_payload=raw,
            )

        def fake_persist(
            _database_url: str,
            _started_at: datetime,
            batches: tuple[FundingBatch, ...],
            failures: tuple[object, ...],
        ) -> FundingStoreResult:
            persisted["batches"] = batches
            persisted["failures"] = failures
            return FundingStoreResult(
                run_id=uuid4(),
                status="partial",
                records_received=2,
                records_written=2,
                records_unchanged=0,
                raw_payloads_written=2,
                admission_rejected=0,
                commit_seconds=0.01,
            )

        monkeypatch.setattr(
            "prep_watchdeck_market.funding_runtime.load_latest_funding_times_url",
            fake_latest,
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.funding_runtime.fetch_funding_history",
            fake_fetch,
        )
        monkeypatch.setattr(
            "prep_watchdeck_market.funding_runtime.persist_funding_sweep_url",
            fake_persist,
        )
        for venue in ("bitget", "hyperliquid", "aster"):
            monkeypatch.setitem(
                funding_runtime_module.FUNDING_REQUEST_PACE_SECONDS,
                venue,
                0,
            )

        runtime = FundingRuntime(
            "postgresql://unused",
            cast(aiohttp.ClientSession, object()),
            lambda: instruments,
            lambda: version_starts,
            utc_clock=lambda: NOW,
        )
        result = await runtime.run_once(asyncio.Event(), started_at=NOW)

        assert result.requests_attempted == 3
        assert result.requests_succeeded == 2
        assert result.failures == 1
        assert result.store is not None and result.store.status == "partial"
        assert len(cast(tuple[object, ...], persisted["batches"])) == 2
        assert len(cast(tuple[object, ...], persisted["failures"])) == 1

    asyncio.run(scenario())


def _hash(value: object) -> str:
    from prep_watchdeck_market.models import canonical_json_sha256

    return canonical_json_sha256(value)


def _instrument(
    venue: str,
    symbol: str,
    interval_seconds: int | None,
) -> CatalogInstrument:
    return CatalogInstrument(
        venue=venue,  # type: ignore[arg-type]
        source_symbol=symbol,
        active=True,
        source_status="normal",
        asset_class="crypto",
        market_type="linear_perpetual",
        execution_model="clob",
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        settle_asset="USDT",
        collateral_asset="USDT",
        quantity_unit="base",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.01"),
        amount_step=Decimal("0.001"),
        funding_interval_seconds=interval_seconds,
        raw_definition={"symbol": symbol},
    )
