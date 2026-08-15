from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from loguru import logger

from prep_watchdeck_market.market_state import MarketBatch
from prep_watchdeck_market.market_store import MarketStoreResult, RunStatus
from prep_watchdeck_market.models import Venue, canonical_json_sha256
from prep_watchdeck_market.scheduler import L1Scheduler, VenueFetcher, next_grid_at
from prep_watchdeck_market.sources.common import CatalogSourceError


def test_partial_failure_becomes_unavailable_without_blocking_other_venues() -> None:
    async def scenario() -> None:
        expected_cycle = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        persisted: list[MarketBatch] = []
        cycle_logs: list[dict[str, object]] = []

        async def success(venue: Venue, cycle: datetime) -> MarketBatch:
            return _batch(venue, cycle)

        async def fail(cycle_at: datetime) -> MarketBatch:
            del cycle_at
            raise CatalogSourceError("source failed", error_code="http_429")

        async def persist(
            cycle_at: datetime, started_at: datetime, batches: Sequence[MarketBatch]
        ) -> MarketStoreResult:
            assert cycle_at == expected_cycle
            assert started_at.tzinfo is not None
            persisted.extend(batches)
            return _store_result("partial")

        scheduler = L1Scheduler(
            (
                VenueFetcher("bitget", "/bitget", lambda cycle_at: success("bitget", cycle_at)),
                VenueFetcher(
                    "hyperliquid",
                    "/hyperliquid",
                    lambda cycle_at: success("hyperliquid", cycle_at),
                ),
                VenueFetcher("aster", "/aster", fail),
            ),
            persist,
        )
        sink_id = logger.add(
            lambda message: cycle_logs.append(dict(message.record["extra"])),
            filter=lambda record: record["extra"].get("event") == "l1_cycle",
        )
        try:
            result = await scheduler.run_cycle(expected_cycle)
        finally:
            logger.remove(sink_id)

        assert result.status == "partial"
        assert result.error_codes == ("aster:http_429",)
        assert {batch.venue for batch in persisted} == {"bitget", "hyperliquid", "aster"}
        failed = next(batch for batch in persisted if batch.venue == "aster")
        assert failed.observations == ()
        assert isinstance(failed.raw_payload, dict)
        assert failed.raw_payload["errorCode"] == "http_429"
        assert len(cycle_logs) == 1
        assert cycle_logs[0] == {
            "event": "l1_cycle",
            "cycle_at": expected_cycle.isoformat(),
            "duration_seconds": cycle_logs[0]["duration_seconds"],
            "status": "partial",
            "fetch_timeout_count": 0,
            "error_codes": "aster:http_429",
            "grid_skips": 0,
            "commit_seconds": 0.01,
        }
        assert isinstance(cycle_logs[0]["duration_seconds"], float)

    asyncio.run(scenario())


def test_running_cycle_skips_overlap_instead_of_queueing() -> None:
    async def scenario() -> None:
        first_cycle = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        second_cycle = datetime(2026, 8, 14, 12, 1, tzinfo=UTC)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked(venue: Venue, cycle: datetime) -> MarketBatch:
            entered.set()
            await release.wait()
            return _batch(venue, cycle)

        async def persist(
            cycle_at: datetime, started_at: datetime, batches: Sequence[MarketBatch]
        ) -> MarketStoreResult:
            del cycle_at, started_at, batches
            return _store_result("succeeded")

        scheduler = L1Scheduler(
            tuple(
                VenueFetcher(
                    venue,
                    f"/{venue}",
                    lambda cycle_at, venue=venue: blocked(venue, cycle_at),
                )
                for venue in ("bitget", "hyperliquid", "aster")
            ),
            persist,
        )
        running = asyncio.create_task(scheduler.run_cycle(first_cycle))
        await entered.wait()
        overlap = await scheduler.run_cycle(second_cycle)
        release.set()
        completed = await running

        assert overlap.status == "skipped"
        assert overlap.store_result is None
        assert completed.status == "succeeded"

    asyncio.run(scenario())


def test_total_deadline_includes_persistence_and_holds_lock_during_cleanup() -> None:
    async def scenario() -> None:
        first_cycle = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        second_cycle = datetime(2026, 8, 14, 12, 1, tzinfo=UTC)
        persistence_cancelled = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_finished = asyncio.Event()

        async def success(venue: Venue, cycle_at: datetime) -> MarketBatch:
            return _batch(venue, cycle_at)

        async def blocked_persist(
            cycle_at: datetime, started_at: datetime, batches: Sequence[MarketBatch]
        ) -> MarketStoreResult:
            del cycle_at, started_at, batches
            try:
                await asyncio.Event().wait()
                raise AssertionError("blocked persistence unexpectedly resumed")
            except asyncio.CancelledError:
                persistence_cancelled.set()
                await cleanup_release.wait()
                cleanup_finished.set()
                raise

        scheduler = L1Scheduler(
            tuple(
                VenueFetcher(
                    venue,
                    f"/{venue}",
                    lambda cycle_at, venue=venue: success(venue, cycle_at),
                )
                for venue in ("bitget", "hyperliquid", "aster")
            ),
            blocked_persist,
            interval_seconds=1,
            deadline_seconds=0.05,
        )
        running = asyncio.create_task(scheduler.run_cycle(first_cycle))
        try:
            await asyncio.wait_for(persistence_cancelled.wait(), timeout=0.2)
            overlap = await scheduler.run_cycle(second_cycle)
            assert overlap.status == "skipped"
            assert not cleanup_finished.is_set()
        finally:
            cleanup_release.set()

        result = await asyncio.wait_for(running, timeout=0.2)
        assert cleanup_finished.is_set()
        assert result.status == "failed"
        assert result.store_result is None
        assert result.error_codes == ("persistence:cycle_deadline_exceeded",)

    asyncio.run(scenario())


def test_next_grid_uses_fixed_rate_minute_boundary() -> None:
    assert next_grid_at(datetime(2026, 8, 14, 12, 0, tzinfo=UTC)) == datetime(
        2026, 8, 14, 12, 0, tzinfo=UTC
    )
    assert next_grid_at(datetime(2026, 8, 14, 12, 0, 20, tzinfo=UTC)) == datetime(
        2026, 8, 14, 12, 1, tzinfo=UTC
    )


def _batch(venue: Venue, cycle_at: datetime) -> MarketBatch:
    raw_payload: dict[str, object] = {"venue": venue}
    return MarketBatch(
        venue=venue,
        cycle_at=cycle_at,
        observed_at=cycle_at,
        endpoint=f"/{venue}",
        payload_hash=canonical_json_sha256(raw_payload),
        observations=(),
        raw_payload=raw_payload,
    )


def _store_result(status: RunStatus) -> MarketStoreResult:
    return MarketStoreResult(
        run_id=UUID(int=1),
        status=status,
        records_received=0,
        records_written=0,
        raw_payloads_written=3,
        unknown_source_rows=0,
        commit_seconds=0.01,
    )
