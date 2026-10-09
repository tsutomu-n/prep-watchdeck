"""Strict envelopes around exact, native database row representations."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from prep_watchdeck_market.bundle_files import BundleError

MAX_ROWS = 20_000
MAX_OBSERVATIONS = 2_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
HASH_PATTERN = r"^[0-9a-f]{64}$"
ID_PATTERN = r"^[0-9a-f]{32}$"
CODE_PATTERN = r"^[a-z][a-z0-9_]{0,99}$"


def instant(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise BundleError("research_timestamp_invalid") from None


def number(value: object, *, positive: bool = False, signed: bool = False) -> Decimal:
    try:
        if value is None or isinstance(value, bool):
            raise ValueError
        text = str(value)
        if len(text) > 256:
            raise ValueError
        result = Decimal(text)
        parts = result.as_tuple()
        if (
            not result.is_finite()
            or not isinstance(parts.exponent, int)
            or not -128 <= parts.exponent <= 128
            or len(parts.digits) > 128
            or abs(result) > Decimal("1e30")
            or (positive and result <= 0)
            or (not signed and result < 0)
        ):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise BundleError("research_number_invalid") from None


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ResearchTarget(ResearchModel):
    instrument_id: str = Field(pattern=r"^(bitget|hyperliquid|aster):[^\s:]{1,150}$")
    version_id: int = Field(strict=True, ge=1)
    definition_hash: str = Field(pattern=HASH_PATTERN)


class ResearchPayload(ResearchModel):
    schema_version: Literal[1] = 1
    evidence_kind: Literal["observed", "synthetic"]
    snapshot_at: datetime
    window_start: datetime
    window_end: datetime
    instrument: dict[str, Any]
    groups: tuple[dict[str, Any], ...] = Field(max_length=MAX_ROWS)
    capabilities: tuple[dict[str, Any], ...] = Field(max_length=200)
    candles: tuple[dict[str, Any], ...] = Field(max_length=MAX_ROWS)
    states: tuple[dict[str, Any], ...] = Field(max_length=MAX_ROWS)
    funding: tuple[dict[str, Any], ...] = Field(max_length=MAX_ROWS)

    @field_validator("snapshot_at", "window_start", "window_end")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if (
            not timedelta(0) < self.window_end - self.window_start <= timedelta(hours=24)
            or self.window_start.second
            or self.window_start.microsecond
            or self.window_end.second
            or self.window_end.microsecond
        ):
            raise ValueError("bounded minute-aligned window required")
        return self

    @property
    def target(self) -> ResearchTarget:
        try:
            return ResearchTarget(
                instrument_id=f"{self.instrument['venue']}:{self.instrument['source_symbol']}",
                version_id=self.instrument["venue_instrument_version_id"],
                definition_hash=self.instrument["definition_hash"],
            )
        except (KeyError, ValueError, TypeError):
            raise BundleError("research_identity_invalid") from None


class ObservationReceipt(ResearchModel):
    schema_version: Literal[1] = 1
    observation_id: str = Field(pattern=ID_PATTERN)
    sequence: int = Field(strict=True, ge=1, le=MAX_OBSERVATIONS)
    kind: Literal["observation", "gap"]
    payload_sha256: str | None = Field(default=None, pattern=HASH_PATTERN)
    previous_receipt_sha256: str | None = Field(default=None, pattern=HASH_PATTERN)
    read_started_at: datetime
    read_completed_at: datetime
    payload_readback_completed_at: datetime
    available_at: datetime
    elapsed_seconds: float = Field(ge=0, le=3600)
    clock_error_seconds: float = Field(ge=0, le=30)
    reasons: tuple[str, ...] = Field(max_length=50)

    @field_validator(
        "read_started_at", "read_completed_at", "payload_readback_completed_at", "available_at"
    )
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.kind == "observation") != (self.payload_sha256 is not None):
            raise ValueError("payload required only for observations")
        if self.available_at != max(
            self.read_completed_at, self.payload_readback_completed_at
        ) + timedelta(seconds=self.clock_error_seconds):
            raise ValueError("conservative reader availability bound required")
        if any(re.fullmatch(CODE_PATTERN, code) is None for code in self.reasons):
            raise ValueError("safe reason codes required")
        return self


def payload_reasons(payload: ResearchPayload, read_completed_at: datetime) -> tuple[str, ...]:
    """Reject malformed identity/rows; retain incomplete data as explicit quality reasons."""
    reasons: set[str] = set()
    target = payload.target
    definition = payload.instrument
    valid_from = instant(definition.get("valid_from"))
    valid_to = None if definition.get("valid_to") is None else instant(definition["valid_to"])
    if valid_from > payload.window_start or (
        valid_to is not None and valid_to < payload.window_end
    ):
        reasons.add("research_version_window_mismatch")
    if definition.get("market_type") != "linear_perpetual":
        raise BundleError("research_identity_invalid")
    if definition.get("quantity_unit") not in {"base", "contracts"}:
        reasons.add("research_quantity_unit_unknown")
    if definition.get("contract_multiplier") is None:
        reasons.add("research_multiplier_unknown")
    else:
        number(definition["contract_multiplier"], positive=True)
    if not re.fullmatch(HASH_PATTERN, str(definition.get("catalog_payload_hash", ""))):
        reasons.add("research_catalog_provenance_missing")
    if definition.get("catalog_observed_at") is None:
        reasons.add("research_catalog_provenance_missing")
    for field in ("catalog_observed_at", "catalog_source_at"):
        if definition.get(field) is not None and instant(definition[field]) > payload.snapshot_at:
            reasons.add("research_future_context")
    for field in ("quote_asset", "settle_asset", "base_asset"):
        if not isinstance(definition.get(field), str) or not definition[field]:
            raise BundleError("research_identity_invalid")
    if not payload.groups:
        reasons.add("research_group_context_missing")
    for membership in payload.groups:
        if membership.get("venue_instrument_version_id") != target.version_id:
            raise BundleError("research_identity_mismatch")
        start = instant(membership.get("valid_from"))
        end = None if membership.get("valid_to") is None else instant(membership["valid_to"])
        if not membership.get("group_id") or (end is not None and end <= start):
            raise BundleError("research_context_invalid")
        if start > payload.snapshot_at:
            reasons.add("research_future_context")
        for field in ("group_created_at", "group_updated_at"):
            if (
                membership.get(field) is not None
                and instant(membership[field]) > payload.snapshot_at
            ):
                reasons.add("research_future_context")
    if not payload.capabilities:
        reasons.add("research_capability_context_missing")
    for capability in payload.capabilities:
        if capability.get("venue") != target.instrument_id.split(":", 1)[0]:
            raise BundleError("research_identity_mismatch")
        if instant(capability.get("observed_at")) > read_completed_at:
            reasons.add("research_future_context")
        if type(capability.get("available")) is not bool:
            raise BundleError("research_context_invalid")

    bucket_sets: dict[str, set[datetime]] = {}
    for dataset in ("candles", "states", "funding"):
        seen: set[datetime] = set()
        for row in getattr(payload, dataset):
            if (
                type(row.get("venue_instrument_version_id")) is not int
                or row["venue_instrument_version_id"] != target.version_id
            ):
                raise BundleError("research_identity_mismatch")
            at = instant(row.get("funding_at" if dataset == "funding" else "bucket_at"))
            if at in seen:
                raise BundleError("research_duplicate_row")
            seen.add(at)
            if not payload.window_start <= at < payload.window_end:
                raise BundleError("research_row_outside_window")
            if dataset != "funding" and (at.second or at.microsecond):
                raise BundleError("research_bucket_invalid")
            for field in ("observed_at", "first_observed_at", "last_observed_at", "finalized_at"):
                if row.get(field) is not None and instant(row[field]) > read_completed_at:
                    reasons.add("research_future_row")
            if row.get("source_at") is not None and instant(row["source_at"]) > read_completed_at:
                reasons.add("research_future_source_time")
            if dataset == "candles":
                o, h, low, c = (
                    number(row.get(k), positive=True)
                    for k in ("open_price", "high_price", "low_price", "close_price")
                )
                if h < max(o, low, c) or low > min(o, h, c):
                    raise BundleError("research_ohlc_invalid")
                for field in ("volume_base", "volume_notional"):
                    if row.get(field) is not None:
                        number(row[field])
                if row.get("volume_notional") is None:
                    reasons.add("research_activity_missing")
                if row.get("finality") not in {"confirmed", "derived_final"}:
                    raise BundleError("research_finality_invalid")
                decided = row.get("finalized_at")
                if decided is None and row["finality"] == "confirmed":
                    decided = row.get("observed_at")
                if decided is None:
                    reasons.add("research_finality_time_unknown")
                elif instant(decided) < at + timedelta(minutes=1):
                    reasons.add("research_finality_before_close")
            elif dataset == "states":
                first, last = (
                    instant(row.get("first_observed_at")),
                    instant(row.get("last_observed_at")),
                )
                if last < first:
                    raise BundleError("research_state_time_invalid")
                if row.get("status") != "ready":
                    reasons.add("research_state_not_ready")
                if row.get("open_interest_raw") is None:
                    reasons.add("research_oi_missing")
                else:
                    number(row["open_interest_raw"])
                if row.get("open_interest_raw_unit") not in {"base", "contracts"}:
                    reasons.add("research_oi_unit_unknown")
                for field in ("mark_price", "best_bid", "best_ask"):
                    if row.get(field) is not None:
                        number(row[field], positive=True)
                if (
                    row.get("best_bid") is not None
                    and row.get("best_ask") is not None
                    and number(row["best_bid"]) > number(row["best_ask"])
                ):
                    raise BundleError("research_crossed_market")
            else:
                number(row.get("funding_rate_raw"), signed=True)
                instant(row.get("observed_at"))
                interval = row.get("funding_interval_seconds")
                if interval is not None and (type(interval) is not int or interval <= 0):
                    raise BundleError("research_funding_interval_invalid")
        bucket_sets[dataset] = seen
    expected = {
        payload.window_start + timedelta(minutes=index)
        for index in range(int((payload.window_end - payload.window_start).total_seconds() // 60))
    }
    if bucket_sets["candles"] != expected:
        reasons.add("research_candle_gap")
    if bucket_sets["states"] != expected:
        reasons.add("research_state_gap")
    if payload.window_end > read_completed_at:
        reasons.add("research_unclosed_window")
    return tuple(sorted(reasons))
