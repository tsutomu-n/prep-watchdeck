from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from prep_watchdeck_market.identity import IdentityResolution
from prep_watchdeck_market.models import CatalogBatch, CatalogInstrument, canonical_json_sha256


class CatalogStoreError(RuntimeError):
    """Catalog persistence failed without exposing connection credentials."""


@dataclass(frozen=True, slots=True)
class CatalogStoreResult:
    raw_payload_id: int
    raw_payload_inserted: bool
    exclusions_inserted: int
    instrument_versions_created: int
    instrument_versions_unchanged: int
    instrument_versions_closed: int
    capabilities_upserted: int
    identity_resolutions_created: int
    memberships_opened: int
    memberships_closed: int


def persist_catalog(
    connection: Connection[Any],
    batch: CatalogBatch,
    identities: Sequence[IdentityResolution],
    *,
    collector_run_id: UUID | None = None,
) -> CatalogStoreResult:
    """Persist one complete Venue catalog and its current identity resolution atomically."""

    instruments, identity_by_id = _validate_input(batch, identities)
    observed_at = batch.provenance.observed_at
    venue = batch.provenance.venue

    try:
        with connection.transaction(), connection.cursor() as cursor:
            raw_payload_id, raw_payload_inserted = _persist_raw_payload(
                cursor, batch, collector_run_id
            )
            exclusions_inserted = _persist_exclusions(cursor, batch, raw_payload_id)
            current_rows = {
                str(row[1]): (int(row[0]), str(row[2]).strip(), row[3])
                for row in cursor.execute(
                    """
                        SELECT venue_instrument_version_id, source_symbol,
                               definition_hash, valid_from
                        FROM venue_instrument_versions
                        WHERE venue = %s AND valid_to IS NULL
                        FOR UPDATE
                    """,
                    (venue,),
                ).fetchall()
            }

            current_version_ids: dict[str, int] = {}
            versions_created = 0
            versions_unchanged = 0
            versions_closed = 0
            memberships_closed = 0

            for source_symbol, (version_id, _, valid_from) in current_rows.items():
                instrument = instruments.get(source_symbol)
                definition_changed = (
                    instrument is not None
                    and instrument.definition_sha256() != current_rows[source_symbol][1]
                )
                if instrument is None or definition_changed:
                    _require_later(observed_at, valid_from, "instrument definition")
                    memberships_closed += _close_version(cursor, version_id, observed_at)
                    versions_closed += 1

            for source_symbol, instrument in instruments.items():
                definition_hash = instrument.definition_sha256()
                current = current_rows.get(source_symbol)
                if current is not None and current[1] == definition_hash:
                    current_version_ids[instrument.venue_instrument_id] = current[0]
                    versions_unchanged += 1
                    continue

                row = cursor.execute(
                    """
                        INSERT INTO venue_instrument_versions (
                            venue, source_symbol, definition_hash, valid_from, active,
                            asset_class, market_type, execution_model, base_asset,
                            quote_asset, settle_asset, collateral_asset, quantity_unit,
                            contract_multiplier, price_tick, amount_step,
                            funding_interval_seconds, source_status, raw_definition,
                            raw_catalog_payload_id, collector_run_id
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s
                        )
                        RETURNING venue_instrument_version_id
                    """,
                    (
                        instrument.venue,
                        instrument.source_symbol,
                        definition_hash,
                        observed_at,
                        instrument.active,
                        instrument.asset_class,
                        instrument.market_type,
                        instrument.execution_model,
                        instrument.base_asset,
                        instrument.quote_asset,
                        instrument.settle_asset,
                        instrument.collateral_asset,
                        instrument.quantity_unit,
                        instrument.contract_multiplier,
                        instrument.price_tick,
                        instrument.amount_step,
                        instrument.funding_interval_seconds,
                        instrument.source_status,
                        Jsonb(instrument.raw_definition),
                        raw_payload_id,
                        collector_run_id,
                    ),
                ).fetchone()
                if row is None:
                    raise CatalogStoreError("instrument version was not created")
                current_version_ids[instrument.venue_instrument_id] = int(row[0])
                versions_created += 1

            capabilities_upserted = _upsert_capabilities(cursor, batch, collector_run_id)
            identity_created, memberships_opened, identity_memberships_closed = _sync_identities(
                cursor,
                instruments,
                identity_by_id,
                current_version_ids,
                observed_at,
            )
            memberships_closed += identity_memberships_closed

        return CatalogStoreResult(
            raw_payload_id=raw_payload_id,
            raw_payload_inserted=raw_payload_inserted,
            exclusions_inserted=exclusions_inserted,
            instrument_versions_created=versions_created,
            instrument_versions_unchanged=versions_unchanged,
            instrument_versions_closed=versions_closed,
            capabilities_upserted=capabilities_upserted,
            identity_resolutions_created=identity_created,
            memberships_opened=memberships_opened,
            memberships_closed=memberships_closed,
        )
    except CatalogStoreError:
        raise
    except psycopg.Error:
        raise CatalogStoreError("catalog persistence failed") from None


