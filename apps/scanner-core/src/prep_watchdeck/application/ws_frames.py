from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from prep_watchdeck.domain.service_models import Candle1mRecord, TickerLatestRecord

WsChannel = Literal["ticker", "candle1m"]
NumberInput = str | int | float


@dataclass(frozen=True)
class ChannelSpec:
    inst_type: str
    channel: WsChannel
    inst_id: str

    def to_arg(self) -> dict[str, str]:
        return {
            "instType": self.inst_type,
            "channel": self.channel,
            "instId": self.inst_id,
        }


@dataclass(frozen=True)
class ParsedWsFrame:
    tickers: list[TickerLatestRecord] = field(default_factory=list)
    candles_1m: list[Candle1mRecord] = field(default_factory=list)


def parse_ws_frame(payload: Mapping[str, Any]) -> ParsedWsFrame:
    event = payload.get("event")
    if event == "error":
        code = _optional_text(payload.get("code")) or "unknown"
        message = _optional_text(payload.get("msg")) or "unknown"
        raise ValueError(f"websocket error {code}: {message}")

    data = payload.get("data")
    if data is None:
        return ParsedWsFrame()

    rows = _as_rows(data)
    if not rows:
        return ParsedWsFrame()

    arg = _as_mapping(payload.get("arg"), "arg")
    channel = _required_text(arg.get("channel"), "arg.channel")

    if channel == "ticker":
        return ParsedWsFrame(tickers=_parse_ticker_rows(arg, payload, rows))
    if channel == "candle1m":
        return ParsedWsFrame(candles_1m=_parse_candle_rows(arg, payload, rows))

    raise ValueError(f"unsupported websocket channel: {channel}")


def build_channel_specs(
    symbols: Iterable[str],
    *,
    inst_type: str = "USDT-FUTURES",
    include_ticker: bool = True,
    include_candle1m: bool = True,
) -> list[ChannelSpec]:
    specs: list[ChannelSpec] = []
    for symbol in _normalize_symbols(symbols):
        if include_ticker:
            specs.append(ChannelSpec(inst_type=inst_type, channel="ticker", inst_id=symbol))
        if include_candle1m:
            specs.append(ChannelSpec(inst_type=inst_type, channel="candle1m", inst_id=symbol))
    return specs


def shard_channel_specs(
    specs: Sequence[ChannelSpec],
    *,
    max_channels: int = 48,
) -> list[list[ChannelSpec]]:
    if max_channels < 1 or max_channels >= 50:
        raise ValueError("max_channels must be between 1 and 49")
    return [
        list(specs[index : index + max_channels]) for index in range(0, len(specs), max_channels)
    ]


def _parse_ticker_rows(
    arg: Mapping[str, Any],
    payload: Mapping[str, Any],
    rows: Sequence[Any],
) -> list[TickerLatestRecord]:
    tickers: list[TickerLatestRecord] = []
    for row in rows:
        item = _as_mapping(row, "ticker row")
        symbol = _normalize_symbol(
            _first_present(item.get("symbol"), item.get("instId"), arg.get("instId"))
        )
        tickers.append(
            TickerLatestRecord(
                symbol=symbol,
                ts_ms=_required_int(
                    _first_present(item.get("ts"), payload.get("ts")),
                    "ticker ts",
                ),
                last_price=_optional_float(item.get("lastPr")),
                bid_price=_optional_float(item.get("bidPr")),
                ask_price=_optional_float(item.get("askPr")),
                high_24h=_optional_float(item.get("high24h")),
                low_24h=_optional_float(item.get("low24h")),
                change_24h=_optional_float(item.get("change24h")),
                funding_rate=_optional_float(item.get("fundingRate")),
                next_funding_time_ms=_optional_int(item.get("nextFundingTime")),
                mark_price=_optional_float(item.get("markPrice")),
                index_price=_optional_float(item.get("indexPrice")),
                holding_amount=_optional_float(item.get("holdingAmount")),
                base_volume_24h=_optional_float(item.get("baseVolume")),
                quote_volume_24h=_optional_float(item.get("quoteVolume")),
                open_utc=_optional_float(item.get("openUtc")),
                updated_at_ms=_required_int(
                    _first_present(payload.get("ts"), item.get("ts")),
                    "ticker updated ts",
                ),
            )
        )
    return tickers


def _parse_candle_rows(
    arg: Mapping[str, Any],
    payload: Mapping[str, Any],
    rows: Sequence[Any],
) -> list[Candle1mRecord]:
    symbol = _normalize_symbol(arg.get("instId"))
    candles: list[Candle1mRecord] = []
    for row in rows:
        values = _as_sequence(row, "candle row")
        if len(values) < 8:
            raise ValueError("candle1m row must contain ts, OHLC, base, quote, and USDT volume")
        candles.append(
            Candle1mRecord(
                symbol=symbol,
                ts_ms=_required_int(values[0], "candle ts"),
                open=_required_float(values[1], "candle open"),
                high=_required_float(values[2], "candle high"),
                low=_required_float(values[3], "candle low"),
                close=_required_float(values[4], "candle close"),
                base_volume=_optional_float(values[5]),
                quote_volume=_optional_float(values[6]),
                usdt_volume=_optional_float(values[7]),
                is_closed=_optional_closed_flag(values[8] if len(values) > 8 else None),
                source="ws-candle1m",
                updated_at_ms=_required_int(
                    _first_present(payload.get("ts"), values[0]),
                    "candle updated ts",
                ),
            )
        )
    return candles


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})


def _normalize_symbol(value: object) -> str:
    symbol = _required_text(value, "symbol").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    return symbol


def _as_rows(data: object) -> list[Any]:
    if isinstance(data, Mapping):
        return [data]
    if isinstance(data, Sequence) and not isinstance(data, str | bytes):
        return list(data)
    raise ValueError("websocket data must be an object or array")


def _as_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"{field_name} must be an object")


def _as_sequence(value: object, field_name: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    raise ValueError(f"{field_name} must be an array")


def _first_present(*values: object) -> object:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _required_text(value: object, field_name: str) -> str:
    if isinstance(value, str):
        return value
    raise ValueError(f"{field_name} must be a string")


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_closed_flag(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "closed", "yes"}
    if isinstance(value, int | float):
        return bool(value)
    return False


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(_number_input(value, "number"))


def _required_float(value: object, field_name: str) -> float:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    return float(_number_input(value, field_name))


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(_number_input(value, "number"))


def _required_int(value: object, field_name: str) -> int:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    return int(_number_input(value, field_name))


def _number_input(value: object, field_name: str) -> NumberInput:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    if isinstance(value, str | int | float):
        return value
    raise ValueError(f"{field_name} must be numeric")
