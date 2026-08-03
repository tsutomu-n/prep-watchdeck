from __future__ import annotations

import time
from collections.abc import Iterable

from prep_watchdeck.application.service_backfill import normalize_symbols
from prep_watchdeck.application.service_gap_audit import (
    ONE_MINUTE_MS,
    ServiceGapAuditStore,
    audit_service_gaps,
)


def select_reconcile_symbols(
    store: ServiceGapAuditStore,
    symbols: Iterable[str],
    *,
    window_limit: int,
    now_ms: int | None = None,
) -> list[str]:
    if window_limit < 1:
        raise ValueError("window_limit must be positive")

    target_symbols = normalize_symbols(symbols)
    if not target_symbols:
        return []

    window_end_ms = latest_closed_1m_bucket_ms(now_ms)
    window_start_ms = window_end_ms - (window_limit - 1) * ONE_MINUTE_MS
    audit = audit_service_gaps(
        store,
        symbols=target_symbols,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
    )
    return [
        item.symbol
        for item in audit.symbols
        if item.missing_count > 0 and item.classification != "ZERO_VOLUME_ONLY"
    ]


def latest_closed_1m_bucket_ms(now_ms: int | None = None) -> int:
    current = int(time.time() * 1000) if now_ms is None else now_ms
    return current // ONE_MINUTE_MS * ONE_MINUTE_MS - ONE_MINUTE_MS
