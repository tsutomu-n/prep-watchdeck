# Bitget intraday activity

timestamp="2026-10-08(木)_15:41 JST"

- 作成: `2026-10-08T15:41:08+09:00`
- 更新: `2026-10-08T15:41:08+09:00`
- 検証: `2026-10-08T15:41:08+09:00`
- 状態: `進行中`

## Goal and approved scope

裁量デイトレーダーがBitget銘柄の直近の活発さ、増減、価格方向を高密度の一覧で判別する。
15分を主表示、1時間を補助とし、24時間売買代金は背景情報として維持する。
Hyperliquidの短時間指標はユーザーの明示回答により今回は実装しない。
参照ランキングの順位・並べ替え・Chartとnative指標の取得元を混同しない。

## Contract

- Bitgetのcurrent contract versionの確定1分足quote turnoverだけを使用する。
- cutoffは既存native metricsと同じ分境界−180秒。全分が正常な窓だけを合計する。
- 15分／1時間の現在値、直前の同じ長さの窓との増減、直近4窓の推移、同期間の価格変化を返す。
- 普段比の基準は過去7日の同時刻・同長窓の中央値。3日以上の完全な履歴が必要。
- ゼロ・欠測・履歴不足・古さ・契約版不一致を別扱いにし、推測補完しない。
- 極小の基準値で倍率が膨らむ場合は強調しない。表示閾値と理由を公開する。
- 保存済みcandleのread-only projectionを独立optional artifactとして1分ごとに更新する。
  既存の5秒native metrics、Ranking、core artifacts、DB schemaは変更しない。
- 表内の既存signal領域を使い、余白・カード・列の増設を最小化する。PC／Mobile、normal／ultraを維持。

## Allowed files and tasks

1. [ ] native activity model、SQL集約、境界／欠測／identity検証と隔離DB検証。
2. [ ] bounded publicationとoptional service loop、schema生成、Web repository/API。
3. [ ] 正確なidentity/freshness adapter、dense signal/detail component、既存Bitget表示へ接続。
4. [ ] 関連unit・型・build・PC/Mobile E2E、必要なrepo gateを実行する。
5. [ ] 現行仕様文書へ反映してplanを閉じ、今回差分のみcommit。

対象はMarket Coreのnative activity新moduleとservice接続、Webの新artifact読み取り・Bitget行内表示、
schema/type生成、関連testsと現行文書。source実装・commitまでが今回の承認範囲。
push、CI、deploy、service操作、live DB migration、live backfillは行わない。

## Validation and completion

最低限: focused Market pytest、Ruff/Pyrefly、schema generation check、Web Vitest/check/build、
BitgetのPC/Mobile（normal/ultra）E2E、Hyperliquid既存表示、docs metadata/links、diff check。
SQLは専用の一時Postgresで境界と完全性・version非混入・bounded queryを確認する。
source成功と実データの履歴充足、本番反映は別に報告する。

## Rollback and unresolved

新artifactはoptionalとし、欠測時も既存一覧が動く。sourceは今回commitのrevertで戻せる。
本番には未配置なのでcutover rollbackは今回対象外。
実データの連続coverageは未確認。必要な履歴が不足する銘柄は比較不可を表示する。
