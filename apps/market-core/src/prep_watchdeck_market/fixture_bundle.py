"""Read a bounded, consistent native DB snapshot into an immutable local bundle."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from prep_watchdeck_market.bundle_files import (
    BundleError,
    json_bytes,
    read_regular,
    safe_relative_path,
    sha256,
    strict_json,
    sums_bytes,
    write_bundle,
)
from prep_watchdeck_market.candle_audit_artifacts import AuditReport
from prep_watchdeck_market.candle_recovery_state import CandleRecoveryState
from prep_watchdeck_market.fixture_models import (
    DatasetName,
    FixtureCapture,
    FixtureDataset,
    FixtureManifest,
    FixtureTarget,
    FixtureWindow,
)

MAX_DATASET_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 20_000
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
DATASET_FILES = {
    "instrument": "instrument.json",
    "market-state": "market-state.json",
    "candles-1m": "candles-1m.snapshot.json",
    "funding": "funding.json",
    "recovery": "recovery.json",
    "audit": "audit/report.json",
}


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _window(since: datetime, until: datetime, now: datetime) -> FixtureWindow:
    if (
        since.tzinfo is None
        or until.tzinfo is None
        or since.utcoffset() is None
        or until.utcoffset() is None
    ):
        raise BundleError("fixture_window_invalid")
    since, until = since.astimezone(UTC), until.astimezone(UTC)
    if (
        since.second
        or since.microsecond
        or until.second
        or until.microsecond
        or not timedelta(0) < until - since <= timedelta(hours=24)
        or until > now
    ):
        raise BundleError("fixture_window_invalid")
    return FixtureWindow(start=since, end=until)


def _query_rows(
    connection: psycopg.Connection[Any], query: LiteralString, params: tuple[object, ...]
) -> list[dict[str, Any]]:
    rows = connection.execute(query, params).fetchmany(MAX_ROWS + 1)
    if len(rows) > MAX_ROWS:
        raise BundleError("fixture_rows_exceeded")
    return [dict(row) for row in rows]


def _read_database(
    database_url: str, instrument_id: str, version_id: int, window: FixtureWindow
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], datetime, datetime]:
    if ":" not in instrument_id or version_id < 1:
        raise BundleError("fixture_target_invalid")
    venue, source_symbol = instrument_id.split(":", 1)
    if venue not in {"bitget", "hyperliquid", "aster"} or not source_symbol:
        raise BundleError("fixture_target_invalid")
    try:
        with (
            psycopg.connect(
                database_url,
                connect_timeout=5,
                options="-c statement_timeout=5000 -c default_transaction_read_only=on",
                autocommit=True,
                row_factory=dict_row,
            ) as connection,
            connection.transaction(),
        ):
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot_row = connection.execute(
                "SELECT transaction_timestamp() AS snapshot_at"
            ).fetchone()
            if snapshot_row is None:
                raise BundleError("fixture_database_unavailable")
            snapshot_at = cast(dict[str, Any], snapshot_row)["snapshot_at"]
            instrument_row = connection.execute(
                """
                    SELECT vi.venue_instrument_version_id, vi.venue, vi.source_symbol,
                           vi.definition_hash, vi.valid_from, vi.valid_to, vi.active,
                           vi.asset_class, vi.market_type, vi.execution_model,
                           vi.base_asset, vi.quote_asset, vi.settle_asset,
                           vi.collateral_asset, vi.contract_multiplier,
                           vi.price_tick, vi.amount_step, vi.source_status,
                           vi.raw_catalog_payload_id, vi.collector_run_id,
                           raw.endpoint AS catalog_endpoint,
                           raw.payload_hash AS catalog_payload_hash,
                           raw.observed_at AS catalog_observed_at,
                           raw.source_at AS catalog_source_at
                    FROM venue_instrument_versions vi
                    JOIN raw_catalog_payloads raw USING (raw_catalog_payload_id)
                    WHERE vi.venue_instrument_version_id = %s AND vi.venue = %s
                      AND vi.source_symbol = %s AND vi.market_type = 'linear_perpetual'
                      AND vi.valid_from <= %s AND (vi.valid_to IS NULL OR %s <= vi.valid_to)
                    """,
                (version_id, venue, source_symbol, window.start, window.end),
            ).fetchone()
            if instrument_row is None:
                raise BundleError("fixture_target_invalid")
            rows: dict[str, list[dict[str, Any]]] = {}
            rows["candles-1m"] = _query_rows(
                connection,
                """
                    SELECT venue_instrument_version_id, bucket_at, open_price, high_price,
                           low_price, close_price, volume_base, volume_notional, trade_count,
                           finality, source_at, observed_at, collector_run_id
                    FROM candle_1m WHERE venue_instrument_version_id = %s
                      AND bucket_at >= %s AND bucket_at < %s ORDER BY bucket_at
                    """,
                (version_id, window.start, window.end),
            )
            rows["market-state"] = _query_rows(
                connection,
                """
                    SELECT venue_instrument_version_id, bucket_at, collector_run_id, status,
                           first_observed_at, last_observed_at, source_at, sample_count,
                           mark_price, reference_price, reference_price_kind, best_bid, best_ask,
                           funding_rate_raw, funding_interval_seconds, funding_rate_per_hour,
                           open_interest_raw, open_interest_raw_unit, open_interest_base,
                           open_interest_notional, volume_24h_raw, volume_24h_unit
                    FROM market_state_1m WHERE venue_instrument_version_id = %s
                      AND bucket_at >= %s AND bucket_at < %s ORDER BY bucket_at
                    """,
                (version_id, window.start, window.end),
            )
            rows["funding"] = _query_rows(
                connection,
                """
                    SELECT venue_instrument_version_id, funding_at, funding_rate_raw,
                           funding_interval_seconds, funding_rate_per_hour, source_at,
                           observed_at, collector_run_id
                    FROM funding_events WHERE venue_instrument_version_id = %s
                      AND funding_at >= %s AND funding_at < %s ORDER BY funding_at
                    """,
                (version_id, window.start, window.end),
            )
            finished_at = datetime.now(UTC)
            return dict(instrument_row), rows, snapshot_at, finished_at
    except BundleError:
        raise
    except (psycopg.Error, OSError):
        raise BundleError("fixture_database_unavailable") from None


def _native_candle_snapshot(
    instrument: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    version = instrument["venue_instrument_version_id"]
    return {
        "schema_version": 1,
        "source_label": "prep-watchdeck-db-snapshot",
        "series": {
            "venue": instrument["venue"],
            "source_symbol": instrument["source_symbol"],
            "venue_instrument_version_id": version,
            "definition_sha256": instrument["definition_hash"],
            "base_asset": instrument["base_asset"],
            "quote_asset": instrument["quote_asset"],
            "settle_asset": instrument["settle_asset"],
            "price_kind": "trade",
            "interval_seconds": 60,
        },
        "records": [
            {
                "venue_instrument_version_id": version,
                "bucket_at": _iso(row["bucket_at"]),
                **{
                    name: None if row[name] is None else str(row[name])
                    for name in (
                        "open_price",
                        "high_price",
                        "low_price",
                        "close_price",
                        "volume_base",
                        "volume_notional",
                    )
                },
                "trade_count": row["trade_count"],
                "finality": row["finality"],
                "source_at": None if row["source_at"] is None else _iso(row["source_at"]),
                "observed_at": _iso(row["observed_at"]),
            }
            for row in rows
        ],
    }


def _dataset_file(
    name: DatasetName, value: object, rows: int, window: FixtureWindow, captured_at: datetime
) -> tuple[FixtureDataset, bytes]:
    data = json_bytes(_json_safe(value))
    if len(data) > MAX_DATASET_BYTES:
        raise BundleError("fixture_dataset_exceeded")
    return (
        FixtureDataset(
            name=name,
            availability="included" if rows else "empty",
            path=DATASET_FILES[name],
            rows=rows,
            bytes=len(data),
            sha256=sha256(data),
            range=window,
            captured_at=captured_at,
            reason=None,
        ),
        data,
    )


def _unavailable(name: DatasetName, reason: str, *, requested: bool = True) -> FixtureDataset:
    return FixtureDataset(
        name=name,
        availability="unavailable" if requested else "not_requested",
        reason=reason,
    )


def export_fixture(
    database_url: str,
    state_dir: Path,
    output_dir: Path,
    *,
    instrument_id: str,
    version_id: int,
    since: datetime,
    until: datetime,
    audit_run: str | None = None,
    evidence_kind: Literal["synthetic", "observed"] = "observed",
) -> tuple[Path, FixtureManifest]:
    """Capture exact DB rows in one read-only transaction, then read optional artifacts."""
    started_at = datetime.now(UTC)
    window = _window(since, until, started_at)
    if audit_run is not None and not RUN_ID.fullmatch(audit_run):
        raise BundleError("fixture_audit_run_invalid")
    instrument, db_rows, snapshot_at, db_finished_at = _read_database(
        database_url, instrument_id, version_id, window
    )
    target = FixtureTarget(
        venue_instrument_id=instrument_id,
        venue_instrument_version_id=version_id,
        definition_hash=instrument["definition_hash"],
    )
    files: dict[str, bytes] = {}
    datasets: list[FixtureDataset] = []
    instrument_record = _json_safe(instrument)
    instrument_record["venueInstrumentId"] = instrument_id
    instrument_record["definitionHash"] = instrument["definition_hash"]
    instrument_record["priceKind"] = "trade"
    dataset, files["instrument.json"] = _dataset_file(
        "instrument", instrument_record, 1, window, db_finished_at
    )
    datasets.append(dataset)
    state_rows = [
        {**row, "qualityReason": None, "reasonAvailability": "not_persisted"}
        for row in db_rows["market-state"]
    ]
    for name, value, count in (
        (
            "market-state",
            {
                "schemaVersion": 1,
                "target": target.model_dump(mode="json", by_alias=True),
                "window": window.model_dump(mode="json", by_alias=True),
                "records": state_rows,
            },
            len(state_rows),
        ),
        (
            "candles-1m",
            _native_candle_snapshot(instrument, db_rows["candles-1m"]),
            len(db_rows["candles-1m"]),
        ),
        (
            "funding",
            {
                "schemaVersion": 1,
                "target": target.model_dump(mode="json", by_alias=True),
                "window": window.model_dump(mode="json", by_alias=True),
                "recordKind": "settled_funding_event",
                "records": db_rows["funding"],
            },
            len(db_rows["funding"]),
        ),
    ):
        dataset, files[DATASET_FILES[name]] = _dataset_file(
            name, value, count, window, db_finished_at
        )
        datasets.append(dataset)

    recovery_path = state_dir / "artifacts" / "candle-recovery-state.json"
    try:
        recovery_raw = read_regular(recovery_path, 1024 * 1024)
        recovery_state = CandleRecoveryState.model_validate(strict_json(recovery_raw))
        details = [
            detail
            for detail in recovery_state.details
            if detail.target.venue_instrument_id == instrument_id
            and detail.target.venue_instrument_version_id == version_id
            and detail.target.definition_hash == target.definition_hash
        ]
        if not details:
            datasets.append(_unavailable("recovery", "target_not_in_run"))
        else:
            captured = datetime.now(UTC)
            value = {
                "schemaVersion": 1,
                "run": recovery_state.model_dump(mode="json", by_alias=True),
                "selectedTarget": details[0].model_dump(mode="json", by_alias=True),
                "artifactCapturedAt": _iso(captured),
            }
            dataset, files["recovery.json"] = _dataset_file("recovery", value, 1, window, captured)
            datasets.append(dataset)
    except (BundleError, ValidationError):
        datasets.append(_unavailable("recovery", "recovery_unavailable"))

    if audit_run is None:
        datasets.append(_unavailable("audit", "not_requested", requested=False))
    else:
        audit_path = state_dir / "candle-audits" / "runs" / audit_run / "report.json"
        try:
            audit_raw = read_regular(audit_path, 32 * 1024 * 1024)
            audit = AuditReport.model_validate(strict_json(audit_raw))
            if (
                audit.run_id != audit_run
                or audit.target.venue_instrument_id != instrument_id
                or audit.target.venue_instrument_version_id != version_id
                or (
                    audit.series is not None
                    and audit.series.definition_sha256 != target.definition_hash
                )
            ):
                raise BundleError("fixture_audit_target_invalid")
            if len(audit_raw) > MAX_DATASET_BYTES:
                raise BundleError("fixture_dataset_exceeded")
            captured = datetime.now(UTC)
            files["audit/report.json"] = audit_raw
            datasets.append(
                FixtureDataset(
                    name="audit",
                    availability="included",
                    path="audit/report.json",
                    rows=1,
                    bytes=len(audit_raw),
                    sha256=sha256(audit_raw),
                    range=FixtureWindow(start=audit.window.start, end=audit.window.end),
                    captured_at=captured,
                    reason=None,
                )
            )
        except (BundleError, ValidationError):
            datasets.append(_unavailable("audit", "audit_unavailable"))

    finished_at = datetime.now(UTC)
    manifest = FixtureManifest(
        schema_version=1,
        bundle_id=uuid4().hex,
        evidence_kind=evidence_kind,
        execution="completed"
        if all(item.availability in {"included", "empty", "not_requested"} for item in datasets)
        else "partial",
        target=target,
        window=window,
        capture=FixtureCapture(
            started_at=started_at,
            finished_at=finished_at,
            database_snapshot_at=snapshot_at,
            method="read_only_repeatable_read",
            point_in_time_replay=False,
        ),
        datasets=tuple(datasets),
        limitations=(
            "DB datasets share one read-only repeatable-read snapshot; artifacts were read later.",
            "This bundle does not provide point-in-time replay or market-truth proof.",
        ),
    )
    files["manifest.json"] = json_bytes(manifest.model_dump(mode="json", by_alias=True))
    if sum(len(data) for data in files.values()) > MAX_BUNDLE_BYTES:
        raise BundleError("fixture_bundle_exceeded")
    path = write_bundle(output_dir, manifest.bundle_id, files, validate=verify_fixture)
    return path, manifest


def verify_fixture(bundle: Path) -> FixtureManifest:
    """Offline verification of exact files, hashes, counts, identity and time window."""
    if bundle.is_symlink() or not bundle.is_dir():
        raise BundleError("fixture_bundle_invalid")
    try:
        manifest_raw = read_regular(bundle / "manifest.json", MAX_DATASET_BYTES)
        manifest = FixtureManifest.model_validate(strict_json(manifest_raw))
    except (BundleError, ValidationError):
        raise BundleError("fixture_manifest_invalid") from None
    if bundle.name not in {manifest.bundle_id, f".staging-{manifest.bundle_id}"}:
        raise BundleError("fixture_manifest_invalid")
    if (
        manifest.window.start >= manifest.window.end
        or manifest.capture.started_at > manifest.capture.finished_at
    ):
        raise BundleError("fixture_manifest_invalid")
    names = [item.name for item in manifest.datasets]
    if names != list(DATASET_FILES):
        raise BundleError("fixture_manifest_invalid")
    expected_paths = {"manifest.json", "SHA256SUMS"}
    data_files: dict[str, bytes] = {"manifest.json": manifest_raw}
    total = len(manifest_raw)
    for dataset in manifest.datasets:
        expected_name = DATASET_FILES[dataset.name]
        if dataset.availability in {"included", "empty"}:
            if (
                dataset.path != expected_name
                or dataset.rows is None
                or dataset.bytes is None
                or dataset.sha256 is None
                or dataset.range is None
                or dataset.captured_at is None
                or dataset.reason is not None
                or (dataset.availability == "empty") != (dataset.rows == 0)
            ):
                raise BundleError("fixture_manifest_invalid")
            relative = dataset.path
            if relative is None:
                raise BundleError("fixture_manifest_invalid")
            safe_relative_path(relative)
            raw = read_regular(bundle / relative, MAX_DATASET_BYTES)
            if len(raw) != dataset.bytes or sha256(raw) != dataset.sha256:
                raise BundleError("fixture_hash_mismatch")
            data_files[relative] = raw
            expected_paths.add(relative)
            total += len(raw)
            payload = strict_json(raw)
            if dataset.name == "instrument":
                if (
                    not isinstance(payload, dict)
                    or payload.get("venueInstrumentId") != manifest.target.venue_instrument_id
                    or payload.get("venue_instrument_version_id")
                    != manifest.target.venue_instrument_version_id
                    or payload.get("definitionHash") != manifest.target.definition_hash
                    or dataset.rows != 1
                ):
                    raise BundleError("fixture_content_invalid")
            elif dataset.name == "candles-1m":
                if (
                    not isinstance(payload, dict)
                    or payload.get("schema_version") != 1
                    or not isinstance(payload.get("series"), dict)
                    or payload["series"].get("venue_instrument_version_id")
                    != manifest.target.venue_instrument_version_id
                    or payload["series"].get("definition_sha256") != manifest.target.definition_hash
                ):
                    raise BundleError("fixture_content_invalid")
                _verify_records(payload, dataset, manifest, "bucket_at")
            elif dataset.name in {"market-state", "funding"}:
                if (
                    not isinstance(payload, dict)
                    or payload.get("schemaVersion") != 1
                    or payload.get("target")
                    != manifest.target.model_dump(mode="json", by_alias=True)
                ):
                    raise BundleError("fixture_content_invalid")
                _verify_records(
                    payload,
                    dataset,
                    manifest,
                    "bucket_at" if dataset.name == "market-state" else "funding_at",
                )
            elif dataset.name == "recovery":
                if (
                    not isinstance(payload, dict)
                    or payload.get("schemaVersion") != 1
                    or not isinstance(payload.get("selectedTarget"), dict)
                    or payload["selectedTarget"].get("target", {}).get("venueInstrumentId")
                    != manifest.target.venue_instrument_id
                    or payload["selectedTarget"].get("target", {}).get("venueInstrumentVersionId")
                    != manifest.target.venue_instrument_version_id
                    or dataset.rows != 1
                ):
                    raise BundleError("fixture_content_invalid")
                try:
                    CandleRecoveryState.model_validate(payload.get("run"))
                except ValidationError:
                    raise BundleError("fixture_content_invalid") from None
            else:
                try:
                    report = AuditReport.model_validate(payload)
                except ValidationError:
                    raise BundleError("fixture_content_invalid") from None
                if (
                    report.target.venue_instrument_id != manifest.target.venue_instrument_id
                    or report.target.venue_instrument_version_id
                    != manifest.target.venue_instrument_version_id
                    or dataset.rows != 1
                ):
                    raise BundleError("fixture_content_invalid")
        elif (
            any(
                value is not None
                for value in (
                    dataset.path,
                    dataset.rows,
                    dataset.bytes,
                    dataset.sha256,
                    dataset.range,
                    dataset.captured_at,
                )
            )
            or dataset.reason is None
        ):
            raise BundleError("fixture_manifest_invalid")
    actual_paths = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise BundleError("fixture_path_invalid")
        if path.is_file():
            actual_paths.add(path.relative_to(bundle).as_posix())
        elif not path.is_dir():
            raise BundleError("fixture_path_invalid")
    if actual_paths != expected_paths:
        raise BundleError("fixture_files_invalid")
    checksums = read_regular(bundle / "SHA256SUMS", 4096)
    total += len(checksums)
    if total > MAX_BUNDLE_BYTES or checksums != sums_bytes(data_files):
        raise BundleError("fixture_hash_mismatch")
    if manifest.execution != (
        "completed"
        if all(
            item.availability in {"included", "empty", "not_requested"}
            for item in manifest.datasets
        )
        else "partial"
    ):
        raise BundleError("fixture_manifest_invalid")
    return manifest


def _verify_records(
    payload: dict[str, Any], dataset: FixtureDataset, manifest: FixtureManifest, key: str
) -> None:
    rows = payload.get("records")
    if not isinstance(rows, list) or len(rows) != dataset.rows or len(rows) > MAX_ROWS:
        raise BundleError("fixture_content_invalid")
    last: datetime | None = None
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("venue_instrument_version_id") != manifest.target.venue_instrument_version_id
        ):
            raise BundleError("fixture_content_invalid")
        try:
            time = datetime.fromisoformat(row[key])
        except (KeyError, TypeError, ValueError):
            raise BundleError("fixture_content_invalid") from None
        if (
            time.tzinfo is None
            or not (manifest.window.start <= time < manifest.window.end)
            or (last is not None and time <= last)
        ):
            raise BundleError("fixture_content_invalid")
        if key == "bucket_at" and (time.second or time.microsecond):
            raise BundleError("fixture_content_invalid")
        last = time
