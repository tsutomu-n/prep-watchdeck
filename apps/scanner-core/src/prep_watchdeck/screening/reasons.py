from __future__ import annotations


def build_risk_tags(
    *,
    label: str,
    roughness_15m: str,
    funding_bias: str,
    btc_relative_15m: str,
    data_quality: str,
) -> list[str]:
    tags: list[str] = []
    if label == "THIN_SPIKE":
        tags.append("THIN_SPIKE")
    if roughness_15m == "TOO_ROUGH":
        tags.append("TOO_ROUGH")
    if funding_bias == "OVERHEATED":
        tags.append("FUNDING_OVERHEATED")
    if btc_relative_15m == "BTC_LINKED":
        tags.append("BTC_LINKED")
    if data_quality != "OK":
        tags.append("DATA_NOT_OK")
    return tags


def build_reason(label: str, risk_tags: list[str]) -> str:
    if risk_tags:
        return f"{label}: risk={','.join(risk_tags)}"
    return label
