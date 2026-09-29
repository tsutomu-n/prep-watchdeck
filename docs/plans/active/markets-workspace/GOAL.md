# Markets workspace 実装

- 作成: `2026-09-28T20:00:00+09:00`
- 更新: `2026-09-29T06:55:18+09:00`
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
