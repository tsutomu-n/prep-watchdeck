import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import CUTOFF, feature, generation

from prep_watchdeck_attention.models import MINUTE
from prep_watchdeck_attention.outcomes import FixtureBarReader, settle_generation_outcomes
from prep_watchdeck_attention.storage import AttentionStore

DAY = 1440 * MINUTE
ROOT = Path(__file__).resolve().parents[3]


def archive_module():
    spec = importlib.util.spec_from_file_location(
        "archive_outcome_day_test", ROOT / "scripts/attention/archive-outcome-day.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources(tmp_path):
    day = CUTOFF // DAY * DAY
    ranking, attention = tmp_path / "ranking", tmp_path / "attention"
    ranking.mkdir()
    store = AttentionStore(attention)
    for index in range(3):
        cutoff = day + index * DAY + MINUTE * 5
        f = feature(cutoff=cutoff)
        inputs, response = generation((f,), generation_id=str(index), cutoff=cutoff)
        store.save_generation(inputs, (f,), response, evidence=True)
    store.close()
    with sqlite3.connect(ranking / "ranking.sqlite3") as conn:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('map', ?)", ('{"version":"map"}',))
        conn.execute(
            "CREATE TABLE minute_bars (reference_key TEXT,end INTEGER,open REAL,"
            "high REAL,low REAL,close REAL,quote_turnover REAL)"
        )
        conn.executemany(
            "INSERT INTO minute_bars VALUES (?,?,?,?,?,?,?)",
            [
                ("bybit:AUSDT:rev1", day + i * MINUTE, 100, 102, 99, 100, 10)
                for i in range(3 * 1440 + 1)
            ],
        )
    return ranking, attention, day


def test_interrupted_edition_preserved_retry_and_completed_rerun(tmp_path, monkeypatch):
    module = archive_module()
    ranking, attention, day = sources(tmp_path)
    archive = tmp_path / "archive"
    monkeypatch.setattr(module.time, "time", lambda: (day + 4 * DAY) / 1000)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=2**50))
    original = module.export_outcome_input

    def interrupted(*args, **kwargs):
        output = args[2]
        output.mkdir()
        (output / "partial.json").write_text("kept")
        raise OSError("injected interruption")

    monkeypatch.setattr(module, "export_outcome_input", interrupted)
    with pytest.raises(OSError, match="injected"):
        module.archive_day(ranking, attention, archive, day_ms=day)
    partial = list(archive.rglob("partial.json"))
    assert len(partial) == 1
    monkeypatch.setattr(module, "export_outcome_input", original)
    completion = module.archive_day(ranking, attention, archive, day_ms=day)
    assert partial[0].read_text() == "kept"
    assert partial[0].parent.parent != completion.parent
    assert json.loads(completion.read_text())["status"] == "COMPLETE"
    monkeypatch.setattr(module, "export_outcome_input", interrupted)
    assert module.archive_day(ranking, attention, archive, day_ms=day) == completion
    ledger = json.loads((archive / "archive-ledger.json").read_text())
    assert ledger["days"][str(day)]["status"] == "COMPLETE"


def test_catchup_covers_missing_days_and_expiry_is_visible(tmp_path, monkeypatch):
    module = archive_module()
    ranking, attention, day = sources(tmp_path)
    archive = tmp_path / "archive"
    monkeypatch.setattr(module.time, "time", lambda: (day + 3 * DAY) / 1000)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=2**50))
    module.archive_day(ranking, attention, archive, day_ms=day + DAY)
    completed = module.archive_closed_days(ranking, attention, archive)
    assert {json.loads(path.read_text())["dayMs"] for path in completed} == {
        day,
        day + DAY,
        day + 2 * DAY,
    }
    assert module.archive_closed_days(ranking, attention, archive) == completed
    reader = FixtureBarReader.from_file(archive)
    assert (
        len(
            reader.bars(
                "bybit:AUSDT:rev1", after=day + DAY - 30 * MINUTE, through=day + DAY + 30 * MINUTE
            )
        )
        == 60
    )
    expired = tmp_path / "expired"
    with sqlite3.connect(ranking / "ranking.sqlite3") as conn:
        conn.execute("DELETE FROM minute_bars WHERE end<?", (day + DAY,))
    with pytest.raises(ValueError, match="expired"):
        module.archive_closed_days(ranking, attention, expired)
    ledger = json.loads((expired / "archive-ledger.json").read_text())
    assert ledger["days"][str(day)]["status"] == "FAILED"
    recovered = list(expired.rglob("archive-completion.json"))
    assert {json.loads(path.read_text())["dayMs"] for path in recovered} == {
        day + DAY,
        day + 2 * DAY,
    }
    assert ledger["days"][str(day + DAY)]["status"] == "COMPLETE"
    assert ledger["days"][str(day + 2 * DAY)]["status"] == "COMPLETE"


def test_first_midnight_generation_is_owned_by_previous_day(tmp_path, monkeypatch):
    module = archive_module()
    ranking, _, day = sources(tmp_path)
    attention = tmp_path / "midnight-attention"
    cutoff = day + DAY
    f = feature(cutoff=cutoff - 5 * MINUTE).model_copy(update={"decision_at": cutoff})
    inputs, response = generation((f,), generation_id="midnight", cutoff=cutoff - 5 * MINUTE)
    inputs = inputs.model_copy(update={"decision_at": cutoff})
    response = response.model_copy(update={"decision_at": cutoff, "inputs": inputs})
    store = AttentionStore(attention)
    store.save_generation(inputs, (f,), response, evidence=True)
    store.close()
    monkeypatch.setattr(module.time, "time", lambda: (day + 3 * DAY) / 1000)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=2**50))
    archive = tmp_path / "midnight-archive"
    completed = module.archive_closed_days(ranking, attention, archive)
    assert day in {json.loads(path.read_text())["dayMs"] for path in completed}
    reader = FixtureBarReader.from_file(archive)
    store = AttentionStore(attention)
    rows = settle_generation_outcomes(
        store, reader, generation_id="midnight", now_ms=cutoff + 60 * MINUTE
    )
    store.close()
    assert {row.horizon_minutes for row in rows if row.status == "ready"} == {15, 60}
