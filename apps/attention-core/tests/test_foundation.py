from pathlib import Path

import pytest
from pydantic import ValidationError

from prep_watchdeck_attention.config import AttentionSettings, isolated_attention_state
from prep_watchdeck_attention.models import RawFeatureValue
from prep_watchdeck_attention.percentiles import midrank_percentiles


def test_state_isolation_and_reserved_ports(tmp_path):
    market, ranking = tmp_path / "market", tmp_path / "ranking"
    for state in (market, market / "child", tmp_path, ranking, Path.home(), Path("/")):
        with pytest.raises(ValueError):
            isolated_attention_state(state, market, ranking)
    link = tmp_path / "linked"
    market.mkdir()
    link.symlink_to(market, target_is_directory=True)
    with pytest.raises(ValueError):
        isolated_attention_state(link / "child", market, ranking)
    settings = AttentionSettings(tmp_path / "attention", market, ranking)
    assert settings.port == 8770
    for port in (80, 5432, 55432, 8769, 65536):
        with pytest.raises(ValueError):
            AttentionSettings(tmp_path / "attention", market, ranking, port=port)


def test_features_distinguish_zero_missing_and_nonfinite():
    good = dict(value=0, status="ready", reason=None, unit="pct", source="fixture")
    assert RawFeatureValue.model_validate(good).value == 0
    for delta in (
        {"value": None},
        {"value": float("nan")},
        {"value": float("inf")},
        {"reason": "missing"},
        {"unexpected": True},
        {"status": "missing"},
    ):
        with pytest.raises(ValidationError):
            RawFeatureValue.model_validate(good | delta)
    assert (
        RawFeatureValue(value=None, status="missing", reason="gap", source="fixture").value is None
    )


def test_midrank_ties_order_and_minimum_peers():
    values = {"d": 9.0, "a": 1.0, "c": 5.0, "b": 5.0}
    assert midrank_percentiles(values, minimum_peers=4) == {
        "a": 0.0,
        "b": 50.0,
        "c": 50.0,
        "d": 100.0,
    }
    assert midrank_percentiles(
        dict(reversed(list(values.items()))), minimum_peers=4
    ) == midrank_percentiles(values, minimum_peers=4)
    assert midrank_percentiles({"a": 0.0, "b": 0.0}, minimum_peers=2) == {"a": 50.0, "b": 50.0}
    with pytest.raises(ValueError, match="insufficient_peers"):
        midrank_percentiles(values, minimum_peers=20)
    with pytest.raises(ValueError):
        midrank_percentiles({"a": float("nan")}, minimum_peers=1)
