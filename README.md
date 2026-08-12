# prep-watchdeck

- 作成: `2026-06-18T04:43:28+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 文書更新作業: `2026-08-12_21:38`（Asia/Tokyo）
- 状態: `現行`

---

`prep-watchdeck`は、Bitgetのpublic market dataを使うローカル市場監視watchdeckです。
scanner-coreがDuckDBとsnapshotを更新し、SvelteKit Webが異常な値動きの発見、
候補の絞り込み、risk/context確認、銘柄annotationの保存を支援します。

取引判断や損益の記録、自動売買、Private API、残高・position、注文endpoint、
自動発注、売買推奨は製品責任に含めません。

## 必要なもの

- Python 3.13
- `uv`
- `bun`
- live利用時のinternet接続

Web依存をまだ導入していない場合:

```bash
cd apps/web
bun install
bun run generate:types
cd ../..
```

## 最短起動

Repo root:

```bash
bash scripts/start-all.sh
```

既定URL:

```text
http://127.0.0.1:5173/
```

5173が使用中なら、5174以降の最初の空きportへ自動fallbackする。`PORT`を指定した
場合も、その値を開始点として最大100候補を昇順に探索する。実際に選んだURLは
起動時の`url=...`へ表示する。選択後に別processが同じportを取得した場合は、
別portへ黙って移らず起動を停止する。

networkを使わないfixture起動:

```bash
SNAPSHOT_SOURCE=fixture bash scripts/start-all.sh
```

既存snapshotだけでWebを起動:

```bash
SNAPSHOT_SOURCE=skip bash scripts/start-all.sh
```

主なoverride:

| 目的 | 例 |
| --- | --- |
| port探索開始値 | `PORT=5174 bash scripts/start-all.sh` |
| live対象数変更 | `LIVE_MAX_SYMBOLS=10 bash scripts/start-all.sh` |
| 全対象 | `LIVE_MAX_SYMBOLS=all bash scripts/start-all.sh` |
| template変更 | `TEMPLATE=aggressive bash scripts/start-all.sh` |
| fallback禁止 | `START_ALL_STRICT_SNAPSHOT=true bash scripts/start-all.sh` |

起動時にscanner-coreとWebが共有する次の絶対pathを表示します。

```text
stateDir=...
snapshotPath=...
databasePath=...
serviceStatePath=...
tickerRuntimePath=...
chartDir=...
```

異なる個別overrideがscanner-coreとWebへ設定されている場合は、起動前に停止します。

## State directory

未指定時はRepo内の`var/`を使います。Repo外へ切り替える場合:

```bash
export PREP_WATCHDECK_STATE_DIR="$HOME/.local/share/prep-watchdeck"
bash scripts/start-all.sh
```

このrootから次を導出します。

```text
watchdeck.duckdb
scanner.lock
snapshots/latest.json
snapshots/service-state.json
snapshots/ticker-runtime.json
snapshots/charts/latest/
past-notes/current.json
past-notes/archive/YYYY-MM/past-notes-YYYY-MM.json
dashboard-view-settings/current.json
usage-events/
ops/daily/v2/
tmp/e2e/
tmp/performance/
tmp/soak/
```

監視stateの個別path環境変数は互換overrideとして残ります。標準運用では
`PREP_WATCHDECK_STATE_DIR`だけを設定してください。
相対state rootを指定した場合はRepo root基準で解決します。

## 既存stateの移行

service、scan、Webを停止してから、コピー先とArchive先を指定します。

```bash
bash scripts/maintenance/migrate-state-dir.sh \
  --target "$HOME/.local/share/prep-watchdeck" \
  --archive-dir "$HOME/watchdeck-local-archive/state-$(date +%Y%m%d-%H%M%S)"
```

このスクリプトは次を行います。

1. 旧`var/`全体をfull Archiveへ複製し、state layout version 2の証拠を付ける。
2. layout v2のDB、snapshot、chart、Past Note、Dashboard settings、usage events、opsだけを
   state rootへ複製する。
3. 相対path manifestとSHA-256、JSON、snapshot/chart runId、監視annotation件数を検証する。
4. 旧`data/scanner.duckdb`があれば`legacy-data/`へ複製する。
5. 旧ファイルを一切削除せず終了する。

既存のversion markerがないArchiveはlayout v1として引き続き検証できます。

切替後の確認:

```bash
export PREP_WATCHDECK_STATE_DIR="$HOME/.local/share/prep-watchdeck"

cd apps/scanner-core
uv run watchdeck status
uv run watchdeck doctor
cd ../..

bash scripts/maintenance/verify-state-dir.sh \
  --source "$PWD/var" \
  --target "$PREP_WATCHDECK_STATE_DIR" \
  --archive-dir "$HOME/watchdeck-local-archive/state-YYYYMMDD-HHMMSS" \
  --mode cutover
