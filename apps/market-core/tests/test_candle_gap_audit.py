from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.candle_gap_audit import (
    AuditScope,
    ContractRange,
    audit_connection,
    build_audit,
    load_evidence,
    main,
    write_evidence,
)
from prep_watchdeck_market.database import apply_migrations

START = datetime(2026, 10, 10, 8, 28, tzinfo=UTC)
END = START + timedelta(minutes=5)
CHANGED = START + timedelta(minutes=2, microseconds=176269)


def scope() -> AuditScope:
    return AuditScope(instrument_ids=("aster:PEARLUSDT",), since=START, until=END)


def contracts() -> tuple[ContractRange, ...]:
    return (
        ContractRange(
            instrument_id="aster:PEARLUSDT",
            version_id=9921,
            definition_hash="a" * 64,
            valid_from=START - timedelta(days=1),
            valid_to=CHANGED,
        ),
        ContractRange(
            instrument_id="aster:PEARLUSDT",
            version_id=9981,
            definition_hash="b" * 64,
            valid_from=CHANGED,
            valid_to=None,
        ),
    )


def audit(*, ranges=None, present=None, previous=None, audit_scope=None):
    return build_audit(
        audit_scope or scope(),
        ranges if ranges is not None else contracts(),
        present or {},
        observed_at=END + timedelta(minutes=1),
        snapshot="1:2:",
        database_identity="unit-fixture",
        previous=previous,
    )


def test_old_missing_minute_and_midminute_boundary_are_not_dropped():
    report = audit(
        present={9921: {START}, 9981: {START + timedelta(minutes=3), END - timedelta(minutes=1)}}
    )
    assert report.expected_minutes == 4
    assert report.present_minutes == 3
    assert [(gap.version_id, gap.bucket) for gap in report.missing] == [
        (9921, START + timedelta(minutes=1))
    ]
    assert [(gap.bucket, [v.version_id for v in gap.contracts]) for gap in report.boundaries] == [
        (START + timedelta(minutes=2), [9921, 9981])
    ]
    assert report.complete is False
    assert report.provider_status == "not_queried"


def test_rescan_only_recovers_same_version_hash_and_retains_boundary():
    first = audit(
        present={9921: {START}, 9981: {START + timedelta(minutes=3), END - timedelta(minutes=1)}}
    )
    second = audit(
        previous=first,
        present={
            9921: {START, START + timedelta(minutes=1)},
            9981: {START + timedelta(minutes=3), END - timedelta(minutes=1)},
        },
    )
    assert [(item.key.version_id, item.status) for item in second.tracked_gaps] == [
        (9921, "recovered")
    ]
    assert second.boundaries == first.boundaries
    changed = contracts()[0].model_copy(update={"definition_hash": "c" * 64})
    third = audit(
        ranges=(changed, contracts()[1]),
        previous=second,
        present={9921: {START, START + timedelta(minutes=1)}},
    )
    assert third.tracked_gaps[0].status == "definition_changed"
    assert third.complete is False


def test_rescan_rejects_moved_window_and_missing_version_stays_unresolved():
    first = audit()
    with pytest.raises(ValueError, match="scope"):
        audit(
            previous=first,
            audit_scope=AuditScope(
                instrument_ids=("aster:PEARLUSDT",), since=START + timedelta(minutes=1), until=END
            ),
        )
    missing_old = audit(ranges=(contracts()[1],), previous=first)
    assert any(
        item.key.version_id == 9921 and item.status == "version_unavailable"
        for item in missing_old.tracked_gaps
    )
    assert missing_old.boundaries == first.boundaries


def test_empty_catalog_is_unknown_and_never_complete():
    report = audit(ranges=())
    assert report.expected_minutes == 0
    assert report.catalog_unavailable[0].since == START
    assert report.catalog_unavailable[0].until == END
    assert report.complete is False


def test_aligned_contract_change_can_complete_after_exact_old_and_new_gaps_recover():
    cutover = START + timedelta(minutes=2)
    ranges = (
        contracts()[0].model_copy(update={"valid_to": cutover}),
        contracts()[1].model_copy(update={"valid_from": cutover}),
    )
    first = audit(
        ranges=ranges,
        present={9921: {START}, 9981: {START + timedelta(minutes=3), END - timedelta(minutes=1)}},
    )
    assert [item.version_id for item in first.missing] == [9921, 9981]
    assert first.boundaries == ()
    second = audit(
        ranges=ranges,
        previous=first,
        present={
            9921: {START, START + timedelta(minutes=1)},
            9981: {cutover, START + timedelta(minutes=3), END - timedelta(minutes=1)},
        },
    )
    assert second.expected_minutes == second.present_minutes == 5
    assert [item.status for item in second.tracked_gaps] == ["recovered", "recovered"]
    assert second.complete is True


