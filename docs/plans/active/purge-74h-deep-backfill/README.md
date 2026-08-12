# 74時間判定・deep backfillパージ計画入口

- 作成: `2026-08-12T17:03:31+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

## 結論

74時間判定は、計算式だけでなくCandidate gate、設定、snapshot field、理由コード、UI、文書まで
一つの機能としてパージする。74時間判定を別条件へ暗黙に置き換えず、Candidate固有UIも撤去する。

74時間判定用の5,885本deep backfillは常駐serviceから完全に切り離す。
`service_deep_backfill.py`とpure testは将来利用できる独立部品として残せるが、service CLI、systemd、
service state、Web進捗表示には接続しない。

Cold snapshot、短期candle、直近reconcile、detail chartは、この計画では削除しない。snapshotは現行Webの
公開境界であり、短期candleは既存の5分・15分・1時間・4時間・24時間指標とchartが依存している。
scanner判定とgap auditは383本5分足/1,915本1分足へ縮小するが、detail chartのsourceは現行の
1,177本5分足/5,885本1分足を暫定維持する。chartの存廃と、Bitget × Hyperliquid Core比較専用アプリへの
全面移行は別判断にする。

## 現在地

- CP-01〜04を実装し、常駐deep backfill接続、Candidate consumer、74時間producer/公開契約を除去した。
- scanner/gapは383本5分足/1,915本1分足、chart sourceは1,177本5分足/5,885本1分足に分離した。
- CP-05のcurrent docs、ADR、旧P1 plan同期と文書focused gateは完了した。全体gateとruntime確認は
  未完了である。
- 計画baselineは`ad3364f6e3b0c30c85469a22da3789f19d3727b9`、現在branchは
  `ai/purge-74h-deep-backfill-20260812-2004`である。
- 実user unitには旧`--deep-backfill-*`引数が残る。CP-06ではrestart前にinstallerで限定driftを確認し、
  unit同期後にscanner/Webを各1回だけrestartする。source実装だけで稼働反映済みとは扱わない。

## 読む順番

1. [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) — メインスレッドへの実装引継ぎ
2. [`PLAN_REVIEW.md`](PLAN_REVIEW.md) — 再監査で確認した誤り、選択肢、修正内容
3. [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — 作業契約、受入条件、checkpoint
4. [`EXECUTION_RUNBOOK.md`](EXECUTION_RUNBOOK.md) — 実行順、検証、停止・回復手順
5. Repo localの`.codex/SP_STATE.md` — 最初のcheckpointだけを対象にした実行checklist

## 正本の優先順位

1. 実装開始時の現行Repo、`AGENTS.md`、schema、tests、CLI help
2. `docs/current/`と`docs/decisions/`
3. [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
4. [`EXECUTION_RUNBOOK.md`](EXECUTION_RUNBOOK.md)と[`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)

計画と現行Repoが食い違う場合は、現行Repoを優先し、resetせず計画のfacts、対象file、受入条件を
更新してから再開する。

## この計画が完了しても残るもの

- Cold snapshotの全量生成処理
- scanner/gap audit用31時間55分と、chart source用98時間5分のcandle履歴
- 直近欠損を修復するreconcile
- detail chartとchart JSON生成
- VPI-Lite+、OI 60分、Watchlist、Raw Sort、Smart Rank
- 旧3市場`marketComparison`とBitget × Hyperliquid Core `perpVenueComparison`

したがって、本計画の完了をscanner高CPU問題の解決とは扱わない。source変更前後でCPU、RSS、
snapshot間隔、生成件数を再計測する。detail chartは全row JSONのflush/fsync、旧`marketComparison`は
製品対象外のBybit取得を残すため、両方を次段の優先削除候補として別計画で判断する。
