# 08 Migration・Rollback・運用注意

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## DB migration

新tableは`CREATE TABLE IF NOT EXISTS`によるadditive migrationとする。

- 既存tableをALTER/DROPしない。
- 既存DB backupをこの実装waveのコードから自動作成しない。
- 現行運用手順にbackupがある場合はそれを使用。
- migration失敗時はsnapshot publishを続行せず、エラーを明示する。

## Deploy / restart

1. serviceとWebを停止。
2. codeを更新。
3. focused/full gate。
4. serviceを起動し、新table初期化を確認。
5. `watchdeck doctor`。
6. 初回snapshotではOI UNKNOWNが正常であることを確認。
7. 60分以上経過後、referenceがある銘柄で状態が変化することを確認。

## Rollback

- source commitをrevert。
- `open_interest_samples` tableは残す。旧コードは参照しない。
- table DROPはrollbackの必須条件ではなく、別の明示的maintenance作業。
- snapshot schemaVersionは変わらないため、旧consumer互換を維持。
- version 3 snapshotを旧codeで読む場合の挙動をfixtureで確認し、問題があればlatest snapshotを旧codeから再発行する。

## Operational expectations

### Upgrade後0〜60分

```text
OI 60分: 履歴不足
OI score contribution: 0
```

### 60分以降

exact target bucketがある銘柄だけ状態を表示。

### Downtime / gap

60分前bucketがなければUNKNOWN。古い別bucketへfallbackしない。

## Storage

- 5分bucket
- 24h retention
- 最大500銘柄で概算144,000 rows
- pruneはbounded
- state Archiveの対象には自然にDuckDBとして含まれる

## Monitoring

新しいGrafana、metrics server、alertは追加しない。

既存の確認手段:

```bash
cd apps/scanner-core
uv run watchdeck status
uv run watchdeck doctor
```

必要ならDuckDBで件数・期間をread-only確認するが、本番service稼働中の別writerは起動しない。
