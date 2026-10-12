"""Executable formal binding, fixed window, and durable one-look/crash-resume regressions."""

import json
import sys
from pathlib import Path

import pytest
from test_evaluation import START, make_store

from prep_watchdeck_attention.evaluation import DAY
from prep_watchdeck_attention.formal_protocol import write_protocol
from prep_watchdeck_attention.models import MINUTE
from prep_watchdeck_attention.storage import AttentionStore


def formal_fixture(tmp_path: Path, *, days=32):
    first, second = make_store(days=days), make_store(days=days, horizon=60)
    first.registered = tuple(
        policy.model_copy(
            update={
                "id": f"{policy.id}:{policy.horizon_minutes}",
                "frozen_at": START - 2 * MINUTE,
            }
        )
        for policy in (*first.registered, *second.registered)
    )
    first.outcome_rows += second.outcome_rows
    # Include one preceding-day generation to prove both fixed boundaries are enforced.
    inputs, features, response = first.generations[0]
    first.generations.insert(
        0,
        (
            inputs.model_copy(
                update={
                    "decision_at": START - MINUTE,
                    "ranking_cutoff": START - MINUTE,
                    "generation_id": "before",
                }
            ),
            features,
            response,
        ),
    )
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "schemaVersion": "attention-formal-scope-v1",
                "familyId": "prospective-1",
                "mapVersion": inputs.ranking_map_version,
                "referenceKeys": {row.asset_id: row.reference_key for row in features},
            }
        )
    )
    protocol = tmp_path / "protocol.json"
    registered = write_protocol(
        protocol,
        first.registered,
        scope_path=scope,
        map_version=inputs.ranking_map_version,
        start_ms=START,
        registered_at_ms=START - 1000,
    )
    return first, protocol, scope, Path(registered.look_ledger_path)


def execute(store, protocol, scope, ledger, **overrides):
    try:
        from prep_watchdeck_attention.formal_evaluation import evaluate_formal_family
    except ModuleNotFoundError:
        pytest.fail("formal evaluator is not executable yet")
    return evaluate_formal_family(
        store,
        protocol_path=protocol,
        scope_path=scope,
        ledger_path=ledger,
        now_ms=START + 40 * DAY,
        **overrides,
    )


def test_formal_first_decision_accepts_fresh_ranking_cutoff_before_window(tmp_path):
    store, protocol, scope, ledger = formal_fixture(tmp_path, days=30)
    inputs, features, response = store.generations[1]
    store.generations[1] = (
        inputs.model_copy(update={"ranking_cutoff": START - MINUTE}),
        features,
        response,
    )
    report = execute(store, protocol, scope, ledger)
    assert all(row.metrics.generation_count == 30 for row in report.evaluations)


def test_formal_fixed_window_single_look_and_changed_input_rejected(tmp_path):
    store, protocol, scope, ledger = formal_fixture(tmp_path)
    report = execute(store, protocol, scope, ledger)
    assert report.seed == 0 and report.bootstrap_samples == 2000
    assert len(report.evaluations) == 12
    assert all(
        row.block_count == 30 and row.metrics.generation_count == 30 for row in report.evaluations
    )
    original = ledger.read_bytes()
    assert execute(store, protocol, scope, ledger) == report
    assert ledger.read_bytes() == original
    old = store.outcome_rows[0]
    store.outcome_rows += (old.model_copy(update={"edition": 2, "max_abs_return": 999.0}),)
    with pytest.raises(ValueError, match="different formal input"):
        execute(store, protocol, scope, ledger)
    assert ledger.read_bytes() == original


@pytest.mark.parametrize(
    "wrong",
    [
        "seed",
        "bootstrap",
        "scope",
        "source",
        "map",
        "family",
        "policy",
        "cutoff",
        "ledger",
        "outcome-cutoff",
        "outcome-reference",
    ],
)
def test_formal_wrong_binding_is_rejected_before_look(tmp_path, wrong):
    store, protocol, scope, ledger = formal_fixture(tmp_path, days=30)
    kwargs = {}
    if wrong == "seed":
        kwargs["seed"] = 1
    elif wrong == "bootstrap":
        kwargs["bootstrap_samples"] = 199
    elif wrong == "scope":
        scope.write_text("{}")
    elif wrong == "source":
        data = json.loads(protocol.read_text())
        data["sourceHashes"]["prep_watchdeck_attention.evaluation"] = "0" * 64
        protocol.write_text(json.dumps(data))
    elif wrong in ("family", "policy"):
        update = {"family_id": "other"} if wrong == "family" else {"version": "other"}
        store.registered = (store.registered[0].model_copy(update=update), *store.registered[1:])
    elif wrong == "ledger":
        ledger = tmp_path / "another-look.json"
    elif wrong.startswith("outcome-"):
        row = store.outcome_rows[0]
        update = (
            {"cutoff": row.cutoff + MINUTE}
            if wrong == "outcome-cutoff"
            else {"reference_key": "other-reference"}
        )
        store.outcome_rows = (row.model_copy(update=update), *store.outcome_rows[1:])
    else:
        inputs, features, response = store.generations[1]
        update = (
            {"ranking_map_version": "other"}
            if wrong == "map"
            else {"ranking_cutoff": inputs.decision_at + MINUTE}
        )
        store.generations[1] = (inputs.model_copy(update=update), features, response)
    with pytest.raises(ValueError):
        execute(store, protocol, scope, ledger, **kwargs)
    assert not ledger.exists()


