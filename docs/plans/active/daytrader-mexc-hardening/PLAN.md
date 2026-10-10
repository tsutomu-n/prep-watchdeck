# MEXC・Discovery 修正と本番反映

timestamp="2026-10-10(土)_09:02 JST"
- 作成: `2026-10-10T08:51:29+09:00`
- 更新: `2026-10-10T09:02:48+09:00`
- 検証: `2026-10-10T08:51:29+09:00`
- 状態: `実装計画`

---

## Goal / scope

MEXC と Discovery の不足を実物から確認・修正し、対象差分を commit・push して本番反映する。
4候補の保存容量、Attention の常駐容量、既存保存内容の再起動後の保持、本番 registry に対応する MEXC map を確認する。
CI・PR は実行しない。未確認の既存資格を推測で承認しない。

## Checkpoint

- 前段 source は 8e6ef26、文書 closeout は 5edf284。60分の MEXC 隔離実データ受入は完了。
- 現在の本番は旧3 Venue。DB、state、unit と release を保全して reader を先行配置する。
- Unicode銘柄の比較保存/GET拒否、warm Discoveryの512 MiB超過、selection再起動時のTTL延長、production map capture未対応を修正済み。
- 本番SQLite約4.3 GBのcopyを512 MiB cgroupで検証し、3世代・障害・同cutoff保留・次cutoff復帰・再起動を確認。既存76episode喪失0。
- 既存3 Venueのversion差分5件を定義で再照合、新規PEARLはunsupportedとして独立保持したcandidateを作成。旧577行の参照/数量/Widgetを保持。
- 本番Postgres custom dumpとSQLite online backup、unitとuser filesを専用archiveへ保全。全体local gate後にcommit/push・tracked releaseのbuild・reader先行配置へ進む。

## 完了条件と検証

1. 再現した保存・常駐・復旧の欠陥を修正し、対応する最小 test と必須静的 check を実行する。
2. tracked source の独立 release を作成し、本番切替前の DB / SQLite / workspace / unit を保全する。
3. reader 先行配置後、本番DBのMEXC registry versionで map を再資格判定する。
4. 実 service、各 API、Web の4候補・監視履歴・native接続を確認する。
5. 対象 branch を origin へ push し、commit・push・本番稼働・実データ受入を別々に報告する。

## Rollback

旧 release / unit / state を保存する。MEXC 登録前は旧設定へ戻せる。
登録後は MEXC 対応済み reader を保持して新規取得を無効化し、未知 enum を旧 reader へ渡さない。
DB downgrade・restore・既存データ削除は行わない。Attention の追加 SQLite table と保存済み判断を保全する。

## 未解決

- 本番MEXC catalog採番・current version再資格判定・map採用・全4Venue収集再開。
- 本番API/ブラウザ・連続世代・cgroupの実反映受入。数量未確認4件・Widget未確認3件を保持して区別する。
