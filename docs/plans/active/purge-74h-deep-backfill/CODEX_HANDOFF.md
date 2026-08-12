# メインスレッドへの実装引継ぎ

- 作成: `2026-08-12T17:03:31+09:00`
- 更新: `2026-08-12T22:54:50+09:00`
- 状態: `実装計画`

---

## 引継ぎ結論

CP-01〜06は完了した。実unitを同期してscanner/Webを各1回restartし、single writer、Bitget/Perp、
Desktop/Mobileを確認した。restart直後の3 snapshotでOI 60分referenceを確認後、Bitget ticker更新失敗により
2周期だけ全OIが`UNKNOWN`となったが、更新回復後の2周期でreference 744/742へ自動復旧した。その後も
exact 60分前bucket欠損で1周期だけreference 0となり、次周期に742へ戻った。snapshot、短期candle、
直近reconcile、detail chart、OI 60分の契約は維持しているが、OIの連続可用性は保証されない。CPU高負荷と
OI diagnosticsの監視盲点は解決していないため、独立P1へ引き継いだ。

正本:

- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
- [`EXECUTION_RUNBOOK.md`](EXECUTION_RUNBOOK.md)
- [`PLAN_REVIEW.md`](PLAN_REVIEW.md)
- Repo localの`.codex/SP_STATE.md`（CP-06完了状態）

## 現在のRepo状態

```text
Repo: /home/tn/projects/prep-watchdeck
Windows view: U:\projects\prep-watchdeck
Branch: ai/purge-74h-deep-backfill-20260812-2004
Implementation checkpoint: 2e23c52
Runtime evidence: implementation checkpoint後のdocs-only commit
HEAD / Worktree: 再開時に`git log -1`と`git status --short`で確認する
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

`.codex/SP_STATE.md`はCP-06の完了証拠を記録する。旧multisource planの任意72時間qualificationは
`docs/plans/active/multisource-display-pilot/IMPLEMENTATION_PLAN.md`のdeferred ACとして引き続き記録されている。

## メインスレッドへ渡す指示

CP-01〜06、full gate、unit同期、restartを再実行しない。次工程は
[`scanner-cpu-snapshot-latency-p1`](../scanner-cpu-snapshot-latency-p1/README.md)だけである。

```text
対象Repo: /home/tn/projects/prep-watchdeck
branch: ai/purge-74h-deep-backfill-20260812-2004
完了済み正本: docs/plans/active/purge-74h-deep-backfill/IMPLEMENTATION_PLAN.md
次工程: docs/plans/active/scanner-cpu-snapshot-latency-p1/README.md

最初に既存log/service stateだけでreconcile実行中と停止後のCPU duty cycleを各3分比較する。
同じ時系列へticker refresh成否、OI sampled/references、snapshot公開時刻を記録する。
原因区間が絞れない場合だけ低overheadなduration logを追加する。現役DBへ別writerを接続しない。
```

OIの一時異常はpurge回帰とは判定していないが、全件`UNKNOWN`でも`oiDiagnostics.status="ok"`になる。再び
`sampled=0`が複数周期続き、ticker更新後も回復しない場合は、P1計測より先にデータ鮮度障害として停止する。

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

## 次工程開始時のread-only確認

```bash
cd /home/tn/projects/prep-watchdeck
git status --short
git branch --show-current
git rev-parse HEAD
systemctl --user show prep-watchdeck-service.service \
  -p MainPID -p ActiveState -p SubState -p NRestarts
jq '{runId,generatedAt,oiDiagnostics:.summary.oiDiagnostics}' \
  /home/tn/.local/share/prep-watchdeck/snapshots/latest.json
```

`verify-local.sh`とCP-06 restartは完了済みである。本計画の再確認だけを理由に繰り返さない。

## 完了条件

- `IMPLEMENTATION_PLAN.md`のAC-01〜AC-11に再現可能なevidenceがある。
- CP-00〜06が完了し、final diffがTargetと一致する。
- 74時間production参照と常駐deep backfill接続が残っていない。
- Candidateを別意味で再利用していない。
- snapshot/Perp比較/OI/reconcile/chart/DB契約とchart source深度の維持をtestとruntimeで確認している。
- scanner CPU問題が残る場合、数値付きの独立P1として引き継いでいる。
