# Markets workspace 実装

timestamp="2026-10-01(木)_20:31 JST"

- 作成: `2026-09-28T20:00:00+09:00`
- 更新: `2026-10-01T20:31:46+09:00`
- 状態: `実装計画`

---

## Goal / scope

`/home/tn/projects/prep-watchdeck/handoffs/prep-watchdeck-markets-codex-handoff-2026-09-28-v2/` の R01〜R19 を M0〜M5 で実装・隔離検証する。M6 の本番反映・日常利用受入は含めない。既存4 artifact、DB migration、3 Venue の収集境界を維持する。

## 起点・保全

- 作業tree: `/home/tn/projects/.ai-worktrees/prep-watchdeck-markets-20260928`、`ai/markets-workspace-20260928-2000`、起点 `origin/main=be281d9`。開始時clean。
- 元checkout: `/home/tn/projects/prep-watchdeck`、`ebab3bb`、clean。共通祖先 `8d12fa6`。HEAD固有の `3055035` は旧ranking snapshotであり、Ranking v2が `origin/main` に統合済み。`ebab3bb` は `handoffs/` のignore。両commitを自動移植しない。補助で必要な差分は元資料を参照して個別に実装する。
- 稼働Web/Marketは `/home/tn/releases/prep-watchdeck/dc2a8d7`、Rankingは `/home/tn/releases/prep-watchdeck/d1c44d5`。作業treeは別。5432は別用途、専用DB待受は127.0.0.1:55432。現役DBには接続しない。

## Checkpoints

- M0: PF01〜03を安全に調べ、AC26と未確認を `acceptance.json` と `RESUME.md` に記録。
- M1: 価格、メモ、単体native、version付きChart、selection競合を修正し、関連test/browserを確認。
- M2: Ranking v3、共通workspaceと一連操作。
- M3: 一覧操作、favorite/saved view、最近見た履歴。
- M4: native metrics、観測context、隔離DB負荷・遅延試験。
- M5: 最終AC、schema/型、文書、repo横断gate。

## 完了条件・rollback・未解決

完了条件は原本の担当AC全pass。作業用台帳は同directoryの `acceptance.json`。未実施は `not_run` のまま。既存状態を破壊せず、開発変更のrollbackはこのbranchを稼働releaseへ反映しないこと。本番M6は別の判断と承認。現役DBのPF01/PF02・実データ確認と実機のPF03は未確認であり、隔離fixtureで進める。

開発受入は`PARTIAL`。隔離gateとworker→Browser接続試験は通過。AC20のOS実IME・実機focus、およびAC21の全必須AC照合が残る。PF01〜03の実データ確認とM6は別の未確認欄で管理する。詳細は同directoryの`RESUME.md`と`acceptance.json`に記録する。

## 2026-10-01 操作受入の追加範囲

本人操作に依存していたMKT-003/004を、依頼に基づき代理ペルソナとPlaywrightで進める。
現在checkoutの起点は`1a0a1b7`、作業branchは`ai/markets-persona-acceptance-20261001-2002`。
上のM0〜M5記録は当時の実施範囲であり、今回のread-only実データ確認は別checkpointとする。

1. Chromiumのtrusted compositionで、変換中の保存応答、銘柄切替、focus、確定・取消、再訪を確認。
2. 現役Universeと採用mapを前後hash付きで読取り、全体とTop20の接続を照合。
3. 専用DBの既存資格で短いREAD ONLY transactionを使い、各Venue最大3契約、5秒以上の間隔、最大6分で端点・到着を観測。候補指標は隔離stateだけへ投影する。
4. 現役artifactと公開RESTから得た実数値を使う隔離候補Webで、Desktop/390pxの参照→native→保存→再訪→次銘柄を確認。

完了条件は上記の代理操作と観測を根拠付きで記録すること。OS候補窓・物理端末・本人の主観、本番配置と本番起動復帰は別の未確認事項として残す。
証拠と再実行方法は[/home/tn/projects/prep-watchdeck/docs/plans/active/markets-workspace/persona-acceptance.md](/home/tn/projects/prep-watchdeck/docs/plans/active/markets-workspace/persona-acceptance.md)へ記録する。
本番へのPOST、unit操作、DB変更、map修復は行わない。rollbackは今回起動した隔離processを終了すること。
