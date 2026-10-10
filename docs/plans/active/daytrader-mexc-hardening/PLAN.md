# MEXC・Discovery 修正と本番反映

timestamp="2026-10-10(土)_09:41 JST"
- 作成: `2026-10-10T08:51:29+09:00`
- 更新: `2026-10-10T09:41:00+09:00`
- 検証: `2026-10-10T09:41:00+09:00`
- 状態: `実装計画`

---

## Goal / scope

MEXC と Discovery の不足を実物から確認・修正し、対象差分を commit・push して本番反映する。
4候補の保存容量、Attention の常駐容量、既存保存内容の再起動後の保持、本番 registry に対応する MEXC map を確認する。
CI・PR は実行しない。未確認の既存資格を推測で承認しない。

## Checkpoint

- Source修正と追加hardeningは `a1ad6ca` までcommit・通常push済み。Webはclean tracked release `/home/tn/releases/prep-watchdeck/a1ad6ca/apps/web` へreader先行反映し、旧drop-in・releaseを保存した。Market/Ranking/Attentionは `c32a2bb` の既存稼働releaseを維持。
- 稼働Web `/health` と `/api/market-data` はHTTP 200。localhost/TailscaleのDesktop/Mobile全4組合せでDiscovery表示とMEXC native chartを確認。BTC_USDT version 9923の500 bars、書込み・selection POST 0、protected state hash不変。
- 本番mapはDBの全1107契約と一致し、MEXCは審査済み10銘柄。MEXC catalog全件や未確認の既存数量4件/Widget3件を審査済みとは扱わない。
- 現在の4主要serviceはactive、再起動回数0。AttentionはMemoryMax 768 MiBに対しmemory.current 805,056,512 byte、peak 805,752,832 byte、OOM/OOM-kill 0。file cache 312 MB、anonymous 489 MB、memory pressure some avg10 0.02。単発値から長時間容量余裕は判定しない。
- Maintenance timerはactiveだが、09:00の実行はfunding sweep成功後にMaintenanceError / exit 2で失敗し、unitのpeakは5.3 GiB。09:00/09:39のread-only data-operationsもranking identity mismatch / metric future timestampでexit 1。失敗partition修正・parquet往復だけで通常maintenance全体を受入済みとしない。
- clean releaseのWeb関連43 tests、Svelte check（0 errors/warnings）、buildはPASS。4ケースのブラウザ受入PASS。pushとWeb反映済みだが、maintenance/data-operations・Attentionの継続運用受入は未完了。
- 進捗: 実装・commit・push・Web反映は完了。下記の運用受入項目が未完了のため、このplanはactiveに保つ。

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

- 次のmaintenance失敗はログ/manifestを用いて非破壊で原因を特定し、個別の失敗partition修復を超えるwriter・retention操作は別承認の下で行う。timer/serviceはactiveだが、成功した次回実行を確認するまでは受入保留。
- data-operationsのread-only failure（09:00 ranking original identity mismatch、09:39 metric future timestamp）をソース・実データ・契約から切り分け、正当なcoverage欠損を0/成功へ丸めずに解消する。
- Attentionは稼働とOOMなしを確認したが、現在の768 MiB上限に対する余裕、長時間・実HTTP負荷、保存増分を再確認する。retention/archive、30日 prospective evidence、容量保証は別の運用受入。
- 数量未確認4件・Widget未確認3件は既存の未確認として保持し、全件review済みとは扱わない。
- 最後に見たproduction status以後の変化や将来の再起動・cutoverは未観測。今回のWeb反映を30日acceptance、候補優位性、全MEXC銘柄coverageの証拠へ読み替えない。
