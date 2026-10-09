"""Bounded read-only OpenMarket comparison route for native one-minute candles."""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp
import psycopg
from pydantic import ValidationError

from prep_watchdeck_market.bundle_files import (
    BundleError,
    _check_directory_path,
    json_bytes,
    read_regular,
    safe_relative_path,
    sha256,
    strict_json,
    sums_bytes,
    write_bundle,
)
from prep_watchdeck_market.candle_audit import load_snapshot
from prep_watchdeck_market.fixture_models import FixtureTarget, FixtureWindow
from prep_watchdeck_market.reference_models import (
    ReferenceAcquisition,
    ReferenceCounts,
    ReferenceFile,
    ReferenceMapping,
    ReferenceRequest,
)
from prep_watchdeck_market.runtime_lock import RuntimeLockUnavailable, exclusive_runtime_lock

BASE_URL = "https://api.openmarket.xyz"
MAX_RESPONSE = 8 * 1024 * 1024
MAX_RAW_TOTAL = 32 * 1024 * 1024
PAGE_SIZE = 100
MAX_METADATA_PAGES = 10
MIN_INTERVAL_SECONDS = 10.0


class ReferenceError(BundleError):
    pass


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _key() -> str:
    key = os.environ.get("OPENMARKET_API_KEY", "").strip()
    if not key:
        raise ReferenceError("reference_auth_missing")
    return key


def _target_from_database(
    database_url: str, instrument_id: str, version_id: int | None = None
) -> dict[str, Any]:
    if ":" not in instrument_id:
        raise ReferenceError("reference_target_invalid")
    venue, symbol = instrument_id.split(":", 1)
    if venue not in {"bitget", "hyperliquid", "aster", "mexc"} or not symbol:
        raise ReferenceError("reference_target_invalid")
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            options="-c statement_timeout=5000 -c default_transaction_read_only=on",
            autocommit=True,
        ) as connection:
            row = connection.execute(
                """
                SELECT venue_instrument_version_id, definition_hash, base_asset,
                       quote_asset, settle_asset, valid_from, active
                FROM venue_instrument_versions
                WHERE venue = %s AND source_symbol = %s AND valid_to IS NULL
                  AND market_type = 'linear_perpetual' AND asset_class = 'crypto'
                """,
                (venue, symbol),
            ).fetchone()
    except (psycopg.Error, OSError):
        raise ReferenceError("reference_database_unavailable") from None
    if row is None or not row[6] or (version_id is not None and row[0] != version_id):
        raise ReferenceError("reference_target_invalid")
    return {
        "venueInstrumentId": instrument_id,
        "venueInstrumentVersionId": int(row[0]),
        "definitionHash": str(row[1]),
        "venue": venue,
        "sourceSymbol": symbol,
        "baseAsset": row[2],
        "quoteAsset": row[3],
        "settleAsset": row[4],
        "validFrom": row[5],
    }


