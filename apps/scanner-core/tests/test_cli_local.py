from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from prep_watchdeck.adapters.fixture import FixtureProvider
from prep_watchdeck.application.run_cycle import run_scan_cycle
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.source_mode import SourceMode
from prep_watchdeck.interfaces.cli import app
from prep_watchdeck.models import CandleBar
from prep_watchdeck.ports.snapshot_cache import SnapshotCache
from prep_watchdeck.ports.snapshot_writer import SnapshotWriter

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_status_reports_effective_state_paths(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("PREP_WATCHDECK_STATE_DIR", str(state_dir))

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "watchdeck scanner-core is ready" in result.output
    assert f"stateDir={state_dir}" in result.output
    assert f"snapshotPath={state_dir / 'snapshots' / 'latest.json'}" in result.output
    assert f"databasePath={state_dir / 'watchdeck.duckdb'}" in result.output


def test_status_resolves_relative_state_dir_from_repo_root(monkeypatch) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_STATE_DIR", "tmp/relative-state")
    state_dir = REPO_ROOT / "tmp/relative-state"

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert f"stateDir={state_dir}" in result.output
    assert f"snapshotPath={state_dir / 'snapshots' / 'latest.json'}" in result.output
    assert f"databasePath={state_dir / 'watchdeck.duckdb'}" in result.output


def test_show_uses_state_dir_snapshot_by_default(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    snapshot_dir = state_dir / "snapshots"
    snapshot_dir.mkdir(parents=True)
    state_snapshot = Path("../../fixtures/snapshots/basic.json").read_text(encoding="utf-8")
    snapshot_dir.joinpath("latest.json").write_text(
        state_snapshot.replace("ALTUSDT", "STATEONLYUSDT"),
        encoding="utf-8",
    )
    monkeypatch.setenv("PREP_WATCHDECK_STATE_DIR", str(state_dir))

    result = runner.invoke(app, ["show"])

    assert result.exit_code == 0
    assert "STATEONLYUSDT" in result.output


def test_scan_fixture_and_cache(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "snapshots"
    cache_db = tmp_path / "watchdeck.duckdb"
    monkeypatch.setenv("PREP_WATCHDECK_OUT_DIR", str(out_dir))
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(cache_db))
    monkeypatch.setenv("PREP_WATCHDECK_FIXTURES_DIR", str(Path("../../fixtures")))

    missing_cache_result = runner.invoke(
        app, ["scan", "--source", "cache", "--template", "balanced"]
    )
    assert missing_cache_result.exit_code == 2
    assert "cache snapshot not found" in missing_cache_result.output

    fixture_result = runner.invoke(
        app,
        ["scan", "--source", "fixture", "--fixture-set", "basic", "--template", "balanced"],
    )
    assert fixture_result.exit_code == 0
    latest = out_dir / "latest.json"
    assert latest.exists()
    assert json.loads(latest.read_text())["source"]["dataSource"] == "fixture"

    cache_result = runner.invoke(app, ["scan", "--source", "cache", "--template", "balanced"])
    assert cache_result.exit_code == 0
    assert json.loads(latest.read_text())["source"]["dataSource"] == "cache"

    show_result = runner.invoke(app, ["show", "--source-file", str(latest)])
    assert show_result.exit_code == 0
    assert "ALTUSDT" in show_result.output


def test_scan_reports_locked_cache(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "snapshots"
    cache_db = tmp_path / "watchdeck.duckdb"
    monkeypatch.setenv("PREP_WATCHDECK_OUT_DIR", str(out_dir))
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(cache_db))
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_LOCK_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_LOCK_RETRY_INTERVAL_SECONDS", "0.001")
    monkeypatch.setenv("PREP_WATCHDECK_FIXTURES_DIR", str(Path("../../fixtures")))

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import duckdb, sys, time; "
                "con = duckdb.connect(sys.argv[1]); "
                "con.execute('CREATE TABLE lock_holder (id INTEGER)'); "
                "print('ready', flush=True); "
                "time.sleep(10)"
            ),
            str(cache_db),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        result = runner.invoke(
            app,
            ["scan", "--source", "fixture", "--fixture-set", "basic", "--template", "balanced"],
        )
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert result.exit_code == 3
    assert "cache locked" in result.output
    assert "another watchdeck process" in result.output


def test_export_schema(tmp_path) -> None:
    out = tmp_path / "scanner-snapshot.schema.json"
    result = runner.invoke(app, ["export-schema", "--out", str(out)])
    assert result.exit_code == 0
    payload = json.loads(out.read_text())
    assert payload["title"] == "PrepWatchdeck ScannerSnapshot"
    assert "properties" in payload


def test_auto_falls_back_to_cache_when_live_unavailable() -> None:
    fixture_provider = FixtureProvider(Path("../../fixtures"))
    cached_snapshot = fixture_provider.build_snapshot(template="balanced", fixture_set="basic")

    class UnavailableLiveProvider:
        def build_snapshot(self, *, template: str, fixture_set: str | None = None):
            raise NotImplementedError("live unavailable")

    class CacheProvider:
        def build_snapshot(self, *, template: str, fixture_set: str | None = None):
            return cached_snapshot

    class MemoryCache(SnapshotCache):
        def __init__(self) -> None:
            self.snapshot = None

        def save(self, snapshot) -> None:
            self.snapshot = snapshot

        def save_candles_5m(self, candles_by_symbol: dict[str, list[CandleBar]]) -> None:
            _ = candles_by_symbol

        def latest(self):
            return self.snapshot

    class MemoryWriter(SnapshotWriter):
        def __init__(self) -> None:
            self.snapshot = None

        def write(self, snapshot) -> None:
            self.snapshot = snapshot

    writer = MemoryWriter()
    snapshot = run_scan_cycle(
        source=SourceMode.AUTO,
        template="balanced",
        fixture_set=None,
        providers={
            DataSource.LIVE: UnavailableLiveProvider(),
            DataSource.CACHE: CacheProvider(),
            DataSource.FIXTURE: fixture_provider,
        },
        writer=writer,
        cache=MemoryCache(),
    )

    assert snapshot.source.data_source == "fixture"
    assert writer.snapshot == snapshot
