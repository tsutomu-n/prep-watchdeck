# API・ユーザーフロー・異常表示

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## U01: APIの完成契約（新設）

WebはDBへ接続せず、producerのvalidated read modelを読む。route名の変更はよいが、機能をCLI専用で終えない。

| method / path案 | 要求・応答 |
| --- | --- |
| GET /api/discovery | profile/scopeを検証してsnapshotを返す。no-store。期限切れ時はstale envelope、現在rankはnull |
| POST /api/discovery/studies | localhost/origin検証、allowlist query、UUID/idempotency。202でjobId/queryHash。重い計算はqueueへ |
| GET /api/discovery/studies/{jobId} | queued/running/succeeded/failed/cancelledと結果。存在しないidは404、期限後は410 |
| DELETE /api/discovery/studies/{jobId} | 未完jobの取消要求のみ。worker cleanup後にcancelled。履歴削除へ流用しない |
| POST /api/discovery/decisions | 選択generationとメモの保存要求。202の保存待ち。workerのDB commit/成果物発行後にのみ保存済み |
| GET /api/discovery/decisions | 保存済recordと個別snapshot。pagination。更新停止時でも当時記録として閲覧可 |
| GET /api/discovery/evidence | 既知revision、原典、source health。任意URL取得proxyにしない |

決定POSTの応答にはrequestIdを付け、GETでcommit確認まで追跡できるようにする。画面上の保存成功を202受領だけで表示しない。サイズ上限/invalid queryは400または413、queue上限は429、producer利用不能は503、idempotency衝突は409。

Web→workerのcontrolはstate-dir内の新専用directory、UUIDファイル名、atomic JSON。親pathやSQL、コードをpayloadで受けない。active/queued合計最大8、1 worker、job最大60秒、重複queryは同一dataRevisionなら結果を再利用。cancelやtimeoutの処理が終わるまで実行slotを解放したことにしない。

## U02: 画面

`/discovery`を新設しUniverseから到達できるようにする。最上部はprofile、Venue/scope、asOf、対象/適格/除外件数、更新状態。主表はrank、symbol/Venue、score、price方向、主要component、品質。row詳細から計算式、入力窓、source、reason、Chart、判断保存、過去検証へ移動する。

単独instrumentのChartは既存selectionがgroup必須か実装で確認し、必要なら別のread-only選択契約を追加する。groupIdを偽装して既存検証をすり抜けない。旧group板/約定は現在の契約を維持する。

study panelには問いを日本語で表示する。「条件成立の入力締切以後、最初の分境界から1時間後の終値が上昇した割合」等とし、「利益確率」「勝率」へ短縮しない。N/k、resolved coverage、guard、Wilson参考区間、依存調整区間、baseline、前後半、直近期間、事例一覧を表示。n<10は全内訳も同様に非表示。

Fedは「公表情報」として別panelに置く。上流公表日、Watchdeck初回確認、取得状況、原典を分け、bullish/bearishの自動加点はしない。

## U03: 保存・比較

判断保存は表示中generationを指定し、backendが同じsnapshotを固定する。更新とのraceで新しい数値へ勝手に差し替えない。producerは表示済みgenerationのimmutable payloadをbounded cache（初期10分）に保持し、保存要求はgenerationIdとinputDigestを照合する。既にDBへ保存済みならそこから読む。どちらにも残っていないgenerationは410とし、再取得の確認を促す。クライアントの自己申告scoreを正本にしない。stale snapshotの保存は「過去時点の記録」として許容し、createdAtとsnapshot asOfを両方表示する。

保存記録から当時の式・入力・順位・対象集合を再表示する。現行profileへ再計算した結果がある場合も別revisionとして区別する。Decisionは実約定ではないのでPnL/Tradeと捏造対応しない。

## U04: アクセシビリティと停止状態

既存theme/tokenを使い、semantic table/form、keyboard、可視focus、非色依存statusを維持する。更新でフォーカスや選択行を飛ばさず、入力中/IME compositionを壊さない。narrow viewportでは重要な欠測理由と操作を隠さない。motionはreduced-motionへ従う。

最終validated snapshotを残す場合、更新停止時刻と現在利用不可を近接表示し、古いrankをリアルタイムとして表示しない。空データ、全除外、初期履歴不足、source一部障害、schema不一致、job失敗・取消を別メッセージにする。旧Universeは新lane障害でも閲覧を継続する。