def test_formal_crash_resumes_same_input_and_preserves_result(tmp_path, monkeypatch):
    from prep_watchdeck_attention import formal_evaluation

    store, protocol, scope, ledger = formal_fixture(tmp_path, days=30)
    evaluator = formal_evaluation.evaluate_candidate_family

    def interrupted(*args, **kwargs):
        raise RuntimeError("isolated crash after durable look reservation")

    monkeypatch.setattr(formal_evaluation, "evaluate_candidate_family", interrupted)
    with pytest.raises(RuntimeError, match="isolated crash"):
        execute(store, protocol, scope, ledger)
    claim = json.loads(ledger.read_text())
    assert claim["status"] == "STARTED" and claim["formalLookCount"] == 1
    monkeypatch.setattr(formal_evaluation, "evaluate_candidate_family", evaluator)
    report = execute(store, protocol, scope, ledger)
    assert json.loads(ledger.read_text())["status"] == "COMPLETE"
    assert report == execute(store, protocol, scope, ledger)


def test_formal_changed_during_calculation_never_publishes_result(tmp_path, monkeypatch):
    from prep_watchdeck_attention import formal_evaluation

    store, protocol, scope, ledger = formal_fixture(tmp_path, days=30)
    evaluator = formal_evaluation.evaluate_candidate_family

    def corrected(*args, **kwargs):
        report = evaluator(*args, **kwargs)
        old = store.outcome_rows[0]
        store.outcome_rows += (old.model_copy(update={"edition": 2, "max_abs_return": 999.0}),)
        return report

    monkeypatch.setattr(formal_evaluation, "evaluate_candidate_family", corrected)
    with pytest.raises(ValueError, match="changed during formal"):
        execute(store, protocol, scope, ledger)
    assert json.loads(ledger.read_text())["status"] == "STARTED"
    assert not store.saved


def test_actual_cli_fixed_protocol_and_same_input_repeat(tmp_path, monkeypatch, capsys):
    from prep_watchdeck_attention import cli, formal_evaluation

    memory, protocol, scope, ledger = formal_fixture(tmp_path, days=30)
    state, market, ranking = (tmp_path / name for name in ("attention", "market", "ranking"))
    store = AttentionStore(state, market_state_dir=market, ranking_state_dir=ranking)
    try:
        store.freeze_family(memory.registered)
        for inputs, features, response in memory.generations[1:]:
            store.save_generation(inputs, features, response, evidence=True)
        for row in memory.outcome_rows:
            store.put_outcome(row)
    finally:
        store.close()
    # The fixture is a prospective synthetic calendar, unrelated to live acceptance.
    monkeypatch.setattr(formal_evaluation.time, "time_ns", lambda: (START + 40 * DAY) * 1_000_000)
    argv = [
        "watchdeck-attention",
        "evaluate-formal",
        "--state-dir",
        str(state),
        "--market-state-dir",
        str(market),
        "--ranking-state-dir",
        str(ranking),
        "--protocol",
        str(protocol),
        "--scope",
        str(scope),
        "--ledger",
        str(ledger),
    ]
    monkeypatch.setattr(sys, "argv", [*argv, "--seed", "1"])
    with pytest.raises(SystemExit) as refused:
        cli.main()
    assert refused.value.code == 2
    assert not ledger.exists()
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() is None
    output = json.loads(capsys.readouterr().out)
    assert output["scope"] == "formal_fixed_protocol_one_look"
    assert output["report"]["seed"] == 0
    assert all(row["blockCount"] == 30 for row in output["report"]["evaluations"])
    original = ledger.read_bytes()
    assert cli.main() is None
    assert json.loads(capsys.readouterr().out)["report"] == output["report"]
    assert ledger.read_bytes() == original
