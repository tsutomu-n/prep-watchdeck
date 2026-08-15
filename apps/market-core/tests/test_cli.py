from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

from typer.testing import CliRunner

from prep_watchdeck_market.cli import app
from prep_watchdeck_market.config import Settings
from prep_watchdeck_market.database import DatabaseError, DatabaseHealth, MigrationResult
from prep_watchdeck_market.maintenance import MaintenanceResult
from prep_watchdeck_market.retention import RawRetentionResult, SelectedRetentionResult
from prep_watchdeck_market.runtime_lock import exclusive_runtime_lock

runner = CliRunner()
DATABASE_URL = "postgresql://prep_watchdeck_market:secret@127.0.0.1:55432/prep_watchdeck_market"


def test_settings_reads_market_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_STATE_DIR", str(tmp_path / "state"))

    settings = Settings()

    assert settings.database_url == DATABASE_URL
    assert settings.state_dir == (tmp_path / "state").resolve()


def test_migrate_status_and_health_call_database_boundary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_STATE_DIR", str(tmp_path / "state"))
    seen: list[tuple[str, str]] = []

    def fake_migrate(database_url: str) -> MigrationResult:
        seen.append(("migrate", database_url))
        return MigrationResult(applied=(1,), current_version=1, pending=0)

    def fake_check(database_url: str) -> DatabaseHealth:
        seen.append(("check", database_url))
        return DatabaseHealth(ready=True, current_version=1, latest_version=1, pending=0)

    monkeypatch.setattr("prep_watchdeck_market.cli.migrate_database", fake_migrate)
    monkeypatch.setattr("prep_watchdeck_market.cli.check_database", fake_check)

    migrate_result = runner.invoke(app, ["migrate"])
    status_result = runner.invoke(app, ["status"])
    health_result = runner.invoke(app, ["health"])

    assert migrate_result.exit_code == 0
    assert "applied=1" in migrate_result.output
    assert "currentVersion=1" in migrate_result.output
    assert status_result.exit_code == 0
    assert "database=ready" in status_result.output
    assert f"stateDir={(tmp_path / 'state').resolve()}" in status_result.output
    assert health_result.exit_code == 0
    assert "healthy" in health_result.output
    assert seen == [
        ("migrate", DATABASE_URL),
        ("check", DATABASE_URL),
        ("check", DATABASE_URL),
    ]


def test_mutating_command_requires_explicit_override_for_isolated_database(monkeypatch) -> None:
    shadow_url = "postgresql://shadow:secret@127.0.0.1:55439/shadow"
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", shadow_url)
    called = False

    def fake_migrate(_database_url: str) -> MigrationResult:
        nonlocal called
        called = True
        return MigrationResult(applied=(), current_version=4, pending=0)

    monkeypatch.setattr("prep_watchdeck_market.cli.migrate_database", fake_migrate)

    rejected = runner.invoke(app, ["migrate"])
    assert rejected.exit_code == 2
    assert not called
    assert shadow_url not in rejected.output
    assert "secret" not in rejected.output

    monkeypatch.setenv("PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET", "true")
    allowed = runner.invoke(app, ["migrate"])
    assert allowed.exit_code == 0
    assert called


def test_health_fails_closed_without_printing_database_url(monkeypatch) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", DATABASE_URL)

    def fake_check(_database_url: str) -> DatabaseHealth:
        raise DatabaseError("database unavailable")

    monkeypatch.setattr("prep_watchdeck_market.cli.check_database", fake_check)

    result = runner.invoke(app, ["health"])

    assert result.exit_code == 2
    assert "database unavailable" in result.output
    assert DATABASE_URL not in result.output
    assert "secret" not in result.output


def test_service_calls_runtime_boundary_and_stops_cleanly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", DATABASE_URL)
    state_dir = tmp_path / "service-state"
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_STATE_DIR", str(state_dir))
    seen: list[tuple[str, Path]] = []

    async def fake_service(
        database_url: str,
        effective_state_dir: Path,
        stop_event: asyncio.Event,
    ) -> None:
        seen.append((database_url, effective_state_dir))
        stop_event.set()

    monkeypatch.setattr("prep_watchdeck_market.cli.run_market_service", fake_service)

    with exclusive_runtime_lock(state_dir / "market-service.lock"):
        blocked = runner.invoke(app, ["service"])
    assert blocked.exit_code == 2
    assert "already running" in blocked.output
    assert seen == []

    result = runner.invoke(app, ["service"])
    assert result.exit_code == 0
    assert seen == [(DATABASE_URL, state_dir.resolve())]
    assert DATABASE_URL not in result.output
    assert "secret" not in result.output


def test_maintenance_uses_explicit_completed_utc_day(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("PREP_WATCHDECK_MARKET_STATE_DIR", str(tmp_path))
    seen: list[date] = []

    def fake_maintenance(
        _database_url: str,
        _state_dir: Path,
        *,
        partition_date: date,
        now: datetime,
    ) -> MaintenanceResult:
        del now
        seen.append(partition_date)
        return MaintenanceResult(
            partition_date=partition_date,
            archives=(),
            retention=(),
            raw_retention=RawRetentionResult(0, False),
            selected_retention=SelectedRetentionResult(0, 0, 0, 0, False),
        )

    monkeypatch.setattr("prep_watchdeck_market.cli.run_daily_maintenance", fake_maintenance)

    result = runner.invoke(app, ["maintenance", "--partition-date", "2026-08-13"])

    assert result.exit_code == 0
    assert seen == [date(2026, 8, 13)]
    assert "archives=0" in result.output
    assert DATABASE_URL not in result.output
