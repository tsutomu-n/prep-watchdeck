# 再開位置

- 作成: `2026-09-28T20:00:00+09:00`
- 更新: `2026-09-28T21:11:00+09:00`
- 状態: `実装計画`

---

段階: M5の隔離gate通過後、受入台帳の残件整理。`origin/main=be281d9` 起点の独立worktree。元checkoutと稼働releaseへ変更なし。本番操作は未実施。Gitの反映状態は作業branchとremote refで確認する。

PF01: 現役名簿とmapの同時copyは未取得。実データの接続率は未確認。参照既定を維持。

PF02: 現役DBへ未接続。端点・到着遅延は未確認。設計初期値180秒lag/300秒上限を採用して隔離fixtureで検証する。

PF03: 本番画面操作はselection/メモ書込回避のため未実施。既存負荷は未測定。M2の隔離Browserで確認する。

M1: 小額価格、groupなしactiveの単体chart/JST、version必須chart、token付きselection、メモの読取無書込/CAS/下書きを実装。A→B→Aの長時間競合などは台帳に残す。

M2: Ranking v3の4期間、共通Markets workspace、参照→nativeのID/version一致導線を実装。Desktop/Mobileで参照→native→戻る操作を確認。

M3: raw値sort/filter、行順固定、favorite・名前付きview・最近見た履歴を実装。2タブ遅延応答、focus/IMEの全境界は未実施。

M4: 任意のnative metrics lane、read-only集合SQL、単一worker、5秒poll、UI結合、メモv2 contextを実装。隔離PostgresでOI数量差、確定足共通cutoff、同cutoff訂正、1201行の10秒未満読取を確認。writer commitからBrowser表示までの実測、実provider到着遅延、全故障注入は未実施。

M5: `bash scripts/verify-local.sh` は隔離PostgresでMarket Core 80件、Ranking Core 123件、Web unit 155件、schema/型、lint、types、build、Desktop/Mobile E2E 44件を通過。最後の鮮度表示修正後にtypecheck、関連unit、build、Desktop/Mobileの該当E2E 4件、docs checker、`git diff --check`を再確認。受入台帳は`acceptance.json`。全ACは満たしていないため開発受入は`PARTIAL`。

次: 残ACの再現試験とworker→Browser遅延測定を追加する。PF01〜03の実データは現役state/DBへ触れる判断を別に行う。M6の本番反映・日常利用受入は別工程。
