# Decision 0015: Independent Attention Core

timestamp="2026-10-09(金)_00:39 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-09T00:39:16+09:00`
- 状態: `設計判断`

Attention is a separate Python app and dedicated SQLite state. Market artifacts and the Ranking loopback API are read-only inputs; neither Core writer, manual selection nor Provider acquisition is extended.

Component scores describe relative attention, separately from quality and coverage. Immutable prospective snapshots and versioned outcomes support frozen candidate-family comparisons. Hot-set allocation is shadow recommendation only. Actual capture requires a separate decision and acceptance of capacity, leases, manual priority and rollback.

The first component policy uses the supplied raw maxima (including OI/funding/spread values with distinct units) followed by per-component midrank percentiles. It is a versioned heuristic, not a calibrated probability or proof of predictive value. Changes require a new policy/family.

No production service operation is authorized by this source implementation. Attention can be disabled while existing Market/Ranking and manual selection continue.


Outcomeの基準はRankingの入力時刻ではなく、判断時刻以後の最初の1分境界とする。offline exportにその境界の確定終値を要求し、後続の完全な15/60本だけを評価する。これは判断時刻をまたぐ足の高安や、古い参照終値からの既知の値動きを未来のedgeと誤認しないためである。元のRanking cutoffはinput provenanceに残す。lead timeは判断時刻から測る。

UTC dayのjoint single-step max-Tと6h感度分析は`attention-family-max-t-v1`の近似手法であり、論文どおりのWhite/SPA/Romano-Wolf検定という主張はしない。day間の弱い依存、十分なblock、非定常性、complete-case選択の制約を持つ。参考一次資料: [Romano and Wolf, Exact and Approximate Stepdown Methods for Multiple Hypothesis Testing](https://www.econ.uzh.ch/dam/jcr:ffffffff-935a-b0d6-ffff-ffffd823d949/jasa.pdf)。power/MDEは計画用で、採用判定はcoverageとfamily-adjusted evidenceによる。
