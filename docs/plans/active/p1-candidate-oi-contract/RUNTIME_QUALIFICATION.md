# 初期Runtime Qualification

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

> **再実行禁止:** 以下は完了当時のCandidate / OI qualification証拠である。Candidate・74hの受入項目は
> [Decision 0010](../../../decisions/0010-retire-74h-candidate-deep-backfill.md)によりsupersedeされた。
> 現行runtimeの受入手順として再利用しない。

## 目的

P1修正がテスト内だけで成立する見せかけを防ぎ、既存の起動・state・service境界で利用可能であることを確認する。新しいqualification frameworkは作らない。

## Mandatory checks

### RQ-01 One-command fixture startup

```bash
SNAPSHOT_SOURCE=fixture bash scripts/start-all.sh
```

- 実際に出力されたURLへ到達できる。
- Candidate / Watchlist / Selected detail / Smart Rankが表示される。
- 74h rule説明がfixtureのactive configと一致する。
- process停止後に孤児processが残らない。

### RQ-02 Isolated finite live smoke

本番stateとは別rootを使う。

```bash
smoke_root="$(mktemp -d)"
cd apps/scanner-core
PREP_WATCHDECK_STATE_DIR="$smoke_root"   uv run watchdeck service --max-symbols 1 --stop-after-records 1
PREP_WATCHDECK_STATE_DIR="$smoke_root" uv run watchdeck doctor
```

- Public market dataを取得できる。
- DB/snapshotを生成できる。
- 本番stateを変更しない。

### RQ-03 OI storage/runtime smoke

- 有効なticker OIから1件以上の5分bucket sampleを保存する。
- 同一bucket再実行で重複しない。
- stale/invalid tickerは保存しない。
- 24hより古いsampleのpruneはdeterministic store testで証明する。
- 60分実時間待機をmandatoryにしない。exact 60m lookupはfixture/integration testで証明する。

### RQ-04 Restart persistence

同じstate rootでservice/processをcontrolled restartし、次を確認する。

- additive OI tableを再利用できる。
- 既存sampleを失わない。
- Past Note / Dashboard settingsを失わない。
- snapshot / Hot tickerが再び前進する。

systemdが利用できない実行環境では、同じstate rootを使うCLI processの停止・再起動で代替し、その制約を証拠へ記録する。

### RQ-05 Reconnect path

- 既存のWebSocket reconnect testを特定して実行する。
- 不足する場合のみ、接続終了→再接続→再購読→ticker/candle ingest再開を直接証明するfocused testを1本追加する。
- 自然な24時間切断は外部時間依存のためmandatory同期gateにしない。運用観測としてresidual riskへ記録する。

### RQ-06 Live artifact semantics

fixtureまたはlive artifactで次を確認する。

- Candidateの全itemが74h composite `true`。
- composite `false/null` rowはCandidateにいない。
- 同rowは監視Universe内ならWatchlistには残る。
- `None`/履歴不足は条件未達と同じ説明にしない。
- OI stateは増加/横ばい/減少/履歴不足であり、強気/弱気へ翻訳しない。

### RQ-07 Final audit

```bash
bash scripts/verify-local.sh
git diff --check
git status --short
git diff --stat
git diff -- apps/scanner-core apps/web docs README.md
```

- full gate exit 0。
- runtime/secret/generated artifactがdiffへ入らない。
- scope外変更なし。
- 未解決P0/P1なし。

## 非blockingな運用観測

- Bitgetの自然な24時間WebSocket切断後の回復。
- 実市場でOI `UNKNOWN`がどの程度残るか。
- fresh stateで74h履歴が揃うまでのCandidate空状態。

これらは記録するが、本計画の同期実行を24時間以上止める理由にはしない。実害が確認された場合のみ別planへ切り出す。
