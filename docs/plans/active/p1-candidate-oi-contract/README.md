# P1 Candidate / OI 実装計画入口

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

> **再開禁止:** このplanは完了済みの歴史的証拠であり、Candidate・74h部分は
> [Decision 0010](../../../decisions/0010-retire-74h-candidate-deep-backfill.md)によりsupersedeされた。
> 現行契約はOI 60分だけを維持する。このdirectoryの手順を実装指示として再利用しない。

## このディレクトリの役割

このディレクトリは、`prep-watchdeck`のPersonaレビューで確認した既知P1を閉じ、監視専用v1.0を**コード完成候補かつ初期runtime適格**まで進めるための正本living planである。

対象は次の2テーマだけ。

1. 74h価格条件と24h USDT売買代金増加条件を三値ANDで評価し、Candidateランキングへ接続する。
2. OIをlocal DuckDBへ5分bucketで保存し、正確な60分前sampleとの比較から状態を算出する。

## 読む順番

1. [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) — Codexへ渡す入口
2. [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — 人間向けの正本計画
3. [`IMPLEMENTATION_PLAN.ai.json`](IMPLEMENTATION_PLAN.ai.json) — AI継続用の構造化正本
4. [`RUNTIME_QUALIFICATION.md`](RUNTIME_QUALIFICATION.md) — 実装後の初期運用適格性
5. [`TASK_BOARD.csv`](TASK_BOARD.csv) — Checkpoint一覧
6. [`appendices/`](appendices/) — 対象ファイル、受入条件、失敗経路

## 完成の定義

```text
Phase A: AC-P1-* をすべてPASS
  → P1修正wave完成

Phase B: AC-RQ-* をすべてPASS
  → 監視専用v1.0のコード完成候補・初期runtime適格
```

Bitgetの自然な24時間WebSocket切断を越える長時間観測は、外部時間依存が大きいため本計画の同期実行を止めるmandatory gateにはしない。代わりに、既存または追加する最小reconnect regression testとcontrolled restartで回復経路を証明し、自然切断は運用観測として残す。

## 正本の優先順位

1. 実際の現行Repo、`AGENTS.md`、schema、tests、CLI help
2. `docs/current/` と `docs/decisions/`
3. 本ディレクトリのliving plans
4. 付録・参考資料

Baseline commitは `47839c33466f970f1c31d665df73e5d24ba77e6c`。実装開始時のHEADが異なる場合、resetせず現行HEADを再監査し、両living planのbaseline、facts、target files、decision logを更新する。

## 禁止

- PR、push、deploy、remote write
- Private API、注文、損益、実約定、Copy/Grid/Bot機能
- VPI/Smart Rankの再設計
- Watchlist列追加、UI全面刷新
- 新規OSS、DB/framework置換
- 目的外refactor
- `UNKNOWN`や履歴不足をもっともらしい値で補完
