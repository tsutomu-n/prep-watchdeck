# Quiet Market Instrument UI改善

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## 目的

`prep-watchdeck`を、同格カードを並べたAI風Dashboardではなく、市場事実を短時間で読む連続した監視道具へ整える。

## 実装入口

1. [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)
2. [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
3. [`IMPLEMENTATION_PLAN.ai.json`](IMPLEMENTATION_PLAN.ai.json)
4. [`appendices/ACCEPTANCE_CRITERIA.md`](appendices/ACCEPTANCE_CRITERIA.md)

## 対象

- 15m / 1h / 4h出来高倍率と活動phase
- Data qualityの異常時表示
- Candidate 1 surface / Mobile tabs
- Watchlist category
- Inspector再構成
- VPI発見lane
- `Smart Rank`の`補正順位`表示

## 対象外

Score再設計、VPI対象拡張、取引機能、Alert、新production dependency、全面theme変更。

## 完了

AC-QMI-001〜017は証拠付きでpassed、AC-QMI-018はこのplanを含むlocal commit自身で成立する。
実装・focused/full/performance gate・visual QA・正本文書同期は完了済みで、Repo外Archive待ちである。