def test_cli_refuses_other_database_before_connecting(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "PREP_WATCHDECK_MARKET_DATABASE_URL", "postgresql://other:secret@127.0.0.1:5432/other"
    )

    def forbidden_connect(*args, **kwargs):
        pytest.fail("audit must reject the database target before connecting")

    monkeypatch.setattr(psycopg, "connect", forbidden_connect)
    output = tmp_path / "never-created.json"
    assert (
        main(
            [
                "--since",
                START.isoformat(),
                "--until",
                END.isoformat(),
                "--instrument-id",
                "aster:PEARLUSDT",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()


def test_evidence_is_exclusive_and_rejects_modified_previous(tmp_path):
    target = tmp_path / "evidence.json"
    first = audit()
    write_evidence(target, first)
    retained = target.read_bytes()
    assert load_evidence(target) == first
    with pytest.raises(FileExistsError):
        write_evidence(target, first)
    assert target.read_bytes() == retained
    target.write_bytes(retained.replace(b'"not_queried"', b'"unknown"'))
    with pytest.raises(ValueError):
        load_evidence(target)


@pytest.mark.parametrize(
    "since,until",
    [(START, START), (START, START + timedelta(hours=25)), (START + timedelta(seconds=1), END)],
)
def test_scope_requires_bounded_full_minutes(since, until):
    with pytest.raises(ValueError):
        AuditScope(instrument_ids=("aster:PEARLUSDT",), since=since, until=until)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="isolated PostgreSQL required")
def test_postgres_audit_retains_old_gap_and_reconciles_same_snapshot_scope(tmp_path):
    url = os.environ["TEST_DATABASE_URL"]
    target = urlsplit(url)
    if (
        target.hostname != "127.0.0.1"
        or target.port in {None, 5432, 55432}
        or target.path != "/prep_watchdeck_test"
        or target.username != "prep_watchdeck_test"
    ):
        pytest.fail("isolated TEST_DATABASE_URL required")
    schema = "gap_audit_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            apply_migrations(connection)
            payload = connection.execute(
                "INSERT INTO raw_catalog_payloads "
                "(venue,endpoint,source_kind,documentation_url,payload_hash,"
                "observed_at,last_observed_at,payload) "
                "VALUES ('aster','/catalog','native_rest','https://example.invalid',%s,%s,%s,'{}') "
                "RETURNING raw_catalog_payload_id",
                ("d" * 64, START, START),
            ).fetchone()[0]
            version_ids = []
            for item in contracts():
                version_ids.append(
                    connection.execute(
                        "INSERT INTO venue_instrument_versions "
                        "(venue,source_symbol,definition_hash,valid_from,valid_to,active,asset_class,market_type,"
                        "base_asset,quote_asset,settle_asset,quantity_unit,contract_multiplier,"
                        "raw_definition,raw_catalog_payload_id) "
                        "VALUES ('aster','PEARLUSDT',%s,%s,%s,true,'crypto','linear_perpetual',"
                        "'PEARL','USDT','USDT','base',1,'{}',%s) "
                        "RETURNING venue_instrument_version_id",
                        (item.definition_hash, item.valid_from, item.valid_to, payload),
                    ).fetchone()[0]
                )
            insert = (
                "INSERT INTO candle_1m (venue_instrument_version_id,bucket_at,open_price,"
                "high_price,"
                "low_price,close_price,finality,observed_at) VALUES (%s,%s,1,1,1,1,'confirmed',%s)"
            )
            for version_id, minute in [
                (version_ids[0], 0),
                (version_ids[1], 3),
                (version_ids[1], 4),
            ]:
                connection.execute(insert, (version_id, START + minute * timedelta(minutes=1), END))
            before = connection.execute("SELECT count(*) FROM candle_1m").fetchone()[0]
            first = audit_connection(connection, scope())
            assert first.session_read_only is True
            assert first.expected_minutes == 4
            assert [(item.version_id, item.bucket) for item in first.missing] == [
                (version_ids[0], START + timedelta(minutes=1))
            ]
            assert len(first.boundaries) == 1
            assert connection.execute("SELECT count(*) FROM candle_1m").fetchone()[0] == before
            path = tmp_path / "first.json"
            write_evidence(path, first)
            connection.execute(insert, (version_ids[0], START + timedelta(minutes=1), END))
            second = audit_connection(connection, scope(), previous=load_evidence(path))
            assert second.missing == ()
            assert [item.status for item in second.tracked_gaps] == ["recovered"]
            assert second.boundaries == first.boundaries
            assert second.complete is False
        finally:
            connection.execute("RESET search_path")
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
