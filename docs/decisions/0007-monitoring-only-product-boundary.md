# Decision 0007: 市場監視専用の製品境界

- 作成: `2026-08-02T22:00:39+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **製品境界はsuperseded:** [Decision 0012](0012-product-evolution-boundary.md)により、
> Watchdeckをmonitoring-onlyへ永久固定する判断、Trade Memo / Attack Ticket / Weekly Review / Pre-Trade等の
> feature名をproductionから禁止する判断、Past Noteだけを唯一の判断記録にする境界は置換された。
>
> 旧state/archive/routeの履歴と、当時退役させた実装を理解するためにこのDecisionを残す。

## 当時の決定

当時はproduction surfaceを市場監視へ限定し、Cold snapshot、Hot ticker、detail chart、Candidate、Watchlist、
Smart Rank、VPI-Lite+、Past Note等を残し、Attack Ticket、Trade Memo、TRADE/SKIP memo、Weekly Review、
Deal Check、Pre-Trade Check、Position Size Pressure等を退役させた。

旧API routeやstate pathも退役対象とした。

## 当時のPast Note境界

Past Noteを60日monitoring annotationとし、trade journalやexecution historyの代替にしなかった。

現在はPast Noteを観測annotationとして維持しつつ、Decision Memo、Trade Journal、review workflowを別conceptとして
追加できる。

## 当時の表示契約

ranking、score、VPI、selection等を自動的な売買推奨と同義にしない方針は、Decision 0005のexecution分離として
現在も有用である。

一方、ranking、score、direction、predictionを表示すること自体は禁止しない。

## State / Archiveの履歴

旧scanner時代のstate layout、retired records archive、legacy usage event等はrollback/data preservationの履歴として
残る場合がある。存在だけをproduction機能復活の根拠にも、再実装禁止の根拠にも使わない。

新しいDecision Memo / Trade Journal等を追加する場合、旧Archiveから自動restoreする必要はない。新しいschema、
state、migration、UI/APIを現在要件から設計する。

## 現在の解釈

- 市場監視だけでなく、発見、ranking、分析、decision support、journal/reviewをWatchdeck内へ持てる。
- 自動注文、資金移動、無人executionはDecision 0005に従い別Decisionを要求する。
- 旧feature名をCIで禁止しない。
- 旧feature実装をそのまま復元する義務もない。必要な価値だけ現在architectureへ再設計する。
