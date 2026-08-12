# Decision 0010: Candidate・74h・常駐deep backfillの退役

- 作成: `2026-08-12T21:38:47+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 状態: `設計判断`

---

## 決定

Candidate surface、74時間の価格・売買代金AND判定、74h timeframe、production deep backfillを
現行機能から廃止する。新しいsnapshot producerは74時間field、Candidate summary、
`rankings.timeframes`を生成せず、DashboardとSymbol画面もCandidate・74h情報を表示しない。
service CLI、runtime task、service state、systemd unit、Web APIにもdeep backfillを接続しない。

`featureVersion=5`、`rulesetVersion=4`、`schemaVersion=1`とする。`rankings`は診断用の
`noTrade`だけを生成する。

## 維持する契約

- Watchlist、Raw Sort、Smart Rank、選択銘柄detail、5m / 15m / 1h / 4h / 24h、activity phase、
  VPI-Lite+、market/perp comparison、Past Noteを維持する。
- OI 60分は廃止しない。`open_interest_samples`、5分bucket、exact 60分lookback、24時間retention、
  `UNKNOWN`無加点、cycle劣化時の診断を維持する。
- scanner分析とgap auditは末尾383本の5分足（1915本の1分足相当）を使う。detail chartは別目的で
  最大1177本の5分足相当（5885本の1分足）を使い、この長さを74時間判定やdeep backfillと結び付けない。
- Cold snapshot、Hot ticker、chart、reconcile、通常backfill、既存の正常なcandleとOI sampleを維持する。

## 互換性

snapshot schemaの`summary`、`rankings`、row `display`は追加propertyを許容するため、旧snapshotに残る
Candidate・74時間fieldをreaderが受け入れることはある。この読取互換は維持するが、旧fieldを現行producerの
公開契約として扱わず、現行UIへ再表示しない。DB migrationや既存market dataの削除は行わない。

## 理由

Candidateと74時間ANDは監視対象の絞り込みに必須ではなく、そのための長時間履歴構築、runtime state、
UI、運用手順が継続的な複雑性と負荷を増やしていた。短期指標、Smart Rank、activity phase、OI 60分を
残すことで、監視用途を保ちながら専用の74時間pipelineを廃止できる。

## 既存Decisionとの関係

- [Decision 0007](0007-monitoring-only-product-boundary.md)のCandidateをproduction surfaceへ含める部分を
  supersedeする。市場監視専用の製品境界は維持する。
- [Decision 0008](0008-candidate-oi-contract.md)のCandidate・74h契約とversion記述をsupersedeする。
  OI 60分契約は維持する。
- [Decision 0009](0009-quiet-market-activity-context.md)のCandidate近傍へVPI-Lite+を置く記述だけを
  supersedeする。activity phaseとVPI-Lite+自体は維持し、optional contextへ表示する。

## 帰結

- Candidate・74h・deep backfillを再導入する場合は、このDecisionを置換する新しいADRと、必要性、
  計算費用、runtime/UI契約、移行・rollback、実測による受入条件が必要である。
- 過去plan、旧snapshot、未接続の低level componentの存在だけを再開根拠にしない。
