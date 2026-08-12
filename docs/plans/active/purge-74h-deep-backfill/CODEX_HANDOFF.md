# メインスレッドへの実装引継ぎ

- 作成: `2026-08-12T17:03:31+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

## 引継ぎ結論

CP-01〜04の実装とCP-05の文書同期・focused gateは完了した。次は全体gateを1回実行し、CP-06で
実unitを同期してruntimeを確認する。snapshot、短期candle、直近reconcile、detail chart、
OI 60分は維持する。実unitには旧deep backfill引数が残るため、source完成だけで稼働反映済みと扱わない。

正本:

- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
- [`EXECUTION_RUNBOOK.md`](EXECUTION_RUNBOOK.md)
- [`PLAN_REVIEW.md`](PLAN_REVIEW.md)
- Repo localの`.codex/SP_STATE.md`（CP-05を対象）

## 現在のRepo状態

```text
Repo: /home/tn/projects/prep-watchdeck
Windows view: U:\projects\prep-watchdeck
Branch: ai/purge-74h-deep-backfill-20260812-2004
HEAD: ad3364f6e3b0c30c85469a22da3789f19d3727b9
Worktree: CP-01〜04 source/testsとCP-05 docsが未コミット。service restartは未実施
```

Windows `U:` viewで文書作成前から表示されたmode-only変更:

```text
M scripts/ops/install-user-services.sh
M scripts/start-all.sh
M scripts/start-local.sh
M scripts/update-live.sh
M scripts/verify-local.sh
?? docs/plans/prep-watchdeck-discovery-breadth-plan-2026-08-11.zip
?? docs/plans/prep-watchdeck-frontend-improvement-20260811.zip
?? docs/plans/prep-watchdeck-marketstate-v1-plan.zip
```

5 scriptはいずれも`100755 → 100644`だけで、内容差分は0行だった。`core.fileMode=false`では表示されない。
canonical Linuxで再確認し、mode changeをstage/commitしない。内容差分がある場合だけ停止する。

無関係なzip、mode-only noise、今回のAllowedFiles外の変更をstage、削除、上書きしない。

`.codex/SP_STATE.md`はCP-05の文書同期とgateだけを対象にする。旧multisource planの任意72時間qualificationは
`docs/plans/active/multisource-display-pilot/IMPLEMENTATION_PLAN.md`のdeferred ACとして引き続き記録されている。

## メインスレッドへ渡す指示

以下を現行の再開指示とする。

```text
対象Repo: /home/tn/projects/prep-watchdeck
branch: ai/purge-74h-deep-backfill-20260812-2004
正本計画: docs/plans/active/purge-74h-deep-backfill/IMPLEMENTATION_PLAN.md
実行手順: docs/plans/active/purge-74h-deep-backfill/EXECUTION_RUNBOOK.md
実行状態: .codex/SP_STATE.md

CP-01〜04を再実装しない。CP-05の文書focused gate後、verify-localを計画全体で1回だけ実行する。
CP-06ではrunbook 8.1の順に実unitをcatし、installer --checkの非0が旧deep引数除去だけによることを
dry-runで確認する。別driftがあれば--applyせず停止する。限定差分だけなら--apply、再--checkを行い、
scannerとWebを各1回だけrestartする。single writer、snapshot 3回、Bitget/Perp/OI/reconcile、
1440px/390px、CPU/RSSを確認する。CPU改善は実測前に断定しない。
```

### 作成時の旧指示（実行禁止）

以下はCP-00開始前の履歴であり、再実行しない。

```text
対象Repo: /home/tn/projects/prep-watchdeck
正本計画: docs/plans/active/purge-74h-deep-backfill/IMPLEMENTATION_PLAN.md
実行手順: docs/plans/active/purge-74h-deep-backfill/EXECUTION_RUNBOOK.md
最初の実行状態: .codex/SP_STATE.md

現行Repoを事実の正本として、74時間判定と常駐deep backfillを計画どおりパージしてください。
まずCP-00でbranch、HEAD、dirty diff、既存planと対象source/testsを再確認し、reset、stash、checkoutで
既存変更を消さないでください。current Perp比較を含むHEADから専用branch
ai/purge-74h-deep-backfill-YYYYMMDD-HHMMを作り、CP-01から順に進めてください。

実装範囲:
1. service CLI/task/state/systemd/Webからdeep backfillを切断する。
2. service_deep_backfill.pyとpure testは未接続の将来用componentとして残す。
3. Candidate用ranking API、Symbol順位、Candidate固有UIを先に削除し、
   全非NO_TRADE銘柄をCandidateへ広げない。
4. consumer切断後に、74h timeframe、long-horizon計算、UserRule、row/summary/reason/schema/config/fixture、
   Candidate gate/ranking dataを削除する。
5. Watchlist、Raw Sort、Smart Rank、rankings.noTrade、OI 60分、短期指標を維持する。
6. scanner判定とgap auditを短期指標から導出した383本5m/1,915本1mへ縮小する。
7. detail chartのsourceは現行1,177本5m/5,885本1mを暫定維持し、scanner/gap windowと分離する。
   383本へ一律縮小して1h/4h/24h chart履歴を減らさない。
8. Cold snapshot、Perp sidecars、reconcile、detail chart、DB schema、schemaVersion 1を維持する。
9. `DESIGN.md`、current docs、新ADR 0010、ADR 0007/0008を実装後の事実へ同期する。
   過去の実装履歴は捏造せずsupersedeを記録し、OI 60分契約を維持する。

TDDは契約を直接固定する最小caseだけにしてください。各checkpointのfocused testがgreenになるまで
次へ進まず、最後にbash scripts/verify-local.shを1回実行してください。未実行、skipped、既存failureを
成功扱いしないでください。

重要な停止条件:
- canonical Linuxでscript内容差分が見つかり、今回差分と衝突する。
- Candidateを別条件へ暗黙に変更する必要がある。
- DB migration、履歴削除、別writer、private APIが必要になる。
- snapshot、Bitget scan、Perp比較、OI 60分、reconcile、chartの維持ができない。
- scanner/gap windowとchart source windowを分離できず、chart履歴を暗黙に減らす必要がある。
- fresh stateのwarm-upを解消するため常駐deep backfillを戻す必要がある。

push、PR、merge、service restartは、メインスレッドの現行ユーザー指示で承認されている範囲だけ
実行してください。source変更前とruntime qualificationで、取得可能なCPU、RSS、3回連続snapshotの
間隔、row/chart件数を同じ条件で記録してください。取得不能値は推測せず未確認としてください。
runtimeではsingle writer、Perp比較、Webの1440px/390pxも確認し、CPU改善は計測前に断定しないでください。
```

## 再開時のコマンド

```bash
cd /home/tn/projects/prep-watchdeck
git status --short
git branch --show-current
git rev-parse HEAD
bun test scripts/maintenance/document-metadata.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun test scripts/maintenance/document-links.test.mjs
bun scripts/maintenance/check-document-links.mjs
npx -p @google/design.md designmd lint DESIGN.md
git diff --check

# 上がすべて成功してから、計画全体で1回だけ実行する。
bash scripts/verify-local.sh
```

## 完了条件

- `IMPLEMENTATION_PLAN.md`のAC-01〜AC-11に再現可能なevidenceがある。
- CP-00〜06が完了し、final diffがTargetと一致する。
- 74時間production参照と常駐deep backfill接続が残っていない。
- Candidateを別意味で再利用していない。
- snapshot/Perp比較/OI/reconcile/chart/DB契約とchart source深度の維持をtestとruntimeで確認している。
- scanner CPU問題が残る場合、数値付きの独立P1として引き継いでいる。
