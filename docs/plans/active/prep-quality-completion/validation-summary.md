# 隔離検証と証拠

- 作成: `2026-09-30T21:49:39+09:00`
- 更新: `2026-09-30T23:21:28+09:00`
- 状態: `実装計画`

---

## 判定とsource

独立して完了できる実装・隔離検証は完了。全体87項目は80 pass / 7 blocked、Audit42項目は41 pass / 1 blocked。
残る項目は本人の実日本語IME、現役M6、OpenMarketの実認証、本番配置とrollback。Discoveryは今回の対象外。

branchは`ai/prep-quality-completion-20260930-1812`、HEADは`cfa040ebd92614fa482effdb4bc65eefc296b099`。
最終source fingerprintは`sha256:eb27bfbb43400d8db786eee83ac6de2364428d54a1f359340360dbbbd63d6784`。
計算法は`HEAD\0<git rev-parse HEADをstripしたbytes>\0`、本planを除く`git diff --binary HEAD`、
sorted untracked sourceの`path\0`とfile bytesを順にSHA-256。本planと台帳の編集は含めない。

## 最終検証

- `bash scripts/verify-local.sh` は自動作成した新しい隔離Postgresでexit 0。
  Repository 18、Market Core 164、Ranking Core 124、Web Vitest 162、Desktop/Mobile Playwright 82件。
  Ruff、format、Pyrefly、schema check、Web check/build、文書metadata/linkも成功。
  logは`/tmp/prep-watchdeck-verify-resume-20260930.log`、SHA-256は
  `d28513ed6f312beb373f1ce82307f926a3ae452c7c1a441db98d11b920382b75`。
- その後のrun開始/INSERT中断の後始末修正はMarket Core全165件、Ruff、format、Pyreflyで確認。
  logは`/tmp/prep-watchdeck-core-final-20260930.log`。Webとschemaの契約はこの修正で変更していない。
- 最初の再開gateでは6試験が空DBのmigration準備に依存して失敗。各feature試験が専用databaseを
  作成・migration・削除するfixtureへ修正し、上記新規DBでのgateを通した。
- Recoveryでは事前scan/rescanの時間予算、残り時間を超えないHTTP timeout、429の次run cooldown、
  connect/start/scanの中断、Liveとの競合を確認。未検査を0件とせず`null`で記録し、DB threadの実終了を待つ。

## 実公開データ

[観測証拠](observed-acceptance.json)はsynthetic試験と別の`observed`証拠。
実公開catalogからBitget BTCUSDT、Hyperliquid BTC、Aster BTCUSDTの現行version/hashを保存した。
実時間のvalid_fromを使い、観測前へ契約時刻を遡らせていない。

対象窓はUTC `[2026-09-30T13:46:00Z, 2026-09-30T13:52:00Z)`。各Venueで実RESTの6本から5本だけを保存し、
13:49開始の1本を意図的に保存しなかった。実CLIは各1要求で1本をINSERT、DB再scanで残欠損0、
既存5本の全column不変、collector_run_id一致を確認。Bitgetはconfirmed、Aster/Hyperliquidはderived_final。
observed_atは実HTTP受信時刻。

初回BitgetはendTimeを1ms引いた要求で最後の足が欠けた。現行公式仕様のinterval丸めと実応答を確認し、
分整列の排他的endへ修正。境界のloopback試験と実REST再取得を通した。

取得DBの18本をpg_dump/pg_restoreした隔離コピーから、実Fixture CLIとAudit CLIを実行。
Audit run `156d95a196cb408db4f73cbe51a3d3f3` は6本/価格24値/数量6値/5分return 1組がmatch。
同じBitget RESTの再取得との比較で、`independence=not_established`を保持している。
Fixture `b7b847efbe5744f7b95d5d2c2f0d3810` はoffline verify exit 0。instrument、candles、Recovery、Auditを含み、
market-state/fundingはDB内の0行としてemptyを記録。export/Audit後も元DBと復元DBの18本は不変。

同じ実ファイルを4177の隔離Webで読み、3 Venue×Desktop 1440/Mobile 390の6画面でRecovery API runId、
Inspectorの欠損1→0/挿入1、横overflowなしを確認。Bitget Auditの実reportも画面で読めた。
スクリーンショットhashと一時pathは観測証拠に保存。現在L1の収集証拠ではなく、その欄は未取得のまま表示する。

## 未確認と運用境界

OpenMarketキーは利用者が未提供と回答済み。実認証や対応mappingを合成値で代用しない。
実機/日本語IME、現役M6のflowと遅延、本番配置・rollbackは未実施。
現役DB、JustPass、production unit、deployは変更していない。
隔離DBとWeb previewは終了し、dump、bundle、状態filesとscreenshotsは一時証拠として保持する。

## Git

作業中に外部processが`cfa040e`をbranchへcommit/pushしたことを観測し、保全した。
本作業のCodex操作ではcommit/pushしていない。remote mainは`4daa37b`のまま。
最終差分は未commit、staged差分なし。稼働sourceはMarket Core `dc2a8d7`、Web/Ranking `d1c44d5`を指す
既存unitのWorkingDirectoryをread-onlyで確認。今回sourceへの切替は行っていない。
