from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck_market.candle_audit import audit_snapshots, main

START = datetime(2026, 9, 27, 23, 56, tzinfo=UTC)
END = START + timedelta(minutes=10)
AS_OF = END + timedelta(minutes=3)


def snapshot() -> dict:
    series = {
        "venue": "hyperliquid",
        "source_symbol": "BTC",
        "venue_instrument_version_id": 10,
        "definition_sha256": hashlib.sha256(b"SYNTHETIC TEST CATALOG").hexdigest(),
        "base_asset": "BTC",
        "quote_asset": "USDC",
        "settle_asset": "USDC",
        "price_kind": "trade",
        "interval_seconds": 60,
    }
    records = []
    for index in range(10):
        stamp = START + timedelta(minutes=index)
        price = 100 + index
        records.append(
            {
                "venue_instrument_version_id": 10,
                "bucket_at": stamp.isoformat(),
                "open_price": str(price),
                "high_price": str(price + 1),
                "low_price": str(price - 1),
                "close_price": str(price),
                "volume_base": "0",
                "volume_notional": None,
                "trade_count": 0,
                "finality": "derived_final",
                "source_at": stamp.isoformat(),
                "observed_at": (stamp + timedelta(minutes=1)).isoformat(),
            }
        )
    return {"schema_version": 1, "source_label": "synthetic", "series": series, "records": records}


def run(tmp_path: Path, left: dict, right: dict, **kwargs) -> dict:
    paths = [tmp_path / "left.json", tmp_path / "right.json"]
    for path, data in zip(paths, (left, right), strict=True):
        path.write_text(json.dumps(data), encoding="utf-8")
    before = [path.read_bytes() for path in paths]
    report = audit_snapshots(*paths, start=START, end=END, as_of=AS_OF, **kwargs)
    assert [path.read_bytes() for path in paths] == before
    return report


def test_match_crosses_utc_midnight_and_keeps_zero_volume(tmp_path):
    report = run(tmp_path, snapshot(), snapshot(), compare_volume_base=True)
    assert report["outcome"] == "match"
    assert report["common_valid_bars"] == 10
    assert report["compared_values"] == 50
    assert report["return_pairs"] == 5
    assert report["sources"]["left"]["derived_final_count"] == 10


def test_timezone_offsets_are_converted_not_removed(tmp_path):
    left, right = snapshot(), snapshot()
    jst = timezone(timedelta(hours=9))
    for row in right["records"]:
        for field in ("bucket_at", "source_at", "observed_at"):
            row[field] = datetime.fromisoformat(row[field]).astimezone(jst).isoformat()
    assert run(tmp_path, left, right)["outcome"] == "match"


def test_same_wall_clock_different_instants_do_not_match(tmp_path):
    left, right = snapshot(), snapshot()
    for row in right["records"]:
        for field in ("bucket_at", "source_at", "observed_at"):
            row[field] = row[field].replace("+00:00", "+09:00")
    report = run(tmp_path, left, right)
    assert report["outcome"] == "unverified"
    assert report["common_valid_bars"] == 0


def test_both_sources_missing_same_minute_are_not_a_match(tmp_path):
    data = snapshot()
    del data["records"][3]
    report = run(tmp_path, data, data)
    assert report["outcome"] == "incomplete"
    assert len(report["sources"]["left"]["missing_buckets"]) == 1
    assert report["return_pairs"] == 4
    assert len(report["return_missing_endpoints"]) == 1


@pytest.mark.parametrize("empty_right", [False, True])
def test_no_data_is_unverified(tmp_path, empty_right):
    left, right = snapshot(), snapshot()
    left["records"] = []
    if empty_right:
        right["records"] = []
    report = run(tmp_path, left, right)
    assert report["outcome"] == "unverified"
    assert report["compared_values"] == 0


def test_duplicate_rows_do_not_overwrite_or_double_count(tmp_path):
    left, right = snapshot(), snapshot()
    duplicate = copy.deepcopy(right["records"][2])
    duplicate["close_price"] = "102.5"
    right["records"].extend([duplicate, copy.deepcopy(duplicate)])
    report = run(tmp_path, left, right)
    assert report["outcome"] == "incomplete"
    assert report["common_valid_bars"] == 9
    assert len(report["sources"]["right"]["findings"]) == 2
    assert not report["differences"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("close_price", "NaN"),
        ("high_price", "Infinity"),
        ("low_price", "-1"),
        ("high_price", "1"),
        ("volume_base", "-1"),
        ("trade_count", True),
        ("trade_count", 1.5),
        ("finality", "provisional"),
        ("venue_instrument_version_id", 11),
        ("observed_at", "2026-09-28T12:00:00+00:00"),
        ("bucket_at", "2026-09-27T23:56:01+00:00"),
        ("observed_at", "2026-09-27T23:55:00+00:00"),
    ],
)
def test_invalid_records_remain_diagnostics_not_market_data(tmp_path, field, value):
    left, right = snapshot(), snapshot()
    right["records"][0][field] = value
    report = run(tmp_path, left, right)
    assert report["outcome"] == "incomplete"
    assert report["common_valid_bars"] == 9
    assert report["sources"]["right"]["findings"]


