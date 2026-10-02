from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp
import psycopg

from prep_watchdeck_market.artifacts import write_artifact_atomic
from prep_watchdeck_market.candle_recovery import _open_connection, _thread_call, recovery_cutoff
from prep_watchdeck_market.candle_recovery_state import (
    CandleRecoveryState,
    RecoveryExecution,
    RecoverySummary,
    RecoveryTargetDetail,
    RecoveryTargetIdentity,
    RecoveryTrigger,
    RecoveryWindow,
)
from prep_watchdeck_market.candle_recovery_store import (
    RecoveryStoreError,
    RecoveryTarget,
    RecoveryVersionChanged,
    finish_recovery_run,
    insert_missing_candles,
    start_recovery_run,
)
from prep_watchdeck_market.candles import Candle1m, CandleParseError
from prep_watchdeck_market.models import Venue
from prep_watchdeck_market.runtime_lock import exclusive_runtime_lock
from prep_watchdeck_market.sources.candle_history import (
    HistoryBudgetExceeded,
    HistoryFetchError,
    HistoryPayloadInvalid,
    HistoryRateLimited,
    NativeCandleHistoryClient,
)

ENDPOINT_RUN_SECONDS = 60.0
ENDPOINT_MAX_REQUESTS = 20
ENDPOINT_REQUEST_INTERVAL_SECONDS = 3.0
ENDPOINT_MINUTE_OFFSETS = (1, 16, 61, 1441)
EndpointSnapshot = dict[RecoveryTarget, tuple[datetime, ...]]


def load_missing_endpoints(
    connection: psycopg.Connection[Any],
    *,
    now: datetime,
    version_id: int | None = None,
) -> EndpointSnapshot:
    """Read absent exact close endpoints inside active current definitions only."""
    cutoff = recovery_cutoff(now)
    try:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            rows = connection.execute(
                """
                SELECT vi.venue_instrument_version_id, vi.venue, vi.source_symbol,
                       vi.definition_hash, vi.valid_from,
                       vi.base_asset, vi.quote_asset, vi.settle_asset, endpoint.bucket_at
                FROM venue_instrument_versions vi
                CROSS JOIN LATERAL (
                    SELECT %s::timestamptz - age * interval '1 minute' AS bucket_at
                    FROM unnest(%s::integer[]) age
                ) endpoint
                LEFT JOIN candle_1m candle
                  ON candle.venue_instrument_version_id = vi.venue_instrument_version_id
                 AND candle.bucket_at = endpoint.bucket_at
                WHERE vi.valid_to IS NULL AND vi.active
                  AND vi.asset_class = 'crypto' AND vi.market_type = 'linear_perpetual'
                  AND vi.venue IN ('bitget', 'hyperliquid', 'aster')
                  AND (%s::bigint IS NULL OR vi.venue_instrument_version_id = %s)
                  AND endpoint.bucket_at >= vi.valid_from
                  AND candle.venue_instrument_version_id IS NULL
                ORDER BY vi.venue, vi.source_symbol, endpoint.bucket_at DESC
                """,
                (cutoff, list(ENDPOINT_MINUTE_OFFSETS), version_id, version_id),
            ).fetchall()
    except psycopg.Error:
        raise RecoveryStoreError("endpoint scan unavailable") from None
    found: dict[RecoveryTarget, list[datetime]] = {}
    for row in rows:
        target = RecoveryTarget(*row[:8])
        found.setdefault(target, []).append(row[8])
    return {target: tuple(buckets) for target, buckets in found.items()}


def _remaining_snapshot(
    connection: psycopg.Connection[Any], before: EndpointSnapshot
) -> EndpointSnapshot:
    """Rescan every observed absent key with one bounded read-only query."""
    if not before:
        return {}
    keys = [(target.version_id, bucket) for target, buckets in before.items() for bucket in buckets]
    try:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            remaining = set(
                connection.execute(
                    """
                    SELECT expected.version_id, expected.bucket_at
                    FROM unnest(%s::bigint[], %s::timestamptz[])
                         AS expected(version_id, bucket_at)
                    LEFT JOIN candle_1m candle
                      ON candle.venue_instrument_version_id = expected.version_id
                     AND candle.bucket_at = expected.bucket_at
                    WHERE candle.venue_instrument_version_id IS NULL
                    """,
                    ([version_id for version_id, _ in keys], [bucket for _, bucket in keys]),
                ).fetchall()
            )
    except psycopg.Error:
        raise RecoveryStoreError("endpoint rescan unavailable") from None
    return {
        target: tuple(bucket for bucket in buckets if (target.version_id, bucket) in remaining)
        for target, buckets in before.items()
    }


