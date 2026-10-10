# MEXC・Discovery 修正と本番反映

timestamp="2026-10-10(土)_09:16 JST"
- 作成: `2026-10-10T08:51:29+09:00`
- 更新: `2026-10-10T09:16:44+09:00`
- 検証: `2026-10-10T08:51:29+09:00`
- 状態: `実装計画`

---

## Goal / scope

MEXC と Discovery の不足を実物から確認・修正し、対象差分を commit・push して本番反映する。
4候補の保存容量、Attention の常駐容量、既存保存内容の再起動後の保持、本番 registry に対応する MEXC map を確認する。
CI・PR は実行しない。未確認の既存資格を推測で承認しない。

## Checkpoint

- 前段 source は 8e6ef26、文書 closeout は 5edf284。60分の MEXC 隔離実データ受入は完了。
- 本番はc32a2bbの4 Venue readerへ切替済み。DB、state、unitと旧releaseを保全し、MEXC取得を有効化した。
- Unicode銘柄の比較保存/GET拒否、warm Discoveryの512 MiB超過、selection再起動時のTTL延長、production map capture未対応を修正済み。
- 本番SQLite約4.3 GBのcopyを512 MiB cgroupで検証し、3世代・障害・同cutoff保留・次cutoff復帰・再起動を確認。既存76episode喪失0。
- 既存3 Venueのversion差分5件を定義で再照合、新規PEARLはunsupportedとして独立保持したcandidateを作成。旧577行の参照/数量/Widgetを保持。
- 全体local gateを通過し、c32a2bbをcommit/push・tracked releaseとして配置。本番DBのMEXC versionでmapを再資格判定し、全1107契約の一致とMEXC10銘柄の連続更新を確認。
- 既存maintenanceの失敗を追跡し、先頭100行がnullの列をPolarsがNull型へ推論する欠陥を再現。SQL列型の明示で修正し、実102行のParquet往復を確認。追加release gate後に失敗partitionのみ再生成する。

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

- archive型修正の追加commit/push・maintenance実反映・失敗partition再生成・timer再開。
- 本番ブラウザの一時chart 503の原因確認。全4組合せの表示成功とwrite 0は確認済み。
- Attentionが実本番で512 MiB OOMと4回の再起動を起こしたため09:17に停止。保存stateを保持し、長時間・実HTTP負荷と容量上限の再確認が必要。短時間隔離probeのPASSでproduction受入を代替しない。
- 数量未確認4件・Widget未確認3件は既存の未確認として保持し、全件review済みとは扱わない。
