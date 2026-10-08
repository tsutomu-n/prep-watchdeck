# Decision 0015: Independent Attention Core

timestamp="2026-10-08(木)_23:47 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-08T23:47:49+09:00`
- 状態: `設計判断`

Attention is a separate Python app and dedicated SQLite state. Market artifacts and the Ranking loopback API are read-only inputs; neither Core writer, manual selection nor Provider acquisition is extended.

Component scores describe relative attention, separately from quality and coverage. Immutable prospective snapshots and versioned outcomes support frozen candidate-family comparisons. Hot-set allocation is shadow recommendation only. Actual capture requires a separate decision and acceptance of capacity, leases, manual priority and rollback.

The first component policy uses the supplied raw maxima (including OI/funding/spread values with distinct units) followed by per-component midrank percentiles. It is a versioned heuristic, not a calibrated probability or proof of predictive value. Changes require a new policy/family.

No production service operation is authorized by this source implementation. Attention can be disabled while existing Market/Ranking and manual selection continue.
