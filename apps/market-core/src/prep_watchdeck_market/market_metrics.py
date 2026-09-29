"""Optional read model for current-version native endpoint changes."""

from __future__ import annotations

import fcntl
import json
import math
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import Field, ValidationError, model_validator

from prep_watchdeck_market.artifacts import ArtifactModel, write_artifact_atomic

CANDLE_LAG_SECONDS = 180
CANDLE_MAX_AGE_SECONDS = 300
METRIC_VERSION = "native-endpoints-v1"
READ_OPTIONS = "-c statement_timeout=5000 -c transaction_timeout=8000"
PROJECTION_TIMEOUT_SECONDS = 10
Availability = Literal["available", "missing", "unsupported", "invalid"]


class MetricValue(ArtifactModel):
    value: float | None
    availability: Availability
    reason_code: str | None
    start_at: datetime | None
    end_at: datetime | None
    start_value: float | None
    end_value: float | None
    start_source_at: datetime | None
    start_observed_at: datetime | None
    end_source_at: datetime | None
    end_observed_at: datetime | None
    end_finality: str | None
    unit: str | None

    @model_validator(mode="after")
    def consistent(self) -> MetricValue:
        if self.availability == "available" and (
            self.value is None or self.reason_code is not None
        ):
            raise ValueError("available metric requires a value and no reason")
        if self.availability != "available" and (self.value is not None or not self.reason_code):
            raise ValueError("unavailable metric requires null and a reason")
        return self


class TimingPolicy(ArtifactModel):
    candle_lag_seconds: Literal[180] = CANDLE_LAG_SECONDS
    candle_max_age_seconds: Literal[300] = CANDLE_MAX_AGE_SECONDS


class MarketMetricRow(ArtifactModel):
    venue_instrument_id: str
    venue_instrument_version_id: int = Field(gt=0)
    venue: str
    source_symbol: str
    quote_asset: str
    settle_asset: str
    price_tick: str | None
    oi_change: dict[str, MetricValue]
    trade_change: dict[str, MetricValue]

    @model_validator(mode="after")
    def complete_windows(self) -> MarketMetricRow:
        if set(self.oi_change) != {"15m", "1h"} or set(self.trade_change) != {"15m", "1h", "24h"}:
            raise ValueError("market metric windows must be complete")
        return self


