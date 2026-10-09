"""Offline coverage and original-preserving archive/funding inspections."""

from __future__ import annotations

import csv
import gzip
import io
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from prep_watchdeck_market.bundle_files import BundleError, read_regular, sha256
from prep_watchdeck_market.research.models import (
    MAX_FILE_BYTES,
    MAX_ROWS,
    ResearchTarget,
    instant,
    number,
)
from prep_watchdeck_market.research.snapshot import verify_snapshot


def _minutes(start: datetime, end: datetime) -> set[datetime]:
    if not timedelta(0) < end - start <= timedelta(hours=24) or any(
        value.second or value.microsecond for value in (start, end)
    ):
        raise BundleError("research_window_invalid")
    return {
        start + timedelta(minutes=index)
        for index in range(int((end - start).total_seconds() // 60))
    }


def quality_report(snapshot_path: Path, *, cutoff: datetime | None = None) -> dict[str, Any]:
    snapshot = verify_snapshot(snapshot_path, cutoff=cutoff)
    expected: set[datetime] = set()
    for observation in snapshot.observations:
        payload = observation.payload
        valid_from = instant(payload.instrument["valid_from"])
        valid_to = payload.instrument.get("valid_to")
        expected.update(
            at
            for at in _minutes(payload.window_start, payload.window_end)
            if at >= valid_from
            and (valid_to is None or at + timedelta(minutes=1) <= instant(valid_to))
        )
    candles = {instant(row["bucket_at"]): row for row in snapshot.rows("candles")}
    states = {instant(row["bucket_at"]): row for row in snapshot.rows("states")}
    common: set[datetime] = set()
    exclusions: Counter[str] = Counter()
    for at in sorted(expected):
        candle, state = candles.get(at), states.get(at)
        reasons = []
        if candle is None:
            reasons.append("candle_missing")
        elif candle.get("volume_notional") is None:
            reasons.append("activity_missing")
        if state is None:
            reasons.append("state_missing")
        else:
            if state.get("open_interest_raw") is None:
                reasons.append("oi_missing")
            if state.get("open_interest_raw_unit") not in {"base", "contracts"}:
                reasons.append("oi_unit_unknown")
            if state.get("status") != "ready":
                reasons.append("state_not_ready")
        exclusions.update(reasons)
        if not reasons:
            common.add(at)
    daily = []
    if expected:
        frame = pl.DataFrame(
            [
                {
                    "day": at.date().isoformat(),
                    "expected": 1,
                    "candles": int(at in candles),
                    "states": int(at in states),
                    "common": int(at in common),
                }
                for at in sorted(expected)
            ]
        )
        daily = frame.group_by("day").agg(pl.exclude("day").sum()).sort("day").to_dicts()
    return {
        "schema_version": 1,
        "kind": "research_quality",
        "snapshot_sha256": snapshot.snapshot_sha256,
        "target": None if snapshot.target is None else snapshot.target.model_dump(mode="json"),
        "cutoff": None if cutoff is None else instant(cutoff).isoformat(),
        "scope": "latest_reader_observed_editions_at_cutoff_not_trading_results",
        "replay_valid": snapshot.replay_valid,
        "qualified_for_ab": snapshot.qualified_for_ab,
        "observed_evidence": snapshot.observed_evidence,
        "reasons": list(snapshot.reasons),
        "counts": {
            "expected_minutes": len(expected),
            "candles": len(candles),
            "states": len(states),
            "common_price_activity_oi": len(common),
            "funding_events": len(snapshot.rows("funding")),
        },
        "missing": {
            "candles": [at.isoformat() for at in sorted(expected - set(candles))],
            "states": [at.isoformat() for at in sorted(expected - set(states))],
        },
        "exclusions": dict(sorted(exclusions.items())),
        "daily_utc": daily,
        "funding_coverage": "observed_rows_only",
        "history_repaired": False,
    }


def _source_bytes(source: object) -> bytes:
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("path"), str)
        or not Path(source["path"]).is_absolute()
    ):
        raise BundleError("research_source_path_invalid")
    data = read_regular(Path(source["path"]), MAX_FILE_BYTES)
    if sha256(data) != source.get("sha256"):
        raise BundleError("research_hash_mismatch")
    return data


