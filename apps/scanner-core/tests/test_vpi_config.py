from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from prep_watchdeck.config.vpi_config import VpiConfig, load_vpi_config
from prep_watchdeck.errors import ConfigError


def valid_config_data() -> dict[str, object]:
    return {
        "enabled": True,
        "benchmark_symbols": ["BTCUSDT", "ETHUSDT"],
        "target_symbols": ["SOLUSDT"],
        "target_order_notional_usd": 300.0,
        "min_required_1m_bars": 120,
        "stale_after_seconds": 180,
        "fast_half_life_bars": 5.0,
        "slow_half_life_bars": 30.0,
        "reason_pressure_threshold": 1.5,
        "early_activity_score": 35.0,
        "active_move_score": 65.0,
        "thin_turnover_notional_multiple": 20.0,
        "single_bar_concentration_threshold": 0.70,
        "funding_overheated_abs_rate": 0.001,
    }


def test_repository_vpi_config_loads_with_expected_defaults() -> None:
    config = load_vpi_config(Path("../../config/vpi-lite-plus.toml"))

    assert config.enabled is True
    assert config.benchmark_symbols == ("BTCUSDT", "ETHUSDT")
    assert config.target_symbols == ("SOLUSDT",)
    assert config.min_required_1m_bars == 120
    assert config.fast_half_life_bars == 5.0
    assert config.slow_half_life_bars == 30.0


def test_vpi_config_normalizes_symbols_before_duplicate_checks() -> None:
    data = valid_config_data()
    data["benchmark_symbols"] = [" btcusdt ", "ETHUSDT"]
    data["target_symbols"] = [" solusdt "]

    config = VpiConfig.model_validate(data)

    assert config.benchmark_symbols == ("BTCUSDT", "ETHUSDT")
    assert config.target_symbols == ("SOLUSDT",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("benchmark_symbols", ["BTCUSDT", "btcusdt"]),
        ("target_symbols", ["SOLUSDT", "solusdt"]),
        ("benchmark_symbols", ["BTCUSDT", ""]),
        ("target_symbols", []),
    ],
)
def test_vpi_config_rejects_duplicate_or_empty_symbols(field: str, value: object) -> None:
    data = valid_config_data()
    data[field] = value

    with pytest.raises(ValidationError):
        VpiConfig.model_validate(data)


def test_vpi_config_rejects_benchmark_target_overlap() -> None:
    data = valid_config_data()
    data["target_symbols"] = ["ethusdt"]

    with pytest.raises(ValidationError, match="overlap"):
        VpiConfig.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_order_notional_usd", 0),
        ("min_required_1m_bars", 0),
        ("stale_after_seconds", 0),
        ("fast_half_life_bars", -1),
        ("slow_half_life_bars", 0),
        ("reason_pressure_threshold", 0),
        ("reason_pressure_threshold", float("inf")),
        ("thin_turnover_notional_multiple", 0),
        ("funding_overheated_abs_rate", 0),
        ("single_bar_concentration_threshold", 1.1),
        ("early_activity_score", -0.1),
        ("active_move_score", 100.1),
    ],
)
def test_vpi_config_rejects_invalid_scalar_constraints(field: str, value: object) -> None:
    data = valid_config_data()
    data[field] = value

    with pytest.raises(ValidationError):
        VpiConfig.model_validate(data)


@pytest.mark.parametrize(
    ("fast", "slow", "early", "active"),
    [(30.0, 30.0, 35.0, 65.0), (31.0, 30.0, 35.0, 65.0), (5.0, 30.0, 65.0, 65.0)],
)
def test_vpi_config_rejects_invalid_ordering(
    fast: float, slow: float, early: float, active: float
) -> None:
    data = valid_config_data()
    data.update(
        fast_half_life_bars=fast,
        slow_half_life_bars=slow,
        early_activity_score=early,
        active_move_score=active,
    )

    with pytest.raises(ValidationError):
        VpiConfig.model_validate(data)


def test_vpi_config_rejects_unknown_fields_and_accepts_disabled() -> None:
    data = valid_config_data()
    data["enabled"] = False
    data["invented"] = True

    with pytest.raises(ValidationError):
        VpiConfig.model_validate(data)

    data.pop("invented")
    assert VpiConfig.model_validate(data).enabled is False


def test_vpi_config_loader_wraps_parse_errors(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text("enabled = [", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid VPI config"):
        load_vpi_config(path)
