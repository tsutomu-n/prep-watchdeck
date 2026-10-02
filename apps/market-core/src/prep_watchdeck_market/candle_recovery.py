from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp
import psycopg

from prep_watchdeck_market.artifacts import write_artifact_atomic
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
    load_recovery_targets,
    scan_missing_candles,
    start_recovery_run,
)
from prep_watchdeck_market.candles import Candle1m, CandleParseError, require_utc_datetime
from prep_watchdeck_market.models import Venue
from prep_watchdeck_market.retention import NORMALIZED_RETENTION
from prep_watchdeck_market.runtime_lock import exclusive_runtime_lock
from prep_watchdeck_market.sources.candle_history import (
    HistoryBudgetExceeded,
    HistoryFetchError,
    HistoryPayloadInvalid,
    HistoryRateLimited,
    NativeCandleHistoryClient,
)

DATABASE_TIMEOUT_OPTIONS = "-c statement_timeout=5000 -c lock_timeout=2000"
AUTOMATIC_RUN_SECONDS = 600
MANUAL_RUN_SECONDS = 14_400


@dataclass(frozen=True, slots=True)
class RecoveryWindowRequest:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        for label, value in (("start", self.start), ("end", self.end)):
            require_utc_datetime(value, field_name=f"recovery {label}")
            if value.second or value.microsecond:
                raise ValueError("recovery window must be minute aligned")
        if not (timedelta(0) < self.end - self.start <= timedelta(hours=24)):
            raise ValueError("recovery window must be longer than zero and at most 24 hours")


def recovery_cutoff(now: datetime) -> datetime:
    require_utc_datetime(now, field_name="recovery now")
    return now.replace(second=0, microsecond=0) - timedelta(seconds=180)