def reconcile_archives(manifest: dict[str, Any]) -> dict[str, Any]:
    """Inspect bounded retained Parquet bytes. Never overwrite or backfill a native store."""
    try:
        target = ResearchTarget.model_validate(
            {key: manifest[key] for key in ("instrument_id", "version_id", "definition_hash")}
        )
        start, end = instant(manifest["window_start"]), instant(manifest["window_end"])
        expected = _minutes(start, end)
        valid_from = instant(manifest["valid_from"])
        valid_to = None if manifest.get("valid_to") is None else instant(manifest["valid_to"])
        if valid_to is not None and valid_to <= valid_from:
            raise BundleError("research_context_invalid")
        expected = {
            at
            for at in expected
            if at >= valid_from and (valid_to is None or at + timedelta(minutes=1) <= valid_to)
        }
        sources = manifest["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
            raise BundleError("research_sources_invalid")
        fields = (
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume_base",
            "volume_notional",
            "trade_count",
            "finality",
        )
        retained: dict[datetime, tuple[tuple[object, ...], str]] = {}
        conflicts: list[dict[str, Any]] = []
        lineage: list[dict[str, Any]] = []
        total_bytes = 0
        for source in sources:
            if not isinstance(source, dict) or source.get("dataset") != "candles":
                raise BundleError("research_archive_dataset_invalid")
            if any(
                source.get(key) != getattr(target, key)
                for key in ("instrument_id", "version_id", "definition_hash")
            ):
                raise BundleError("research_identity_mismatch")
            raw = _source_bytes(source)
            total_bytes += len(raw)
            if total_bytes > 64 * 1024 * 1024:
                raise BundleError("research_size_exceeded")
            # Scan only the requested native version; no provider joins or symbol aliases.
            frame = (
                pl.scan_parquet(io.BytesIO(raw))
                .filter(pl.col("venue_instrument_version_id") == target.version_id)
                .limit(MAX_ROWS + 1)
                .collect(engine="streaming")
            )
            if frame.height > MAX_ROWS:
                raise BundleError("research_rows_exceeded")
            matched = 0
            local_seen: set[datetime] = set()
            for row in frame.to_dicts():
                at = instant(row.get("bucket_at"))
                if at not in expected:
                    continue
                if at in local_seen:
                    raise BundleError("research_duplicate_row")
                local_seen.add(at)
                prices = tuple(
                    number(row.get(field), positive=True)
                    for field in ("open_price", "high_price", "low_price", "close_price")
                )
                o, high, low, c = prices
                if high < max(o, low, c) or low > min(o, high, c):
                    raise BundleError("research_ohlc_invalid")
                volumes = tuple(
                    None if row.get(field) is None else number(row[field])
                    for field in ("volume_base", "volume_notional")
                )
                trades = row.get("trade_count")
                if trades is not None and (type(trades) is not int or trades < 0):
                    raise BundleError("research_trade_count_invalid")
                finality = row.get("finality")
                if finality is not None and finality not in {"confirmed", "derived_final"}:
                    raise BundleError("research_finality_invalid")
                values = (*prices, *volumes, trades, finality)
                matched += 1
                previous = retained.get(at)
                if previous is not None and previous[0] != values:
                    conflicts.append(
                        {
                            "at": at.isoformat(),
                            "first_sha256": previous[1],
                            "other_sha256": source["sha256"],
                            "fields": [
                                field
                                for field, first, other in zip(
                                    fields, previous[0], values, strict=True
                                )
                                if first != other
                            ],
                        }
                    )
                else:
                    retained[at] = (values, source["sha256"])
            lineage.append(
                {
                    "path": source["path"],
                    "sha256": source["sha256"],
                    "selected_rows": frame.height,
                    "window_rows": matched,
                }
            )
        return {
            "schema_version": 1,
            "kind": "archive_reconciliation",
            "target": target.model_dump(mode="json"),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "expected_minutes": len(expected),
            "retained_minutes": len(retained),
            "conflicts": conflicts,
            "lineage": lineage,
            "backfill_candidates": [at.isoformat() for at in sorted(expected - set(retained))],
            "point_in_time_replay": False,
            "writes_performed": False,
            "availability_reconstructed": False,
        }
    except BundleError:
        raise
    except (KeyError, ValueError, TypeError, pl.exceptions.PolarsError):
        raise BundleError("research_archive_invalid") from None


def inspect_funding_sources(manifest: dict[str, Any]) -> dict[str, Any]:
    """Check Classic Bitget immutable CSV lineage without borrowing current intervals as history."""
    try:
        venue, category, symbol = (manifest[key] for key in ("venue", "category", "symbol"))
        if (
            venue != "bitget"
            or category != "USDT-FUTURES"
            or not isinstance(symbol, str)
            or not symbol
        ):
            raise BundleError("research_identity_invalid")
        start, end = instant(manifest["window_start"]), instant(manifest["window_end"])
        if not timedelta(0) < end - start <= timedelta(days=3660):
            raise BundleError("research_window_invalid")
        sources = manifest["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
            raise BundleError("research_sources_invalid")
        rates: dict[datetime, Decimal] = {}
        lineage: list[dict[str, Any]] = []
        for source in sources:
            raw = _source_bytes(source)
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise BundleError("research_size_exceeded")
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
            if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise BundleError("research_funding_schema_invalid")
            times: list[datetime] = []
            count = 0
            intervals: set[int] = set()
            for row in reader:
                count += 1
                if count > MAX_ROWS:
                    raise BundleError("research_rows_exceeded")
                if (row.get("venue"), row.get("category"), row.get("symbol")) != (
                    venue,
                    category,
                    symbol,
                ):
                    raise BundleError("research_identity_mismatch")
                timestamp = int(row["funding_time_ms"])
                at = datetime.fromtimestamp(timestamp / 1000, UTC)
                rate = number(row["funding_rate"], signed=True)
                interval = int(row["current_instrument_fund_interval_hours"])
                if interval <= 0 or interval > 596_523:
                    raise BundleError("research_funding_interval_invalid")
                intervals.add(interval * 3600)
                times.append(at)
                previous = rates.get(at)
                if previous is not None and previous != rate:
                    raise BundleError("research_funding_conflict")
                rates[at] = rate
            if not times or (source.get("row_count") is not None and source["row_count"] != count):
                raise BundleError("research_funding_row_count_invalid")
            lineage.append(
                {
                    "path": source["path"],
                    "sha256": source["sha256"],
                    "rows": count,
                    "actual_first_event": min(times).isoformat(),
                    "actual_last_event": max(times).isoformat(),
                    "reported_current_intervals_seconds": sorted(intervals),
                }
            )
        selected = sorted((at, rate) for at, rate in rates.items() if start <= at < end)
        return {
            "schema_version": 1,
            "kind": "funding_lineage_inspection",
            "venue": venue,
            "category": category,
            "symbol": symbol,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "rows": len(selected),
            "lineage": lineage,
            "events": [
                {"funding_at": at.isoformat(), "funding_rate_raw": str(rate)}
                for at, rate in selected
            ],
            "coverage": "observed_rows_only",
            "schedule_verified": False,
            "limitation": "current_instrument_interval_does_not_prove_historical_schedule",
            "point_in_time_replay": False,
            "writes_performed": False,
        }
    except BundleError:
        raise
    except (KeyError, ValueError, TypeError, OSError, EOFError, csv.Error, OverflowError):
        raise BundleError("research_funding_source_invalid") from None
