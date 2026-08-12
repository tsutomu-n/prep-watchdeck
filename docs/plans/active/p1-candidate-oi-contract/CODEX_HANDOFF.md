# Codex実装指示

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

> **停止:** 以下は完了当時の歴史的promptであり、実行・再開してはならない。Candidate・74h部分は
> [Decision 0010](../../../decisions/0010-retire-74h-candidate-deep-backfill.md)によりsupersedeされた。
> OI 60分だけが現行契約である。現行作業はcurrent docsと新しいactive planを正本にする。

以下をCodexへそのまま渡す。

```text
対象Repo: /home/tn/projects/prep-watchdeck
正本計画: docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.md
AI計画: docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.ai.json

現行Repoを事実の正本として、上記living planを読み、全mandatory acceptance criteriaが再現可能な証拠付きでPASSするまで自律実装してください。分析・計画更新だけで止まらず、実装、focused tests、full gate、初期runtime qualification、最終差分監査まで完了してください。

開始時に必ずRepo root、AGENTS.md、README、DESIGN.md、docs/current、docs/decisions、既存plan template/schema、Git状態、対象source/testsを確認してください。HEADが計画baselineと異なる場合はresetせず、現行HEADへ計画を再同期してください。既存の未コミット変更を上書きせず、専用branch `ai/p1-candidate-oi-YYYYMMDD-HHMM` を使用してください。

対象は次だけです。
1. 74h価格±閾値 AND 24h USDT売買代金増加閾値を三値で計算し、Candidate rankingだけをgateする。Watchlist/Raw Sort/Smart Rankの広い監視面は維持する。
2. OIを5分bucket、24時間retentionで既存DuckDB storeへadditiveに保存し、exact 60分前bucketと比較する。欠損・stale・invalidはUNKNOWN。UNKNOWNへ注目度の正加点を与えない。
3. Candidateのactive rule説明と、Symbol Monitoring RailのOI 60分状態だけを最小表示する。
4. featureVersion/rulesetVersion、tests、current docs、ADR、両living planを同期する。
5. Phase A後、RUNTIME_QUALIFICATION.mdのPhase Bを実行する。

TDDは必要最小限です。変更契約を直接守るfocused regression testだけを先に追加し、意図したredを確認後に最小実装し、最後に `bash scripts/verify-local.sh` を1回実行してください。既存testが同じ契約を十分証明するなら重複testを作らないでください。

push、PR、merge、deployは行わないでください。外部write、不可逆操作、secret変更が必要になった場合は停止し、該当AC/Checkpoint、証拠、最小再開条件を両planへ記録してください。

完了宣言の条件:
- AC-P1-* と AC-RQ-* がすべてpassed
- focused testsとfull gateがexit 0
- scope外変更なし
- 未解決P0/P1なし
- IMPLEMENTATION_PLAN.md と .ai.json が最終HEAD・結果・証拠で同期
- final_result、goal_gap、remaining_workが実態と一致
```

## 最初のコマンド

```bash
cd /home/tn/projects/prep-watchdeck
git status --short
git branch --show-current
git rev-parse HEAD
find .. -name AGENTS.md -print
sed -n '1,260p' AGENTS.md
sed -n '1,260p' docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.md
```