def _validate_input(
    batch: CatalogBatch, identities: Sequence[IdentityResolution]
) -> tuple[dict[str, CatalogInstrument], dict[str, IdentityResolution]]:
    if batch.provenance.observed_at.tzinfo is None:
        raise ValueError("catalog observed_at must be timezone-aware")
    if batch.provenance.source_at is not None and batch.provenance.source_at.tzinfo is None:
        raise ValueError("catalog source_at must be timezone-aware")
    if canonical_json_sha256(batch.raw_payload) != batch.provenance.payload_hash:
        raise ValueError("catalog payload hash does not match raw payload")
    if not batch.instruments:
        raise ValueError("catalog batch must contain at least one instrument")

    instruments: dict[str, CatalogInstrument] = {}
    instrument_ids: set[str] = set()
    for instrument in batch.instruments:
        if instrument.venue != batch.provenance.venue:
            raise ValueError("catalog instrument venue does not match provenance")
        if instrument.source_symbol in instruments:
            raise ValueError(f"duplicate source symbol: {instrument.source_symbol}")
        instruments[instrument.source_symbol] = instrument
        instrument_ids.add(instrument.venue_instrument_id)

    for capability in batch.capabilities:
        if capability.venue != batch.provenance.venue:
            raise ValueError("catalog capability venue does not match provenance")
    for exclusion in batch.exclusions:
        if exclusion.venue != batch.provenance.venue:
            raise ValueError("catalog exclusion venue does not match provenance")
        if not exclusion.reason:
            raise ValueError("catalog exclusion reason must not be empty")

    identity_by_id: dict[str, IdentityResolution] = {}
    for identity in identities:
        if identity.venue_instrument_id in identity_by_id:
            raise ValueError(f"duplicate identity resolution: {identity.venue_instrument_id}")
        if identity.group_id is None:
            if identity.mapping_method is not None or not identity.unmapped_reason:
                raise ValueError("unmapped identity must have only an unmapped reason")
        elif not identity.mapping_method or identity.unmapped_reason is not None:
            raise ValueError("mapped identity must have a method and no unmapped reason")
        identity_by_id[identity.venue_instrument_id] = identity

    if set(identity_by_id) != instrument_ids:
        raise ValueError("identity resolutions must cover every catalog instrument exactly once")
    return instruments, identity_by_id