def recovery_window(
    now: datetime,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> RecoveryWindowRequest:
    cutoff = recovery_cutoff(now)
    if (since is None) != (until is None):
        raise ValueError("since and until must be supplied together")
    if since is None or until is None:
        return RecoveryWindowRequest(cutoff - timedelta(hours=6), cutoff)
    if since.tzinfo is None or until.tzinfo is None:
        raise ValueError("recovery CLI time must include a UTC offset")
    requested = RecoveryWindowRequest(since.astimezone(UTC), until.astimezone(UTC))
    if requested.end > cutoff or requested.start < now - NORMALIZED_RETENTION:
        raise ValueError("recovery window is outside the closed retained history")
    return requested


async def _thread_call[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Join a DB thread even when its awaiting task is cancelled."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _open_connection(database_url: str, *, apply: bool) -> psycopg.Connection[Any]:
    task = asyncio.create_task(
        asyncio.to_thread(
            psycopg.connect,
            database_url,
            connect_timeout=5,
            options=(
                DATABASE_TIMEOUT_OPTIONS
                if apply
                else DATABASE_TIMEOUT_OPTIONS + " -c default_transaction_read_only=on"
            ),
            autocommit=True,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        results = await asyncio.gather(task, return_exceptions=True)
        connection = results[0]
        if isinstance(connection, psycopg.Connection):
            await _thread_call(connection.close)
        raise


def _target_identity(target: RecoveryTarget) -> RecoveryTargetIdentity:
    return RecoveryTargetIdentity(
        venue_instrument_id=target.instrument_id,
        venue_instrument_version_id=target.version_id,
        definition_hash=target.definition_hash,
    )


def _state(
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime | None,
    execution: RecoveryExecution,
    trigger: RecoveryTrigger,
    window: RecoveryWindowRequest,
    target_count: int,
    scanned_count: int,
    http_requests: int,
    missing_before: int | None,
    inserted: int,
    newly_present: int | None,
    remaining: int | None,
    failed_targets: int,
    deferred_targets: int,
    details: list[RecoveryTargetDetail],
    error_code: str | None,
) -> CandleRecoveryState:
    return CandleRecoveryState(
        run_id=run_id,
        generated_at=datetime.now(UTC),
        started_at=started_at,
        finished_at=finished_at,
        execution=execution,
        trigger=trigger,
        window=RecoveryWindow(start=window.start, end=window.end),
        summary=RecoverySummary(
            target_count=target_count,
            scanned_target_count=scanned_count,
            http_requests=http_requests,
            missing_before=missing_before,
            inserted=inserted,
            newly_present=newly_present,
            remaining=remaining,
            failed_targets=failed_targets,
            deferred_targets=deferred_targets,
        ),
        details=tuple(details[:128]),
        details_truncated=len(details) > 128,
        error_code=error_code,
    )


class CandleRecovery:
    """Bounded missing-row recovery, shared by service and manual CLI."""

    def __init__(
        self,
        database_url: str,
        state_dir: Path,
        *,
        on_inserted: Callable[[], None] | None = None,
    ) -> None:
        self._database_url = database_url
        self._state_dir = state_dir
        self._on_inserted = on_inserted
        self._next_start = 0
        self._venue_cooldown_until: dict[Venue, float] = {}

    async def run(
        self,
        session: aiohttp.ClientSession | None,
        window: RecoveryWindowRequest,
        *,
        apply: bool,
        trigger: RecoveryTrigger = "manual",
        venue: Venue | None = None,
        instrument_id: str | None = None,
    ) -> CandleRecoveryState:
        if apply and session is None:
            raise ValueError("HTTP session is required when applying recovery")
        if instrument_id and ":" not in instrument_id:
            raise ValueError("instrument ID must include venue and source symbol")
        if venue == "hyperliquid" and window.start < recovery_cutoff(datetime.now(UTC)) - timedelta(
            minutes=5000
        ):
            raise ValueError("Hyperliquid history exceeds the recent 5,000-bar limit")
        if apply:
            with exclusive_runtime_lock(self._state_dir / "control" / "candle-recovery.lock"):
                return await self._run_locked(
                    session,
                    window,
                    apply=True,
                    trigger=trigger,
                    venue=venue,
                    instrument_id=instrument_id,
                )
        return await self._run_locked(
            None,
            window,
            apply=False,
            trigger=trigger,
            venue=venue,
            instrument_id=instrument_id,
        )

    async def _run_locked(
        self,
        session: aiohttp.ClientSession | None,
        window: RecoveryWindowRequest,
        *,
        apply: bool,
        trigger: RecoveryTrigger,
        venue: Venue | None,
        instrument_id: str | None,
    ) -> CandleRecoveryState:
        started_at = datetime.now(UTC)
        loop = asyncio.get_running_loop()
        deadline_at = loop.time() + (
            AUTOMATIC_RUN_SECONDS if trigger != "manual" else MANUAL_RUN_SECONDS
        )
        run_id = uuid4()
        connection = await _open_connection(self._database_url, apply=apply)
        state_path = self._state_dir / "artifacts" / "candle-recovery-state.json"
        run_started = False
        finalized = False
        targets: tuple[RecoveryTarget, ...] = ()
        before: dict[RecoveryTarget, tuple[datetime, ...]] = {}
        inserted_by_target: dict[RecoveryTarget, int] = {}
        client: NativeCandleHistoryClient | None = None
        try:
            if apply:
                # A cancellation can arrive after the DB thread commits the start row.
                # Failure cleanup must still finalize that row once the thread is joined.
                run_started = True
                await _thread_call(
                    start_recovery_run,
                    connection,
                    run_id,
                    started_at,
                    metrics={
                        "windowStart": window.start.isoformat(),
                        "windowEnd": window.end.isoformat(),
                    },
                )
                write_artifact_atomic(
                    state_path,
                    _state(
                        run_id=run_id.hex,
                        started_at=started_at,
                        finished_at=None,
                        execution="running",
                        trigger=trigger,
                        window=window,
                        target_count=0,
                        scanned_count=0,
                        http_requests=0,
                        missing_before=None,
                        inserted=0,
                        newly_present=None,
                        remaining=None,
                        failed_targets=0,
                        deferred_targets=0,
                        details=[],
                        error_code=None,
                    ),
                )
            targets = await _thread_call(
                load_recovery_targets, connection, venue=venue, instrument_id=instrument_id
            )
            assert isinstance(targets, tuple)
            if instrument_id and not targets:
                raise ValueError("recovery target is not an active current contract")
            ordered = list(targets)
            offset = 0
            if ordered:
                offset = self._next_start % len(ordered)
                ordered = ordered[offset:] + ordered[:offset]
            deferred: set[RecoveryTarget] = set()
            for index, target in enumerate(ordered):
                if loop.time() >= deadline_at:
                    deferred.add(target)
                    continue
                if target.venue == "hyperliquid" and window.start < recovery_cutoff(
                    started_at
                ) - timedelta(minutes=5000):
                    raise ValueError("Hyperliquid history exceeds its recent 5,000-bar limit")
                missing = await _thread_call(
                    scan_missing_candles,
                    connection,
                    target,
                    start=window.start,
                    end=window.end,
                )
                assert isinstance(missing, tuple)
                before[target] = missing
                self._next_start = (offset + index + 1) % len(ordered)
            if not apply:
                details = [
                    RecoveryTargetDetail(
                        target=_target_identity(target),
                        missing_before=len(before[target]) if target in before else None,
                        inserted=0,
                        remaining=len(before[target]) if target in before else None,
                    )
                    for target in targets
                ]
                total = None if deferred else sum(len(missing) for missing in before.values())
                return _state(
                    run_id=run_id.hex,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    execution="succeeded" if total == 0 else "partial",
                    trigger=trigger,
                    window=window,
                    target_count=len(targets),
                    scanned_count=len(before),
                    http_requests=0,
                    missing_before=total,
                    inserted=0,
                    newly_present=0,
                    remaining=total,
                    failed_targets=0,
                    deferred_targets=len(deferred),
                    details=details,
                    error_code=(
                        "recovery_budget_exceeded"
                        if deferred
                        else None
                        if total == 0
                        else "recovery_missing"
                    ),
                )

            assert session is not None
            client = NativeCandleHistoryClient(
                session,
                max_requests=120 if trigger != "manual" else 3000,
                deadline_seconds=max(0.0, deadline_at - loop.time()),
            )
            errors: dict[RecoveryTarget, str] = {}
            blocked_venues = {
                venue for venue, until in self._venue_cooldown_until.items() if until > loop.time()
            }
            exhausted = False
            for index, target in enumerate(ordered):
                if target not in before:
                    continue
                missing = before[target]
                if not missing:
                    continue
                if exhausted or target.venue in blocked_venues:
                    deferred.add(target)
                    continue
                try:
                    # Resume after the last served contract, rather than shifting only
                    # one row per run and repeatedly consuming the budget on one venue.
                    self._next_start = (offset + index + 1) % len(ordered)
                    fetched = await client.fetch_missing(
                        target,
                        missing,
                        max_pages=6 if trigger != "manual" else 16,
                        coalesce=trigger != "manual",
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
                            # Keep the committed result even if the await is cancelled.
                            inserted_by_target[current] = count
                            return count

                        inserted = await _thread_call(insert_target, target, fetched.candles)
                        assert isinstance(inserted, int)
                        if inserted and self._on_inserted:
                            self._on_inserted()
                    if fetched.budget_scope is not None:
                        if target not in errors:
                            deferred.add(target)
                        if fetched.budget_scope == "run":
                            if fetched.pages == 0:
                                self._next_start = (offset + index) % len(ordered)
                            exhausted = True
                except HistoryRateLimited as error:
                    blocked_venues.add(target.venue)
                    self._venue_cooldown_until[target.venue] = loop.time() + (
                        error.retry_after_seconds if error.retry_after_seconds is not None else 900
                    )
                    errors[target] = "history_rate_limited"
                except HistoryBudgetExceeded:
                    deferred.add(target)
                    self._next_start = (offset + index) % len(ordered)
                    exhausted = True
                except RecoveryVersionChanged:
                    errors[target] = "target_version_changed"
                except HistoryPayloadInvalid:
                    errors[target] = "history_payload_invalid"
                except (HistoryFetchError, CandleParseError, RecoveryStoreError, ValueError):
                    errors[target] = "history_unavailable"

            after: dict[RecoveryTarget, tuple[datetime, ...]] = {}
            after_failed = False
            for target in targets:
                if target not in before or loop.time() >= deadline_at:
                    if target not in errors:
                        deferred.add(target)
                    continue
                try:
                    missing = await _thread_call(
                        scan_missing_candles,
                        connection,
                        target,
                        start=window.start,
                        end=window.end,
                    )
                    assert isinstance(missing, tuple)
                    after[target] = missing
                except RecoveryStoreError:
                    after_failed = True
                    errors[target] = "recovery_rescan_failed"
                    deferred.discard(target)
            missing_before = (
                None
                if len(before) != len(targets)
                else sum(len(missing) for missing in before.values())
            )
            inserted = sum(inserted_by_target.values())
            after_unknown = len(after) != len(targets)
            remaining = None if after_unknown else sum(len(missing) for missing in after.values())
            newly_present = (
                None
                if after_unknown
                else sum(len(set(before[target]) - set(after[target])) for target in targets)
            )
            details = [
                RecoveryTargetDetail(
                    target=_target_identity(target),
                    missing_before=len(before[target]) if target in before else None,
                    inserted=inserted_by_target.get(target, 0),
                    remaining=None if target not in after else len(after[target]),
                    error_code=errors.get(target),
                )
                for target in targets
            ]
            execution: RecoveryExecution = (
                "succeeded" if remaining == 0 and not errors and not deferred else "partial"
            )
            error_code = (
                "recovery_rescan_failed"
                if after_failed
                else "recovery_target_failed"
                if errors
                else "recovery_budget_exceeded"
                if deferred
                else "recovery_missing"
                if remaining
                else None
            )
            finished_at = max(datetime.now(UTC), started_at)
            state = _state(
                run_id=run_id.hex,
                started_at=started_at,
                finished_at=finished_at,
                execution=execution,
                trigger=trigger,
                window=window,
                target_count=len(targets),
                scanned_count=len(before),
                http_requests=client.request_count,
                missing_before=missing_before,
                inserted=inserted,
                newly_present=newly_present,
                remaining=remaining,
                failed_targets=len(errors),
                deferred_targets=len(deferred),
                details=details,
                error_code=error_code,
            )
            await _thread_call(
                finish_recovery_run,
                connection,
                run_id,
                finished_at,
                status=execution,
                received=sum(len(missing) for missing in before.values()),
                inserted=inserted,
                error_code=error_code,
                metrics={
                    "windowStart": window.start.isoformat(),
                    "windowEnd": window.end.isoformat(),
                    "targetCount": len(targets),
                    "scannedTargetCount": len(before),
                    "httpRequests": client.request_count,
                    "missingBefore": missing_before,
                    "inserted": inserted,
                    "remaining": remaining,
                    "failedTargets": len(errors),
                    "deferredTargets": len(deferred),
                },
            )
            finalized = True
            write_artifact_atomic(state_path, state)
            return state
        except BaseException:
            if apply and run_started and not finalized:
                failed_at = max(datetime.now(UTC), started_at)
                try:
                    await _thread_call(
                        finish_recovery_run,
                        connection,
                        run_id,
                        failed_at,
                        status="failed",
                        received=sum(len(missing) for missing in before.values()),
                        inserted=sum(inserted_by_target.values()),
                        error_code="recovery_run_failed",
                        metrics={
                            "windowStart": window.start.isoformat(),
                            "windowEnd": window.end.isoformat(),
                        },
                    )
                    write_artifact_atomic(
                        state_path,
                        _state(
                            run_id=run_id.hex,
                            started_at=started_at,
                            finished_at=failed_at,
                            execution="failed",
                            trigger=trigger,
                            window=window,
                            target_count=len(targets),
                            scanned_count=len(before),
                            http_requests=client.request_count if client is not None else 0,
                            missing_before=(
                                sum(len(missing) for missing in before.values())
                                if targets and len(before) == len(targets)
                                else None
                            ),
                            inserted=sum(inserted_by_target.values()),
                            newly_present=None,
                            remaining=None,
                            failed_targets=0,
                            deferred_targets=0,
                            details=[
                                RecoveryTargetDetail(
                                    target=_target_identity(target),
                                    missing_before=(
                                        len(before[target]) if target in before else None
                                    ),
                                    inserted=inserted_by_target.get(target, 0),
                                    remaining=None,
                                )
                                for target in targets
                            ],
                            error_code="recovery_run_failed",
                        ),
                    )
                except Exception:
                    pass
            raise
        finally:
            await _thread_call(connection.close)
