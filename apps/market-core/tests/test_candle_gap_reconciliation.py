from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


def seal(payload):
    payload = deepcopy(payload)
    payload.pop("evidenceHash", None)
    payload["evidenceHash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return payload


def ledger(schema="candle-gap-audit-v1"):
    scope = {
        "instrumentIds": ["aster:PEARLUSDT"],
        "since": "2026-10-10T08:28:00Z",
        "until": "2026-10-10T08:33:00Z",
    }
    ranges = [
        {
            "instrumentId": "aster:PEARLUSDT",
            "versionId": 9921,
            "definitionHash": "a" * 64,
            "validFrom": "2026-10-09T12:00:00Z",
            "validTo": "2026-10-10T08:30:00.176269Z",
        },
        {
            "instrumentId": "aster:PEARLUSDT",
            "versionId": 9981,
            "definitionHash": "b" * 64,
            "validFrom": "2026-10-10T08:30:00.176269Z",
            "validTo": None,
        },
    ]
    missing = {
        "instrumentId": "aster:PEARLUSDT",
        "versionId": 9921,
        "definitionHash": "a" * 64,
        "bucket": "2026-10-10T08:29:00Z",
    }
    return seal(
        {
            "schemaVersion": schema,
            "scope": scope,
            "scopeHash": hashlib.sha256(
                json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "observedAt": "2026-10-10T08:34:00Z",
            "snapshot": "1:2:",
            "databaseIdentity": "d" * 64,
            "sessionReadOnly": True,
            "databaseMutations": 0,
            "providerRequests": 0,
            "providerStatus": "not_queried",
            "contractRanges": ranges,
            "expectedMinutes": 4,
            "presentMinutes": 3,
            "missing": [missing],
            "boundaries": [
                {
                    "instrumentId": "aster:PEARLUSDT",
                    "bucket": "2026-10-10T08:30:00Z",
                    "status": "boundary_unresolved",
                    "contracts": ranges,
                }
            ],
            "catalogUnavailable": [],
            "trackedGaps": [{"key": missing, "status": "missing"}],
            "previousEvidenceHash": None,
        }
    )


def save(path, payload):
    raw = (json.dumps(payload, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def compare(tmp_path, old=None, baseline=None):
    from prep_watchdeck_market.candle_gap_reconciliation import reconcile_files

    old_path, baseline_path = tmp_path / "old.json", tmp_path / "baseline.json"
    save(old_path, ledger() if old is None else old)
    save(baseline_path, ledger("candle-gap-audit-v2") if baseline is None else baseline)
    return reconcile_files((old_path,), baseline_path)


def test_retains_every_old_unresolved_key_and_exact_boundary(tmp_path):
    old = ledger()
    obsolete = dict(old["missing"][0], versionId=1234, definitionHash="c" * 64)
    old["trackedGaps"].append({"key": obsolete, "status": "version_unavailable"})
    old = seal(old)
    baseline = ledger("candle-gap-audit-v2")
    baseline["contractRanges"][0]["validTo"] = "2026-10-10T08:30:00Z"
    baseline["contractRanges"][1]["validFrom"] = "2026-10-10T08:30:00Z"
    baseline.update(expectedMinutes=5, presentMinutes=4, boundaries=[])
    report = compare(tmp_path, old=old, baseline=seal(baseline))
    assert [entry["key"] for entry in report["gapComparisons"]] == [
        obsolete,
        old["missing"][0],
    ]
    assert [entry["status"] for entry in report["gapComparisons"]] == [
        "missing_from_new_baseline",
        "still_missing",
    ]
    assert report["preservedBoundaries"][0]["boundary"] == old["boundaries"][0]
    assert (
        report["legacyInputs"][0]["rawSha256"]
        == hashlib.sha256((tmp_path / "old.json").read_bytes()).hexdigest()
    )
    assert report["databaseIdentityRelationship"] == "unverified_cross_schema"
    assert report["allLegacyUnresolvedRecovered"] is False
    assert report["globalHistoryAcceptance"] == "not_assessed"


@pytest.mark.parametrize(
    "change,want",
    [
        ("missing", "still_missing"),
        ("absent", "missing_from_new_baseline"),
        ("exact_recovered", "unknown"),
        ("changed_hash", "identity_changed"),
    ],
)
def test_new_baseline_cannot_silently_recover_old_gap(tmp_path, change, want):
    new = ledger("candle-gap-audit-v2")
    if change in {"absent", "exact_recovered"}:
        new.update(presentMinutes=4, missing=[])
        new["trackedGaps"] = (
            [] if change == "absent" else [{"key": ledger()["missing"][0], "status": "recovered"}]
        )
    elif change == "changed_hash":
        new["contractRanges"][0]["definitionHash"] = "e" * 64
        new["missing"][0]["definitionHash"] = "e" * 64
        new["trackedGaps"][0]["key"]["definitionHash"] = "e" * 64
    report = compare(tmp_path, baseline=seal(new))
    assert report["gapComparisons"][0]["status"] == want
    assert report["allLegacyUnresolvedRecovered"] is False
    if change == "exact_recovered":
        assert report["gapComparisons"][0]["baselineStatus"] == "recovered"


def test_preserves_catalog_unknown_even_when_new_catalog_covers_window(tmp_path):
    old = ledger()
    old.update(
        expectedMinutes=0,
        presentMinutes=0,
        contractRanges=[],
        missing=[],
        trackedGaps=[],
        boundaries=[],
        catalogUnavailable=[
            {
                "instrumentId": "aster:PEARLUSDT",
                "since": "2026-10-10T08:28:00Z",
                "until": "2026-10-10T08:33:00Z",
                "status": "catalog_unavailable",
            }
        ],
    )
    report = compare(tmp_path, old=seal(old))
    assert report["preservedCatalogUnavailable"][0]["interval"] == old["catalogUnavailable"][0]
    assert report["allLegacyUnresolvedRecovered"] is False


def test_multiple_legacy_files_keep_union_and_source_hashes(tmp_path):
    from prep_watchdeck_market.candle_gap_reconciliation import reconcile_files

    first, second, baseline = (tmp_path / name for name in ("first.json", "second.json", "v2.json"))
    old = ledger()
    save(first, old)
    extra = dict(old["missing"][0], versionId=1234, definitionHash="c" * 64)
    later = deepcopy(old)
    later["trackedGaps"].append({"key": extra, "status": "version_unavailable"})
    later = seal(later)
    save(second, later)
    save(baseline, ledger("candle-gap-audit-v2"))
    report = reconcile_files((first, second), baseline)
    assert len(report["legacyInputs"]) == 2
    assert report["legacyUnresolvedKeys"] == 2
    assert report["gapComparisons"][1]["sourceEvidenceHashes"] == [
        old["evidenceHash"],
        later["evidenceHash"],
    ]
    assert len(report["preservedBoundaries"]) == 2


@pytest.mark.parametrize("corruption", ["hash", "counts", "instrument_ids"])
def test_rejects_invalid_v2_or_instrument_scope_change(tmp_path, corruption):
    baseline = ledger("candle-gap-audit-v2")
    if corruption == "hash":
        baseline["snapshot"] = "changed"
    elif corruption == "counts":
        baseline["presentMinutes"] = 4
        baseline = seal(baseline)
    else:
        baseline = json.loads(json.dumps(baseline).replace("PEARLUSDT", "OTHERUSDT"))
        baseline["scopeHash"] = hashlib.sha256(
            json.dumps(baseline["scope"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        baseline = seal(baseline)
    with pytest.raises(ValueError):
        compare(tmp_path, baseline=baseline)


@pytest.mark.parametrize("corruption", ["hash", "scope_hash", "counts", "schema", "scope"])
def test_rejects_tampering_malformed_legacy_and_different_scope(tmp_path, corruption):
    old = ledger()
    if corruption == "hash":
        old["snapshot"] = "changed"
    elif corruption == "scope_hash":
        old["scopeHash"] = "f" * 64
        old = seal(old)
    elif corruption == "counts":
        old["presentMinutes"] = 4
        old = seal(old)
    elif corruption == "schema":
        old["schemaVersion"] = "other-ledger"
        old = seal(old)
    else:
        old["scope"]["since"] = "2026-10-10T08:27:00Z"
        old["scopeHash"] = hashlib.sha256(
            json.dumps(old["scope"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        old["expectedMinutes"] = 5
        old["presentMinutes"] = 4
        old = seal(old)
    with pytest.raises(ValueError):
        compare(tmp_path, old=old)


def test_cli_success_means_comparison_only_and_refuses_overwrite(tmp_path, capsys):
    from prep_watchdeck_market.candle_gap_reconciliation import main

    old, baseline, output = (tmp_path / name for name in ("old.json", "new.json", "out.json"))
    save(old, ledger())
    save(baseline, ledger("candle-gap-audit-v2"))
    originals = old.read_bytes(), baseline.read_bytes()
    argv = ["--legacy", str(old), "--baseline", str(baseline), "--output", str(output)]
    assert main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["comparisonStatus"] == "comparison_complete"
    assert summary["allLegacyUnresolvedRecovered"] is False
    assert summary["globalHistoryAcceptance"] == "not_assessed"
    retained = output.read_bytes()
    assert main(argv) == 2
    assert output.read_bytes() == retained
    assert originals == (old.read_bytes(), baseline.read_bytes())


def test_symlink_output_cannot_replace_an_existing_ledger(tmp_path):
    from prep_watchdeck_market.candle_gap_reconciliation import main

    old, baseline, output = (tmp_path / name for name in ("old.json", "new.json", "out.json"))
    save(old, ledger())
    save(baseline, ledger("candle-gap-audit-v2"))
    output.symlink_to(old)
    retained = old.read_bytes()
    assert main(["--legacy", str(old), "--baseline", str(baseline), "--output", str(output)]) == 2
    assert old.read_bytes() == retained
    assert output.is_symlink()


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversize"])
def test_unsafe_input_is_rejected_without_output_or_blocking(tmp_path, kind):
    old, baseline, output = (tmp_path / name for name in ("old.json", "new.json", "out.json"))
    if kind == "symlink":
        target = tmp_path / "target.json"
        save(target, ledger())
        old.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(old)
    else:
        with old.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
    save(baseline, ledger("candle-gap-audit-v2"))
    script = Path(__file__).parents[3] / "scripts/market/reconcile-candle-history.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--legacy",
            str(old),
            "--baseline",
            str(baseline),
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 2
    assert not output.exists()
