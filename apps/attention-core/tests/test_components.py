from test_inputs import NOW, bundle, metric_row, ranking

from prep_watchdeck_attention.components import ComponentPolicy, score_attention
from prep_watchdeck_attention.features import build_feature_generation


def test_component_missing_is_not_zero():
    generation, rows = build_feature_generation(
        bundle(rows=(metric_row(),)), ranking(), decision_at=NOW
    )
    response = score_attention(
        generation, rows, policy=ComponentPolicy(version="test", minimum_peers=1)
    )
    row = response.rows[0]
    assert row.ready_component_count == 4
    assert row.components["confluence"].score == 50
    missing = rows[0].reference_turnover_ratio15m.model_copy(
        update={"status": "missing", "value": None, "reason": "missing"}
    )
    rows = (
        rows[0].model_copy(
            update={"reference_turnover_ratio15m": missing, "reference_turnover_ratio1h": missing}
        ),
    )
    response = score_attention(
        generation, rows, policy=ComponentPolicy(version="test", minimum_peers=1)
    )
    assert response.rows[0].components["activity"].score is None
    assert response.rows[0].components["confluence"].score is None
    assert response.rows[0].ready_component_count == 3


def test_component_raw_policy_direction_order_and_comparability():
    from prep_watchdeck_attention.models import content_digest

    generation, rows = build_feature_generation(
        bundle(rows=(metric_row(),)), ranking(), decision_at=NOW
    )
    base = rows[0]

    def value(raw, number):
        return raw.model_copy(update={"value": number, "status": "ready", "reason": None})

    first = base.model_copy(
        update={
            "reference_return15m": value(base.reference_return15m, -5),
            "reference_return1h": value(base.reference_return1h, 5),
            "reference_turnover_ratio15m": value(base.reference_turnover_ratio15m, 4),
            "reference_turnover_ratio1h": value(base.reference_turnover_ratio1h, 6),
            "oi_change15m_median": value(base.oi_change15m_median, -7),
            "oi_change1h_median": value(base.oi_change1h_median, 3),
        }
    )
    second = base.model_copy(update={"asset_id": "asset:AAA"})
    policy = ComponentPolicy(version="test", minimum_peers=2)
    response = score_attention(generation, (second, first), policy=policy)
    btc = next(r for r in response.rows if r.asset_id == "asset:BTC")
    assert btc.components["movement"].raw_value == 5
    assert btc.components["movement"].direction == "down"
    assert btc.components["activity"].raw_value == 6
    assert btc.components["positioning"].raw_value == 7
    assert btc.components["dislocation"].raw_value == 200
    assert response.rows[0].asset_id == "asset:BTC"
    assert response == score_attention(generation, (first, second), policy=policy)
    later = generation.model_copy(
        update={
            "generation_id": content_digest("later"),
            "decision_at": generation.decision_at + 60000,
        }
    )
    later_rows = tuple(
        r.model_copy(update={"decision_at": later.decision_at}) for r in (first, second)
    )
    compared = score_attention(later, later_rows, policy=policy, previous=response)
    assert all(r.components["movement"].rank_change == 0 for r in compared.rows)
    changed = score_attention(
        later, later_rows, policy=ComponentPolicy(version="new", minimum_peers=2), previous=response
    )
    assert all(r.components["movement"].rank_change is None for r in changed.rows)
