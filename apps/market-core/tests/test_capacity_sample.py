from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from prep_watchdeck_market.archive import _PartitionRows
from prep_watchdeck_market.capacity_sample import (
    _partition_elapsed_seconds,
    _write_temporary_parquet,
    project_partition_sample,
)


def test_capacity_projection_is_buffered_and_empty_samples_fail_closed(tmp_path: Path) -> None:
    projection = project_partition_sample(
        dataset="market_state_1m",
        venue="bitget",
        row_count=100,
        parquet_bytes=1_000,
        elapsed_seconds=21_600,
    )

    assert projection.projectedRowsPerDay == 500
    assert projection.projectedParquetBytesPerDay == 5_000
    assert projection.sampleElapsedSeconds == 21_600
    assert projection.status == "projected"

    empty = project_partition_sample(
        dataset="funding_events",
        venue="aster",
        row_count=0,
        parquet_bytes=0,
        elapsed_seconds=3_600,
    )
    assert empty.projectedParquetBytesPerDay == 0
    assert empty.status == "optional_no_rows"

    missing_required = project_partition_sample(
        dataset="candle_1m",
        venue="aster",
        row_count=0,
        parquet_bytes=0,
        elapsed_seconds=3_600,
    )
    assert missing_required.status == "insufficient_data"

    partition = _PartitionRows(
        columns=("venue_instrument_version_id", "venue", "bucket_at", "mark_price"),
        unique_key_columns=("venue_instrument_version_id", "bucket_at"),
        timestamp_column="bucket_at",
        rows=((1, "bitget", datetime(2026, 8, 14, tzinfo=UTC), Decimal("100.5")),),
    )
    path = tmp_path / "sample.parquet"
    assert _write_temporary_parquet(partition, path) > 0
    assert pl.read_parquet(path).columns == list(partition.columns)

    fresh_shadow_partition = _PartitionRows(
        columns=partition.columns,
        unique_key_columns=partition.unique_key_columns,
        timestamp_column=partition.timestamp_column,
        rows=((1, "bitget", datetime(2026, 8, 14, 22, 0, tzinfo=UTC), Decimal("100.5")),),
    )
    assert (
        _partition_elapsed_seconds(
            fresh_shadow_partition,
            sampled_at=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
            day_start=datetime(2026, 8, 14, tzinfo=UTC),
        )
        == 3_600
    )

    with pytest.raises(ValueError, match="non-empty sample"):
        project_partition_sample(
            dataset="candle_1m",
            venue="hyperliquid",
            row_count=1,
            parquet_bytes=0,
            elapsed_seconds=60,
        )
