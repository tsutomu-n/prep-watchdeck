from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

from prep_watchdeck.application.service_plan import SubscriptionPlan
from prep_watchdeck.domain.service_models import (
    BackfillProgress,
    ServiceDiagnostics,
    ServiceStateSnapshot,
)


class ServiceStateStore(Protocol):
    def diagnostics(self) -> ServiceDiagnostics:
        """Return service diagnostics."""


class ServiceStateWriter(Protocol):
    def write(self, snapshot: ServiceStateSnapshot) -> None:
        """Atomically publish service state."""


def build_service_state_snapshot(
    store: ServiceStateStore,
    *,
    product_type: str,
    subscription: SubscriptionPlan,
    backfill: BackfillProgress | None = None,
    reconcile: BackfillProgress | None = None,
    generated_at_ms: int | None = None,
) -> ServiceStateSnapshot:
    diagnostics = store.diagnostics()
    generated_at_ms = int(time.time() * 1000) if generated_at_ms is None else generated_at_ms
    return ServiceStateSnapshot(
        generated_at_ms=generated_at_ms,
        data_as_of_ms=diagnostics.latest_candle_1m_ts_ms,
        product_type=product_type,
        stream_symbols=subscription.symbol_count,
        stream_channels=subscription.channel_count,
        stream_shards=subscription.shard_count,
        diagnostics=diagnostics,
        backfill=backfill,
        reconcile=reconcile,
    )


def publish_service_state_once(
    store: ServiceStateStore,
    writer: ServiceStateWriter,
    *,
    product_type: str,
    subscription: SubscriptionPlan,
    backfill: BackfillProgress | None = None,
    reconcile: BackfillProgress | None = None,
    generated_at_ms: int | None = None,
) -> ServiceStateSnapshot:
    snapshot = build_service_state_snapshot(
        store,
        product_type=product_type,
        subscription=subscription,
        backfill=backfill,
        reconcile=reconcile,
        generated_at_ms=generated_at_ms,
    )
    writer.write(snapshot)
    return snapshot


async def publish_service_state_periodically(
    store: ServiceStateStore,
    writer: ServiceStateWriter,
    *,
    product_type: str,
    subscription: SubscriptionPlan,
    interval_seconds: float,
    publish_immediately: bool = True,
    backfill_provider: Callable[[], BackfillProgress | None] | None = None,
    reconcile_provider: Callable[[], BackfillProgress | None] | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if publish_immediately:
        await asyncio.to_thread(
            publish_service_state_once,
            store,
            writer,
            product_type=product_type,
            subscription=subscription,
            backfill=backfill_provider() if backfill_provider is not None else None,
            reconcile=reconcile_provider() if reconcile_provider is not None else None,
        )
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(
            publish_service_state_once,
            store,
            writer,
            product_type=product_type,
            subscription=subscription,
            backfill=backfill_provider() if backfill_provider is not None else None,
            reconcile=reconcile_provider() if reconcile_provider is not None else None,
        )