def _persist_raw_payload(
    cursor: Any, batch: CatalogBatch, collector_run_id: UUID | None
) -> tuple[int, bool]:
    provenance = batch.provenance
    row = cursor.execute(
        """
            INSERT INTO raw_catalog_payloads (
                collector_run_id, venue, endpoint, source_kind, documentation_url,
                payload_hash, observed_at, last_observed_at, source_at, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (venue, endpoint, payload_hash) DO NOTHING
            RETURNING raw_catalog_payload_id
        """,
        (
            collector_run_id,
            provenance.venue,
            provenance.endpoint,
            provenance.source_kind,
            provenance.documentation_url,
            provenance.payload_hash,
            provenance.observed_at,
            provenance.observed_at,
            provenance.source_at,
            Jsonb(batch.raw_payload),
        ),
    ).fetchone()
    if row is not None:
        return int(row[0]), True

    row = cursor.execute(
        """
            UPDATE raw_catalog_payloads
            SET last_observed_at = GREATEST(last_observed_at, %s)
            WHERE venue = %s AND endpoint = %s AND payload_hash = %s
            RETURNING raw_catalog_payload_id
        """,
        (
            provenance.observed_at,
            provenance.venue,
            provenance.endpoint,
            provenance.payload_hash,
        ),
    ).fetchone()
    if row is None:
        raise CatalogStoreError("catalog payload deduplication failed")
    return int(row[0]), False


def _close_version(cursor: Any, version_id: int, observed_at: datetime) -> int:
    membership_count = cursor.execute(
        """
            UPDATE group_memberships
            SET valid_to = %s
            WHERE venue_instrument_version_id = %s AND valid_to IS NULL
        """,
        (observed_at, version_id),
    ).rowcount
    cursor.execute(
        """
            UPDATE identity_resolutions
            SET valid_to = %s
            WHERE venue_instrument_version_id = %s AND valid_to IS NULL
        """,
        (observed_at, version_id),
    )
    cursor.execute(
        """
            UPDATE venue_instrument_versions
            SET valid_to = %s
            WHERE venue_instrument_version_id = %s AND valid_to IS NULL
        """,
        (observed_at, version_id),
    )
    return int(membership_count)


def _persist_exclusions(cursor: Any, batch: CatalogBatch, raw_payload_id: int) -> int:
    inserted = 0
    for exclusion in batch.exclusions:
        cursor.execute(
            """
                INSERT INTO catalog_exclusions (
                    raw_catalog_payload_id, venue, source_symbol, reason, raw_definition
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """,
            (
                raw_payload_id,
                exclusion.venue,
                exclusion.source_symbol,
                exclusion.reason,
                Jsonb(exclusion.raw_definition),
            ),
        )
        inserted += int(cursor.rowcount)
    return inserted


def _upsert_capabilities(cursor: Any, batch: CatalogBatch, collector_run_id: UUID | None) -> int:
    updated = 0
    for capability in batch.capabilities:
        cursor.execute(
            """
                INSERT INTO capabilities (
                    venue, capability, available, source_kind, endpoint_or_channel,
                    documentation_url, observed_at, collector_run_id, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (venue, capability) DO UPDATE SET
                    available = EXCLUDED.available,
                    source_kind = EXCLUDED.source_kind,
                    endpoint_or_channel = EXCLUDED.endpoint_or_channel,
                    documentation_url = EXCLUDED.documentation_url,
                    observed_at = EXCLUDED.observed_at,
                    collector_run_id = EXCLUDED.collector_run_id,
                    details = EXCLUDED.details
                WHERE EXCLUDED.observed_at >= capabilities.observed_at
            """,
            (
                capability.venue,
                capability.capability,
                capability.available,
                capability.source_kind,
                capability.endpoint_or_channel,
                capability.documentation_url,
                batch.provenance.observed_at,
                collector_run_id,
                Jsonb(capability.details),
            ),
        )
        updated += int(cursor.rowcount)
    return updated


