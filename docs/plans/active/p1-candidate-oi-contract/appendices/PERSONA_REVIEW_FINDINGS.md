# 付録E PersonaレビューFindingと採否

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## Review method

Core 4 + Boundary 2 + Meta Reviewを使用。Personaは正解ではなく、異なる失敗経路を探す仮想ユーザーとして扱った。

## 採用Finding

| ID | Severity | Finding | 採否 |
|---|---|---|---|
| F-01 | P1 | 74h価格・売買代金条件がOR | 採用、ANDへ修正 |
| F-02 | P1 | 74h条件がCandidate rankingへ未接続 | 採用、Candidateだけgate |
| F-03 | P1 | OI 60分lookbackがservice snapshotへ未配線 | 採用、local historyを追加 |

## 今回採用しないFinding

| 内容 | 分類 | 理由 |
|---|---|---|
| 注目度contribution UI | P2 | 現行raw指標/risk表示で監視成立 |
| multi-timeframe volume ratio | P2 | 今回のP1外 |
| 30秒以内の候補到達 | 未確認 | 実画面操作が必要 |
| Market Cap filter | 未確認 | 現行Repoの責務として未確定 |
| Spread / Liquidation / Funding percentile | Preference | 新data/責務追加 |
| R/R / Entry / Stop | Reject | 取引判断機能 |
| Copy Exposure | Reject | Copy Trading境界外 |
| Bot control | Reject | Automation境界外 |

## Meta review

- Momentum偏重は、Funding/Thin/Rough/BTC/data-quality riskで一定程度反証済み。
- UI全面再設計を正当化する証拠はない。
- 2つのP1修正後に、Persona要望を追加実装しない。
