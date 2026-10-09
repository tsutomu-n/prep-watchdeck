"""Explicit OSS boundaries: API comparison and bounded full-feed replay preparation."""

from __future__ import annotations

import importlib
import io
import math
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any
from uuid import uuid4

from prep_watchdeck_market.bundle_files import (
    BundleError,
    json_bytes,
    read_regular,
    sha256,
    strict_json,
    sums_bytes,
    write_bundle,
)
from prep_watchdeck_market.research.files import checked_files, isolated_root, plain_json
from prep_watchdeck_market.research.models import MAX_ROWS, ResearchTarget, instant, number
from prep_watchdeck_market.research.quality import _source_bytes
from prep_watchdeck_market.research.snapshot import verify_snapshot

HFT_TYPE_SOURCE = (
    "https://github.com/nkaz001/hftbacktest/blob/master/py-hftbacktest/hftbacktest/types.py"
)
HFT_FIELDS = ["ev", "exch_ts", "local_ts", "px", "qty", "order_id", "ival", "fval"]
HFT_DTYPES = ["u8", "i8", "i8", "f8", "f8", "u8", "i8", "f8"]


def capability_status(value: object) -> str:
    if value is True:
        return "supported"
    if value is False:
        return "unsupported"
    if value == "emulated":
        return "emulated"
    if value is None:
        return "unknown"
    raise BundleError("research_ccxt_capability_invalid")


def local_ccxt_capabilities(venue: str) -> dict[str, Any]:
    """Inspect an explicitly installed CCXT adapter without credentials or network calls."""
    if venue not in {"bitget", "hyperliquid", "aster"}:
        raise BundleError("research_identity_invalid")
    try:
        module = importlib.import_module("ccxt")
    except ImportError:
        raise BundleError("research_optional_ccxt_unavailable") from None
    try:
        exchange = getattr(module, venue)({"enableRateLimit": True, "timeout": 5000})
        capabilities = {
            name: capability_status(exchange.has.get(name))
            for name in (
                "fetchOHLCV",
                "fetchOpenInterest",
                "fetchOpenInterestHistory",
                "fetchFundingRateHistory",
                "fetchOrderBook",
                "fetchTrades",
            )
        }
        return {
            "schema_version": 1,
            "kind": "ccxt_capability_inspection",
            "exchange_id": venue,
            "ccxt_version": str(module.__version__),
            "capabilities": capabilities,
            "network_requests": 0,
            "provider_contract_verified": False,
        }
    except (AttributeError, TypeError, ValueError):
        raise BundleError("research_ccxt_adapter_invalid") from None