class MarketMetricsArtifact(ArtifactModel):
    schema_version: Literal[1] = 1
    metric_version: Literal["native-endpoints-v1"] = METRIC_VERSION
    generation_id: str
    generated_at: datetime
    candle_cutoff: datetime
    timing_policy: TimingPolicy = TimingPolicy()
    rows: tuple[MarketMetricRow, ...]

    @model_validator(mode="after")
    def unique_current_versions(self) -> MarketMetricsArtifact:
        keys = [(row.venue_instrument_id, row.venue_instrument_version_id) for row in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate market metric identity")
        return self


def candle_cutoff(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("metrics clock must be timezone-aware")
    return now.astimezone(UTC).replace(second=0, microsecond=0) - timedelta(
        seconds=CANDLE_LAG_SECONDS
    )


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _missing(reason: str, start_at: datetime | None, end_at: datetime | None) -> MetricValue:
    return MetricValue(
        value=None,
        availability="missing",
        reason_code=reason,
        start_at=start_at,
        end_at=end_at,
        start_value=None,
        end_value=None,
        start_source_at=None,
        start_observed_at=None,
        end_source_at=None,
        end_observed_at=None,
        end_finality=None,
        unit=None,
    )


def _change(
    start: Any,
    end: Any,
    *,
    start_at: datetime,
    end_at: datetime,
    source_at: datetime | None,
    observed_at: datetime | None,
    start_source_at: datetime | None,
    start_observed_at: datetime | None,
    finality: str | None,
    unit: str,
    now: datetime,
    maximum_age_seconds: int,
) -> MetricValue:
    baseline, current = _number(start), _number(end)
    if baseline is None or current is None or (unit != "base" and current == 0):
        return _missing("endpoint_missing", start_at, end_at)
    if baseline == 0:
        return _missing("no_baseline", start_at, end_at)
    if end_at > now or any(
        stamp is not None and stamp > now
        for stamp in (source_at, observed_at, start_source_at, start_observed_at)
    ):
        return _missing("future_timestamp", start_at, end_at)
    if (now - end_at).total_seconds() > maximum_age_seconds or (
        source_at is not None and (now - source_at).total_seconds() > maximum_age_seconds
    ):
        return _missing("endpoint_stale", start_at, end_at)
    change = 100 * (current / baseline - 1)
    if not math.isfinite(change):
        return _missing("invalid_change", start_at, end_at)
    return MetricValue(
        value=change,
        availability="available",
        reason_code=None,
        start_at=start_at,
        end_at=end_at,
        start_value=baseline,
        end_value=current,
        start_source_at=start_source_at,
        start_observed_at=start_observed_at,
        end_source_at=source_at,
        end_observed_at=observed_at,
        end_finality=finality,
        unit=unit,
    )


def build_market_metrics(rows: list[dict[str, Any]], *, now: datetime) -> MarketMetricsArtifact:
    cutoff = candle_cutoff(now)
    results: list[MarketMetricRow] = []
    for row in rows:
        instrument_id = f"{row['venue']}:{row['source_symbol']}"
        oi: dict[str, MetricValue] = {}
        latest_at = row["l_cycle_at"]
        for name, minutes in (("15m", 15), ("1h", 60)):
            anchor = latest_at - timedelta(minutes=minutes) if latest_at else None
            if latest_at is None or anchor is None or row["l_oi_base"] is None:
                oi[name] = _missing("endpoint_missing", anchor, latest_at)
            else:
                oi[name] = _change(
                    row[f"oi_{name}_base"],
                    row["l_oi_base"],
                    start_at=anchor,
                    end_at=latest_at,
                    source_at=row["l_source_at"],
                    observed_at=row["l_observed_at"],
                    start_source_at=row[f"oi_{name}_source_at"],
                    start_observed_at=row[f"oi_{name}_observed_at"],
                    finality=None,
                    unit="base",
                    now=now,
                    maximum_age_seconds=120,
                )
        trade: dict[str, MetricValue] = {}
        for name, minutes in (("15m", 15), ("1h", 60), ("24h", 1440)):
            start_at = cutoff - timedelta(minutes=minutes)
            current_finality = row["c_end_finality"]
            baseline_finality = row[f"c_{name}_finality"]
            if current_finality not in ("confirmed", "derived_final") or baseline_finality not in (
                "confirmed",
                "derived_final",
            ):
                trade[name] = _missing("endpoint_missing", start_at, cutoff)
            else:
                trade[name] = _change(
                    row[f"c_{name}_close"],
                    row["c_end_close"],
                    start_at=start_at,
                    end_at=cutoff,
                    source_at=row["c_end_source_at"],
                    observed_at=row["c_end_observed_at"],
                    start_source_at=row[f"c_{name}_source_at"],
                    start_observed_at=row[f"c_{name}_observed_at"],
                    finality=current_finality,
                    unit=row["quote_asset"],
                    now=now,
                    maximum_age_seconds=CANDLE_MAX_AGE_SECONDS,
                )
        results.append(
            MarketMetricRow(
                venue_instrument_id=instrument_id,
                venue_instrument_version_id=row["venue_instrument_version_id"],
                venue=row["venue"],
                source_symbol=row["source_symbol"],
                quote_asset=row["quote_asset"],
                settle_asset=row["settle_asset"],
                price_tick=str(row["price_tick"]) if row["price_tick"] is not None else None,
                oi_change=oi,
                trade_change=trade,
            )
        )
    return MarketMetricsArtifact(
        generation_id=f"{cutoff.isoformat()}:{uuid4().hex}",
        generated_at=now,
        candle_cutoff=cutoff,
        rows=tuple(results),
    )


METRICS_SQL = """
SELECT vi.venue_instrument_version_id, vi.venue, vi.source_symbol,
       vi.quote_asset, vi.settle_asset, vi.price_tick,
       l.cycle_at AS l_cycle_at, l.open_interest_base AS l_oi_base,
       l.source_at AS l_source_at, l.observed_at AS l_observed_at,
       oi15.open_interest_base AS oi_15m_base, oi60.open_interest_base AS oi_1h_base,
       oi15.source_at AS oi_15m_source_at, oi15.last_observed_at AS oi_15m_observed_at,
       oi60.source_at AS oi_1h_source_at, oi60.last_observed_at AS oi_1h_observed_at,
       c0.close_price AS c_end_close, c0.finality AS c_end_finality,
       c0.source_at AS c_end_source_at, c0.observed_at AS c_end_observed_at,
       c15.close_price AS c_15m_close, c15.finality AS c_15m_finality,
       c15.source_at AS c_15m_source_at, c15.observed_at AS c_15m_observed_at,
       c60.close_price AS c_1h_close, c60.finality AS c_1h_finality,
       c60.source_at AS c_1h_source_at, c60.observed_at AS c_1h_observed_at,
       c1440.close_price AS c_24h_close, c1440.finality AS c_24h_finality,
       c1440.source_at AS c_24h_source_at, c1440.observed_at AS c_24h_observed_at
FROM venue_instrument_versions vi
LEFT JOIN latest_market_state l
  ON l.venue_instrument_version_id = vi.venue_instrument_version_id
LEFT JOIN market_state_1m oi15
  ON oi15.venue_instrument_version_id = vi.venue_instrument_version_id
 AND oi15.bucket_at = l.cycle_at - interval '15 minutes'
LEFT JOIN market_state_1m oi60
  ON oi60.venue_instrument_version_id = vi.venue_instrument_version_id
 AND oi60.bucket_at = l.cycle_at - interval '60 minutes'
LEFT JOIN candle_1m c0
  ON c0.venue_instrument_version_id = vi.venue_instrument_version_id
 AND c0.bucket_at = %s::timestamptz - interval '1 minute'
LEFT JOIN candle_1m c15
  ON c15.venue_instrument_version_id = vi.venue_instrument_version_id
 AND c15.bucket_at = %s::timestamptz - interval '16 minutes'
LEFT JOIN candle_1m c60
  ON c60.venue_instrument_version_id = vi.venue_instrument_version_id
 AND c60.bucket_at = %s::timestamptz - interval '61 minutes'
LEFT JOIN candle_1m c1440
  ON c1440.venue_instrument_version_id = vi.venue_instrument_version_id
 AND c1440.bucket_at = %s::timestamptz - interval '1441 minutes'
WHERE vi.valid_to IS NULL AND vi.active = true
ORDER BY vi.venue, vi.source_symbol
"""


def read_market_metrics(connection: Connection[Any], *, now: datetime) -> MarketMetricsArtifact:
    cutoff = candle_cutoff(now)
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(METRICS_SQL, (cutoff,) * 4).fetchall()
        artifact = build_market_metrics(rows, now=now)
    return artifact


def _metrics_snapshot(path: Path) -> tuple[bytes, tuple[int, ...]] | None:
    """Read only a stable regular file; permission errors are not corruption."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("metrics target is not a regular file")
        content = handle.read()
        after = os.fstat(handle.fileno())

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    if identity(before) != identity(after) or identity(after) != identity(path.lstat()):
        raise ValueError("metrics changed during read")
    return content, identity(after)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_market_metrics(database_url: str, artifact_root: Path, *, now: datetime) -> int:
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = artifact_root / "market-metrics.json"
    # Keep the lock inode: unlinking it would allow two independent lock owners.
    descriptor = os.open(
        artifact_root / ".market-metrics.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = _metrics_snapshot(path)
        old = None
        corrupt = False
        if previous is not None:
            try:
                decoded = json.loads(previous[0])
            except (json.JSONDecodeError, UnicodeDecodeError):
                corrupt = True
            else:
                if (
                    not isinstance(decoded, dict)
                    or type(decoded.get("schemaVersion")) is not int
                    or decoded["schemaVersion"] != 1
                    or decoded.get("metricVersion", METRIC_VERSION) != METRIC_VERSION
                ):
                    raise ValueError("unknown metrics schema")
                try:
                    old = MarketMetricsArtifact.model_validate(decoded)
                except ValidationError:
                    corrupt = True
        with psycopg.connect(
            database_url, connect_timeout=2, options=READ_OPTIONS, autocommit=True
        ) as connection:
            artifact = read_market_metrics(connection, now=now)
        if old is not None and old.candle_cutoff > artifact.candle_cutoff:
            return len(old.rows)
        staged = artifact_root / f".market-metrics.{uuid4().hex}.pending"
        try:
            write_artifact_atomic(staged, artifact)
            if _metrics_snapshot(path) != previous:
                raise ValueError("metrics changed during projection")
            if corrupt and previous is not None:
                backup = artifact_root / f"market-metrics.json.corrupt-{uuid4().hex}"
                with backup.open("xb") as handle:
                    handle.write(previous[0])
                    handle.flush()
                    os.fsync(handle.fileno())
                _sync_directory(artifact_root)
                if backup.read_bytes() != previous[0]:
                    raise ValueError("metrics preservation failed")
            if _metrics_snapshot(path) != previous:
                raise ValueError("metrics changed before publication")
            os.replace(staged, path)
            _sync_directory(artifact_root)
        finally:
            staged.unlink(missing_ok=True)
        return len(artifact.rows)


def publish_market_metrics_bounded(database_url: str, artifact_root: Path, *, now: datetime) -> int:
    """Bound the entire optional projection, including filesystem work.

    A timed-out thread cannot release its connection/lock safely. The short-lived
    child owns both; subprocess.run kills and reaps it before another run starts.
    Credentials travel on stdin, never in command-line arguments or error output.
    """
    result = subprocess.run(
        [sys.executable, "-m", "prep_watchdeck_market.market_metrics"],
        input=json.dumps(
            {"database_url": database_url, "root": str(artifact_root), "now": now.isoformat()}
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=PROJECTION_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("metrics projection failed")
    return int(result.stdout)


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        count = publish_market_metrics(
            request["database_url"],
            Path(request["root"]),
            now=datetime.fromisoformat(request["now"]),
        )
        print(count)
    except Exception:
        sys.exit(1)
