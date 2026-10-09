"""Bounded native DB reader: one read-only repeatable-read transaction per poll."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, LiteralString, cast
from urllib.parse import unquote, urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from prep_watchdeck_market.bundle_files import BundleError
from prep_watchdeck_market.research.models import MAX_ROWS, ResearchPayload, instant


@dataclass(frozen=True)
class ReadObservation:
    payload: ResearchPayload
    read_started_at: datetime
    read_completed_at: datetime
    elapsed_seconds: float


def require_database_target(database_url: str) -> None:
    """Permit only this project's dedicated database or its disposable test database."""
    try:
        target = urlsplit(database_url)
        port = target.port
        user = unquote(target.username or "")
        database = unquote(target.path.removeprefix("/"))
        production = (
            port == 55432
            and user in {"prep_watchdeck_market", "prep_watchdeck_market_reader"}
            and database == "prep_watchdeck_market"
        )
        testing = (
            port not in {None, 5432, 55432}
            and user == "prep_watchdeck_test"
            and (
                database == "prep_watchdeck_test"
                or re.fullmatch(r"feature_test_[0-9a-f]{32}", database)
            )
        )
        if (
            target.scheme not in {"postgresql", "postgres"}
            or target.hostname != "127.0.0.1"
            or target.query
            or target.fragment
            or not target.password
            or not (production or testing)
        ):
            raise ValueError
    except ValueError:
        raise BundleError("research_database_target_invalid") from None


def _safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return instant(value).isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _rows(
    connection: psycopg.Connection[Any], query: LiteralString, params: tuple[object, ...]
) -> list[dict[str, Any]]:
    rows = connection.execute(query, params).fetchmany(MAX_ROWS + 1)
    if len(rows) > MAX_ROWS:
        raise BundleError("research_rows_exceeded")
    return [_safe(dict(row)) for row in rows]


def read_observation(
    database_url: str,
    *,
    instrument_id: str,
    version_id: int | None,
    since: datetime,
    until: datetime,
) -> ReadObservation:
    require_database_target(database_url)
    since, until = instant(since), instant(until)
    started = datetime.now(UTC)
    tick = time.monotonic()
    if re.fullmatch(r"(bitget|hyperliquid|aster):[^\s:]{1,150}", instrument_id) is None or (
        version_id is not None and (type(version_id) is not int or version_id < 1)
    ):
        raise BundleError("research_identity_invalid")
    if (
        not timedelta(0) < until - since <= timedelta(hours=24)
        or since.second
        or since.microsecond
        or until.second
        or until.microsecond
        or until > started
    ):
        raise BundleError("research_window_invalid")
    venue, symbol = instrument_id.split(":", 1)
    try:
        with (
            psycopg.connect(
                database_url,
                connect_timeout=5,
                autocommit=True,
                row_factory=dict_row,
                options="-c default_transaction_read_only=on -c statement_timeout=5000 "
                "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=10000",
            ) as connection,
            connection.transaction(),
        ):
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = connection.execute("SELECT transaction_timestamp() AS at").fetchone()
            if snapshot is None:
                raise BundleError("research_database_unavailable")
            instruments = _rows(
                connection,
                """
                    SELECT vi.*, raw.endpoint AS catalog_endpoint,
                           raw.source_kind AS catalog_source_kind,
                           raw.documentation_url AS catalog_documentation_url,
                           raw.payload_hash AS catalog_payload_hash,
                           raw.observed_at AS catalog_observed_at,
                           raw.source_at AS catalog_source_at
                    FROM venue_instrument_versions vi
                    JOIN raw_catalog_payloads raw USING (raw_catalog_payload_id)
                    WHERE vi.venue=%s AND vi.source_symbol=%s
                      AND ((%s::bigint IS NULL AND vi.valid_to IS NULL AND vi.active)
                           OR vi.venue_instrument_version_id=%s)
                      AND vi.market_type='linear_perpetual'
                    ORDER BY vi.venue_instrument_version_id LIMIT 2
                    """,
                (venue, symbol, version_id, version_id),
            )
            if len(instruments) != 1:
                raise BundleError("research_target_not_found")
            instrument = instruments[0]
            actual_version = instrument["venue_instrument_version_id"]
            params = (actual_version, since, until, MAX_ROWS + 1)
            candles = _rows(
                connection,
                """
                    SELECT * FROM candle_1m WHERE venue_instrument_version_id=%s
                      AND bucket_at >= %s AND bucket_at < %s ORDER BY bucket_at LIMIT %s
                    """,
                params,
            )
            states = _rows(
                connection,
                """
                    SELECT * FROM market_state_1m WHERE venue_instrument_version_id=%s
                      AND bucket_at >= %s AND bucket_at < %s ORDER BY bucket_at LIMIT %s
                    """,
                params,
            )
            funding = _rows(
                connection,
                """
                    SELECT * FROM funding_events WHERE venue_instrument_version_id=%s
                      AND funding_at >= %s AND funding_at < %s ORDER BY funding_at LIMIT %s
                    """,
                params,
            )
            groups = _rows(
                connection,
                """
                    SELECT m.*, g.base_asset, g.asset_class, g.market_type,
                           g.created_at AS group_created_at, g.updated_at AS group_updated_at
                    FROM group_memberships m JOIN market_groups g USING (group_id)
                    WHERE m.venue_instrument_version_id=%s AND m.valid_from < %s
                      AND (m.valid_to IS NULL OR m.valid_to > %s)
                    ORDER BY m.valid_from, m.group_membership_id LIMIT %s
                    """,
                (actual_version, until, since, MAX_ROWS + 1),
            )
            capabilities = _rows(
                connection,
                """
                    SELECT * FROM capabilities WHERE venue=%s ORDER BY capability LIMIT 201
                    """,
                (venue,),
            )
            payload = ResearchPayload(
                evidence_kind="observed",
                snapshot_at=cast(dict[str, Any], snapshot)["at"],
                window_start=since,
                window_end=until,
                instrument=instrument,
                groups=tuple(groups),
                capabilities=tuple(capabilities),
                candles=tuple(candles),
                states=tuple(states),
                funding=tuple(funding),
            )
        # Neither transaction_timestamp nor a pre-commit clock is called availability.
        completed = datetime.now(UTC)
        return ReadObservation(payload, started, completed, time.monotonic() - tick)
    except BundleError:
        raise
    except psycopg.errors.QueryCanceled:
        raise BundleError("research_database_timeout") from None
    except (psycopg.Error, OSError):
        raise BundleError("research_database_unavailable") from None
