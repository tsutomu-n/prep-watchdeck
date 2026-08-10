from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol

from prep_watchdeck.config.filter_config import FilterConfig
from prep_watchdeck.domain.service_models import (
    BootstrapResult,
    InstrumentRecord,
    TickerLatestRecord,
)
from prep_watchdeck.domain.symbols import is_safe_public_symbol
from prep_watchdeck.models import ContractInfo, TickerInfo
from prep_watchdeck.screening.categories import contract_is_valid, universe_symbols


class UniverseFetcher(Protocol):
    async def fetch_contracts(self, product_type: str) -> list[ContractInfo]:
        """Fetch futures contract metadata."""

    async def fetch_tickers(self, product_type: str) -> list[TickerInfo]:
        """Fetch latest ticker data."""


class UniverseStore(Protocol):
    def upsert_instruments(self, instruments: list[InstrumentRecord]) -> None:
        """Persist instruments."""

    def upsert_ticker_latest(self, tickers: list[TickerLatestRecord]) -> None:
        """Persist latest ticker rows."""


async def bootstrap_universe(
    *,
    store: UniverseStore,
    fetcher: UniverseFetcher,
    config: FilterConfig,
    template: str,
    max_symbols: int | None,
    now_ms: int | None = None,
) -> BootstrapResult:
    updated_at_ms = int(time.time() * 1000) if now_ms is None else now_ms
    product_type = config.universe.product_type
    contracts = await fetcher.fetch_contracts(product_type)
    tickers = await fetcher.fetch_tickers(product_type)
    supported_contracts = [
        contract for contract in contracts if is_safe_public_symbol(contract.symbol)
    ]
    supported_tickers = [ticker for ticker in tickers if is_safe_public_symbol(ticker.symbol)]
    selected_symbols = universe_symbols(config, supported_contracts, supported_tickers)
    valid_symbols = _valid_stream_symbols(supported_contracts, supported_tickers)
    if max_symbols is not None:
        selected_symbols = selected_symbols[:max_symbols]

    store.upsert_instruments(
        [_instrument_from_contract(item, updated_at_ms) for item in supported_contracts]
    )
    store.upsert_ticker_latest(
        ticker_latest_records(supported_tickers, updated_at_ms=updated_at_ms)
    )

    return BootstrapResult(
        product_type=product_type,
        template=template,
        fetched_contract_count=len(contracts),
        fetched_ticker_count=len(tickers),
        selected_symbols=selected_symbols,
        valid_symbols=valid_symbols,
    )


def _instrument_from_contract(contract: ContractInfo, updated_at_ms: int) -> InstrumentRecord:
    return InstrumentRecord(
        symbol=contract.symbol,
        product_type=contract.product_type,
        symbol_type=contract.symbol_type,
        symbol_status=contract.symbol_status,
        base_coin=contract.base_coin,
        quote_coin=contract.quote_coin,
        max_leverage=float(contract.max_lever) if contract.max_lever is not None else None,
        min_trade_num=None,
        is_rwa=contract.is_rwa,
        updated_at_ms=updated_at_ms,
    )


async def refresh_ticker_latest_periodically(
    *,
    store: UniverseStore,
    fetcher: Callable[[str], Awaitable[list[TickerInfo]]],
    product_type: str,
    interval_seconds: float,
    publish_immediately: bool,
    ticker_sink: Callable[[list[TickerLatestRecord]], None] | None,
    on_error: Callable[[Exception], None],
    now_ms_provider: Callable[[], int] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    now_ms_provider = now_ms_provider or (lambda: int(time.time() * 1000))
    if not publish_immediately:
        await sleep(interval_seconds)
    while True:
        try:
            tickers = await fetcher(product_type)
            records = ticker_latest_records(tickers, updated_at_ms=now_ms_provider())
            await asyncio.to_thread(store.upsert_ticker_latest, records)
            if ticker_sink is not None:
                ticker_sink(records)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            on_error(exc)
        await sleep(interval_seconds)


def ticker_latest_records(
    tickers: Iterable[TickerInfo], *, updated_at_ms: int
) -> list[TickerLatestRecord]:
    return [
        _ticker_latest_from_ticker(ticker, updated_at_ms)
        for ticker in tickers
        if is_safe_public_symbol(ticker.symbol)
    ]


def _ticker_latest_from_ticker(ticker: TickerInfo, updated_at_ms: int) -> TickerLatestRecord:
    return TickerLatestRecord(
        symbol=ticker.symbol,
        ts_ms=ticker.ts or updated_at_ms,
        last_price=float(ticker.last_price) if ticker.last_price is not None else None,
        high_24h=float(ticker.high_24h) if ticker.high_24h is not None else None,
        low_24h=float(ticker.low_24h) if ticker.low_24h is not None else None,
        change_24h=float(ticker.change_24h) if ticker.change_24h is not None else None,
        funding_rate=float(ticker.funding_rate) if ticker.funding_rate is not None else None,
        holding_amount=float(ticker.holding_amount) if ticker.holding_amount is not None else None,
        quote_volume_24h=float(ticker.usdt_volume_24h)
        if ticker.usdt_volume_24h is not None
        else None,
        updated_at_ms=updated_at_ms,
    )


def _valid_stream_symbols(contracts: list[ContractInfo], tickers: list[TickerInfo]) -> list[str]:
    contract_map = {contract.symbol: contract for contract in contracts}
    symbols: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        symbol = ticker.symbol
        contract = contract_map.get(symbol)
        if contract is None or not contract_is_valid(contract) or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols
