import json
import runpy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[3]
PROJECTION = runpy.run_path(str(PROJECT / "scripts/ops/check-runtime-capacity.py"))[
    "capacity_projection"
]


@pytest.mark.parametrize("escape", ["traversal", "symlink"])
def test_capacity_rejects_output_escape_before_writing(tmp_path, monkeypatch, escape):
    roots = {core: tmp_path / core for core in ("market", "ranking", "attention")}
    for root in roots.values():
        root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if escape == "traversal":
        output = outside / ".." / "market" / "unexpected.json"
    else:
        (outside / "linked").symlink_to(roots["market"], target_is_directory=True)
        output = outside / "linked" / "unexpected.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capacity",
            *[arg for core, root in roots.items() for arg in (f"--{core}-state", str(root))],
            "--output",
            str(output),
        ],
    )
    main = runpy.run_path(str(PROJECT / "scripts/ops/check-runtime-capacity.py"))["main"]
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2
    assert not (roots["market"] / "unexpected.json").exists()


def test_capacity_cannot_forecast_without_postgres_and_external_archive():
    first = {
        "sampledAt": "2026-10-10T00:00:00+00:00",
        "measurementCoverage": "complete",
        "filesystemAvailableBytes": 200 * 1024**3,
        "stateBytes": {
            core: {"root": f"/isolated/{core}", "knownBytes": 100}
            for core in ("market", "ranking", "attention")
        },
    }
    last = {**first, "sampledAt": "2026-10-11T00:00:00+00:00"}
    report = PROJECTION([first, last])
    assert report["status"] == "not_validated"
    assert report["scope"] == "diagnostic_only"
    assert report["reason"] == "incomplete_measurement_scope"


def test_legacy_capacity_call_keeps_unmeasured_export_unknown(tmp_path, monkeypatch):
    arguments = ["capacity"]
    for core in ("market", "ranking", "attention"):
        root = tmp_path / core
        root.mkdir()
        arguments.extend([f"--{core}-state", str(root)])
    output = tmp_path / "capacity.json"
    monkeypatch.setattr(sys, "argv", [*arguments, "--output", str(output)])
    main = runpy.run_path(str(PROJECT / "scripts/ops/check-runtime-capacity.py"))["main"]
    assert main() == 0
    result = json.loads(output.read_text())
    assert result["measurementCoverage"] == "partial"
    assert result["missingScopes"] == ["outcome_archive", "postgres"]
    assert result["stagingCoverage"] == "partial"
    assert result["stagingBytesByKind"]["export"] is None
    assert result["stagingBytes"] is None
    assert result["projection"]["scope"] == "diagnostic_only"


@pytest.mark.parametrize("condition", ["short", "missing", "unknown", "valid"])
def test_capacity_projection_requires_valid_sample_period(condition: str) -> None:
    start = datetime(2026, 10, 11, tzinfo=UTC)
    first = {
        "sampledAt": start.isoformat(),
        "measurementCoverage": "complete",
        "filesystemAvailableBytes": 200 * 1024**3,
        "stagingCoverage": "complete",
        "filesystemDevice": 1,
        "stateBytes": {
            **{
                core: {"root": f"/isolated/{core}", "knownBytes": 100}
                for core in ("market", "ranking", "postgres", "outcome_archive")
            },
            "attention": {"root": "/isolated/attention", "knownBytes": 1024**3},
        },
    }
    last = {
        **first,
        "sampledAt": (start + timedelta(hours=24)).isoformat(),
        "stateBytes": {
            **first["stateBytes"],
            "attention": {"root": "/isolated/attention", "knownBytes": 2 * 1024**3},
        },
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


@pytest.mark.parametrize("receipt", ["valid", "stale", "wrong_device"])
def test_capacity_supplement_is_bound_and_nested_postgres_is_counted_once(
    tmp_path, monkeypatch, receipt
):
    roots = {core: tmp_path / core for core in ("market", "ranking", "attention")}
    for root in roots.values():
        root.mkdir()
    postgres = roots["market"] / "postgres"
    archive = tmp_path / "outcome-archive"
    postgres.mkdir()
    archive.mkdir()
    (roots["market"] / "observed.json").write_bytes(b"abc")
    (postgres / "physical").write_bytes(b"abcde")
    (roots["ranking"] / "ranking.sqlite3").write_bytes(b"abcd")
    (roots["attention"] / "attention.sqlite3").write_bytes(b"abcdefgh")
    (archive / "outcomes.json").write_bytes(b"abcdefghi")
    sampled = datetime.now(UTC) - timedelta(seconds=120 if receipt == "stale" else 1)
    supplement = tmp_path / "supplement.json"
    supplement.write_text(
        json.dumps(
            {
                "schemaVersion": "runtime-capacity-supplement-v1",
                "sampledAt": sampled.isoformat(),
                "filesystemDevice": roots["market"].stat().st_dev + (receipt == "wrong_device"),
                "measurements": {
                    "postgres": {"root": str(postgres), "knownBytes": 5, "complete": True}
                },
            }
        )
    )
    output = tmp_path / "capacity.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capacity",
            *[arg for core, root in roots.items() for arg in (f"--{core}-state", str(root))],
            "--postgres-root",
            str(postgres),
            "--outcome-archive",
            str(archive),
            "--trusted-supplement",
            str(supplement),
            "--export-staging-bytes",
            "11",
            "--staging-bytes",
            "100",
            "--output",
            str(output),
        ],
    )
    main = runpy.run_path(str(PROJECT / "scripts/ops/check-runtime-capacity.py"))["main"]
    if receipt != "valid":
        with pytest.raises(SystemExit) as failure:
            main()
        assert failure.value.code == 2
        assert not output.exists()
        return
    assert main() == 0
    result = json.loads(output.read_text())
    assert result["measurementCoverage"] == "complete"
    assert result["stateBytes"]["market"]["knownBytes"] == 3
    assert result["stateBytes"]["postgres"]["knownBytes"] == 5
    assert sum(value["knownBytes"] for value in result["stateBytes"].values()) == 29
    assert result["stagingBytes"] == 100
    assert result["stagingBytesByKind"] == {
        "copy": 12,
        "export": 11,
        "restore": 17,
        "additionalReserve": 60,
    }
    assert result["projection"]["status"] == "not_validated"


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
