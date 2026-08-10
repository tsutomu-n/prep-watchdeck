# Quiet Market Instrument UI構造

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## Desktop

```text
Topbar
Discovery surface
  ├─ Candidate: one continuous surface / four columns
  └─ VPI activity lane: narrow supporting rail with explicit coverage
Main workspace
  ├─ Watchlist (primary)
  └─ Inspector (selected symbol)
```

## Mobile

```text
Topbar compact
Candidate tabs
VPI activity lane (compact / collapsible)
Watchlist
Selected symbol / Symbol page
```

## 禁止パターン

- 同格KPI cards
- nested cards
- giant score gauge
- gradient / glass / glow
- badge soup
- AI Insights / おすすめ銘柄
- color-only state

## 文言

| 現在 | 表示 |
|---|---|
| Candidate Radar | 候補 |
| Smart Rank | 補正順位 |
| Market Context | 市場状況 |
| Monitoring Rail | 監視情報 |
| Data Quality | 正常時非表示、異常理由だけ |
| volume ratio | 15分量倍率 / 1時間量倍率 / 4時間量倍率 |
