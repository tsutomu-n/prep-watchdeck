from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from prep_watchdeck.adapters.duckdb import DuckDbSnapshotCache
from prep_watchdeck.adapters.fixture import FixtureProvider
from prep_watchdeck.application.rekindle import detect_rekindle_notes
from prep_watchdeck.application.run_cycle import run_scan_cycle
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.enums import DataSource
from prep_watchdeck.domain.source_mode import SourceMode
from prep_watchdeck.interfaces.cli import app
from prep_watchdeck.models import CandleBar
from prep_watchdeck.storage.past_notes import PastNoteRepository

runner = CliRunner()

FIVE_MINUTES_MS = 300_000
DAY_MS = 24 * 60 * 60 * 1000


def test_live_scan_persists_provider_candles(tmp_path: Path) -> None:
    cache = DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb")
    writer = MemoryWriter()
    provider = LiveProvider(
        snapshot=live_snapshot(),
        candles_by_symbol={"ALTUSDT": event_bars("ALTUSDT", now_ms=1_781_000_000_000)},
    )

    run_scan_cycle(
        source=SourceMode.LIVE,
        template="balanced",
        fixture_set=None,
        providers={
            DataSource.LIVE: provider,
            DataSource.CACHE: provider,
            DataSource.FIXTURE: provider,
        },
        writer=writer,
        cache=cache,
    )

    loaded = cache.load_candles_5m(["ALTUSDT"])

    assert len(loaded["ALTUSDT"]) == 60
    assert loaded["ALTUSDT"][-1].close == Decimal("1.0900")


def test_detect_rekindle_notes_writes_auto_note_and_skips_no_trade(tmp_path: Path) -> None:
    now_ms = 1_781_000_000_000
    cache = DuckDbSnapshotCache(tmp_path / "watchdeck.duckdb")
    cache.save(
        FixtureProvider(Path("../../fixtures")).build_snapshot(
            template="balanced", fixture_set="basic"
        )
    )
    cache.save_candles_5m(
        {
            "ALTUSDT": event_bars("ALTUSDT", now_ms=now_ms),
            "THINUSDT": event_bars("THINUSDT", now_ms=now_ms),
        }
    )
    repo = PastNoteRepository(tmp_path / "past-notes")

    result = detect_rekindle_notes(cache=cache, past_notes=repo, now_ms=now_ms)

    assert result.written_count == 1
    payload = json.loads((tmp_path / "past-notes" / "current.json").read_text())
    assert [note["symbol"] for note in payload["notes"]] == ["ALTUSDT"]
    assert payload["notes"][0]["reason"] == "自動検出: 過去急変"
    assert "4h変化率=+9.0%" in payload["notes"][0]["note"]
    assert "4h売買代金=336,000 USDT" in payload["notes"][0]["note"]


def test_past_note_repository_archives_expired_notes(tmp_path: Path) -> None:
    root = tmp_path / "past-notes"
    root.mkdir()
    (root / "current.json").write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "symbol": "OLDUSDT",
                        "reason": "old move",
                        "observedAt": "2026-03-01T00:00:00.000Z",
                        "expiresAt": "2026-05-01T00:00:00.000Z",
                        "note": "archive me",
                    },
                    {
                        "symbol": "ALTUSDT",
                        "reason": "manual",
                        "observedAt": "2026-06-20T00:00:00.000Z",
                        "expiresAt": "2026-08-19T00:00:00.000Z",
                        "note": "keep me",
                    },
                ]
            }
        )
        + "\n"
    )
    repo = PastNoteRepository(root)

    active = repo.save_many([], now_ms=1_781_000_000_000)

    assert [note.symbol for note in active] == ["ALTUSDT"]
    archive = json.loads((root / "archive" / "2026-03" / "past-notes-2026-03.json").read_text())
    assert [note["symbol"] for note in archive["notes"]] == ["OLDUSDT"]


def test_detect_rekindle_cli_writes_current_json(tmp_path: Path, monkeypatch) -> None:
    now_ms = 1_781_000_000_000
    cache_db = tmp_path / "watchdeck.duckdb"
    past_notes_dir = tmp_path / "past-notes"
    cache = DuckDbSnapshotCache(cache_db)
    cache.save(
        FixtureProvider(Path("../../fixtures")).build_snapshot(
            template="balanced", fixture_set="basic"
        )
    )
    cache.save_candles_5m({"ALTUSDT": event_bars("ALTUSDT", now_ms=now_ms)})
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(cache_db))
    monkeypatch.setenv("PREP_WATCHDECK_PAST_NOTES_DIR", str(past_notes_dir))

    result = runner.invoke(app, ["detect-rekindle", "--now-ms", str(now_ms)])

    assert result.exit_code == 0
    assert "1件" in result.output
    assert (past_notes_dir / "current.json").exists()


def test_detect_rekindle_cli_exits_zero_with_no_history(tmp_path: Path, monkeypatch) -> None:
    now_ms = 1_781_000_000_000
    cache_db = tmp_path / "watchdeck.duckdb"
    cache = DuckDbSnapshotCache(cache_db)
    cache.save(
        FixtureProvider(Path("../../fixtures")).build_snapshot(
            template="balanced", fixture_set="basic"
        )
    )
    monkeypatch.setenv("PREP_WATCHDECK_CACHE_DB_PATH", str(cache_db))
    monkeypatch.setenv("PREP_WATCHDECK_PAST_NOTES_DIR", str(tmp_path / "past-notes"))

    result = runner.invoke(app, ["detect-rekindle", "--now-ms", str(now_ms)])

    assert result.exit_code == 0
    assert "0件" in result.output


class MemoryWriter:
    def __init__(self) -> None:
        self.snapshot: SnapshotDTO | None = None

    def write(self, snapshot: SnapshotDTO) -> None:
        self.snapshot = snapshot


class LiveProvider:
    def __init__(
        self, snapshot: SnapshotDTO, candles_by_symbol: dict[str, list[CandleBar]]
    ) -> None:
        self.snapshot = snapshot
        self.latest_candles_by_symbol = candles_by_symbol

    def build_snapshot(self, *, template: str, fixture_set: str | None = None) -> SnapshotDTO:
        _ = template
        _ = fixture_set
        return self.snapshot


def live_snapshot() -> SnapshotDTO:
    snapshot = FixtureProvider(Path("../../fixtures")).build_snapshot(
        template="balanced", fixture_set="basic"
    )
    payload = snapshot.model_dump(by_alias=True)
    payload["source"]["dataSource"] = DataSource.LIVE.value
    payload["source"]["fixtureSet"] = None
    return SnapshotDTO.model_validate(payload)


def event_bars(symbol: str, *, now_ms: int) -> list[CandleBar]:
    start = now_ms - 10 * DAY_MS
    bars = []
    for index in range(60):
        close = Decimal("1.0000")
        if index >= 48:
            close = Decimal("1.0900")
        bars.append(
            CandleBar(
                symbol=symbol,
                ts=start + index * FIVE_MINUTES_MS,
                open=close,
                high=close * Decimal("1.01"),
                low=close * Decimal("0.99"),
                close=close,
                base_vol=Decimal("100"),
                quote_vol=Decimal("7000"),
            )
        )
    return bars
