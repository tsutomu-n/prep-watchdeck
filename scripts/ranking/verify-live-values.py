"""Compare one frozen generation against public REST using separate Decimal arithmetic."""

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path

import aiohttp


async def verify(port: int, output: Path) -> None:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20), trust_env=False
    ) as session:
        snapshots = []
        for period in ("15m", "1h", "daily"):
            async with session.get(
                f"http://127.0.0.1:{port}/rankings",
                params={"period": period, "order": "turnover", "dailyReferenceJst": "00:00"},
            ) as response:
                response.raise_for_status()
                snapshots.append(await response.json())
        assert len({item["generationId"] for item in snapshots}) == 1, "generation changed; rerun"
        samples = []
        for provider in ("bybit", "binance"):
            selected = next(
                row
                for row in snapshots[0]["rows"]
                if row["state"] == "ready" and row["reference"]["provider"] == provider
            )
            symbol = selected["reference"]["symbol"]
            cutoff = snapshots[0]["cutoff"]
            first = min(item["anchor"] for item in snapshots)
            bars = {}
            raw = []
            end = cutoff
            for _ in range(2):
                start = max(first, end - 999 * 60_000) - 60_000
                url = (
                    "https://api.bybit.com/v5/market/kline"
                    if provider == "bybit"
                    else "https://fapi.binance.com/fapi/v1/klines"
                )
                params = (
                    {
                        "category": "linear",
                        "symbol": symbol,
                        "interval": "1",
                        "start": start,
                        "end": end - 1,
                        "limit": 1000,
                    }
                    if provider == "bybit"
                    else {
                        "symbol": symbol,
                        "interval": "1m",
                        "startTime": start,
                        "endTime": end - 1,
                        "limit": 1000,
                    }
                )
                async with session.get(url, params=params, allow_redirects=False) as response:
                    response.raise_for_status()
                    payload = await response.json()
                raw.append({"url": url, "params": params, "body": payload})
                entries = payload["result"]["list"] if provider == "bybit" else payload
                for row in entries:
                    timestamp = int(row[0]) + 60_000
                    if first <= timestamp <= cutoff:
                        bars[timestamp] = (
                            Decimal(str(row[4])),
                            Decimal(str(row[6 if provider == "bybit" else 7])),
                        )
                end = min(bars) - 60_000
                if end < first:
                    break
            comparisons = []
            for snapshot in snapshots:
                actual = next(row for row in snapshot["rows"] if row["id"] == selected["id"])
                anchor = snapshot["anchor"]
                expected_return = (bars[cutoff][0] / bars[anchor][0] - 1) * 100
                expected_turnover = sum(
                    bars[t][1] for t in range(anchor + 60_000, cutoff + 1, 60_000)
                )
                return_error = abs(Decimal(str(actual["returnPct"])) - expected_return)
                volume_error = abs(Decimal(str(actual["quoteTurnover"])) - expected_turnover)
                passed = return_error < Decimal("0.00000001") and volume_error < max(
                    Decimal("0.01"), expected_turnover * Decimal("0.000000001")
                )
                comparisons.append(
                    {
                        "period": snapshot["period"],
                        "anchor": anchor,
                        "expectedReturn": str(expected_return),
                        "expectedTurnover": str(expected_turnover),
                        "actualReturn": actual["returnPct"],
                        "actualTurnover": actual["quoteTurnover"],
                        "returnError": str(return_error),
                        "turnoverError": str(volume_error),
                        "passed": passed,
                    }
                )
            samples.append(
                {"provider": provider, "symbol": symbol, "raw": raw, "comparisons": comparisons}
            )
        output.write_text(
            json.dumps(
                {
                    "generationId": snapshots[0]["generationId"],
                    "cutoff": cutoff,
                    "samples": samples,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        summaries = [
            {"provider": s["provider"], "symbol": s["symbol"], "comparisons": s["comparisons"]}
            for s in samples
        ]
        print(json.dumps(summaries))
        assert all(c["passed"] for s in samples for c in s["comparisons"]), "REST values differ"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in (5432, 55432):
        parser.error("use the dedicated ranking port")
    asyncio.run(verify(args.port, args.output))
