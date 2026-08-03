from __future__ import annotations

from typing import Any

from prep_watchdeck.vpi.models import VpiLitePlusResult


def serialize_vpi_result(result: VpiLitePlusResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "state": result.state.value,
        "score": result.score,
        "reasonCodes": list(result.reason_codes),
        "riskTagCodes": list(result.risk_tag_codes),
        "fundingState": result.funding_state.value,
        "openInterestState": result.open_interest_state.value,
        "dataQuality": result.data_quality.value,
        "dataAsOf": result.data_as_of,
    }


def build_vpi_snapshot_block(
    *,
    generated_at_ms: int,
    benchmarks: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "mode": "lite_plus_v0",
        "generatedAt": generated_at_ms,
        "benchmarks": benchmarks,
        "targets": targets,
    }