def _sync_identities(
    cursor: Any,
    instruments: dict[str, CatalogInstrument],
    identity_by_id: dict[str, IdentityResolution],
    current_version_ids: dict[str, int],
    observed_at: datetime,
) -> tuple[int, int, int]:
    version_ids = list(current_version_ids.values())
    current_identity = {
        int(row[1]): (int(row[0]), row[2], row[3], row[4], row[5])
        for row in cursor.execute(
            """
                SELECT identity_resolution_id, venue_instrument_version_id,
                       group_id, mapping_method, unmapped_reason, valid_from
                FROM identity_resolutions
                WHERE venue_instrument_version_id = ANY(%s) AND valid_to IS NULL
                FOR UPDATE
            """,
            (version_ids,),
        ).fetchall()
    }
    current_membership = {
        int(row[1]): (int(row[0]), str(row[2]), str(row[3]), row[4])
        for row in cursor.execute(
            """
                SELECT group_membership_id, venue_instrument_version_id,
                       group_id, mapping_method, valid_from
                FROM group_memberships
                WHERE venue_instrument_version_id = ANY(%s) AND valid_to IS NULL
                FOR UPDATE
            """,
            (version_ids,),
        ).fetchall()
    }

    identity_created = 0
    memberships_opened = 0
    memberships_closed = 0
    for instrument in instruments.values():
        identity = identity_by_id[instrument.venue_instrument_id]
        version_id = current_version_ids[instrument.venue_instrument_id]
        desired_identity = (
            identity.group_id,
            identity.mapping_method,
            identity.unmapped_reason,
        )

        if identity.group_id is not None:
            _ensure_group(cursor, identity.group_id, instrument, observed_at)

        existing_identity = current_identity.get(version_id)
        existing_identity_state = None if existing_identity is None else existing_identity[1:4]
        if existing_identity_state != desired_identity:
            if existing_identity is not None:
                _require_later(observed_at, existing_identity[4], "identity resolution")
                cursor.execute(
                    """
                        UPDATE identity_resolutions
                        SET valid_to = %s
                        WHERE identity_resolution_id = %s
                    """,
                    (observed_at, existing_identity[0]),
                )
            cursor.execute(
                """
                    INSERT INTO identity_resolutions (
                        venue_instrument_version_id, group_id, mapping_method,
                        unmapped_reason, valid_from
                    )
                    VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    identity.group_id,
                    identity.mapping_method,
                    identity.unmapped_reason,
                    observed_at,
                ),
            )
            identity_created += 1

        desired_membership = (
            None if identity.group_id is None else (identity.group_id, identity.mapping_method)
        )
        existing_membership = current_membership.get(version_id)
        existing_membership_state = (
            None if existing_membership is None else existing_membership[1:3]
        )
        if existing_membership_state == desired_membership:
            continue
        if existing_membership is not None:
            _require_later(observed_at, existing_membership[3], "group membership")
            cursor.execute(
                """
                    UPDATE group_memberships
                    SET valid_to = %s
                    WHERE group_membership_id = %s
                """,
                (observed_at, existing_membership[0]),
            )
            memberships_closed += 1
        if desired_membership is not None:
            cursor.execute(
                """
                    INSERT INTO group_memberships (
                        group_id, venue_instrument_version_id, mapping_method, valid_from
                    )
                    VALUES (%s, %s, %s, %s)
                """,
                (identity.group_id, version_id, identity.mapping_method, observed_at),
            )
            memberships_opened += 1

    return identity_created, memberships_opened, memberships_closed


def _ensure_group(
    cursor: Any,
    group_id: str,
    instrument: CatalogInstrument,
    observed_at: datetime,
) -> None:
    cursor.execute(
        """
            INSERT INTO market_groups (
                group_id, base_asset, asset_class, market_type, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (group_id) DO NOTHING
        """,
        (
            group_id,
            instrument.base_asset,
            instrument.asset_class,
            instrument.market_type,
            observed_at,
            observed_at,
        ),
    )
    row = cursor.execute(
        """
            SELECT base_asset, asset_class, market_type
            FROM market_groups
            WHERE group_id = %s
        """,
        (group_id,),
    ).fetchone()
    expected = (instrument.base_asset, instrument.asset_class, instrument.market_type)
    if row is None or tuple(row) != expected:
        raise CatalogStoreError("market group definition conflicts with an existing group")
    cursor.execute(
        """
            UPDATE market_groups
            SET updated_at = GREATEST(updated_at, %s)
            WHERE group_id = %s
        """,
        (observed_at, group_id),
    )


def _require_later(observed_at: datetime, valid_from: datetime, subject: str) -> None:
    if observed_at <= valid_from:
        raise CatalogStoreError(f"{subject} change must be observed after its current version")