def compare_ccxt(snapshot_path: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """Compare exact native identity and explicit volume units; never fill missing history."""
    snapshot = verify_snapshot(snapshot_path)
    if snapshot.target is None:
        raise BundleError("research_no_observations_at_cutoff")
    try:
        if reference.get("schema_version") != 1 or reference.get("source") != "ccxt":
            raise BundleError("research_ccxt_reference_invalid")
        native_id = f"{reference['exchange_id']}:{reference['native_symbol']}"
        if native_id != snapshot.target.instrument_id:
            raise BundleError("research_identity_mismatch")
        captured = instant(reference["captured_at"])
        if not isinstance(reference["ccxt_version"], str) or not reference["ccxt_version"]:
            raise BundleError("research_ccxt_reference_invalid")
        if reference["volume_unit"] not in {"base", "notional"}:
            raise BundleError("research_ccxt_unit_unknown")
        if not isinstance(reference["has"], dict):
            raise BundleError("research_ccxt_reference_invalid")
        capabilities = {key: capability_status(value) for key, value in reference["has"].items()}
        records = reference["ohlcv"]
        if not isinstance(records, list) or len(records) > MAX_ROWS:
            raise BundleError("research_rows_exceeded")
        native = {instant(row["bucket_at"]): row for row in snapshot.rows("candles")}
        matched = 0
        absent: list[str] = []
        differences: list[dict[str, Any]] = []
        seen: set[datetime] = set()
        volume_key = "volume_base" if reference["volume_unit"] == "base" else "volume_notional"
        for row in records:
            if not isinstance(row, list) or len(row) != 6 or type(row[0]) is not int:
                raise BundleError("research_ccxt_reference_invalid")
            at = datetime.fromtimestamp(row[0] / 1000, UTC)
            if at.second or at.microsecond or at in seen or at > captured:
                raise BundleError("research_ccxt_timestamp_invalid")
            seen.add(at)
            values = [number(value, positive=index < 4) for index, value in enumerate(row[1:])]
            o, high, low, close, _volume = values
            if high < max(o, low, close) or low > min(o, high, close):
                raise BundleError("research_ohlc_invalid")
            candidate = native.get(at)
            if candidate is None:
                absent.append(at.isoformat())
                continue
            fields = ["open_price", "high_price", "low_price", "close_price", volume_key]
            mismatch = [
                field
                for field, value in zip(fields, values, strict=True)
                if candidate.get(field) is None or number(candidate[field]) != value
            ]
            if mismatch:
                differences.append({"bucket_at": at.isoformat(), "fields": mismatch})
            else:
                matched += 1
        return {
            "schema_version": 1,
            "kind": "ccxt_value_comparison",
            "snapshot_sha256": snapshot.snapshot_sha256,
            "reference_sha256": sha256(json_bytes(plain_json(reference))),
            "ccxt_version": reference["ccxt_version"],
            "captured_at": captured.isoformat(),
            "capabilities": capabilities,
            "matched_rows": matched,
            "differences": differences,
            "reference_only_buckets": absent,
            "history_repaired": False,
            "provider_contract_verified": False,
            "comparison_scope": "native_identity_and_declared_units_not_first_availability",
        }
    except BundleError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise BundleError("research_ccxt_reference_invalid") from None


def _tick(value: object, step: Decimal, *, positive: bool) -> Decimal:
    result = number(value, positive=positive)
    try:
        invalid = result % step != 0 or abs(Decimal(str(float(result))) - result) > step / 1000
    except DecimalException:
        raise BundleError("research_hft_grid_invalid") from None
    if invalid:
        raise BundleError("research_hft_grid_invalid")
    return result


def _prepare_hft_files(metadata: dict[str, Any], source: bytes) -> dict[str, bytes]:
    """Validate a declared continuous L2/trade capture and emit native hftbacktest event fields.

    This does not turn sparse selected-market snapshots into a continuous order book.
    Completeness/side evidence is caller-declared, and retained as such in the manifest.
    """
    try:
        target = ResearchTarget.model_validate(
            {key: metadata[key] for key in ("instrument_id", "version_id", "definition_hash")}
        )
        if (
            metadata.get("schema_version") != 1
            or metadata.get("feed_kind") != "continuous_l2_and_trades"
            or metadata.get("capture_complete") is not True
            or metadata.get("aggressor_side_verified") is not True
            or metadata.get("sequence_scope") not in {"exchange", "combined_capture"}
            or metadata.get("quantity_unit") != "base"
        ):
            raise BundleError("research_hft_feed_ineligible")
        tick = number(metadata["tick_size"], positive=True)
        lot = number(metadata["lot_size"], positive=True)
        if sha256(source) != metadata["source_sha256"]:
            raise BundleError("research_hash_mismatch")
        events = strict_json(source)
        if not isinstance(events, list) or not 3 <= len(events) <= MAX_ROWS:
            raise BundleError("research_hft_feed_ineligible")
        if not isinstance(events[0], dict) or events[0].get("kind") != "snapshot":
            raise BundleError("research_hft_initial_book_missing")
        rows: list[list[int | float]] = []
        book: dict[str, dict[Decimal, Decimal]] = {"bid": {}, "ask": {}}
        previous_sequence: int | None = None
        previous_exchange, previous_local = 0, 0
        saw_trade = saw_depth = False
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise BundleError("research_hft_event_invalid")
            sequence, exchange, local = (
                event[key] for key in ("sequence", "exchange_ns", "local_ns")
            )
            if any(
                type(value) is not int or not 0 < value < 2**63
                for value in (sequence, exchange, local)
            ):
                raise BundleError("research_hft_timestamp_invalid")
            if previous_sequence is not None and sequence != previous_sequence + 1:
                raise BundleError("research_hft_sequence_gap")
            if local < exchange or exchange < previous_exchange or local < previous_local:
                raise BundleError("research_hft_timestamp_invalid")
            previous_sequence, previous_exchange, previous_local = sequence, exchange, local
            kind = event.get("kind")
            changes: list[tuple[str, object, object, int]] = []
            if index == 0:
                for side, field in (("bid", "bids"), ("ask", "asks")):
                    levels = event.get(field)
                    if not isinstance(levels, list) or not 1 <= len(levels) <= 5000:
                        raise BundleError("research_hft_initial_book_missing")
                    for level in levels:
                        if not isinstance(level, list) or len(level) != 2:
                            raise BundleError("research_hft_event_invalid")
                        changes.append((side, level[0], level[1], 4))
            elif kind in {"depth", "trade"}:
                side = event.get("side")
                allowed = {"bid", "ask"} if kind == "depth" else {"buy", "sell"}
                if not isinstance(side, str) or side not in allowed:
                    raise BundleError("research_hft_side_unknown")
                changes.append(
                    (side, event["price"], event["quantity"], 1 if kind == "depth" else 2)
                )
                saw_depth |= kind == "depth"
                saw_trade |= kind == "trade"
            else:
                raise BundleError("research_hft_event_invalid")
            for side, price, quantity, event_kind in changes:
                px = _tick(price, tick, positive=True)
                qty = _tick(quantity, lot, positive=event_kind != 1)
                if event_kind != 2:
                    if index == 0 and px in book[side]:
                        raise BundleError("research_hft_duplicate_level")
                    if qty == 0:
                        book[side].pop(px, None)
                    else:
                        book[side][px] = qty
                flag = (1 << 29) if side in {"bid", "buy"} else (1 << 28)
                rows.append(
                    [
                        event_kind | flag | (1 << 31) | (1 << 30),
                        exchange,
                        local,
                        float(px),
                        float(qty),
                        0,
                        0,
                        0.0,
                    ]
                )
            if not book["bid"] or not book["ask"] or max(book["bid"]) >= min(book["ask"]):
                raise BundleError("research_hft_book_invalid")
            if len(rows) > MAX_ROWS:
                raise BundleError("research_rows_exceeded")
        if not saw_trade or not saw_depth:
            raise BundleError("research_hft_feed_ineligible")
        normalized = {
            "fields": HFT_FIELDS,
            "dtypes": HFT_DTYPES,
            "timestamp_unit": "nanoseconds",
            "rows": rows,
        }
        files = {
            "events.json": json_bytes(normalized),
            "source-events.json": source,
            "source-metadata.json": json_bytes(plain_json(metadata)),
        }
        manifest = {
            "schema_version": 1,
            "kind": "hftbacktest_prepared_input",
            "target": target.model_dump(mode="json"),
            "tick_size": str(tick),
            "lot_size": str(lot),
            "rows": len(rows),
            "fields_source": HFT_TYPE_SOURCE,
            "files": {name: sha256(data) for name, data in files.items()},
            "provider_completeness_verified": False,
            "completeness_basis": "caller_declaration_and_supplied_sequence_checks",
            "actual_fill_evidence": False,
            "backtest_executed": False,
        }
        files["manifest.json"] = json_bytes(manifest)
        return files
    except BundleError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise BundleError("research_hft_input_invalid") from None


def prepare_hft_input(metadata: dict[str, Any], output_dir: Path) -> Path:
    try:
        source = _source_bytes(
            {"path": metadata["source_path"], "sha256": metadata["source_sha256"]}
        )
        files = _prepare_hft_files(metadata, source)
        return write_bundle(isolated_root(output_dir), uuid4().hex, files)
    except BundleError:
        raise
    except (KeyError, TypeError, ValueError):
        raise BundleError("research_hft_input_invalid") from None


def export_hft_npz(prepared_dir: Path, output_dir: Path) -> Path:
    """Optional actual NumPy adapter; normal research commands do not depend on NumPy/HFT."""
    manifest_bytes = read_regular(prepared_dir / "manifest.json", 16384)
    manifest = strict_json(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("kind") != "hftbacktest_prepared_input":
        raise BundleError("research_hft_input_invalid")
    try:
        if set(manifest["files"]) != {"events.json", "source-events.json", "source-metadata.json"}:
            raise BundleError("research_hft_input_invalid")
        files = checked_files(prepared_dir, manifest["files"])
        original = {**files, "manifest.json": manifest_bytes}
        if read_regular(prepared_dir / "SHA256SUMS", 4096) != sums_bytes(original):
            raise BundleError("research_hash_mismatch")
        if {item.name for item in prepared_dir.iterdir()} != set(original) | {"SHA256SUMS"}:
            raise BundleError("research_unexpected_file")
        metadata = strict_json(files["source-metadata.json"])
        if _prepare_hft_files(metadata, files["source-events.json"]) != original:
            raise BundleError("research_hft_input_invalid")
        events = strict_json(files["events.json"])
        if (
            events["fields"] != HFT_FIELDS
            or events["dtypes"] != HFT_DTYPES
            or len(events["rows"]) > MAX_ROWS
        ):
            raise BundleError("research_hft_input_invalid")
        module = importlib.import_module("numpy")
        array = module.array(
            [tuple(row) for row in events["rows"]],
            dtype=module.dtype(list(zip(HFT_FIELDS, HFT_DTYPES, strict=True)), align=True),
        )
        if not all(math.isfinite(float(value)) for name in ("px", "qty") for value in array[name]):
            raise BundleError("research_hft_input_invalid")
        buffer = io.BytesIO()
        module.savez_compressed(buffer, data=array)
        data = buffer.getvalue()
        output = {
            "kind": "hftbacktest_npz",
            "source_events_sha256": sha256(files["events.json"]),
            "npz_sha256": sha256(data),
            "numpy_version": str(module.__version__),
            "backtest_executed": False,
            "actual_fill_evidence": False,
        }
        return write_bundle(
            isolated_root(output_dir, (prepared_dir,)),
            uuid4().hex,
            {"data.npz": data, "manifest.json": json_bytes(output)},
        )
    except ImportError:
        raise BundleError("research_optional_numpy_unavailable") from None
    except BundleError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise BundleError("research_hft_input_invalid") from None
