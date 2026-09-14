# 運用・隔離検証・復旧

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## O01: 初期運用値と実測

nativeは既存60秒cycle、計算同時1、待ち最新1、Web poll5秒、snapshot expiry120秒を初期値とする。研究は同時1/queue8/365日/10,000観測/60秒deadline、Fed fetchは07の上限。これらは永久上限でなく、計測して設定と文書へ反映する設計値。

現行active universeで2連続cycleのwall time、CPU/RSS、DB read time、payload bytes、lagを記録する。暫定budgetは、確認した各cycleのnative計算時間が30秒以下で、snapshotがexpiry前に読めること。2点でp95を測ったとは言わない。継続smokeで十分な測定数が得られた場合にのみ分位を追加し、最大値・測定回数・hardware・instrument数を併記する。

毎時runの実サイズ×24×instrument scope数を基に30日DB/365日archiveを見積もる。ログ・job・snapshotごとのquotaを設定し、容量不足ではproducerやDB全体を落とす前に新規低優先度保存を停止して理由を公開する。高cardinalityのinstrumentをmetric labelへ無制限追加しない。

## O02: migrationと隔離

最初に有効設定を秘密抜きで確認。test専用DB、state-dir、portを明示し、productionや他projectと一致なら拒否する。JustPass/5432等へ接触しない。既存のtest target validatorとverify-localの隔離方式を再利用する。

空DB→全migration、既存0004相当→新migration、同migration再実行、rollback前提のreader compatibilityを確認する。live DBへDDLしない。新table以外の既存schemaを不要に変更しない。実装に必要なmigrationは作成するが、本番適用は別承認。

## O03: 実データsmoke

公開read-only dataから限定した実responseを隔離targetへ取得し、native input→3profile→snapshot→API→UI→decision保存→再起動読戻しを確認する。scoreだけfixtureで上書きしない。history不足のprofileはデータ不足を正しく示し、必要な範囲の許可された履歴取得で実値経路を確認する。

Fedは実manifestとresponseを取得し、revision/hash/sourceUrl/time precision/件数を検査する。古い配布物でも「fresh」としない。通信不可の場合はBLOCKEDと記録し、録画fixture成功と分離する。

十分な長期観測がないときはstudyのlow-N表示を実入力で確認し、CI/大標本経路は人工fixtureで別検証する。数週間待てば完了すると約束せず、未実証の実市場統計を明示する。

## O04: 復旧試験

DB commit直後・publish前に停止→再起動して同digestの成果物を再発行。temp write中断→旧正常JSONが残る。同request再送→重複decisionなし。archive write→readback/hash不一致→DB保持。正常archive→retention→DB+archiveから同じstudy入力を復元。generation違いを混ぜたreaderは拒否。

時計ずれ、feed停止、DB read timeout、queue満杯、job取消、permission error、disk fullを隔離で注入し、native既存laneと新laneの障害を分離する。secretがexception/logへ出ないことを確認する。

## O05: 無効化と本番反映

featureの起動設定は既存configへ自然に追加する。独立laneの有効/無効というライフサイクルだけを表し、data状態へ流用しない。無効化時は新job受付停止→実行中job終了/取消→最後の状態を明示し、旧Universeを継続する。

schema追加後のrollbackは、まず互換な現行binaryでlaneを無効化する。古いbinaryが追加migration/tableを許容するか試験なしに戻さない。down migrationやarchive削除を復旧の既定にしない。decision記録は保全する。

資料/コードの完成、隔離検証、本番展開は別の記録。承認がない限りservice install/start/stop/restart、live migrate、deploy/cutoverをしない。承認後にのみ、backup/restore確認→単一対象→readback/health→限定画面確認→監視確認の順で反映する。

## 実装後の検証コマンド

現行正本 `docs/current/validation.md` を確認してから実行する。

```bash
# root: 文書
bun test scripts/maintenance/document-contracts.test.mjs scripts/maintenance/product-boundary.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
git diff --check
# apps/market-core: 関連pytestから、storage変更なので最後に全pytest
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
# apps/web
bun run generate:types
bun test
bun run check
bun run build
PREP_WATCHDECK_FULL_E2E=1 bun run test:e2e
# root: repo横断の最後に1回。上記と重複するbuildを無目的に反復しない
bash scripts/verify-local.sh
```

新しいCLI subcommandは実装後の `watchdeck-market --help` とsubcommand helpで存在を検証して文書へ書く。この資料のpath案やprofile名を、既に使えるCLI commandとして報告しない。
