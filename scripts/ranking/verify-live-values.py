"""Compare one frozen generation against public REST using separate Decimal arithmetic."""

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from statistics import median

import aiohttp


async def verify(port: int | None, output: Path, snapshot: Path | None, assets: list[str]) -> None:
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20), trust_env=False
    ) as session:
        snapshots = []
        saved = json.loads(snapshot.read_text()) if snapshot else None
        for period in ("15m", "1h", "daily"):
            if saved is not None:
                snapshots.append(saved[period])
            else:
                async with session.get(
                    f"http://127.0.0.1:{port}/rankings",
                    params={"period": period, "order": "turnover", "dailyReferenceJst": "00:00"},
                ) as response:
                    response.raise_for_status()
                    snapshots.append(await response.json())
        assert len({item["generationId"] for item in snapshots}) == 1, "generation changed; rerun"
        samples = []
        selected_rows = [
            next(
                row
                for row in snapshots[0]["rows"]
                if row["state"] == "ready"
                and row["reference"]["provider"] == provider
                and row["turnoverRatio"]["status"] == row["dayRangePosition"]["status"] == "ready"
            )
            for provider in ("bybit", "binance")
        ]
        multiplied = next(
            (
                row
                for row in snapshots[0]["rows"]
                if row["reference"]
                and row["reference"]["multiplier"] > 1
                and row["state"] == "ready"
                and row["turnoverRatio"]["status"] == row["dayRangePosition"]["status"] == "ready"
            ),
            None,
        )
        if multiplied and multiplied["id"] not in {row["id"] for row in selected_rows}:
            selected_rows.append(multiplied)
        for asset in assets:
            selected = next(row for row in snapshots[0]["rows"] if row["asset"] == asset)
            assert selected["state"] == "ready", f"requested asset is not ready: {asset}"
            assert selected["reference"] is not None, f"requested asset has no reference: {asset}"
            if selected["id"] not in {row["id"] for row in selected_rows}:
                selected_rows.append(selected)
        for selected in selected_rows:
            provider = selected["reference"]["provider"]
            symbol = selected["reference"]["symbol"]
            cutoff = snapshots[0]["cutoff"]
            first = cutoff - 1440 * 60_000
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
                            Decimal(str(row[2])),
                            Decimal(str(row[3])),
                        )
                end = min(bars) - 60_000
                if end < first:
                    break
            comparisons = []
            day_start = (cutoff + 9 * 3_600_000) // 86_400_000 * 86_400_000 - 9 * 3_600_000
            day_bars = [bars[t] for t in range(day_start + 60_000, cutoff + 1, 60_000)]
            high, low = max(bar[2] for bar in day_bars), min(bar[3] for bar in day_bars)
            expected_position = 100 * (bars[cutoff][0] - low) / (high - low)
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
                position_error = abs(
                    Decimal(str(actual["dayRangePosition"]["value"])) - expected_position
                )
                passed = (
                    passed
                    and actual["dayRangePosition"]["status"] == "ready"
                    and position_error < Decimal("0.00000001")
                )
                expected_ratio = None
                baseline = None
                ratio_error = None
                if snapshot["period"] != "daily":
                    width = (15 if snapshot["period"] == "15m" else 60) * 60_000
                    windows = [
                        sum(bars[t][1] for t in range(a + 60_000, a + width + 1, 60_000))
                        for a in range(first, cutoff, width)
                    ]
                    baseline = median(windows[:-1])
                    expected_ratio = windows[-1] / baseline
                    ratio_error = abs(
                        Decimal(str(actual["turnoverRatio"]["value"])) - expected_ratio
                    )
                    passed = (
                        passed
                        and actual["turnoverRatio"]["status"] == "ready"
                        and ratio_error < Decimal("0.00000001")
                    )
                else:
                    passed = (
                        passed
                        and actual["turnoverRatio"]["status"] == "unsupported_period"
                        and actual["turnoverRatio"]["value"] is None
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
                        "baselineQuoteTurnover": str(baseline) if baseline is not None else None,
                        "expectedTurnoverRatio": str(expected_ratio)
                        if expected_ratio is not None
                        else None,
                        "actualTurnoverRatio": actual["turnoverRatio"],
                        "turnoverRatioError": str(ratio_error) if ratio_error is not None else None,
                        "dayStart": day_start,
                        "dayHigh": str(high),
                        "dayLow": str(low),
                        "endClose": str(bars[cutoff][0]),
                        "expectedDayPosition": str(expected_position),
                        "actualDayPosition": actual["dayRangePosition"],
                        "dayPositionError": str(position_error),
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
                    "mapVersion": snapshots[0]["mapVersion"],
                    "metricVersion": snapshots[0]["metricVersion"],
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--port", type=int)
    source.add_argument(
        "--snapshot", type=Path, help="saved acceptance generation with all periods"
    )
    parser.add_argument("--asset", action="append", default=[], help="additional required asset")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.port is not None and (not 1024 <= args.port <= 65535 or args.port in (5432, 55432)):
        parser.error("use the dedicated ranking port")
    asyncio.run(verify(args.port, args.output, args.snapshot, args.asset))
