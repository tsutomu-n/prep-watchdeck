from __future__ import annotations

from prep_watchdeck.bitget.client import BitgetPublicClient
from prep_watchdeck.models import ContractInfo


async def fetch_contracts(client: BitgetPublicClient, product_type: str) -> list[ContractInfo]:
    payload = await client.get_json(
        "/api/v2/mix/market/contracts",
        {"productType": product_type},
    )
    return [
        ContractInfo.model_validate({**item, "productType": product_type})
        for item in payload.get("data", [])
    ]
