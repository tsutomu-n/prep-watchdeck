# 付録F 誤謬・失敗経路チェックリスト

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 実装前

- [ ] 「出来高」をbase volumeへ勝手に読み替えていない
- [ ] CandidateとWatchlistの責務を混同していない
- [ ] current Repoのstore実体を確認した
- [ ] Candidate閾値をUIへhardcodeしていない
- [ ] 既存OI historyの有無を確認した
- [ ] pre-existing test failureを記録した

## 74h

- [ ] ORをANDにした
- [ ] NoneをFalseへ丸めていない
- [ ] zero historical turnoverを比較不能にした
- [ ] reason codeをcomponent単位で付けた
- [ ] Candidateへ接続した
- [ ] Watchlist rowsを削っていない
- [ ] noTrade diagnosticを失っていない

## OI

- [ ] source timestampでbucket化した
- [ ] finiteかつpositiveだけ保存
- [ ] stale current tickerをsampleしていない
- [ ] exact 60m target bucketのみ使用
- [ ] missingはUNKNOWN
- [ ] UNKNOWNは0 contribution
- [ ] per-symbol queryをしていない
- [ ] 24h retentionがある
- [ ] additive tableで既存DBを壊さない
- [ ] service restart後のsample再利用testがある

## UI/version

- [ ] Candidate gateを明記
- [ ] OIをBullish/Bearishと表示していない
- [ ] Watchlist列を増やしていない
- [ ] featureVersion/rulesetVersionを上げた
- [ ] schemaVersionを不要に上げていない

## 終了前

- [ ] focused red証拠
- [ ] focused green証拠
- [ ] full gate exit 0
- [ ] diff check
- [ ] unrelated changeなし
- [ ] living plans同期
- [ ] final_resultとgoal_gap記録
