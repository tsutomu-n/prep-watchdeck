from __future__ import annotations

import math
from dataclasses import dataclass

from prep_watchdeck.vpi.models import VpiState


@dataclass(frozen=True)
class VpiClassificationInput:
    score: float
    turnover_pressure: float
    thin_turnover: bool
    single_bar_suspect: bool
    data_stale: bool
    data_insufficient: bool


def classify_vpi_state(
    value: VpiClassificationInput,
    *,
    early_activity_score: float,
    active_move_score: float,
    reason_pressure_threshold: float,
) -> VpiState:
    if value.data_stale:
        return VpiState.DATA_STALE
    if value.data_insufficient:
        return VpiState.DATA_INSUFFICIENT
    if not math.isfinite(value.score) or not 0 <= value.score <= 100:
        return VpiState.UNKNOWN
    if value.single_bar_suspect and value.score >= early_activity_score:
        return VpiState.SINGLE_BAR_SUSPECT
    if value.thin_turnover and value.score >= early_activity_score:
        return VpiState.THIN_VOLATILITY
    if (
        value.score >= active_move_score
        and value.turnover_pressure >= reason_pressure_threshold
        and not value.thin_turnover
        and not value.single_bar_suspect
    ):
        return VpiState.ACTIVE_MOVE
    if value.score >= early_activity_score:
        return VpiState.EARLY_ACTIVITY
    return VpiState.CALM