class CandleEndpointRecovery:
    """Repair current metric endpoints without fabricating or overwriting candles."""

    def __init__(
        self,
        database_url: str,
        state_dir: Path,
        *,
        on_inserted: Callable[[], None] | None = None,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database_url = database_url
        self._state_dir = state_dir
        self._on_inserted = on_inserted
        self._clock = utc_clock or (lambda: datetime.now(UTC))
        self._last_targets: dict[str, tuple[str, str, int]] = {}
        self._venue_cooldown_until: dict[Venue, float] = {}

    @staticmethod
    def _key(target: RecoveryTarget) -> tuple[str, str, int]:
        return target.venue, target.source_symbol, target.version_id

    async def run(
        self,
        session: aiohttp.ClientSession,
        *,
        trigger: RecoveryTrigger = "periodic",
    ) -> CandleRecoveryState:
        with exclusive_runtime_lock(self._state_dir / "control" / "candle-endpoint-recovery.lock"):
            return await self._run_locked(session, trigger=trigger)

    async def _run_locked(
        self, session: aiohttp.ClientSession, *, trigger: RecoveryTrigger
    ) -> CandleRecoveryState:
        started_at = self._clock()
        cutoff = recovery_cutoff(started_at)
        last_target_cutoff = cutoff
        loop = asyncio.get_running_loop()
        deadline = loop.time() + ENDPOINT_RUN_SECONDS
        run_id = uuid4()
        state_path = self._state_dir / "artifacts" / "candle-endpoint-recovery-state.json"
        connection = await _open_connection(self._database_url, apply=True)
        before: EndpointSnapshot = {}
        after: EndpointSnapshot | None = None
        inserted: dict[RecoveryTarget, int] = {}
        errors: dict[RecoveryTarget, str] = {}
        deferred: set[RecoveryTarget] = set()
        scanned = False
        run_started = False
        finalized = False
        client: NativeCandleHistoryClient | None = None
        priority_requests = dict.fromkeys(("current", "recent", "daily"), 0)

        def state(execution: RecoveryExecution, error_code: str | None) -> CandleRecoveryState:
            missing = sum(map(len, before.values())) if scanned else None
            remaining = sum(map(len, after.values())) if after is not None else None
            details = tuple(
                RecoveryTargetDetail(
                    target=RecoveryTargetIdentity(
                        venue_instrument_id=target.instrument_id,
                        venue_instrument_version_id=target.version_id,
                        definition_hash=target.definition_hash,
                    ),
                    missing_before=len(buckets),
                    inserted=inserted.get(target, 0),
                    remaining=len(after[target]) if after is not None else None,
                    error_code=errors.get(target),
                )
                for target, buckets in before.items()
            )
            return CandleRecoveryState(
                run_id=run_id.hex,
                generated_at=self._clock(),
                started_at=started_at,
                finished_at=None if execution == "running" else self._clock(),
                execution=execution,
                trigger=trigger,
                window=RecoveryWindow(
                    start=cutoff - timedelta(minutes=1441), end=last_target_cutoff
                ),
                summary=RecoverySummary(
                    target_count=len(before),
                    scanned_target_count=len(before),
                    http_requests=client.request_count if client else 0,
                    missing_before=missing,
                    inserted=sum(inserted.values()),
                    newly_present=missing - remaining
                    if missing is not None and remaining is not None
                    else None,
                    remaining=remaining,
                    failed_targets=len(errors),
                    deferred_targets=len(deferred),
                ),
                details=details[:128],
                details_truncated=len(details) > 128,
                error_code=error_code,
            )

        def audit_metrics() -> dict[str, object]:
            failed_targets = sorted(errors, key=self._key)
            return {
                "recoveryMode": "endpoints",
                "initialCutoff": cutoff.isoformat(),
                "lastTargetCutoff": last_target_cutoff.isoformat(),
                "minuteOffsets": list(ENDPOINT_MINUTE_OFFSETS),
                "refreshedBeforeEachTarget": True,
                "currentEndpointsFirst": True,
                "priorityRequests": dict(priority_requests),
                "targetCount": len(before),
                "httpRequests": client.request_count if client else 0,
                "missingBefore": sum(map(len, before.values())) if scanned else None,
                "remaining": sum(map(len, after.values())) if after is not None else None,
                "targetErrors": [
                    {
                        "venueInstrumentId": target.instrument_id,
                        "venueInstrumentVersionId": target.version_id,
                        "errorCode": errors[target],
                    }
                    for target in failed_targets[:128]
                ],
                "targetErrorsTruncated": len(failed_targets) > 128,
            }

        try:
            run_started = True
            await _thread_call(
                start_recovery_run, connection, run_id, started_at, metrics=audit_metrics()
            )
            write_artifact_atomic(state_path, state("running", None))
            before = await _thread_call(load_missing_endpoints, connection, now=started_at)
            scanned = True
            current_end = cutoff - timedelta(minutes=1)
            recent_start = cutoff - timedelta(minutes=61)
            priorities = {
                "current": [target for target, buckets in before.items() if current_end in buckets],
                "recent": [
                    target
                    for target, buckets in before.items()
                    if current_end not in buckets
                    and any(bucket >= recent_start for bucket in buckets)
                ],
                "daily": [
                    target
                    for target, buckets in before.items()
                    if any(bucket < recent_start for bucket in buckets)
                ],
            }
            client = NativeCandleHistoryClient(
                session,
                max_requests=ENDPOINT_MAX_REQUESTS,
                deadline_seconds=max(0.0, deadline - loop.time()),
                min_interval_seconds=ENDPOINT_REQUEST_INTERVAL_SECONDS,
            )
            exhausted = False
            for priority, targets in priorities.items():
                ordered = sorted(targets, key=self._key)
                last_target = self._last_targets.get(priority)
                if last_target is not None:
                    split = next(
                        (
                            index
                            for index, target in enumerate(ordered)
                            if self._key(target) > last_target
                        ),
                        len(ordered),
                    )
                    ordered = ordered[split:] + ordered[:split]
                for target in ordered:
                    if (
                        exhausted
                        or loop.time() >= deadline
                        or client.request_count >= ENDPOINT_MAX_REQUESTS
                    ):
                        deferred.add(target)
                        continue
                    if self._venue_cooldown_until.get(target.venue, 0) > loop.time():
                        deferred.add(target)
                        continue
                    target_now = self._clock()
                    target_cutoff = recovery_cutoff(target_now)
                    last_target_cutoff = max(last_target_cutoff, target_cutoff)
                    refreshed = await _thread_call(
                        load_missing_endpoints,
                        connection,
                        now=target_now,
                        version_id=target.version_id,
                    )
                    missing = tuple(
                        bucket
                        for bucket in refreshed.get(target, ())
                        if (bucket >= target_cutoff - timedelta(minutes=61))
                        == (priority != "daily")
                    )
                    if not missing:
                        self._last_targets[priority] = self._key(target)
                        continue
                    before[target] = tuple(sorted(set(before[target]).union(missing), reverse=True))
                    requests_before = client.request_count
                    try:
                        fetched = await client.fetch_missing(
                            target, missing, max_pages=1, coalesce=True, newest_first=True
                        )
                        if fetched.rejected_buckets:
                            errors[target] = "history_conflicting_bucket"
                        if fetched.candles:

                            def insert_target(
                                current: RecoveryTarget, candles: tuple[Candle1m, ...]
                            ) -> int:
                                count = insert_missing_candles(
                                    connection, current, candles, run_id=run_id
                                )
                                inserted[current] = inserted.get(current, 0) + count
                                return count

                            count = await _thread_call(insert_target, target, fetched.candles)
                            if count and self._on_inserted:
                                self._on_inserted()
                        if fetched.budget_scope:
                            deferred.add(target)
                            exhausted = fetched.budget_scope == "run"
                    except HistoryRateLimited as error:
                        errors[target] = "history_rate_limited"
                        self._venue_cooldown_until[target.venue] = loop.time() + (
                            error.retry_after_seconds
                            if error.retry_after_seconds is not None
                            else 60
                        )
                    except HistoryBudgetExceeded:
                        deferred.add(target)
                        exhausted = True
                    except RecoveryVersionChanged:
                        errors[target] = "target_version_changed"
                    except HistoryPayloadInvalid:
                        errors[target] = "history_payload_invalid"
                    except (HistoryFetchError, CandleParseError, RecoveryStoreError, ValueError):
                        errors[target] = "history_unavailable"
                    finally:
                        started_requests = client.request_count - requests_before
                        priority_requests[priority] += started_requests
                        if started_requests:
                            self._last_targets[priority] = self._key(target)
            after = await _thread_call(_remaining_snapshot, connection, before)
            remaining = sum(map(len, after.values()))
            error_code = (
                "recovery_target_failed"
                if errors
                else "recovery_budget_exceeded"
                if deferred
                else "recovery_missing"
                if remaining
                else None
            )
            result = state("partial" if error_code else "succeeded", error_code)
            await _thread_call(
                finish_recovery_run,
                connection,
                run_id,
                self._clock(),
                status=result.execution,
                received=sum(map(len, before.values())),
                inserted=sum(inserted.values()),
                error_code=error_code,
                metrics=audit_metrics(),
            )
            finalized = True
            write_artifact_atomic(state_path, result)
            return result
        except BaseException:
            if run_started and not finalized:
                try:
                    await _thread_call(
                        finish_recovery_run,
                        connection,
                        run_id,
                        self._clock(),
                        status="failed",
                        received=sum(map(len, before.values())),
                        inserted=sum(inserted.values()),
                        error_code="endpoint_recovery_failed",
                        metrics=audit_metrics(),
                    )
                    write_artifact_atomic(state_path, state("failed", "endpoint_recovery_failed"))
                except Exception:
                    pass
            raise
        finally:
            await _thread_call(connection.close)