class OpenMarketClient:
    """A single paced lane; never exposes credentials or response bodies in errors."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        key: str,
        *,
        base_url: str = BASE_URL,
        min_interval: float = MIN_INTERVAL_SECONDS,
    ) -> None:
        self.session = session
        self.key = key
        self.base_url = base_url
        self.min_interval = min_interval
        self.last_start: float | None = None
        self.remaining_weight: int | None = None
        self.reset_at: int | None = None

    async def get(self, path: str, params: dict[str, str]) -> tuple[bytes, datetime]:
        for attempt in range(3):
            if self.remaining_weight == 0:
                seconds = None if self.reset_at is None else self.reset_at - int(time.time())
                if seconds is None or seconds > 60:
                    raise ReferenceError("reference_rate_limited")
                if seconds > 0:
                    await asyncio.sleep(seconds)
                self.remaining_weight = None
            now = time.monotonic()
            if self.last_start is not None:
                wait = self.min_interval - (now - self.last_start)
                if wait > 0:
                    await asyncio.sleep(wait)
            self.last_start = time.monotonic()
            try:
                async with self.session.get(
                    self.base_url + path,
                    params=params,
                    headers={"X-OpenMarket-Key": self.key},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status in {401, 403}:
                        raise ReferenceError("reference_auth_rejected")
                    if response.status == 429:
                        raw_wait = response.headers.get("Retry-After", "")
                        retry_after = int(raw_wait) if raw_wait.isdecimal() else 0
                        if attempt == 2 or retry_after > 60:
                            raise ReferenceError("reference_rate_limited")
                        await asyncio.sleep(max(10, retry_after))
                        continue
                    if response.status >= 500:
                        if attempt == 2:
                            raise ReferenceError("reference_provider_unavailable")
                        continue
                    if response.status != 200:
                        raise ReferenceError("reference_provider_rejected")
                    raw = await response.content.read(MAX_RESPONSE + 1)
                    received_at = datetime.now(UTC)
                    if len(raw) > MAX_RESPONSE:
                        raise ReferenceError("reference_response_too_large")
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    reset = response.headers.get("X-RateLimit-Reset")
                    self.remaining_weight = (
                        int(remaining) if remaining and remaining.isdecimal() else None
                    )
                    self.reset_at = int(reset) if reset and reset.isdecimal() else None
                    return raw, received_at
            except ReferenceError:
                raise
            except (aiohttp.ClientError, TimeoutError):
                if attempt == 2:
                    raise ReferenceError("reference_transport_unavailable") from None
        raise ReferenceError("reference_provider_unavailable")


async def _metadata(
    client: OpenMarketClient, *, symbol: str, coin: str
) -> tuple[list[tuple[dict[str, Any], bytes]], bool]:
    """Return exact symbol entries with their source-page bytes and completeness flag."""
    entries: list[tuple[dict[str, Any], bytes]] = []
    offset = 0
    visited = set()
    for _page in range(MAX_METADATA_PAGES):
        if offset in visited:
            return entries, False
        visited.add(offset)
        raw, _received = await client.get(
            "/v1/markets",
            {
                "symbolFilter": symbol,
                "coin": coin,
                "category": "PERPETUAL",
                "type": "TRADE_SIDE_AGNOSTIC_AGG",
                "distinct": "false",
                "pageSize": str(PAGE_SIZE),
                "pageOffset": str(offset),
            },
        )
        try:
            data = strict_json(raw)
        except BundleError:
            raise ReferenceError("reference_metadata_invalid") from None
        if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
            raise ReferenceError("reference_metadata_invalid")
        symbols = data["symbols"]
        if len(symbols) > PAGE_SIZE or not all(isinstance(entry, dict) for entry in symbols):
            raise ReferenceError("reference_metadata_invalid")
        for entry in symbols:
            if entry.get("category") == "PERPETUAL" and entry.get("coin") == coin:
                entries.append((entry, raw))
        next_offset = data.get("nextOffset")
        if len(symbols) < PAGE_SIZE:
            return entries, True
        if not isinstance(next_offset, int) or next_offset <= offset:
            return entries, False
        offset = next_offset
    return entries, False


async def reference_markets(
    database_url: str,
    client: OpenMarketClient,
    *,
    venue: str,
    symbol: str,
    output: Path,
) -> dict[str, Any]:
    target = _target_from_database(database_url, f"{venue}:{symbol}")
    entries, complete = await _metadata(client, symbol=symbol, coin=target["baseAsset"])
    candidates = [
        {
            "exchange": entry.get("exchange"),
            "rawSymbol": entry.get("rawSymbol"),
            "coin": entry.get("coin"),
            "category": entry.get("category"),
            "normalizedSymbol": entry.get("normalizedSymbol"),
            "availableSince": entry.get("availableSince"),
            "metadataSha256": sha256(raw),
        }
        for entry, raw in entries
    ]
    result = {
        "schemaVersion": 1,
        "target": {
            key: _timestamp(value) if isinstance(value, datetime) else value
            for key, value in target.items()
        },
        "metadataComplete": complete,
        "candidates": candidates,
        "missingChecks": [
            "operator must verify exchange, quote, settlement, "
            "contract multiplier and exact market",
            "candidate presence does not establish an identity mapping",
        ],
        "checkedAt": _timestamp(datetime.now(UTC)),
    }
    if output.is_symlink() or output.exists():
        raise ReferenceError("reference_output_exists")
    _check_directory_path(output.absolute().parent)
    data = json_bytes(result)
    if len(data) > MAX_RESPONSE:
        raise ReferenceError("reference_output_too_large")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return result


def _validate_mapping(mapping: ReferenceMapping, target: dict[str, Any]) -> None:
    native = mapping.native
    if (
        target["venue"] != native.venue
        or target["sourceSymbol"] != native.source_symbol
        or target["venueInstrumentVersionId"] != native.venue_instrument_version_id
        or target["definitionHash"] != native.definition_sha256
        or target["baseAsset"] != native.base_asset
        or target["quoteAsset"] != native.quote_asset
        or target["settleAsset"] != native.settle_asset
        or not mapping.provider.exchange.upper().startswith(native.venue.upper())
        or mapping.provider.coin != native.base_asset
        or native.quote_asset != native.settle_asset
        or len(f"openmarket:{mapping.provider.exchange}:{mapping.provider.raw_symbol}") > 128
    ):
        raise ReferenceError("reference_mapping_invalid")


def _point_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _positive(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result > 0 else None


def _nonnegative(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _parse_points(
    raw: bytes,
    mapping: ReferenceMapping,
    chunk_start: datetime,
    chunk_end: datetime,
    observed_at: datetime,
) -> tuple[list[dict[str, Any]], int, int]:
    try:
        data = strict_json(raw)
    except BundleError:
        raise ReferenceError("reference_points_invalid") from None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("series"), list)
        or len(data["series"]) != 1
    ):
        raise ReferenceError("reference_points_invalid")
    series = data["series"][0]
    provider = mapping.provider
    expected_id = provider.model_dump(mode="json", by_alias=True)
    if (
        not isinstance(series, dict)
        or series.get("id") != expected_id
        or not isinstance(series.get("points"), list)
    ):
        raise ReferenceError("reference_series_mismatch")
    points = series["points"]
    if len(points) > 1000:
        raise ReferenceError("reference_points_invalid")
    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    invalid = 0
    for wrapper in points:
        point = wrapper.get("Point") if isinstance(wrapper, dict) else None
        if not isinstance(point, dict):
            invalid += 1
            continue
        stamp = point.get("timestamp")
        seconds = _point_integer(stamp.get("s")) if isinstance(stamp, dict) else None
        nanos = _point_integer(stamp.get("ns", 0)) if isinstance(stamp, dict) else None
        if (
            seconds is None
            or nanos != 0
            or seconds % 60 != 0
            or seconds < int(chunk_start.timestamp())
            or seconds >= int(chunk_end.timestamp())
            or seconds in seen
        ):
            invalid += 1
            continue
        seen.add(seconds)
        values = [_positive(point.get(key)) for key in ("open", "high", "low", "close")]
        volume = _nonnegative(point.get("volume"))
        if any(value is None for value in values) or volume is None:
            invalid += 1
            continue
        open_, high, low, close = values
        assert open_ is not None and high is not None and low is not None and close is not None
        if high < max(open_, close) or low > min(open_, close) or high < low:
            invalid += 1
            continue
        records.append(
            {
                "venue_instrument_version_id": mapping.native.venue_instrument_version_id,
                "bucket_at": _timestamp(datetime.fromtimestamp(seconds, UTC)),
                "open_price": str(open_),
                "high_price": str(high),
                "low_price": str(low),
                "close_price": str(close),
                "volume_base": str(volume),
                "volume_notional": None,
                "trade_count": None,
                "finality": "derived_final",
                "source_at": None,
                "observed_at": _timestamp(observed_at),
            }
        )
    return records, len(points), invalid


async def reference_snapshot(
    database_url: str,
    state_dir: Path,
    client: OpenMarketClient,
    *,
    mapping_path: Path,
    since: datetime,
    until: datetime,
    output_dir: Path,
) -> tuple[Path, ReferenceAcquisition]:
    started = datetime.now(UTC)
    if (
        since.tzinfo is None
        or until.tzinfo is None
        or since.utcoffset() is None
        or until.utcoffset() is None
    ):
        raise ReferenceError("reference_window_invalid")
    since, until = since.astimezone(UTC), until.astimezone(UTC)
    if (
        since.second
        or since.microsecond
        or until.second
        or until.microsecond
        or not timedelta(minutes=6) <= until - since <= timedelta(hours=24)
        or since < started - timedelta(days=7)
        or until > started - timedelta(minutes=3)
    ):
        raise ReferenceError("reference_window_invalid")
    try:
        mapping_raw = read_regular(mapping_path, 64 * 1024)
        mapping = ReferenceMapping.model_validate(strict_json(mapping_raw))
    except (BundleError, ValueError):
        raise ReferenceError("reference_mapping_invalid") from None
    target = _target_from_database(
        database_url,
        f"{mapping.native.venue}:{mapping.native.source_symbol}",
        mapping.native.venue_instrument_version_id,
    )
    _validate_mapping(mapping, target)
    if since < target["validFrom"] or mapping.checked_at > started:
        raise ReferenceError("reference_mapping_invalid")
    try:
        with exclusive_runtime_lock(state_dir / "control" / "reference-snapshot.lock"):
            return await _snapshot_locked(
                client, mapping, mapping_raw, target, since, until, output_dir, started
            )
    except RuntimeLockUnavailable:
        raise ReferenceError("reference_busy") from None


async def _snapshot_locked(
    client: OpenMarketClient,
    mapping: ReferenceMapping,
    mapping_raw: bytes,
    target: dict[str, Any],
    since: datetime,
    until: datetime,
    output_dir: Path,
    started: datetime,
) -> tuple[Path, ReferenceAcquisition]:
    entries, complete = await _metadata(
        client, symbol=mapping.provider.raw_symbol, coin=mapping.provider.coin
    )
    matches = [
        (entry, raw)
        for entry, raw in entries
        if entry.get("exchange") == mapping.provider.exchange
        and entry.get("rawSymbol") == mapping.provider.raw_symbol
        and entry.get("coin") == mapping.provider.coin
        and entry.get("category") == mapping.provider.category
    ]
    if not complete or len(matches) != 1 or sha256(matches[0][1]) != mapping.metadata_sha256:
        raise ReferenceError("reference_mapping_invalid")
    entry, metadata_raw = matches[0]
    normalized = entry.get("normalizedSymbol")
    if not isinstance(normalized, str) or not normalized.upper().endswith(
        "-" + mapping.native.quote_asset.upper()
    ):
        raise ReferenceError("reference_mapping_invalid")
    available = entry.get("availableSince")
    available_seconds = _point_integer(available.get("s")) if isinstance(available, dict) else None
    if available_seconds is None or since.timestamp() < available_seconds:
        raise ReferenceError("reference_history_unavailable")

    files: dict[str, bytes] = {"metadata.json": metadata_raw, "mapping.json": mapping_raw}
    records: list[dict[str, Any]] = []
    received = invalid = 0
    error_code: str | None = None
    cursor = since
    raw_index = 0
    while cursor < until:
        chunk_end = min(until, cursor + timedelta(minutes=1000))
        try:
            raw, observed = await client.get(
                "/v1/points",
                {
                    "type": "TRADE_SIDE_AGNOSTIC_AGG",
                    "exchange": mapping.provider.exchange,
                    "rawSymbol": mapping.provider.raw_symbol,
                    "interval": "MINUTE",
                    "from": str(int(cursor.timestamp())),
                    "period": str(int((chunk_end - cursor).total_seconds())),
                    "gapfill": "false",
                },
            )
            if (
                sum(len(data) for name, data in files.items() if name.startswith("raw-")) + len(raw)
                > MAX_RAW_TOTAL
            ):
                raise ReferenceError("reference_response_too_large")
            page_records, page_received, page_invalid = _parse_points(
                raw, mapping, cursor, chunk_end, observed
            )
        except ReferenceError as exc:
            if raw_index == 0 or exc.code in {
                "reference_auth_rejected",
                "reference_series_mismatch",
                "reference_points_invalid",
            }:
                raise
            error_code = exc.code
            break
        files[f"raw-{raw_index:03d}.json"] = raw
        records.extend(page_records)
        received += page_received
        invalid += page_invalid
        raw_index += 1
        cursor = chunk_end
    records.sort(key=lambda record: record["bucket_at"])
    if len({record["bucket_at"] for record in records}) != len(records):
        raise ReferenceError("reference_points_invalid")
    snapshot = {
        "schema_version": 1,
        "source_label": f"openmarket:{mapping.provider.exchange}:{mapping.provider.raw_symbol}",
        "series": {
            "venue": mapping.native.venue,
            "source_symbol": mapping.native.source_symbol,
            "venue_instrument_version_id": mapping.native.venue_instrument_version_id,
            "definition_sha256": mapping.native.definition_sha256,
            "base_asset": mapping.native.base_asset,
            "quote_asset": mapping.native.quote_asset,
            "settle_asset": mapping.native.settle_asset,
            "price_kind": "trade",
            "interval_seconds": 60,
        },
        "records": records,
    }
    files["reference.snapshot.json"] = json_bytes(snapshot)
    expected = int((until - since).total_seconds() // 60)
    valid = len(records)
    acquisition = ReferenceAcquisition(
        schema_version=1,
        run_id=uuid4().hex,
        evidence_kind=mapping.evidence_kind,
        provider="openmarket",
        execution="completed"
        if error_code is None and invalid == 0 and valid == expected
        else "partial",
        started_at=started,
        finished_at=datetime.now(UTC),
        target=FixtureTarget(
            venue_instrument_id=target["venueInstrumentId"],
            venue_instrument_version_id=target["venueInstrumentVersionId"],
            definition_hash=target["definitionHash"],
        ),
        window=FixtureWindow(start=since, end=until),
        mapping_sha256=sha256(mapping_raw),
        request=ReferenceRequest(
            exchange=mapping.provider.exchange,
            rawSymbol=mapping.provider.raw_symbol,
            interval="MINUTE",
            type="TRADE_SIDE_AGNOSTIC_AGG",
            gapfill=False,
        ),
        counts=ReferenceCounts(
            expected_bars=expected,
            received_points=received,
            valid_bars=valid,
            missing_bars=expected - valid,
            invalid_points=invalid,
        ),
        files=tuple(
            ReferenceFile(path=name, sha256=sha256(data), bytes=len(data))
            for name, data in sorted(files.items())
        ),
        error_code=error_code,
        limitations=(
            "Provider values are compared as a separate acquisition route; "
            "independence is not established.",
            "source_at is unknown; first and last trade timestamps are retained "
            "only in raw responses.",
        ),
    )
    files["acquisition.json"] = json_bytes(acquisition.model_dump(mode="json", by_alias=True))
    path = write_bundle(output_dir, acquisition.run_id, files, validate=verify_reference_bundle)
    return path, acquisition


def verify_reference_bundle(bundle: Path) -> ReferenceAcquisition:
    """Validate a reference run offline before publication or later Audit use."""
    if bundle.is_symlink() or not bundle.is_dir():
        raise ReferenceError("reference_bundle_invalid")
    for path in bundle.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ReferenceError("reference_bundle_invalid")
    try:
        receipt_raw = read_regular(bundle / "acquisition.json", 64 * 1024)
        receipt = ReferenceAcquisition.model_validate(strict_json(receipt_raw))
    except (BundleError, ValidationError):
        raise ReferenceError("reference_acquisition_invalid") from None
    if bundle.name not in {receipt.run_id, f".staging-{receipt.run_id}"}:
        raise ReferenceError("reference_acquisition_invalid")
    if (
        receipt.window.start >= receipt.window.end
        or receipt.started_at > receipt.finished_at
        or receipt.counts.expected_bars
        != int((receipt.window.end - receipt.window.start).total_seconds() // 60)
        or receipt.counts.missing_bars != receipt.counts.expected_bars - receipt.counts.valid_bars
        or receipt.counts.received_points < receipt.counts.valid_bars
    ):
        raise ReferenceError("reference_acquisition_invalid")
    listed = {item.path for item in receipt.files}
    if len(listed) != len(receipt.files) or not {
        "metadata.json",
        "mapping.json",
        "reference.snapshot.json",
    }.issubset(listed):
        raise ReferenceError("reference_acquisition_invalid")
    if any(
        path not in {"metadata.json", "mapping.json", "reference.snapshot.json"}
        and re.fullmatch(r"raw-[0-9]{3}\.json", path) is None
        for path in listed
    ):
        raise ReferenceError("reference_acquisition_invalid")
    files: dict[str, bytes] = {"acquisition.json": receipt_raw}
    raw_total = 0
    for entry in receipt.files:
        safe_relative_path(entry.path)
        try:
            limit = MAX_RESPONSE if entry.path != "mapping.json" else 64 * 1024
            data = read_regular(bundle / entry.path, limit)
        except BundleError:
            raise ReferenceError("reference_bundle_invalid") from None
        if len(data) != entry.bytes or sha256(data) != entry.sha256:
            raise ReferenceError("reference_hash_mismatch")
        files[entry.path] = data
        if entry.path.startswith("raw-"):
            raw_total += len(data)
        try:
            strict_json(data)
        except BundleError:
            raise ReferenceError("reference_bundle_invalid") from None
    if raw_total > MAX_RAW_TOTAL:
        raise ReferenceError("reference_bundle_invalid")
    try:
        mapping = ReferenceMapping.model_validate(strict_json(files["mapping.json"]))
    except (BundleError, ValidationError):
        raise ReferenceError("reference_mapping_invalid") from None
    if (
        sha256(files["mapping.json"]) != receipt.mapping_sha256
        or mapping.native.venue_instrument_version_id != receipt.target.venue_instrument_version_id
        or mapping.native.definition_sha256 != receipt.target.definition_hash
        or f"{mapping.native.venue}:{mapping.native.source_symbol}"
        != receipt.target.venue_instrument_id
        or sha256(files["metadata.json"]) != mapping.metadata_sha256
    ):
        raise ReferenceError("reference_bundle_invalid")
    try:
        snapshot = load_snapshot(
            bundle / "reference.snapshot.json",
            start=receipt.window.start,
            end=receipt.window.end,
            as_of=receipt.finished_at,
        )
    except (ValueError, OSError):
        raise ReferenceError("reference_snapshot_invalid") from None
    if snapshot.findings or snapshot.input_rows != receipt.counts.valid_bars:
        raise ReferenceError("reference_snapshot_invalid")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise ReferenceError("reference_bundle_invalid")
        if path.is_file():
            actual.add(path.relative_to(bundle).as_posix())
        elif not path.is_dir():
            raise ReferenceError("reference_bundle_invalid")
    if actual != listed | {"acquisition.json", "SHA256SUMS"}:
        raise ReferenceError("reference_bundle_invalid")
    checksums = read_regular(bundle / "SHA256SUMS", 4096)
    if checksums != sums_bytes(files):
        raise ReferenceError("reference_hash_mismatch")
    return receipt
