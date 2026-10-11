import importlib.util
import json
from pathlib import Path

import pytest
from test_evaluation import START, make_store

from prep_watchdeck_attention.cli import BASELINE_SIGNALS, SIGNALS
from prep_watchdeck_attention.models import CandidatePolicy, RawFeatureValue


def frozen():
    return tuple(
        CandidatePolicy(
            id=f"fixed:{signal}:{horizon}",
            family_id="fixed",
            signal=signal,
            version="attention-reference-baselines-v1"
            if signal in BASELINE_SIGNALS
            else "attention-components-v1",
            frozen_at=START - 60_000,
            horizon_minutes=horizon,
        )
        for signal in SIGNALS
        for horizon in (15, 60)
    )


def test_registration_refuses_unverified_scope_hash(tmp_path):
    from prep_watchdeck_attention.formal_protocol import write_protocol

    with pytest.raises(ValueError, match="scope document"):
        write_protocol(
            tmp_path / "protocol.json",
            frozen(),
            map_version="fixed-map",
            scope_sha256="a" * 64,
            start_ms=START,
            registered_at_ms=START - 1000,
        )


@pytest.mark.parametrize("package", ["prep_watchdeck_market", "prep_watchdeck_ranking"])
def test_registration_refuses_ledger_in_execution_source(tmp_path, package):
    from prep_watchdeck_attention.formal_protocol import write_protocol

    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "schemaVersion": "attention-formal-scope-v1",
                "familyId": "fixed",
                "mapVersion": "fixed-map",
                "referenceKeys": {"a": None},
            }
        )
    )
    spec = importlib.util.find_spec(package)
    target = Path(spec.origin).parent / "never-created-formal-ledger.json"
    with pytest.raises(ValueError, match="execution source"):
        write_protocol(
            tmp_path / "protocol.json",
            frozen(),
            map_version="fixed-map",
            scope_path=scope,
            ledger_path=target,
            start_ms=START,
            registered_at_ms=START - 1000,
        )
    assert not target.exists()


@pytest.mark.parametrize("changed", ["cutoff", "seed", "family"])
def test_protocol_rejects_changed_cutoff_seed_or_family(tmp_path, changed):
    from prep_watchdeck_attention.formal_protocol import write_protocol

    path = tmp_path / "protocol.json"
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "schemaVersion": "attention-formal-scope-v1",
                "familyId": "fixed",
                "mapVersion": "fixed-map",
                "referenceKeys": {"a": "reference:a"},
            }
        )
    )
    policies = frozen()
    write_protocol(
        path,
        policies,
        map_version="fixed-map",
        scope_path=scope,
        start_ms=START,
        registered_at_ms=START - 1000,
    )
    before = path.read_bytes()
    if changed == "seed":
        payload = json.loads(before)
        payload["seed"] = 1
        path.write_text(json.dumps(payload))
    if changed == "family":
        policies = tuple(p.model_copy(update={"family_id": "changed"}) for p in policies)
    with pytest.raises(ValueError):
        write_protocol(
            path,
            policies,
            map_version="fixed-map",
            scope_path=scope,
            start_ms=START + (86_400_000 if changed == "cutoff" else 0),
            registered_at_ms=START - 1000,
        )
    if changed != "seed":
        assert path.read_bytes() == before


def test_common_eligible_is_selected_before_outcome():
    from prep_watchdeck_attention.formal_protocol import common_eligible_ids

    store = make_store(days=2)
    inputs, features, response = store.generations[0]
    changed = features[0].model_copy(
        update={
            "reference_turnover_ratio15m": RawFeatureValue(
                value=None, status="missing", reason="unknown", source="fixed input"
            )
        }
    )
    record = (inputs, (changed, *features[1:]), response)
    pool = common_eligible_ids(record, store.registered)
    assert len(pool) == 29 and changed.asset_id not in pool
    store.outcome_rows = ()
    assert common_eligible_ids(record, store.registered) == pool
