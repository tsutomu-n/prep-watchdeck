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
