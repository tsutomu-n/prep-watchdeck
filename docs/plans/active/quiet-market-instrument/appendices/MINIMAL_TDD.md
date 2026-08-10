# 必要最小限のTDD

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## 原則

- 既存test runnerとfixtureを使用する。
- 1契約1つの最小parameterized testを優先する。
- 同じ契約をunitとE2Eで重複assertしない。
- Visual変更はE2Eとscreenshot、計算はunit、schemaはcontract testで証明する。

## 必須RED

1. 1h / 4h ratioが現在`None`であることから始める。
2. activity phase fieldが未存在であることを示す。
3. OK表示、category非表示、Mobile 4panel縦積み、VPI詳細限定の現状を対象E2Eで固定する。

## 必須GREEN

- Volume ratio unit cases
- Phase truth table
- Candidate quality regression
- Schema/fixture generation
- Data quality labels
- Mobile tabs keyboard/ARIA
- VPI lane filter/sort/coverage
- Smart Rank表示のみ変更、計算不変

## Full gate

source確定後に`bash scripts/verify-local.sh`とWeb performanceを1回実行する。
