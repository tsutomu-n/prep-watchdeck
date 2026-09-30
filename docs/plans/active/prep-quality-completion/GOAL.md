# 保存足の品質機能完成

- 作成: `2026-09-30T18:12:00+09:00`
- 更新: `2026-09-30T18:12:00+09:00`
- 状態: `実装計画`

---

## Goal と範囲

`prep-watchdeck-complete-handoff-20260929.zip` の6機能を、既存Marketsを保持して実装する。
対象はMarkets残受入、Candle Recovery、Candle Audit、Source/Quality Inspector、
OpenMarket Reference、Fixture Export。Discoveryは将来オプションの記録のみ。

作業ブランチは `ai/prep-quality-completion-20260930-1812`。開始時のHEADは `b472fd4`、
remote mainは `4daa37b`、未コミット差分なし。HEADの後続コミットを保全する。

## Checkpoint

1. Markets残受入と既存境界を確認し、台帳の未確認を分離する。
2. Recoveryを隔離DB、native履歴、手動CLI、起動・周期、API、Inspectorへ接続する。
3. Audit計算・不変公開・安全なGET・Native詳細・Chart markerを接続する。
4. OpenMarket手動取得とAudit入力、Core証拠Exportとoffline検証を接続する。
5. 同梱の全体87項目・Audit42項目を証拠付きで照合し、必要な隔離統合試験と
   `scripts/verify-local.sh` を実行する。

## 完了条件と検証

CLI、DB、ファイル、API、UIの実入口を通す。`acceptance.json`と`audit-acceptance.json`は
`pass`、`partial`、`blocked`、`not_run`を実証拠に応じて更新する。
実IME、実Provider、現役データ、本番配置は隔離開発試験とは別の判定とする。
同梱fixtureだけで実データ受入をPASSにしない。

## Rollback と未解決

このブランチを稼働releaseへ反映しない限り、現役serviceとDBは不変。変更を配置する際は
旧sourceへ戻し、追加した任意のsidecarを無効化しても既存4 artifactを読めることを確認する。
本番DB変更、service操作、deploy、commit、push、PR、mergeは資料の別承認対象。
現時点で実IME、OpenMarketキーと実対応契約、現役DBコピー、本人の稼働受入は未確認。
