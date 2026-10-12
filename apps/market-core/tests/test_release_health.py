import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/verify-release-health.py"
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


def checker() -> dict:
    try:
        return runpy.run_path(str(SCRIPT))
    except FileNotFoundError:
        pytest.fail("functional release verification is missing")


def state() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "l1": {
            "status": "ready",
            "errorCode": None,
            "latestAt": (NOW - timedelta(seconds=20)).isoformat(),
            "maxAgeSeconds": 120,
        },
        "collectors": [
            {
                "runKind": "l1",
                "status": "succeeded",
                "errorCode": None,
                "startedAt": (NOW - timedelta(seconds=21)).isoformat(),
                "completedAt": (NOW - timedelta(seconds=19)).isoformat(),
                "recordsWritten": 37,
            }
        ],
    }


@pytest.mark.parametrize("condition", ["healthy", "failed", "unavailable", "old_cycle"])
def test_publication_requires_a_fresh_successful_l1_cycle(condition: str) -> None:
    artifact = state()
    if condition == "failed":
        artifact["collectors"][0]["status"] = "failed"
    elif condition == "unavailable":
        artifact["l1"]["status"] = "unavailable"
    elif condition == "old_cycle":
        artifact["collectors"][0]["startedAt"] = (NOW - timedelta(minutes=5)).isoformat()
    errors = checker()["publication_blockers"](artifact, after=NOW - timedelta(seconds=30), now=NOW)
    assert bool(errors) is (condition != "healthy")


def test_reload_of_config_does_not_prove_pid_source_changed() -> None:
    verify = checker()["binding_blockers"]
    release = Path("/isolated/releases/new")
    props = {
        "ActiveState": "active",
        "SubState": "running",
        "WorkingDirectory": str(release / "apps/market-core"),
        "MainPID": "37",
    }
    assert (
        verify(
            "prep-watchdeck-market.service",
            props,
            release=release,
            process_cwd=release / "apps/market-core",
            argv=[str(release / ".venv/bin/watchdeck-market"), "service"],
        )
        == []
    )
    errors = verify(
        "prep-watchdeck-market.service",
        props,
        release=release,
        process_cwd=Path("/isolated/releases/old/apps/market-core"),
        argv=["/isolated/releases/old/.venv/bin/watchdeck-market", "service"],
    )
    assert "process_source_mismatch" in errors


@pytest.mark.parametrize("field", ["l1", "collectors"])
def test_invalid_publication_is_reported_as_a_blocker(field: str) -> None:
    artifact = state()
    artifact[field] = None
    assert "market_publication_invalid" in checker()["publication_blockers"](
        artifact, after=NOW - timedelta(seconds=30), now=NOW
    )
