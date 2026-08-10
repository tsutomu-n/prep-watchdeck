from __future__ import annotations


def bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def priority_score(
    *,
    change_15m: float | None,
    volume_ratio_15m: float | None,
    turnover_1h: float | None,
    min_turnover_1h: float,
    btc_relative_15m: str,
    open_interest_state: str,
    data_quality: str,
    risk_tags: list[str],
) -> float:
    price_score = bounded(abs(change_15m or 0.0) / 5.0)
    volume_score = bounded((volume_ratio_15m or 0.0) / 5.0)
    turnover_score = bounded((turnover_1h or 0.0) / max(min_turnover_1h * 4.0, 1.0))
    btc_score = {"ALT_SPIKE": 1.0, "ALT_STRONG": 0.8, "ALT_WEAK": 0.3, "BTC_LINKED": 0.5}.get(
        btc_relative_15m,
        0.2,
    )
    oi_score = {"INCREASING": 1.0, "STABLE": 0.5, "DECREASING": 0.3}.get(open_interest_state, 0.0)
    data_score = 1.0 if data_quality == "OK" else 0.0
    penalty = 0.0
    for tag in risk_tags:
        penalty += {
            "TOO_ROUGH": 40.0,
            "THIN_SPIKE": 40.0,
            "FUNDING_OVERHEATED": 15.0,
            "DATA_NOT_OK": 100.0,
            "BTC_LINKED": 5.0,
        }.get(tag, 0.0)
    score = (
        25 * price_score
        + 25 * volume_score
        + 20 * turnover_score
        + 15 * btc_score
        + 10 * oi_score
        + 5 * data_score
        - penalty
    )
    return round(max(0.0, min(100.0, score)), 2)