```

旧stateが更新された、監視stateが欠けた、runIdが不一致、full gateが失敗した場合は、
旧`var/`を削除せず環境変数を外して戻します。

## Scanner service

scanner-core:

```bash
cd apps/scanner-core
uv run watchdeck service
```

有限確認:

```bash
uv run watchdeck service --max-symbols 1 --stop-after-records 1
uv run watchdeck doctor
```

同じDuckDBへ複数writerを起動しないでください。service実行中のsnapshot再発行は
`watchdeck publish-service`経路を使います。

serviceは最新1分足timestampの前進を監視する。既定では起動後300秒を判定対象外とし、
60秒ごとに確認する。300秒以上前進しない場合だけBitget public RESTを1銘柄・1件で
確認し、REST正常下の停止が3回連続した場合に非0終了する。RESTも失敗中なら外部障害と
みなし、serviceを終了させず既存WebSocket再接続を継続する。

自動復旧にはprocess manager側の`Restart=on-failure`が必要である。緊急時は
`--watchdog-interval-sec 0`でwatchdogを無効化できる。Bitget RESTの429、対象5xx、
network timeoutは最大5 attemptsのbounded retryを行うが、その他の4xxや不正responseは
再試行しない。詳細な確認とrollbackは[現行運用](docs/current/operations.md)を参照する。

## 個別操作

live snapshotだけ更新:

```bash
bash scripts/update-live.sh
```

scanner状態確認:

```bash
cd apps/scanner-core
uv run watchdeck status
uv run watchdeck doctor
```

fixture snapshot:

```bash
cd apps/scanner-core
uv run watchdeck scan --source fixture --fixture-set basic --template balanced
```

日次サマリー:

```bash
bun scripts/ops/watchdeck-daily-summary.mjs
```

schema v2出力は解決済みstate rootの`ops/daily/v2/`へ保存されます。
`PREP_WATCHDECK_STATE_DIR`未指定時はrepo `var/ops/daily/v2/`です。既存のschema v1出力は
上書きしません。

## 検証

full local gate:

```bash
bash scripts/verify-local.sh
```

Realtime performance / soak:

```bash
cd apps/web
bun run test:performance
SOAK_DURATION_MS=3600000 bun run test:soak
```

文書metadata:

```bash
bun test scripts/maintenance/document-metadata.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun test scripts/maintenance/document-links.test.mjs
bun scripts/maintenance/check-document-links.mjs
```

旧文書とmockupをRepo外へArchiveする場合:

```bash
bash scripts/maintenance/archive-repo-history.sh \
  --archive-dir "$HOME/watchdeck-local-archive/repo-history-$(date +%Y%m%d-%H%M%S)"
```

Git追跡を外す直前に、tracked集合、現在のsource、Archive本体を再照合します。

```bash
bash scripts/maintenance/verify-repo-history-archive.sh \
  --archive-dir "$HOME/watchdeck-local-archive/repo-history-YYYYMMDD-HHMMSS"
```

この再検証が失敗した場合は旧文書を削除しません。

Repo historyとstateの両Archiveが揃った後の最終化:

```bash
bash scripts/maintenance/finalize-reorganization.sh \
  --repo-history-archive "$HOME/watchdeck-local-archive/repo-history-YYYYMMDD-HHMMSS" \
  --state-target "$HOME/.local/share/prep-watchdeck" \
  --state-archive-dir "$HOME/watchdeck-local-archive/state-YYYYMMDD-HHMMSS"
```

既定はdry-run。出力を確認してから同じコマンドへ`--apply`を付ける。
`--apply`でも、検証済みmanifest記載の旧文書・mockupと、検証済みlegacy DBだけを
削除する。旧`var/`はrollback用として保持する。

`--apply`は削除開始前にRepo history Archive内へ一時証跡を実際に作成する。
作成・書込みができなければ削除0件で停止する。削除完了後は
`REPO_FINALIZATION_VERIFIED`へ確定する。削除開始後に失敗して
`.REPO_FINALIZATION_VERIFIED.*`が残った場合は、消さずに部分実行を調査する。

## ディレクトリ境界

- Git Repo: `apps/`、`config/`、`schemas/`、`fixtures/`、`scripts/`、現行文書
- Runtime state: DB、snapshot、chart、Past Note、Dashboard settings、usage events、ops
- Local Archive: 旧文書、完了計画、mockup、backup、過去検証証跡

現行文書の入口は[docs/README.md](docs/README.md)です。

## 現行仕様

- [現行概要](docs/current/overview.md)
- [アーキテクチャ](docs/current/architecture.md)
- [運用](docs/current/operations.md)
- [データ契約](docs/current/data-contracts.md)
- [UIワークフロー](docs/current/ui-workflow.md)
- [検証](docs/current/validation.md)
- [UI設計規則](DESIGN.md)

## Security

- Bitget public market dataだけを扱う。
- API key、secret、残高、position、注文機能を追加しない。
- local write APIとruntime commandはlocalhostだけに許可する。
- `git clean -fdx`や`git clean -fdX`を使わない。ignored stateを削除する危険がある。

## OI 60分

serviceはBitget public tickerのOpen Interestを5分bucketで24時間だけDuckDBへ保持し、
exact 60分前と比較します。履歴不足・古い値・不正値は「不明」で、注目度へ加点しません。
