from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import polars as pl
import psycopg
from psycopg import Connection
from pydantic import ValidationError

from prep_watchdeck_market.archive import (
    ArchiveDataset,
    _fetch_partition,
    _PartitionRows,
)
from prep_watchdeck_market.config import Settings
from prep_watchdeck_market.models import Venue

SECONDS_PER_DAY = 86_400
PROJECTION_SAFETY_FACTOR = 1.25
DATASETS: tuple[ArchiveDataset, ...] = (
    "market_state_1m",
    "candle_1m",
    "funding_events",
)
VENUES: tuple[Venue, ...] = ("bitget", "hyperliquid", "aster")


class CapacitySampleError(RuntimeError):
    """A read-only capacity sample could not be produced safely."""


@dataclass(frozen=True, slots=True)
class PartitionProjection:
    dataset: ArchiveDataset
    venue: Venue
    rowCount: int
    parquetBytes: int
    sampleElapsedSeconds: float
    projectedRowsPerDay: int
    projectedParquetBytesPerDay: int
    status: str


def project_partition_sample(
    *,
    dataset: ArchiveDataset,
    venue: Venue,
    row_count: int,
    parquet_bytes: int,
    elapsed_seconds: float,
    safety_factor: float = PROJECTION_SAFETY_FACTOR,
) -> PartitionProjection:
    """Project one partial UTC-day Parquet sample with a fixed safety margin."""

    if row_count < 0 or parquet_bytes < 0:
        raise ValueError("sample counts must be non-negative")
    if elapsed_seconds <= 0 or safety_factor < 1:
        raise ValueError("projection inputs are invalid")
    if row_count == 0:
        return PartitionProjection(
            dataset=dataset,
            venue=venue,
            rowCount=0,
            parquetBytes=0,
            sampleElapsedSeconds=elapsed_seconds,
            projectedRowsPerDay=0,
            projectedParquetBytesPerDay=0,
            status=("optional_no_rows" if dataset == "funding_events" else "insufficient_data"),
        )
    if parquet_bytes <= 0:
        raise ValueError("a non-empty sample must have Parquet bytes")

    bounded_elapsed = min(elapsed_seconds, float(SECONDS_PER_DAY))
    scale = (SECONDS_PER_DAY / bounded_elapsed) * safety_factor
    return PartitionProjection(
        dataset=dataset,
        venue=venue,
        rowCount=row_count,
        parquetBytes=parquet_bytes,
        sampleElapsedSeconds=elapsed_seconds,
        projectedRowsPerDay=math.ceil(row_count * scale),
        projectedParquetBytesPerDay=math.ceil(parquet_bytes * scale),
        status="projected",
    )


def sample_capacity(
    connection: Connection[Any],
    temporary_root: Path,
    *,
    sampled_at: datetime,
) -> dict[str, Any]:
    """Read today's normalized rows and measure production-shaped temporary Parquet files."""

    sampled_at = _as_utc(sampled_at)
    _require_read_only(connection)
    sample_date = sampled_at.date()
    day_start = datetime.combine(sample_date, time.min, tzinfo=UTC)
    temporary_root.mkdir(parents=True, exist_ok=True)

    projections: list[PartitionProjection] = []
    with TemporaryDirectory(prefix="watchdeck-capacity-", dir=temporary_root) as directory:
        sample_root = Path(directory)
        for dataset in DATASETS:
            for venue in VENUES:
                partition = _fetch_partition(connection, dataset, venue, sample_date)
                elapsed_seconds = _partition_elapsed_seconds(
                    partition,
                    sampled_at=sampled_at,
                    day_start=day_start,
                )
                parquet_bytes = _write_temporary_parquet(
                    partition,
                    sample_root / f"{dataset}-{venue}.parquet",
                )
                projections.append(
                    project_partition_sample(
                        dataset=dataset,
                        venue=venue,
                        row_count=len(partition.rows),
                        parquet_bytes=parquet_bytes,
                        elapsed_seconds=elapsed_seconds,
                    )
                )

    projected_bytes = sum(item.projectedParquetBytesPerDay for item in projections)
    required_missing = [
        f"{item.dataset}:{item.venue}"
        for item in projections
        if item.dataset != "funding_events" and item.status != "projected"
    ]
    optional_empty = [
        f"{item.dataset}:{item.venue}"
        for item in projections
        if item.dataset == "funding_events" and item.status == "optional_no_rows"
    ]
    return {
        "schemaVersion": 1,
        "sampledAt": sampled_at.isoformat().replace("+00:00", "Z"),
        "sampleDate": sample_date.isoformat(),
        "compression": "zstd",
        "safetyFactor": PROJECTION_SAFETY_FACTOR,
        "projectionComplete": not required_missing,
        "requiredMissingPartitions": required_missing,
        "optionalEmptyPartitions": optional_empty,
        "observedRows": sum(item.rowCount for item in projections),
        "observedParquetBytes": sum(item.parquetBytes for item in projections),
        "projectedParquetBytesPerDay": projected_bytes,
        "projectedParquetGbPerDay": projected_bytes / 1_000_000_000,
        "partitions": [asdict(item) for item in projections],
    }


def _write_temporary_parquet(partition: _PartitionRows, path: Path) -> int:
    if not partition.rows:
        return 0
    frame = pl.DataFrame(
        partition.rows,
        schema=list(partition.columns),
        orient="row",
        strict=False,
    )
    frame.write_parquet(path, compression="zstd", statistics=True)
    readback = pl.read_parquet(path)
    if readback.columns != list(partition.columns) or readback.height != len(partition.rows):
        raise CapacitySampleError("temporary Parquet schema or row count mismatch")
    return path.stat().st_size


def _partition_elapsed_seconds(
    partition: _PartitionRows,
    *,
    sampled_at: datetime,
    day_start: datetime,
) -> float:
    if not partition.rows:
        return max(1.0, (sampled_at - day_start).total_seconds())
    timestamp_index = partition.columns.index(partition.timestamp_column)
    first_timestamp = min(_as_utc(row[timestamp_index]) for row in partition.rows)
    observation_start = max(day_start, first_timestamp)
    return max(1.0, (sampled_at - observation_start).total_seconds())


def _require_read_only(connection: Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        row = cursor.fetchone()
    if row is None or str(row[0]).lower() != "on":
        raise CapacitySampleError("capacity sampling requires a read-only database session")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("sample timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure today's production-shaped Parquet footprint without DB writes."
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Indent the JSON report for human-readable evidence.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        settings = Settings()
        temporary_root = settings.state_dir / "tmp"
        with psycopg.connect(
            settings.database_url,
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
        ) as connection:
            report = sample_capacity(
                connection,
                temporary_root,
                sampled_at=datetime.now(UTC),
            )
    except (
        CapacitySampleError,
        OSError,
        ValueError,
        ValidationError,
        pl.exceptions.PolarsError,
        psycopg.Error,
    ) as error:
        print(f"capacity sample failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
