# Phase A 限定本番反映

timestamp="2026-10-11(日)_11:09 JST"

- 作成: `2026-10-11T11:02:51+09:00`
- 更新: `2026-10-11T11:09:44+09:00`
- 検証: `2026-10-11T11:09:44+09:00`
- 状態: `実装計画`

## Goalとscope

ユーザーの「コミット、プッシュ、本番反映」に基づき、検証済みPhase Aの4修正を本番へ配置する。
稼働baselineはc805056、元の実装commitは0fa5834。未採用のRecovery証拠・監査・Bundle機能を追加せず、
5 source fileと4 test fileの差分だけをbaselineへ適用した。schema、migration、dependencyは変更しない。
初回の元実装branch pushは完了。専用本番branchとrollback可能な別releaseを用意する。

## 完了条件と検証

- 関連pytest、Web unit/check/build/E2E、repo必須release gateを専用DB/state/portで確認する。
- 新commitを専用branchへpushし、remote SHAを照合する。CI/PR/main mergeは行わない。
- tracked commitから別releaseをbuildし、sourceとartifactを照合する。既存env、state、mapを保持する。
- Market/Webのみ限定drop-inとrestartで切替。Ranking/AttentionのunitとPIDを維持する。
- 起動後health・artifact世代・OI意味・UI配信・protected controlsを確認する。
- 元workspaceの4 dirty filesと旧releaseを保持し、結果とrollback根拠をlocal archiveへ残す。

## Checkpoint

- 全4unitはc805056でactive。dataopsは開始前からfailed/status1であり、今回の合格へ混ぜない。
- 新baselineにないstate.evidence/latest-completed/order assertionsだけを追加回帰から除き、
  history_limit・他Venue継続・unknown件数・ledger終端・保存診断の確認は維持する。
- 現在: source patch適用済み。必須release gateはPASS（Market393、Ranking176、Attention78、Web266、E2E167 passed / 1 skipped）。新releaseのbuild・切替・本番確認は未実行。

## Rollbackと未解決事項

旧drop-inとc805056 releaseを保持する。今回追加したMarket/Web drop-inだけを外し、
daemon-reload後に対象2unitを再起動して旧配置へ戻す。state/DB/history/旧sourceは削除しない。
起動・health・protected control・writer排他・artifactに変更起因の異常があれば切り戻す。
既存map/PEARL/履歴完全性、新7200秒受入、30日evidenceは別作業のまま。
