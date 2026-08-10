# 失敗経路チェックリスト

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## Data

- [ ] 15m既存値が変わっていない
- [ ] 1h / 4h不足を0で補完していない
- [ ] Activity phaseが売買方向を示していない
- [ ] Stale dataがCandidateへ入らない
- [ ] PARTIALを無条件に全除外していない

## Ranking

- [ ] 1h / 4h / phaseをScoreへ加点していない
- [ ] VPIを主rankingへ混ぜていない
- [ ] Smart Rank計算を変更していない
- [ ] rankings.noTradeを失っていない

## UI

- [ ] 正常`OK`を表示していない
- [ ] 異常を隠していない
- [ ] Badgeが増えていない
- [ ] 320pxで横scrollしない
- [ ] Mobile tabがkeyboardで操作できる
- [ ] VPI coverageを市場全体と誤認させない

## Scope

- [ ] 新dependencyなし
- [ ] Private/trade/order APIなし
- [ ] Alert、通知、MLなし
- [ ] Chart変更なし
- [ ] unrelated refactorなし
