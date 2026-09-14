# 実コードとの対応と変更箇所

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## 確認済みの基準

基準HEADはsources.lock.jsonに固定。現行は3 VenueのPerp収集で、WebはDBへ直接接続せずJSONを読む。Python依存にはPolars、psycopg、Pydantic、aiohttp、Typerがある。rankingは現行UI文書で未実装とされる。これを将来の禁止とは扱わない。

| 確認した既存path / symbol | 再利用・注意点 |
| --- | --- |
| `apps/market-core/src/prep_watchdeck_market/models.py` / `canonical_json_sha256` | canonical化とdigest。Decimal・日時は契約どおり文字列化してからhashする |
| 同 `/artifacts.py` / `ArtifactModel` | camelCase、extra forbid、NaN禁止、既存quality。新成果物を既存4種へ無理に混ぜない |
| 同 `/service.py` / `MarketService.run_forever` | 複数async lane。重い集計をevent loopへ直置きしない |
| 同 `/cli.py` / `app` | Typer subcommand、既存Settings、lockとexit code方針を使う |
| 同 `/database.py`、`migrations/0001`〜`0004` | migration仕組みを確認して次番号を採る。現在ファイルを改変しない |
| 同 `/archive.py`、`retention.py` | confirmed/readback/digest境界。新履歴にも検証前削除を許さない |
| `apps/web/src/lib/server/market-artifact-repository.ts` | Ajv検証、generation整合、120秒/selected15秒の現行鮮度。新lane失敗で旧bundleを失敗させない |
| 同 `/market-state-paths.ts`、`atomic-json-store.ts`、`lock-file-guard.ts` | path、atomic write、並行write。任意pathをAPIから受けない |
| `apps/web/src/lib/components/universe/UniverseChart.svelte` | 既存Chart維持。今回Velaへの置換は不要 |
| 同 `/MarketPastNotesPanel.svelte`、serverのnote repository | 観測annotation。判断時点snapshotを既存noteの別statusへ押し込めない |
| `schemas/`、Web `src/lib/generated/` | JSON Schemaを正本に型生成。生成済みTSは手編集しない |
| `scripts/maintenance/check-document-metadata.mjs` | 新規docsもH1と先頭metadata対象。状態は参考/実装計画等 |
| `docs/current/validation.md` | 変更面ごとのgate。旧shadowツールは退役済みなので使わない |

ファイル存在確認と、全内部関数の実行検証を混同しない。service/artifacts/cliは関係範囲の読取り、archive等は存在・現行文書での契約確認である。

## 新設候補（現在存在すると主張しない）

- Market Core `discovery/`：`features.py`、`ranking.py`、`studies.py`、`evidence.py`、`store.py`、`runtime.py`、`contracts.py`。初期から空classを並べず、実際に分かれる責務だけ分割する。
- migration：`discovery_runs`、`decision_records`、`public_evidence_revisions`。独立した保存・削除寿命が理由。study jobはstate-dir上の小さなcontrol/resultで足りる。
- schema：`discovery-snapshot.schema.json`、`discovery-study.schema.json`、`discovery-decision.schema.json`。関連requestは適切にschema化。互換性を明示する。
- Web：`src/lib/server/discovery-repository.ts`、`src/lib/components/discovery/`、`src/routes/api/discovery/`、`src/routes/discovery/`。
- tests：Market Coreの既存pytest配下とWebのunit/E2E配下。11のIDで追跡する。

## 接続の基準

L1/candle保存後の通知から、重複しないbounded discovery計算へ接続する。専用executor/thread内でDB readとPolars処理を行い、同時実行数1、queue上限1の最新要求優先。I/O timeout後のthreadを残したまま新計算を無制限に積まない。キャンセル・終了まで追跡する。

studyは優先度を下げた同じbounded workerで処理し、UIのpollから重い集計を直接実行しない。既存collectorが失敗しても成功Venueの情報は残し、比較scope全体の完全性は別に示す。API path/新class名は案だが、これらの境界は要件である。
