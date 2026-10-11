import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from helpers import CUTOFF, feature, generation

from prep_watchdeck_attention.models import MINUTE
from prep_watchdeck_attention.outcomes import FixtureBarReader, settle_generation_outcomes
from prep_watchdeck_attention.storage import AttentionStore


def test_export_roundtrip_keeps_availability_clock_and_detects_changed_copy(tmp_path: Path) -> None:
    from prep_watchdeck_attention.outcome_export import export_outcome_input

    root = tmp_path / "copy"
    root.mkdir()
    original = feature()
    inputs, response = generation((original,))
    store = AttentionStore(root)
    store.save_generation(inputs, (original,), response, evidence=True)
    store.close()
    ranking = root / "ranking.sqlite3"
    with sqlite3.connect(ranking) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO metadata VALUES ('map', ?)", ('{"version":"map"}',))
        connection.execute(
            "CREATE TABLE minute_bars (reference_key TEXT,end INTEGER,open REAL,"
            "high REAL,low REAL,close REAL,quote_turnover REAL)"
        )
        connection.executemany(
            "INSERT INTO minute_bars VALUES (?,?,?,?,?,?,?)",
            [("bybit:AUSDT:rev1", CUTOFF + i * MINUTE, 100, 102, 99, 100, 10) for i in range(63)],
        )
    files = {
        name: {"sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
        for name in ("ranking.sqlite3", "attention.sqlite3")
    }
    (root / "copy-manifest.json").write_text(json.dumps({"status": "COMPLETE", "files": files}))
    manifest = export_outcome_input(
        ranking,
        root / "attention.sqlite3",
        tmp_path / "export",
        map_version="map",
        after_ms=CUTOFF,
        through_ms=CUTOFF + 62 * MINUTE,
    )
    reader = FixtureBarReader.from_file(manifest)
    points = reader.native_points(original.asset_id, after=CUTOFF, through=CUTOFF + 62 * MINUTE)
    assert points and points[0].at >= original.decision_at
    scratch = AttentionStore(tmp_path / "scratch")
    try:
        scratch.save_generation(inputs, (original,), response, evidence=True)
        outcomes = settle_generation_outcomes(
            scratch, reader, generation_id=inputs.generation_id, now_ms=CUTOFF + 62 * MINUTE
        )
        assert {
            row.horizon_minutes
            for row in outcomes
            if row.family == "reference" and row.status == "ready"
        } == {15, 60}
        assert all(row.status == "unscorable" for row in outcomes if row.family == "native")
    finally:
        scratch.close()
    # A later map does not rewrite the exact reference revision of saved generations.
    with sqlite3.connect(ranking) as connection:
        connection.execute("UPDATE metadata SET value=? WHERE key='map'", ('{"version":"later"}',))
    files["ranking.sqlite3"]["sha256"] = hashlib.sha256(ranking.read_bytes()).hexdigest()
    (root / "copy-manifest.json").write_text(json.dumps({"status": "COMPLETE", "files": files}))
    historical = export_outcome_input(
        ranking,
        root / "attention.sqlite3",
        tmp_path / "historical-map",
        map_version="map",
        after_ms=CUTOFF,
        through_ms=CUTOFF + 62 * MINUTE,
    )
    assert FixtureBarReader.from_file(historical).bars(
        "bybit:AUSDT:rev1", after=CUTOFF, through=CUTOFF + MINUTE
    ) == reader.bars("bybit:AUSDT:rev1", after=CUTOFF, through=CUTOFF + MINUTE)
    with sqlite3.connect(ranking) as connection:
        connection.execute("UPDATE minute_bars SET close=101 WHERE end=?", (CUTOFF,))
    with pytest.raises(ValueError, match="copy hash"):
        export_outcome_input(
            ranking,
            root / "attention.sqlite3",
            tmp_path / "changed",
            map_version="map",
            after_ms=CUTOFF,
            through_ms=CUTOFF + MINUTE,
        )
