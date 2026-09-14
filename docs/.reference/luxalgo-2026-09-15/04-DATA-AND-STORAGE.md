# データ契約・時点整合・永続化

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## 時刻とidentity

時刻はtimezone-aware UTC、JSONはISO-8601。`asOf`は計算入力の採用締切、`windowEnd`は最後の完了1分足の終了時刻、`generatedAt`は出力時刻。3者を置換しない。`windowEnd <= asOf <= generatedAt`を検証する。

足は `[openAt, openAt+1m)`。入力は終了がwindowEnd以下、observedAtがasOf以下で、許容finality・同じinstrument versionに属するものだけ。sourceAtがない場合はnullのまま、観測時刻基準であると表示する。日付しかない公表情報をUTC00:00という正確な公表時刻へ変換しない。

`venueInstrumentId`と`venueInstrumentVersionId`を保持し、scopeはasset class/market type/Venue/quote currency/価格basis/feature window/profile revision。ticker名だけでFed以外の事実をinstrumentへ自動対応させない。historical identityの変更を無断で跨がない。

## 新read modelの要求

以下は新設契約の必須要素。最終のJSON Schemaを実装時に作り、Pydantic/TSを一致させる。

| 概念 | 必須情報 |
| --- | --- |
| Snapshot envelope | schemaVersion、generationId、asOf、windowEnd、generatedAt、expiresAt、calculationVersion、profileHash、scope、inputDigest、sourceCycleRefs |
| Scope coverage | activeCount、evaluatedCount、eligibleCount、excludedCount、failedSources、comparisonComplete、rankingAvailable |
| Candidate | identity/version、profileId、score/rankまたはnull、eligibility、reasons、components、inputEvidenceRefs |
| Component | name、valueまたはnull、unit、window、weight、contributionまたはnull、quality、missingReason、observedAt/sourceAt、source/hash |
| Study result | query定義/hash、dataRevision、asOf、outcomeStartAt/outcomeEndAt、母集団・適格・resolved・censored・除外数、k/n、estimate/intervals、guard、期間別内訳、事例refs |
| Decision record | recordId、createdAt、immutable snapshot/digest、選択候補、任意メモ。実約定・損益ではない |

qualityは元値の状態、eligibilityは指定profileに使えるか、comparisonCompleteはscope全体の取得成否、job stateは処理の寿命。異なる主体なので分ける。細かい独立enumを無目的に増やさない。新しいschemaはunknown property/NaN/Infinityを拒否し、nullableにはreasonを要求する。

## 保存モデル

`discovery_runs`：毎時自動保存または手動保存が参照する、入力値・計算定義・対象一覧・除外理由込みのimmutable payload。idはcanonical payloadのdigestから決め、同じidで内容が違えば衝突エラー。DB commit後に成果物をpublishする。process再起動後はcommit済みrunから再発行できる。

`decision_records`：ユーザーの独立した意思記録。runへ参照を持ち、必要なsnapshotを自身でも保持してauto履歴削除から守る。Past Noteは観測annotationのまま維持。idempotency key同一・同一payloadは同じrecord、異なるpayloadは409相当。メモ修正が必要ならrevisionを残す。

`public_evidence_revisions`：dataset/id/rawHashで重複排除し、firstSeenAtを更新しない。訂正は別revision、最新参照のみ更新。同一取得の再送で過去のfirstSeenAtを新しくしない。

raw既存tableを追加のwriterで直接修正しない。新migrationは次の未使用番号。既存rawのretentionで消えるrowだけへのFKをsnapshot再現の唯一の根拠にしない。入力の使用値とdefinitionをrun内に固定する。

## 発行と同時更新

新しい発見snapshotは単一JSONとしてatomic replace。study結果はquery+data revisionごとのimmutable result、別のjob stateをatomic writeする。JSON Schema検証→同一filesystemのtemp→flush/fsync→rename→必要なdir fsync。失敗時に元ファイルを破壊しない。

Webは新lane専用repositoryでvalidateする。既存MarketArtifactBundleへ必須追加して新lane失敗でUniverseを落とさない。requestしたinstrument/profile/generationと結果が一致するか確認し、遅着レスポンスが新selectionを上書きしない。

## 時間・容量の既定

native表示は既存60秒cycleに合わせ、expiresAtはasOf+120秒を初期値とする。再生成しただけで古い入力の寿命を延長しない。clock skewが将来5秒超なら異常として扱う。値は設定で変えられるが、profile/計算definitionと一緒に保存する。

毎分の全量を無制限に保存しない。自動研究用snapshotは毎時UTC境界H後の最初の有効cycle（許容遅延120秒）で作る。そのwindowEndはHへ固定し、asOfは実際の入力採用時刻とする。遅延でwindowEndをH+1分へずらさない。H+120秒を過ぎた時刻を後から当時観測済みとして作らない。自動runは直近30日DB、以降はconfirmed archiveへ移し、初期365日を保持方針とする。手動decisionは自動期限削除しない。容量quota超過では自動保存停止を明示し、手動保存の失敗を黙って成功にしない。

archive dataset追加はreadback/hash/manifest/restoreまで実装する。既存3 datasetが新datasetも処理すると仮定しない。設定日数は設計値であり、実測容量に基づき変更し、文書と試験へ反映する。
