# Web読み込み改善と本番反映

timestamp="2026-10-09(金)_17:53 JST"
- 作成: `2026-10-09T17:53:00+09:00`
- 更新: `2026-10-09T17:53:00+09:00`
- 状態: `実装計画`

## Goalと承認範囲

初回ランキング表示と画面への復帰を速くし、検証したWebを本番へ反映する。
2026-10-09のユーザーは実装、本番反映、現在のWeb停止を承認済み。
前ターンで比較した本番配信・圧縮、一覧保持、必要画面の遅延読み込みと先読みを実装する。
Git push、PR、Market/Ranking/Attention collectorの変更、DB migrationは含まない。

## 実装境界

- 配信: `apps/web/package.json`、lockfile、`svelte.config.js`、`server/`、Web unit template。
  公式adapter-nodeのhandlerとstream対応圧縮で配信し、loopback bindとsocket由来client addressを維持する。
  static hashed assetsをcacheし、APIのno-storeと認証・same-origin判定を保つ。
- 復帰: `ReferenceMarkets.svelte`とbrowser専用のbounded session state。
  query、表示条件、選択、表示行数、scroll、取得結果を保持し、復帰直後から再表示する。
  元のcutoff/qualityを保って再検証し、旧queryの遅着応答を新queryへ適用しない。
  hidden/unmounted画面のpoll/heartbeatを残さない。
- 初回: `MarketsWorkspace.svelte`、page loader、画面import helper。
  ReferenceではNative bundleを初期HTMLへ同梱しない。Native指定時は既存artifact contractを維持する。
  非選択画面のcodeを分割し、idle/hover/focusでcodeだけ先読みする。
  Referenceの契約確認・取引所売買代金は必要時に既存APIから取得する。
- 文書: current operations、UI workflowと必要なvalidationを現行behaviorに合わせて更新する。

## Checkpointと完了条件

- [ ] 配信・読み込み・一覧復帰を実装し、意味のある局所testで検証する。
- [ ] Web unit/check/build、Desktop/Mobileの関連E2E、production HTTP圧縮・認証を確認する。
- [ ] releaseに必要な`bash scripts/verify-local.sh`を隔離DBで実行する。CIは使わない。
- [ ] 統合diffをreviewし、今回の差分だけをcommitする。
- [ ] tracked sourceの独立releaseをbuildし、専用state/portで起動確認する。
- [ ] Web専用drop-inを追加してrestartし、HTTPS/loopback、圧縮、画面復帰を確認する。
- [ ] 旧Web停止と既存collector継続を確認する。source/commit/live/実機受入を区別して報告する。
- [ ] 現行仕様をcurrentへ反映してこのplanとindex linkを削除する。

## 検証とreview focus

最小regressionは復帰時のcached表示、期限切れ/通信失敗の表示、旧requestの遅着、
URL指定と端末既定値の優先順位、Nativeの契約リンク・選択、gzipのHTTP実応答、
Tailscale経由の認証とsame-origin、hash付きassetのcache headerとする。
schema、ランキング計算、全体検索・sortを変更しない。

性能は同じsnapshot・通信/CPU条件で旧配信と新配信を比較する。
前回の隔離比較は10Mbps/80ms/CPU4、開発配信約7.0秒、本番build+gzip約1.6秒。
新しい実測値を本番や本人端末の保証へ読み替えない。

## Rollback

開始時の稼働Webは`/home/tn/releases/prep-watchdeck/944f91b/apps/web`のdev配信。
既存unit/drop-in/stateを上書きせず、今回専用の最終優先drop-inでWorkingDirectoryとExecStartを変更する。
失敗時は今回追加したdrop-inだけを退避し、daemon-reloadとWeb restartで旧releaseへ戻す。
旧release、runtime state、DB、既存collectorを削除しない。

## 未解決事項

本番adapter起動時のOriginとsocket addressをHTTP testで確認してからcutoverする。
本人端末の操作感は本番反映後の別受入である。
