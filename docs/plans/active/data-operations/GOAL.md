# データ運用の欠測・名簿更新

timestamp="2026-10-02(金)_14:59 JST"
- 作成: `2026-10-02T13:55:30+09:00`
- 更新: `2026-10-02T14:59:39+09:00`
- 状態: `実装計画`

## 目的・対象

現在の銘柄対応表の陳腐化とnative確定足指標の欠測を実物から診断し、回復可能な欠測を
修復し、継続運用で再発を検知・回復できる状態へ進める。欠測を0、前回値、推測値で埋めない。
今回の対象はMarketの収集・保存・回復、Rankingの名簿・資格根拠・対応表、必要な運用手順。
ユーザーの既存push・main統合・稼働反映の承認を適用し、PRとCIは実行しない。

## checkpoint・完了条件

1. 現行source・設定・live snapshotから欠測を分類し、再現可能な根本原因を確定する。
2. 更新名簿の完全性、original ID/version/definition、参照市場の資格と根拠を照合する。
   symbolのみの同一視、参照providerの暗黙切替を行わない。
3. 必要な最小修正と隔離検証を完了する。回復はbounded、missing-only、version/hash guarded。
4. 稼働data・設定を保全し、検証済みsource・mapと必要な回復を反映する。
5. live API・DB・収集周期から更新・計算・identity・再発防止を確認し、正当な欠測と
   修復済み問題を区別する。source・commit・push・稼働反映を別々に記録する。

## 検証

変更箇所に近いpytest・Ruff・型確認、map/schema/evidence検証、docs metadata/link、diffを行う。
release gateは専用の一時Postgresと隔離stateで実行し、CIを使わない。
live確認は専用Market DB 55432と既存Ranking state/APIに限定し、時刻・単位・finality・provenanceを保つ。
欠測原因を分類し、複数収集周期で回復と継続更新を確認する。

## rollback

稼働変更前に専用DB・Ranking SQLite・map・unit/drop-inの原本を保存する。
新release/mapは旧releaseへの切戻しを保持する。既存確定足は更新・削除せず、回復は
不足行だけ追加する。復元は必要性を確認してから行い、現役dataを不用意に戻さない。
main統合時に必要な2つの保護条件だけを一時解除し、成功・失敗を問わず元の設定へ戻す。

## 未解決事項

- Bitget取得時刻固定、Hyperliquid配信穴、catalog補助項目による不要な版更新を診断・修正した。
- 現行1,095契約に照合し、536固定参照・40未対応・quantity/Widget未確認各3件を保持した。
- 隔離release gate成功（Core187、Ranking131、Web170、E2E94）。fa83be5をmainへ反映し、保護設定を復元した。
- 専用DBを再起動・移行せず、3serviceへ配置。1,095契約が全件一致し、5分周期のread-only監視が稼働した。
- Bitgetの大量欠測は回復し、定期catalog更新で不要な版更新の停止を確認。初回履歴回復は600秒・120req上限内、失敗0で完了。
- Hyperliquidの現在値が過去基準の補修待ちに圧迫されることを固定窓の公式APIで確定し、現足優先の補修へ修正した。
- 現足優先、件数累積、失敗の継続記録を13件のfocused検証・Ruff・型確認で検証した。追加修正の稼働反映と複数周期の確認が未完了。
- 実際のスマホでの受入はこのデータ運用修正の完了条件に含めない。
