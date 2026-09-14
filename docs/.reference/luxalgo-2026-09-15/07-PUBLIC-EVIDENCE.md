# 公表情報の取得・利用・改訂

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## E01: 今回の実接続

必須の外部adapterはmarket-trackers-dataの `fed-communications` のみ。macro contextとして表示し、個別instrumentの方向点や価格予測に変換しない。nativeの価格・volume provenanceは各候補の根拠として別に残す。

上流schemaVersion=2、exportDir=`fed/communications`を調査済み。producerの固定schemaは12/sources.lock参照。取得先は設定した固定リポジトリのcommitに固定し、manifestとdataを同じrevisionから読む。初回はmanifest指定snapshot、通常は直近deltaとrevision再取得。local dump importも同一validation/normalize経路を通す。

| 上流field | Watchdeckでの扱い |
| --- | --- |
| id | datasetとの複合natural key |
| type | statement/minutes/pressRelease/speech/testimonyだけ許容 |
| date | YYYY-MM-DD、米東部の日付。eventDateに保存し精度dayとする |
| title、speaker、venue、note | textとして表示。nullableを捏造補完しない |
| url、videoUrl | 原典リンク。表示・クリックのみ、無条件サーバーfetchしない |
| provenance | source/sourceUrl/retrievedAt/parser/confidence/needsReviewを保持 |

正確なpublic timestampがないためpublishedAt=null、firstSeenAtはWatchdeckの初回取得時刻。当日00:00や上流retrievedAtを、Watchdeckがその時点に知っていた証拠へ置換しない。

## E02: 取得と完全性

manifest/schema検証→source status確認→許可されたpathのみ取得→件数/型/日時/hash検査→DB transactionでrevision保存→成功後のみcursor更新。全件成功と一部成功を区別し、失敗cursorで取り逃しを固定化しない。

latest.jsonは最新ingestion-dayのdeltaであり全履歴ではない。直近3 UTC日の再読込みでproducerの書換え期間を覆い、停止が長いときはbounded snapshotで再同期する。404を機械的に「新情報なし」にしない。manifest・repository listingでその日のfileがないことを確認できた場合と、取得/権限失敗を分ける。

同一dataset/idでrawHashが変化したら新revision。同じhashの再取得ではfirstSeenAtを保持。backfillの旧dateを当時利用可能だった事実としない。Parquet型は上流で推定されるため、このadapterの正本はJSON。

## E03: 鮮度の再判定

manifestのstale=falseを信用せず、consumer nowでgeneratedAtとlastSyncAtを再判定する。初期transport期限48時間、future許容5秒。rowの古さとtransport障害を別にする。新しい公表がない静かな日を、通信断と同一視しない。source lastSyncOk=falseやschema変化なら新規情報扱いを止め、最終成功とエラーを表示する。

sourceごとに独立したhealthを返し、Fed停止でnative rankingや保存機能を落とさない。既存evidenceは過去の事実として読めるが「今の材料」として強調しない。needsReview=trueは自動採用せず参考・要確認とする。

## E04: HTTP・保存の防御

接続先host/repoとpathをallowlistし、manifest由来の `..`、絶対path、未知host、userinfo付きURLを拒否する。redirectも再検証。TLS検証無効化、任意URL fetch、shellを使った展開はしない。初期上限は1応答16 MiB、gzip展開後64 MiB、connect5秒/total30秒、同時2、429/5xxの指数backoff最大3回。上限超過は理由付き失敗。

ETag/Last-Modifiedを利用してもsourceの取得時刻を捏造しない。本文はtext escape、URLはhttpsか許可したschemeのみ。credentials、HTTP Authorization、秘密付きqueryをlogやartifactに出さない。public source取得にユーザーのbroker鍵は不要。

## E05: 利用条件

Senate eFDのcommercial-use制限を確認済み。Congress、House由来資料はCC0表示だけで許可とみなさず、今回のnetwork allowlistに入れない。FINRA short volume≠short interest。FDA承認履歴≠将来承認予測、13F periodEnd≠公開日、政府award≠売上認識という意味の違いも後続sourceで検証する。

新sourceはsource terms、必要credential、redistribution、使用目的、identity mapping、公開時刻精度、coverage、失敗条件を記録し、未確認のまま有効化しない。利用条件の代理同意・購入はしない。Fedの実接続についても使用する配布物/原典の現行条件を実装開始時に確認し、metadataとリンクだけを扱い、全文転載を避ける。
