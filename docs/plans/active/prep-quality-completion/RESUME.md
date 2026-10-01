# 再開位置

- 作成: `2026-09-30T18:12:00+09:00`
- 更新: `2026-09-30T23:21:28+09:00`
- 状態: `実装計画`

---

## 現在の到達点

ZIPの6機能をsourceへ接続し、隔離Postgres・HTTP server・CLI・生成ファイル・
Web GET・Desktop/Mobile画面を通した。全体gateはexit 0。さらに3 Venueの実RESTから
短窓を取得し、実CLI回収→DB再scan→実GET→Inspectorまで通した。取得DBのdump/restore
コピーからAuditとFixture export/verifyも確認した。細部は
[検証記録](validation-summary.md)、項目ごとの結果は
[全体台帳](acceptance.json)と[Audit台帳](audit-acceptance.json)を参照する。
Discoveryは将来オプションだけとして実装・導入・試験していない。

作業branchは`ai/prep-quality-completion-20260930-1812`。開始時HEADは`b472fd4`、
実際のremote mainは`4daa37b`だった。作業途中で外部processによる`cfa040e`の
commit/pushを観測し、保全した。Codex自身はcommit/pushしていない。
このcommitの後にも今回の未commit差分がある。stage済み差分はない。

## 次に必要な確認

1. OpenMarketキーは未提供と回答済み。承認済みkeyとexact契約が得られた時だけ、
   Reference短窓→Audit→Inspectorを実データ受入する。native 3 VenueのRecovery、
   実公開データの隔離復元DBでのAudit/Fixtureはpass済み。
2. 本人の日本語IMEと実画面操作でMarkets/Inspector/Chartを確認する。
3. 本番配置が承認された時だけ、exact sourceと設定/状態先を確定し、backup/readback、
   Recovery無効の配置、短窓scan、許可範囲のapply、必要時の有効化、rollbackを行う。
4. 各境界がpassしたら台帳のblockedを更新し、現行事実と採用判断を正本へ反映して
   active planを削除する。commit/pushは資料の別承認が必要。

未確認を合成結果から繰り上げない。現役DB、JustPassのDB、user service、deployは
今回操作していない。今回の隔離Dockerと4177のWeb previewは検証後に終了する。
本番承認の具体的範囲は[配置確認資料](release-review.md)を参照する。
