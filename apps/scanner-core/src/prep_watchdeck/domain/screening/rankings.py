from __future__ import annotations

from typing import Any

from prep_watchdeck.domain.dto import ScannerRowDTO

RankingItem = dict[str, float | str]
RankingBucket = dict[str, list[RankingItem]]
RankingMetaItem = dict[str, bool | int]
RankingMetaBucket = dict[str, RankingMetaItem]
RankingTree = dict[str, Any]


def build_rankings(rows: list[ScannerRowDTO], top_n: int = 10) -> RankingTree:
    timeframes: dict[str, RankingBucket] = {}
    meta_timeframes: dict[str, RankingMetaBucket] = {}
    candidate_rows = [
        row for row in rows if row.category != "NO_TRADE" and row.user_rule_74h_matched is True
    ]
    for tf in ("5m", "15m", "1h", "4h", "24h", "74h"):
        metrics = {
            "changeUp": (lambda row, tf=tf: row.change_pct_by_tf.get(tf), True),
            "changeDown": (lambda row, tf=tf: row.change_pct_by_tf.get(tf), False),
            "volumeUp": (lambda row, tf=tf: row.volume_ratio_by_tf.get(tf), True),
            "turnoverTop": (lambda row, tf=tf: row.turnover_usdt_by_tf.get(tf), True),
        }
        timeframes[tf] = {
            metric: _rank(candidate_rows, getter, reverse=reverse, top_n=top_n)
            for metric, (getter, reverse) in metrics.items()
        }
        meta_timeframes[tf] = {
            metric: _meta(candidate_rows, getter, top_n=top_n)
            for metric, (getter, _reverse) in metrics.items()
        }
    return {
        "timeframes": timeframes,
        "noTrade": [_no_trade_item(row) for row in rows if row.category == "NO_TRADE"],
        "meta": {"timeframes": meta_timeframes},
    }


def _rank(rows: list[ScannerRowDTO], getter, reverse: bool, top_n: int) -> list[RankingItem]:
    ranked = [
        {"symbol": row.symbol, "value": value} for row in rows if (value := getter(row)) is not None
    ]
    return sorted(ranked, key=lambda item: float(item["value"]), reverse=reverse)[:top_n]


def _meta(rows: list[ScannerRowDTO], getter, top_n: int) -> RankingMetaItem:
    total_eligible = sum(1 for row in rows if getter(row) is not None)
    return {"limit": top_n, "totalEligible": total_eligible, "excludedNoTrade": True}


def candidate_rule_counts(rows: list[ScannerRowDTO]) -> dict[str, int]:
    source = [row for row in rows if row.category != "NO_TRADE"]
    return {
        "eligible": sum(row.user_rule_74h_matched is True for row in source),
        "notMatched": sum(row.user_rule_74h_matched is False for row in source),
        "unknown": sum(row.user_rule_74h_matched is None for row in source),
    }


def _no_trade_item(row: ScannerRowDTO) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "category": row.category.value,
        "priorityScore": row.attention_score,
        "changePct": row.change_pct_by_tf.get("15m"),
        "volumeRatio": row.volume_ratio_by_tf.get("15m"),
        "turnoverUsdt": row.turnover_usdt_by_tf.get("15m"),
        "label": row.label,
    }
