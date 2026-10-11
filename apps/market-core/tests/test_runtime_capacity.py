import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[3]
PROJECTION = runpy.run_path(str(PROJECT / "scripts/ops/check-runtime-capacity.py"))[
    "capacity_projection"
]


@pytest.mark.parametrize("condition", ["short", "missing", "unknown", "valid"])
def test_capacity_projection_requires_valid_sample_period(condition: str) -> None:
    start = datetime(2026, 10, 11, tzinfo=UTC)
    first = {
        "sampledAt": start.isoformat(),
        "measurementCoverage": "complete",
        "filesystemAvailableBytes": 200 * 1024**3,
        "stateBytes": {"attention": {"root": "/isolated/attention", "knownBytes": 1024**3}},
    }
    last = {
        **first,
        "sampledAt": (start + timedelta(hours=24)).isoformat(),
        "stateBytes": {"attention": {"root": "/isolated/attention", "knownBytes": 2 * 1024**3}},
    }
    if condition == "short":
        last["sampledAt"] = (start + timedelta(minutes=15)).isoformat()
    if condition == "unknown":
        last["measurementCoverage"] = "partial"
    report = PROJECTION([first] if condition == "missing" else [first, last])
    assert report["status"] == ("forecast" if condition == "valid" else "not_validated")
    if condition == "valid":
        assert report["projectedGrowthBytes"] == 30 * 1024**3
        assert report["scope"] == "forecast_not_30day_measurement"


def test_timed_out_copy_keeps_source_and_can_retry(tmp_path: Path) -> None:
    import sqlite3
    import time

    backup = runpy.run_path(str(PROJECT / "scripts/ops/copy-runtime-evidence.py"))["online_backup"]
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "copy.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE observations (value INTEGER)")
        connection.execute("INSERT INTO observations VALUES (37)")
    original = source.read_bytes()
    with pytest.raises(TimeoutError):
        backup(source, destination, time.monotonic() - 1)
    assert source.read_bytes() == original
    assert not destination.exists()
    backup(source, destination, time.monotonic() + 5)
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM observations").fetchone() == (37,)


def test_copy_rejects_parent_traversal_before_creating_live_output(tmp_path: Path) -> None:
    copy = runpy.run_path(str(PROJECT / "scripts/ops/copy-runtime-evidence.py"))[
        "copy_runtime_evidence"
    ]
    ranking, attention, archive = (tmp_path / name for name in ("ranking", "attention", "archive"))
    for path in (ranking, attention, archive):
        path.mkdir()
    with pytest.raises(ValueError):
        copy(ranking, attention, archive / ".." / "ranking" / "unexpected")
    assert not (ranking / "unexpected").exists()
