from __future__ import annotations

from prep_watchdeck.bitget.client import BitgetPublicClient
from prep_watchdeck.models import TickerInfo


async def fetch_all_tickers(client: BitgetPublicClient, product_type: str) -> list[TickerInfo]:
    payload = await client.get_json(
        "/api/v2/mix/market/tickers",
        {"productType": product_type},
    )
    return [TickerInfo.model_validate(item) for item in payload.get("data", [])]
