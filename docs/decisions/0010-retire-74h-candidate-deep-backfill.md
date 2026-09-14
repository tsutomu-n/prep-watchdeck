# Decision 0010: Candidate・74h・常駐deep backfillの退役

- 作成: `2026-08-12T21:38:47+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **旧scannerの履歴:** このDecisionは旧Candidate/74h pipelineを当時のproductionから退役させた記録である。
> Decision 0011で旧scanner production contract自体が置換され、Decision 0012でranking/backfill等の将来境界が
> 再定義された。Candidate、longer lookback、deep/bounded backfillを将来永久禁止する根拠にしない。

## 当時の決定

Candidate surface、74時間価格・売買代金AND、74h timeframe、production常駐deep backfillを旧scannerから退役した。
当時は長時間履歴構築、runtime state、UI、運用負荷に対して得られる監視価値が小さいと判断した。

旧Watchlist、Raw Sort、Smart Rank、短期Chart、activity context等は当時維持した。

## 当時の理由

74h Candidate専用pipelineがruntime complexityとloadを増やしていたため、旧scannerを軽量化する目的だった。

## 現在の解釈

- ranking、Candidate相当のshortlist、20D/55D等のlonger lookbackは再設計できる。
- historical backfillは`常駐deep backfillを旧方式で復活`する必要はなく、必要な期間とsourceをbounded jobとして設計できる。
- lookback/timeframe/retentionを固定せず、feature valueとcapacity/rate-limitから決める。
- 過去の低level componentやsnapshotをそのまま復活させる義務はない。
- 新機能は現在のPostgres/Parquetまたは新しいbounded contextへ適合する形で設計する。