def test_missing_volume_is_not_zero_and_does_not_discard_valid_price(tmp_path):
    left, right = snapshot(), snapshot()
    right["records"][4]["volume_base"] = None
    report = run(tmp_path, left, right, compare_volume_base=True)
    assert report["outcome"] == "incomplete"
    assert report["compared_values"] == 49
    assert report["return_pairs"] == 5
    assert len(report["missing_values"]) == 1
    assert not report["differences"]
    assert run(tmp_path, left, right)["outcome"] == "match"


def test_price_tolerance_requires_both_thresholds(tmp_path):
    left, right = snapshot(), snapshot()
    right["records"][5]["close_price"] = "105.01"
    assert run(tmp_path, left, right)["outcome"] == "differences"
    report = run(
        tmp_path,
        left,
        right,
        price_abs_tol=Decimal("0.01"),
        return_tol_bps=Decimal(100),
    )
    assert report["outcome"] == "match"
    report = run(
        tmp_path,
        left,
        right,
        price_rel_tol=Decimal("0.01"),
        return_tol_bps=Decimal(100),
    )
    assert report["outcome"] == "match"


def test_return_difference_uses_real_endpoint_times(tmp_path):
    left, right = snapshot(), snapshot()
    right["records"][5]["close_price"] = "105.5"
    report = run(tmp_path, left, right)
    differences = [item for item in report["differences"] if item["field"] == "log_return"]
    assert len(differences) == 1
    assert datetime.fromisoformat(differences[0]["end_at"]) - datetime.fromisoformat(
        differences[0]["start_at"]
    ) == timedelta(minutes=5)
    assert differences[0]["start_at"] == (START + timedelta(minutes=1)).isoformat()


def test_large_real_move_is_not_deleted(tmp_path):
    data = snapshot()
    row = data["records"][6]
    row.update(open_price="499", high_price="501", low_price="498", close_price="500")
    assert run(tmp_path, data, data)["outcome"] == "match"


@pytest.mark.parametrize(
    "field,value",
    [
        ("venue", "aster"),
        ("source_symbol", "ETH"),
        ("base_asset", "ETH"),
        ("quote_asset", "USDT"),
        ("settle_asset", "USDT"),
        ("price_kind", "mark"),
        ("definition_sha256", "f" * 64),
        ("interval_seconds", 300),
        ("venue_instrument_version_id", 11),
    ],
)
def test_different_markets_versions_and_units_cannot_be_compared(tmp_path, field, value):
    left, right = snapshot(), snapshot()
    right["series"][field] = value
    with pytest.raises(ValueError):
        run(tmp_path, left, right)


@pytest.mark.parametrize("bad", [Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
def test_bad_tolerance_is_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        run(tmp_path, snapshot(), snapshot(), price_abs_tol=bad)


def test_cli_exit_codes_and_input_hashes(tmp_path, capsys):
    left, right = tmp_path / "left.json", tmp_path / "right.json"
    args = [
        str(left),
        str(right),
        "--start",
        START.isoformat(),
        "--end",
        END.isoformat(),
        "--as-of",
        AS_OF.isoformat(),
    ]
    data = snapshot()
    for path in (left, right):
        path.write_text(json.dumps(data))
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    expected_hash = hashlib.sha256(left.read_bytes()).hexdigest()
    assert report["sources"]["left"]["input_sha256"] == expected_hash
    data["records"] = []
    right.write_text(json.dumps(data))
    assert main(args) == 3
    capsys.readouterr()
    right.write_text('{"schema_version":1,"schema_version":1}')
    assert main(args) == 2
    assert json.loads(capsys.readouterr().err)["outcome"] == "invalid_input"


def test_naive_timestamp_is_not_assumed_utc(tmp_path):
    left, right = snapshot(), snapshot()
    right["records"][0]["observed_at"] = "2026-09-27T23:57:00"
    report = run(tmp_path, left, right)
    assert report["outcome"] == "incomplete"
    assert report["sources"]["right"]["findings"][0]["reason"] == "timestamp must be timezone-aware"


@pytest.mark.parametrize("value", ["not-a-number", "NaN"])
def test_cli_bad_numeric_option_is_argument_error(value):
    args = [
        "left.json",
        "right.json",
        "--start",
        START.isoformat(),
        "--end",
        END.isoformat(),
        "--as-of",
        AS_OF.isoformat(),
        "--price-abs-tol",
        value,
    ]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
