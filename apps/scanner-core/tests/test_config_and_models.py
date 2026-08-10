from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck.config.filter_config import OpenInterestConfig
from prep_watchdeck.config.templates import load_template
from prep_watchdeck.errors import ConfigError
from prep_watchdeck.models import CandleBar, ContractInfo, TickerInfo
from prep_watchdeck.settings import Settings


def test_rev5_templates_validate() -> None:
    config_dir = Path("../../config/scanner-filters")
    configs = {
        template: load_template(config_dir, template)
        for template in ["balanced", "conservative", "aggressive"]
    }
    config = configs["balanced"]

    assert config.candles.min_required_bars == 1177
    assert config.candles.bootstrap_days == 14
    assert config.user_rule.volume_74h_mode == "current_24h_vs_74h_ago_24h"
    assert config.data_quality.min_coverage_ratio == 0.98
    assert config.category.min_attention_score_for_display == 40
    assert configs["aggressive"].turnover.min_turnover_1h_usdt == 3000
    assert configs["aggressive"].volume.volume_leading_ratio == 2.0
    assert configs["aggressive"].roughness.warn_move_concentration_15m == 0.86


def test_unknown_template_fails() -> None:
    with pytest.raises(ConfigError):
        load_template(Path("../../config/scanner-filters"), "unknown")


def test_live_max_symbols_accepts_all(monkeypatch) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_LIVE_MAX_SYMBOLS", "all")

    settings = Settings()

    assert settings.live_max_symbols is None


def test_live_max_symbols_accepts_integer(monkeypatch) -> None:
    monkeypatch.setenv("PREP_WATCHDECK_LIVE_MAX_SYMBOLS", "100")

    settings = Settings()

    assert settings.live_max_symbols == 100


def test_bitget_models_parse_public_payloads() -> None:
    contract = ContractInfo.model_validate(
        {
            "symbol": "ALTUSDT",
            "productType": "USDT-FUTURES",
            "baseCoin": "ALT",
            "quoteCoin": "USDT",
            "symbolStatus": "normal",
            "minTradeUSDT": "5",
            "maxLever": "25",
            "isRwa": "no",
        }
    )
    ticker = TickerInfo.model_validate(
        {
            "symbol": "ALTUSDT",
            "ts": 1_781_000_000_000,
            "lastPr": "1.23",
            "change24h": "0.04",
            "usdtVolume": "1200000",
            "fundingRate": "0.0001",
            "holdingAmount": "100000",
        }
    )

    assert contract.product_type == "USDT-FUTURES"
    assert contract.min_trade_usdt == Decimal("5")
    assert contract.is_rwa is False
    assert ticker.last_price == Decimal("1.23")


def test_negative_volume_is_invalid() -> None:
    with pytest.raises(ValueError):
        CandleBar(
            symbol="ALTUSDT",
            ts=1_781_000_000_000,
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            base_vol=Decimal("1"),
            quote_vol=Decimal("-1"),
        )


@pytest.mark.parametrize("lookback", [0, -5, 7])
def test_open_interest_lookback_requires_positive_five_minute_multiple(lookback: int) -> None:
    with pytest.raises(ValueError):
        OpenInterestConfig(
            change_lookback_minutes=lookback,
            increase_threshold_pct=5.0,
            decrease_threshold_pct=-5.0,
        )


def test_open_interest_lookback_accepts_sixty_minutes() -> None:
    config = OpenInterestConfig(
        change_lookback_minutes=60,
        increase_threshold_pct=5.0,
        decrease_threshold_pct=-5.0,
    )

    assert config.change_lookback_minutes == 60
