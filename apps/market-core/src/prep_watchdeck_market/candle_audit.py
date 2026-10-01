"""Read-only reconciliation of two explicitly identified native candle snapshots.

This diagnostic never fetches data, writes market state, repairs candles, or chooses a winner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any, cast, get_args

from prep_watchdeck_market.candles import (
    Candle1m,
    CandleFinality,
    decimal_value,
    non_negative_integer,
    require_list,
    require_mapping,
    require_text,
)
from prep_watchdeck_market.models import Venue

PRICE_FIELDS = ("open_price", "high_price", "low_price", "close_price")
SERIES_FIELDS = {
    "venue",
    "source_symbol",
    "venue_instrument_version_id",
    "definition_sha256",
    "base_asset",
    "quote_asset",
    "settle_asset",
    "price_kind",
    "interval_seconds",
}
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_WINDOW_MINUTES = 7 * 24 * 60


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601 text with an offset")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("timestamp must be ISO-8601 text with an offset") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return stamp.astimezone(UTC)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object contains a duplicate key")
        result[key] = value
    return result


def _optional_decimal(value: object, field: str) -> Decimal | None:
    return None if value is None else decimal_value(value, field_name=field)


@dataclass(frozen=True)
class Snapshot:
    series: dict[str, Any]
    source_label: str
    sha256: str
    rows: dict[datetime, Candle1m]
    present: frozenset[datetime]
    findings: tuple[dict[str, Any], ...]
    input_rows: int


def load_snapshot(path: Path, *, start: datetime, end: datetime, as_of: datetime) -> Snapshot:
    try:
        current = Path(path.absolute().anchor)
        for part in path.absolute().parts[1:-1]:
            current /= part
            if current.is_symlink():
                raise ValueError("snapshot path contains a symlink")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("snapshot must be a regular file")
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError:
        raise ValueError("snapshot unavailable") from None
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("snapshot exceeds the 16 MiB input limit")
    payload = require_mapping(
        json.loads(raw, parse_float=Decimal, object_pairs_hook=_unique_object),
        field_name="snapshot",
    )
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported snapshot schema_version")
    series = require_mapping(payload.get("series"), field_name="series")
    if set(series) != SERIES_FIELDS:
        raise ValueError("series metadata fields do not match the snapshot contract")
    for field in SERIES_FIELDS - {"venue_instrument_version_id", "interval_seconds"}:
        text = require_text(series[field], field_name=field)
        if text != series[field]:
            raise ValueError("series metadata must not have surrounding whitespace")
    if series["venue"] not in get_args(Venue):
        raise ValueError("snapshot venue is outside the current native candle contract")
    version = series["venue_instrument_version_id"]
    if type(version) is not int or version <= 0:
        raise ValueError("series version must be a positive integer")
    if not re.fullmatch(r"[0-9a-f]{64}", str(series["definition_sha256"])):
        raise ValueError("series requires the actual catalog definition SHA-256")
    if type(series["interval_seconds"]) is not int or series["interval_seconds"] != 60:
        raise ValueError("only native 1-minute snapshots are accepted")
    if series["price_kind"] != "trade":
        raise ValueError(
            "only trade-price candles are accepted; mark/index are not interchangeable"
        )
    label = require_text(payload.get("source_label"), field_name="source_label")
    if len(label) > 128 or any(ord(char) < 32 for char in label):
        raise ValueError("source_label must be short printable text, not credentials")
    records = require_list(payload.get("records"), field_name="records")
    rows: dict[datetime, Candle1m] = {}
    seen: set[datetime] = set()
    findings: list[dict[str, Any]] = []
    for number, value in enumerate(records, 1):
        bucket: datetime | None = None
        try:
            record = require_mapping(value, field_name="record")
            bucket = _time(record.get("bucket_at"))
            if not start <= bucket < end:
                continue
            if bucket in seen:
                rows.pop(bucket, None)
                raise ValueError("duplicate_bucket")
            seen.add(bucket)
            if type(record.get("venue_instrument_version_id")) is not int or (
                record["venue_instrument_version_id"] != version
            ):
                raise ValueError("record_version_mismatch")
            finality = record.get("finality")
            if finality not in get_args(CandleFinality):
                raise ValueError("record_is_not_final")
            source_at = None if record.get("source_at") is None else _time(record["source_at"])
            candle = Candle1m(
                venue=cast(Venue, series["venue"]),
                source_symbol=str(series["source_symbol"]),
                bucket_start=bucket,
                open_price=decimal_value(
                    record.get("open_price"), field_name="open_price", positive=True
                ),
                high_price=decimal_value(
                    record.get("high_price"), field_name="high_price", positive=True
                ),
                low_price=decimal_value(
                    record.get("low_price"), field_name="low_price", positive=True
                ),
                close_price=decimal_value(
                    record.get("close_price"), field_name="close_price", positive=True
                ),
                volume_base=_optional_decimal(record.get("volume_base"), "volume_base"),
                volume_notional=_optional_decimal(record.get("volume_notional"), "volume_notional"),
                trade_count=(
                    None
                    if record.get("trade_count") is None
                    else non_negative_integer(record["trade_count"], field_name="trade_count")
                ),
                finality=cast(CandleFinality, finality),
                source_at=source_at,
                observed_at=_time(record.get("observed_at")),
            )
            if candle.bucket_end > candle.observed_at:
                raise ValueError("observed_before_close")
            if candle.observed_at > as_of or (source_at is not None and source_at > as_of):
                raise ValueError("unavailable_at_as_of")
            rows[bucket] = candle
        except (ValueError, DecimalException) as exc:
            findings.append(
                {
                    "row": number,
                    "bucket_at": None if bucket is None else bucket.isoformat(),
                    "reason": str(exc),
                }
            )
    return Snapshot(
        dict(series),
        label,
        hashlib.sha256(raw).hexdigest(),
        rows,
        frozenset(seen),
        tuple(findings),
        len(records),
    )


def _difference(a: Decimal, b: Decimal) -> tuple[Decimal, Decimal]:
    difference = abs(a - b)
    denominator = (abs(a) + abs(b)) / 2
    return difference, difference / denominator if denominator else Decimal(0)


def audit_snapshots(
    left_path: Path,
    right_path: Path,
    *,
    start: datetime,
    end: datetime,
    as_of: datetime,
    price_abs_tol: Decimal = Decimal(0),
    price_rel_tol: Decimal = Decimal(0),
    compare_volume_base: bool = False,
    volume_abs_tol: Decimal = Decimal(0),
    volume_rel_tol: Decimal = Decimal(0),
    return_minutes: int = 5,
    return_tol_bps: Decimal = Decimal(0),
) -> dict[str, Any]:
    start, end, as_of = (_time(stamp.isoformat()) for stamp in (start, end, as_of))
    if any(stamp.second or stamp.microsecond for stamp in (start, end)):
        raise ValueError("window boundaries must be aligned to one minute")
    count = int((end - start).total_seconds() // 60)
    if type(return_minutes) is not int or not 1 <= return_minutes < count <= MAX_WINDOW_MINUTES:
        raise ValueError("window must exceed the positive return horizon and be at most 7 days")
    if end > as_of:
        raise ValueError("window contains candles not closed at as_of")
    tolerances = {
        "price_abs_tol": price_abs_tol,
        "price_rel_tol": price_rel_tol,
        "volume_abs_tol": volume_abs_tol,
        "volume_rel_tol": volume_rel_tol,
        "return_tol_bps": return_tol_bps,
    }
    for name, tolerance in tolerances.items():
        decimal_value(tolerance, field_name=name)
    left = load_snapshot(left_path, start=start, end=end, as_of=as_of)
    right = load_snapshot(right_path, start=start, end=end, as_of=as_of)
    if left.series != right.series:
        raise ValueError("series_mismatch: market, version, units and price basis must all match")
    expected = tuple(start + timedelta(minutes=index) for index in range(count))
    common = tuple(stamp for stamp in expected if stamp in left.rows and stamp in right.rows)
    differences: list[dict[str, Any]] = []
    missing_values: list[dict[str, str]] = []
    compared_values = 0
    return_pairs = 0
    return_missing: list[str] = []
    fields = (*PRICE_FIELDS, "volume_base") if compare_volume_base else PRICE_FIELDS
    with localcontext() as context:
        context.prec = 34
        for stamp in common:
            a, b = left.rows[stamp], right.rows[stamp]
            for field in fields:
                av, bv = getattr(a, field), getattr(b, field)
                if av is None or bv is None:
                    missing_values.append({"bucket_at": stamp.isoformat(), "field": field})
                    continue
                compared_values += 1
                absolute, relative = _difference(av, bv)
                abs_tol, rel_tol = (
                    (volume_abs_tol, volume_rel_tol)
                    if field == "volume_base"
                    else (price_abs_tol, price_rel_tol)
                )
                if absolute > abs_tol and relative > rel_tol:
                    differences.append(
                        {
                            "bucket_at": stamp.isoformat(),
                            "field": field,
                            "left": str(av),
                            "right": str(bv),
                            "abs_diff": str(absolute),
                            "rel_diff_bps": str(relative * 10_000),
                        }
                    )
        for stamp in expected[return_minutes:]:
            previous = stamp - timedelta(minutes=return_minutes)
            if any(time not in snap.rows for snap in (left, right) for time in (previous, stamp)):
                return_missing.append((stamp + timedelta(minutes=1)).isoformat())
                continue
            ar, br = (
                (snap.rows[stamp].close_price / snap.rows[previous].close_price).ln()
                for snap in (left, right)
            )
            return_pairs += 1
            diff_bps = abs(ar - br) * 10_000
            if diff_bps > return_tol_bps:
                differences.append(
                    {
                        "field": "log_return",
                        "start_at": (previous + timedelta(minutes=1)).isoformat(),
                        "end_at": (stamp + timedelta(minutes=1)).isoformat(),
                        "left": str(ar),
                        "right": str(br),
                        "abs_diff_bps": str(diff_bps),
                    }
                )
    sources = {}
    for label, snapshot in (("left", left), ("right", right)):
        sources[label] = {
            "source_label": snapshot.source_label,
            "input_sha256": snapshot.sha256,
            "input_rows": snapshot.input_rows,
            "valid_rows": len(snapshot.rows),
            "missing_buckets": [t.isoformat() for t in expected if t not in snapshot.present],
            "unusable_buckets": [t.isoformat() for t in expected if t not in snapshot.rows],
            "findings": snapshot.findings,
            "source_time_missing_count": sum(c.source_at is None for c in snapshot.rows.values()),
            "derived_final_count": sum(
                c.finality == "derived_final" for c in snapshot.rows.values()
            ),
        }
    incomplete = bool(
        len(common) != count or missing_values or return_missing or left.findings or right.findings
    )
    outcome = (
        "unverified"
        if not common or not return_pairs
        else "differences"
        if differences
        else "incomplete"
        if incomplete
        else "match"
    )
    return {
        "schema_version": 1,
        "audit_version": "native-candle-snapshots-v1",
        "outcome": outcome,
        "coverage_complete": not incomplete,
        "series": left.series,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "as_of": as_of.isoformat(),
        "expected_bars": count,
        "common_valid_bars": len(common),
        "compared_values": compared_values,
        "compared_fields": fields,
        "tolerances": {k: str(v) for k, v in tolerances.items()},
        "return_minutes": return_minutes,
        "return_pairs": return_pairs,
        "expected_return_pairs": count - return_minutes,
        "return_missing_endpoints": return_missing,
        "sources": sources,
        "missing_values": missing_values,
        "differences": differences,
        "limitation": (
            "Input metadata is caller-declared; agreement does not prove source correctness "
            "or independence. No market data is repaired or overwritten."
        ),
    }


def _tolerance(value: str) -> Decimal:
    try:
        return decimal_value(value, field_name="tolerance")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="保存済みの同一市場1分足を読み取り専用で照合する")
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    for option in ("start", "end", "as-of"):
        parser.add_argument(f"--{option}", type=_time, required=True)
    parser.add_argument("--compare-volume-base", action="store_true")
    parser.add_argument("--return-minutes", type=int, default=5)
    for option in (
        "price-abs-tol",
        "price-rel-tol",
        "volume-abs-tol",
        "volume-rel-tol",
        "return-tol-bps",
    ):
        parser.add_argument(f"--{option}", type=_tolerance, default=Decimal(0))
    args = vars(parser.parse_args(argv))
    try:
        report = audit_snapshots(args.pop("left"), args.pop("right"), **args)
    except (OSError, ValueError, DecimalException, TypeError, OverflowError) as exc:
        # File-system errors can contain private paths; never echo raw input data.
        message = "snapshot_io_error" if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"outcome": "invalid_input", "error": message}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return {"match": 0, "differences": 1, "incomplete": 1, "unverified": 3}[report["outcome"]]


if __name__ == "__main__":
    raise SystemExit(main())
