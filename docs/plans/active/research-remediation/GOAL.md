# Research remediation implementation

timestamp="2026-10-09(金)_15:08 JST"
- 作成: `2026-10-09T14:28:00+09:00`
- 更新: `2026-10-09T15:08:03+09:00`
- 状態: `実装計画`

## Goal and authority

2026-10-09のPhase0、不足事項の修復調査、既存資産/OSS再利用提案を、独立した研究readerと
offline検証・評価へ実装する。利用者は「これまで計画した全てを実装」「エラーハンドリングも強化」
を指示した。利益やB優位を成功条件にしない。

## Scope and contract

- 一契約/version、最大24時間のread-only REPEATABLE READ観測。candle、state/OI、settled funding、
  instrument/local validity/group/capabilityを同一snapshotで読む。
- 観測payloadをimmutable保存し、同一bytesの公開/readback後に研究readerのavailability上限を記録。
  全producer訂正捕捉、取引所初回availability、過去の欠落版の復元は主張しない。
- 入力hash、版、時刻順序、欠測、clock drift、poll gap、中断、破損をofflineで検証。
  同一bucketの訂正は別editionに保存し、未来のeditionを過去cutoffへ入れない。
- A=price/activity continuation、B=A+固定OI条件。共通cohort、no-position control、単一long、
  有限cash、明示fee/slippage、settled fundingのevent順序、M2M恒等式、時系列split/purge。
  trial/rule/evaluator/input hashを実行前にfreezeし、失敗/no-tradeも保存する。
- Polarsによるgap/cohort/件数report、fundingのSHA/identity/時刻/重複矛盾検査、既存archiveとの
  read-only照合と限定backfill候補出力。原本は変更しない。
- Hyperliquid candidate receiptとfinality decisionを分離、遅着訂正を受理する明示規則。
  Aster fundingInfoのintervalを観測provenance付きで接続。監視map不一致を診断可能にする。
- CCXTは明示的な照合入力/結果を扱う補助。hftbacktestは完全な板・約定feedが必要な別受入として、
  入力資格の検査と再現可能な準備を提供する。未確認Aster OIは欠測のままA/Bから除外する。

## Boundaries

Python 3.13、既存uv/Polars/Pydantic/psycopgを使う。既存fixture契約とPhase0成果物は不変。
研究出力はMarket/Ranking/Attention stateと別root。production DBへのwrite、live migration、
service操作、常駐開始、deploy、push、PR、CIは今回実行しない。既存DB時刻の遡及書換えは禁止。
source/local検証と本番配置、24時間/30日実データ受入を分ける。

## Completion and rollback

全項目についてcode、focused tests、CLI経路、エラー終了、使用法と制約を対応づける。
新研究出力を破棄せず、旧read pathへ戻せる。provider source修正はcommit単位でrevert可能。
live未反映、未取得OI、長期データ不足は未達として残す。外部依存の条件を偽造してPASSにしない。

## Checkpoints

- [x] 現行checkout/clean tree、既存契約、研究提案を確認。
- [x] 将来観測journal、self-contained snapshot、offline/as-of検証。
- [x] provider finality/funding/monitor修正。
- [x] fixed trial、共通cohort、有限口座event evaluator。
- [x] quality/archive/funding検査、CCXT照合とhft入力資格。
- [x] 統合CLI、schema、docs、focused gate、独立review。commitはacceptanceを参照。

## Decisions and unresolved acceptance

- 実装済みAttentionのimmutable/freeze/edition設計を再利用し、Attention runtimeへ研究writerを追加しない。
- 別Bitget repo全体を依存にせず、少量の検査ロジックを当repoの契約に合わせる。
- 未確認OIの取得契約、長期統計、実約定、production map採用/監視回復は外部受入。

## Source completion / remaining acceptance

Repository実装とlocal gateは完了。gate・review・元データ保全は
[/home/tn/projects/prep-watchdeck/docs/plans/active/research-remediation/acceptance.json](acceptance.json)、現行usage/contractは
[/home/tn/projects/prep-watchdeck/docs/current/research.md](../../../current/research.md)、採用判断は
[/home/tn/projects/prep-watchdeck/docs/decisions/0016-reader-observed-research.md](../../../decisions/0016-reader-observed-research.md)へ反映した。
このplanは以下の未実施受入だけを再開対象として残す。実装作業を未完了と誤認して再実装しない。

- [ ] 承認されたrelease/DBにMigration 0005を適用し、sourceを配置してProvider finality/intervalを実受入する。
- [ ] 監視と稼働mapの根拠review・validation・採用後monitorを確認する。現在のmapを推測で書き換えない。
- [ ] 研究rootで新しいrule登録後に将来観測し、24時間captureと複数日/30日evidenceを別段階で確認する。
- [ ] Aster OIはnative symbol・単位・side/multiplier・時刻を確認できる取得契約と実応答が揃うまで除外する。
- [ ] hftbacktest engine受入は完全な連続feedとlatency/queue仮定が揃ってから行う。

production DBへのwrite、unit操作、map稼働採用、deployは明示許可後の実行対象。
既存journal・Phase0・runtime stateは保全し、過去availabilityや未観測値を埋めない。
