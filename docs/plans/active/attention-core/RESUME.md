# Attention Core checkpoint

timestamp="2026-10-09(金)_07:10 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-09T07:10:30+09:00`
- 状態: `実装計画`

F0–F7 source implementation: **PASS**。Product validation: **PARTIAL**。F8: **in_progress**（push完了、配置準備中）。
検証済みsource commit: `3ea11242423b9de0856da00c26e12c54a3d24ffc`。branch: `ai/attention-core-20261008-2347`。

## 再開点

今回のsource実装・ローカル受入は完了。次はF8のproduction配置、capacity/retention、30日prospective evidence、候補優位性、本人の日常利用受入である。今回の明示承認はAttention/Webの配置と必要なunit操作・push。live DB、Provider追加取得、actual captureは対象外。F9 actual captureは別Decisionを要する。

## 実装と証拠

独立Python app、stable read-only inputs、exact identity/時刻、4成分＋confluence、SQLite証拠、15/60分のoffline将来結果、固定候補群のday-block max-T/6h感度分析、3種のshadow allocation、loopback API、`/attention`、隔離runnerを接続した。現行契約は[architecture](../../../current/architecture.md)、[data contracts](../../../current/data-contracts.md)、[UI](../../../current/ui-workflow.md)、[operations](../../../current/operations.md)、[validation](../../../current/validation.md)。採用判断は[Decision 0015](../../../decisions/0015-attention-core.md)。

- `bash scripts/verify-local.sh`: exit 0。Repo 18、Market 216、Ranking 156、Attention 56、Web unit 221、Desktop/Mobile E2E 136 passed。Ruff/Pyrefly/schema、Web check/build、docsも通過。
- 最終の行ごとの基準時刻表示追加後、Web unit 221、check 0 errors/warnings、build、Attention Desktop/Mobile E2E 2 passed。全体gateを不要に反復していない。
- Linux bubblewrapによる2秒の隔離起動・停止に成功。専用stateだけDBを作り、Marketのselection fixtureのhashとRanking rootを保全。実データの意味・capacityの受入ではない。
- 独立レビューはPASS、未解決指摘なし。判断以前の動きをoutcomeへ混ぜない修正と、empty/pending evidenceを候補棄却にしない修正を直接再現で再確認した。
- CLI help、workflow source parse、local script構文、doc metadata/link、diffを確認。Hosted CIは未実行。

項目別の対応test、実行command、log hash、制約は[acceptance.json](acceptance.json)。一時logの保持を前提にせず、同じsourceとcommandで再実行できる。元資料のtask checkboxは依頼時の手順であり、現在の状態はこの記録と受入台帳を参照する。

## 保持する境界

Outcome cutoffは`ceil(decisionAt / minute)`で、Ranking input cutoffとは別。正確なbaseline closeとその後の15/60本を要求する。old closeの補完はしない。lead timeはdecisionAtから測る。訂正はeditionを増やし旧評価をstale化する。

既定familyは3 baseline＋5 component × 2 horizonの16 policyを初回の実時刻にfreezeする。policyを変える場合は新familyを使う。stats methodはversioned approximationであり、powerはplanning-only。実データ上の有効性・利益・production capacityは未確認。

F0–F7 source受入時点ではMarket/Ranking writer、manual selection、Provider、production stateへの書込み、push / merge / PR / deploy / systemd操作は未実施だった。F8での実行状態は下記を参照する。Attention停止後も既存画面は独立して利用できる。専用stateの削除は不要。

## F8 rollout checkpoint

2026-10-09のuser明示指示で、今回のAttention branchのpushと本番反映を開始した。地理空間のGISか実市場データかの確認は並行中。実データ受入の対象は回答に従う。

1. 現行source・unit・稼働版・healthとrollback設定をread-onlyで確認する。
2. 同じsourceで、専用scratch Attention stateとportから現行Market artifacts / Ranking APIだけを読み、世代・欠測・容量・resource使用を観測する。
3. 受入後にAttention専用unit templateと制限を用意し、tracked sourceだけを新releaseへ配置する。WebのWorkingDirectoryを切り替え、Attentionを専用state/8770で起動する。Market/Rankingの既存writer・manual selection・DBは変更しない。
4. API・Browser・実際の世代更新とcgroup制限、既存process継続、Attention停止/復帰時の独立性を確認し、結果をcommit/pushする。

初期確認: Web/Marketはrelease 5b82a7d、Rankingはd4aa5f9。Rankingは4 original contract versionsのreview_requiredを返す。これを自動承認・補完しない。切戻しは旧Web drop-inの復元と新Attention unitの停止。状態は保持し、削除しない。CI、PR、main merge、actual capture、credential変更は依頼に含めない。30日間の証拠が未蓄積なら短時間の確認で代用しない。

進捗: `194d49c`をoriginの同名branchへpush済み。Linux隔離の実市場入力で毎分更新と577行を確認し、専用unit templateのsystemd構文検証を通過。短時間の実測はoutcome前約5.1 GiB/日で、長期capacity/retention受入は未完了。
