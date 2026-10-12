from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime

import aiohttp

from prep_watchdeck_market.market_state import (
    MarketBatch,
    MarketObservation,
    finite_decimal,
    funding_per_hour,
    non_negative_decimal,
    positive_decimal,
)
from prep_watchdeck_market.models import CatalogInstrument, canonical_json_sha256
from prep_watchdeck_market.sources.common import (
    observed_now,
    positive_int,
    require_list,
    require_mapping,
    timestamp_from_milliseconds,
)
from prep_watchdeck_market.sources.mexc import fetch_mexc_json, mexc_data, mexc_quantity_multiplier
from prep_watchdeck_market.sources.mexc_funding import (
    MexcFundingSnapshot,
    funding_reason,
    funding_snapshot,
)

MEXC_L1_ENDPOINT = "/api/v1/contract/ticker"


async def fetch_mexc_l1(
    session: aiohttp.ClientSession,
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime | None = None,
    funding_snapshots: Mapping[str, MexcFundingSnapshot] | None = None,
) -> MarketBatch:
    selected = [i for i in instruments if i.venue == "mexc" and i.active]
    ticker = await fetch_mexc_json(session, "/api/v1/contract/ticker")
    return parse_mexc_l1(
        ticker,
        funding_snapshots or {},
        selected,
        cycle_at=cycle_at,
        observed_at=observed_at or observed_now(),
    )


def parse_mexc_l1(
    ticker_payload: object,
    funding_payloads: Mapping[str, object | MexcFundingSnapshot],
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketBatch:
    rows = require_list(mexc_data(ticker_payload), field_name="MEXC tickers")
    by_symbol = {r.get("symbol"): r for r in rows if isinstance(r, dict)}
    provenance: dict[str, object] = {}
    raw = {
        "fundingProvenance": provenance,
        "ticker": ticker_payload,
        "funding": {
            key: value.payload if isinstance(value, MexcFundingSnapshot) else value
            for key, value in funding_payloads.items()
        },
    }
    observations = []
    for item in instruments:
        if item.venue != "mexc" or not item.active:
            continue
        row = by_symbol.get(item.source_symbol, {})
        value = funding_payloads.get(item.source_symbol)
        snapshot = (
            value
            if isinstance(value, MexcFundingSnapshot)
            else funding_snapshot(value, item, observed_at=observed_at)
            if value is not None
            else None
        )
        reason = funding_reason(snapshot, item, observed_at)
        funding = (
            require_mapping(mexc_data(snapshot.payload), field_name="MEXC funding")
            if snapshot is not None and reason is None
            else {}
        )
        interval_hours = positive_int(funding.get("collectCycle"))
        interval = None if interval_hours is None else interval_hours * 3600
        rate = finite_decimal(funding.get("fundingRate"))
        mark = positive_decimal(row.get("fairPrice"))
        reference = positive_decimal(row.get("indexPrice"))
        bid, ask = positive_decimal(row.get("bid1")), positive_decimal(row.get("ask1"))
        if bid is not None and ask is not None and ask < bid:
            bid = ask = None
        oi = non_negative_decimal(row.get("holdVol"))
        base = None if oi is None else oi * mexc_quantity_multiplier(item)
        volume = non_negative_decimal(row.get("amount24"))
        next_at = timestamp_from_milliseconds(funding.get("nextSettleTime"))
        ticker_at = timestamp_from_milliseconds(row.get("timestamp"))
        source_at = ticker_at
        ticker_complete = (
            all(v is not None for v in (mark, reference, bid, ask, oi, base, volume, source_at))
            and source_at is not None
            and 0 <= (observed_at - source_at).total_seconds() <= 120
        )
        complete = ticker_complete and reason is None
        row_raw: dict[str, object] = {
            "ticker": row,
            "funding": None if snapshot is None else snapshot.payload,
            "fundingSourceAt": None
            if snapshot is None or snapshot.source_at is None
            else snapshot.source_at.isoformat(),
            "fundingObservedAt": None
            if snapshot is None or snapshot.observed_at is None
            else snapshot.observed_at.isoformat(),
            "fundingValidUntil": None
            if snapshot is None or snapshot.valid_until is None
            else snapshot.valid_until.isoformat(),
            "fundingErrorCode": reason,
            "fundingContractVersion": None if snapshot is None else snapshot.contract_version,
            "watchdeckBasePerContract": format(mexc_quantity_multiplier(item), "f"),
        }
        provenance[item.source_symbol] = {
            key: row_raw[key]
            for key in (
                "fundingSourceAt",
                "fundingObservedAt",
                "fundingValidUntil",
                "fundingErrorCode",
                "fundingContractVersion",
            )
        }
        observations.append(
            MarketObservation(
                item.venue_instrument_id,
                item.source_symbol,
                cycle_at,
                observed_at,
                source_at,
                "ready" if complete else "partial",
                mark,
                reference,
                "index" if reference else "none",
                bid,
                ask,
                rate,
                interval,
                funding_per_hour(rate, interval),
                next_at,
                oi,
                "contracts" if oi is not None else None,
                base,
                base * mark if base is not None and mark is not None else None,
                volume,
                "quote" if volume is not None else None,
                item.quote_asset,
                item.collateral_asset,
                canonical_json_sha256(row_raw),
                None
                if complete
                else (
                    "funding_only_partial:" + str(reason)
                    if ticker_complete
                    else "incomplete_source_row"
                ),
                row_raw,
                funding_source_at=None if snapshot is None else snapshot.source_at,
                funding_observed_at=None if snapshot is None else snapshot.observed_at,
                funding_valid_until=None if snapshot is None else snapshot.valid_until,
            )
        )
    return MarketBatch(
        "mexc",
        cycle_at,
        observed_at,
        MEXC_L1_ENDPOINT,
        canonical_json_sha256(raw),
        tuple(observations),
        raw,
    )
