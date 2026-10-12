import hashlib
import json
from pathlib import Path

from helpers import CUTOFF, feature, generation

from prep_watchdeck_attention.models import MINUTE, outcome_cutoff
from prep_watchdeck_attention.outcomes import FixtureBarReader, settle_generation_outcomes
from prep_watchdeck_attention.storage import AttentionStore


def bundle(root: Path, after: int, through: int, *, revision: str = "rev1") -> Path:
    root.mkdir()
    proof = b'{"status":"COMPLETE"}'
    (root / "copy-manifest.json").write_bytes(proof)
    payload = {
        "schemaVersion": "attention-outcome-input-v1",
        "mapVersion": "map",
        "bars": [
            dict(
                referenceKey=f"bybit:AUSDT:{revision}",
                end=at,
                open=100,
                high=102,
                low=99,
                close=100,
                quoteTurnover=10,
            )
            for at in range(after + MINUTE, through + MINUTE, MINUTE)
        ],
    }
    raw = json.dumps(payload).encode()
    (root / "fragment.json").write_bytes(raw)
    path = root / "outcome-bundle.json"
    path.write_text(
        json.dumps(
            dict(
                schemaVersion="attention-outcome-bundle-v1",
                mapVersion="map",
                afterMs=after,
                throughMs=through,
                copyManifestSha256=hashlib.sha256(proof).hexdigest(),
                files=[
                    dict(
                        name="fragment.json",
                        sha256=hashlib.sha256(raw).hexdigest(),
                        referenceKeys=[f"bybit:AUSDT:{revision}"],
                        assetIds=[],
                        afterMs=after,
                        throughMs=through,
                    )
                ],
            )
        )
    )
    return path


def test_unrelated_bundle_preserves_ready_and_joined_midnight_paths(tmp_path):
    day = CUTOFF // (1440 * MINUTE) * (1440 * MINUTE)
    end = day + 1440 * MINUTE
    first = bundle(tmp_path / "one", day, end)
    second = bundle(tmp_path / "two", end, end + 1440 * MINUTE)
    early_cutoff, late_cutoff = day + 10 * MINUTE, end - 10 * MINUTE
    store = AttentionStore(tmp_path / "state")
    try:
        for name, cutoff in (("early", early_cutoff), ("late", late_cutoff)):
            f = feature(cutoff=cutoff)
            inputs, response = generation((f,), generation_id=name, cutoff=cutoff)
            store.save_generation(inputs, (f,), response, evidence=True)
        own = settle_generation_outcomes(
            store,
            FixtureBarReader.from_file(first),
            generation_id="early",
            now_ms=end + 120 * MINUTE,
        )
        old = tuple(r for r in own if r.family == "reference")
        assert all(r.status == "ready" for r in old)
        assert (
            settle_generation_outcomes(
                store,
                FixtureBarReader.from_file(second),
                generation_id="early",
                now_ms=end + 120 * MINUTE,
            )
            == ()
        )
        assert (
            tuple(r for r in store.outcomes_for_generation("early") if r.family == "reference")
            == old
        )
        partial = settle_generation_outcomes(
            store,
            FixtureBarReader.from_file(first),
            generation_id="late",
            now_ms=end + 120 * MINUTE,
        )
        assert all(r.status == "unscorable" for r in partial if r.family == "reference")
        joined = FixtureBarReader.from_files([first, second])
        rows = settle_generation_outcomes(
            store, joined, generation_id="late", now_ms=end + 120 * MINUTE
        )
        assert all(r.status == "ready" and r.edition == 2 for r in rows if r.family == "reference")
        assert len(joined.bars("bybit:AUSDT:rev1", after=end - MINUTE, through=end + MINUTE)) == 2
        assert not joined.bars("bybit:AUSDT:rev2", after=end - MINUTE, through=end + MINUTE)
    finally:
        store.close()


def test_streaming_evidence_window_and_direct_lookup(tmp_path):
    store = AttentionStore(tmp_path / "state")
    try:
        for index in range(3):
            cutoff = CUTOFF + index * 5 * MINUTE
            f = feature(cutoff=cutoff)
            inputs, response = generation((f,), generation_id=str(index), cutoff=cutoff)
            store.save_generation(inputs, (f,), response, evidence=True)
        start = CUTOFF + 10_000
        assert [
            g[0].generation_id
            for g in store.iter_evidence_generations(start_ms=start, end_ms=start + 5 * MINUTE)
        ] == ["0"]
        assert store.evidence_generation("2")[0].generation_id == "2"
        assert outcome_cutoff(store.evidence_generation("2")[0].decision_at) > CUTOFF
    finally:
        store.close()


def test_bundle_proof_and_fragment_tampering_rejected(tmp_path):
    import pytest

    path = bundle(tmp_path / "bundle", CUTOFF, CUTOFF + 120 * MINUTE)
    fragment = path.parent / "fragment.json"
    original = fragment.read_bytes()
    fragment.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="fragment hash"):
        FixtureBarReader.from_file(path)
    fragment.write_bytes(original)
    (path.parent / "copy-manifest.json").write_bytes(b'{"status":"COMPLETE", "changed":true}')
    with pytest.raises(ValueError, match="copy manifest hash"):
        FixtureBarReader.from_file(path)


def test_legacy_plain_input_cannot_downgrade_unrelated_generation(tmp_path):
    from test_outcomes import reader

    f = feature()
    inputs, response = generation((f,))
    store = AttentionStore(tmp_path / "state")
    try:
        store.save_generation(inputs, (f,), response, evidence=True)
        original = settle_generation_outcomes(
            store, reader(), generation_id="test", now_ms=CUTOFF + 62 * MINUTE
        )
        later = reader().data.model_copy(
            update={
                "bars": tuple(
                    bar.model_copy(update={"end": bar.end + 1440 * MINUTE})
                    for bar in reader().data.bars
                )
            }
        )
        assert (
            settle_generation_outcomes(
                store, FixtureBarReader(later), generation_id="test", now_ms=CUTOFF + 1500 * MINUTE
            )
            == ()
        )
        assert store.outcomes_for_generation("test") == tuple(
            sorted(original, key=lambda row: (row.asset_id, row.horizon_minutes, row.family))
        )
        fixed = settle_generation_outcomes(
            store, reader(corrected=True), generation_id="test", now_ms=CUTOFF + 62 * MINUTE
        )
        assert all(row.edition == 2 for row in fixed if row.family == "reference")
    finally:
        store.close()
