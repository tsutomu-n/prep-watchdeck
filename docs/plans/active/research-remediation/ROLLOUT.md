# Research production rollout and initial data acceptance

timestamp="2026-10-09(金)_16:01 JST"
- 作成: `2026-10-09T15:42:23+09:00`
- 更新: `2026-10-09T16:01:26+09:00`
- 状態: `実装計画`

## Goal and authorization

2026-10-09のuser指示「プッシュして本番反映して実際のデータを受け入れ始めて」に従い、
commit 35de6f2をcurrent branchへpushし、Marketとmonitorを反映、独立したBitget研究観測を開始する。
PR/main merge/CI、課金、credential変更、自動注文、過去データ削除は含まない。
24時間/30日完了や戦略優位性を開始受入と混同しない。

## Task 1: Release preparation

- [x] current branch、remote、稼働unit/config/schema、容量とrollbackを確認する。
- [x] Repositoryのrelease gateを隔離DB/stateで実行し、tracked commitから新しいreleaseを用意する。
- [x] current branchだけをpushし、remote SHAを確認する（workflowはmain push/PRだけ）。
Expected: local gate PASS、remoteは対象branchとexact source、secret/原本を混入しない。

## Task 2: Market and monitor cutover

- [x] dedicated DBの検証済みbackupと旧unit/drop-inを保全する。
- [x] Market writer/maintenanceを制御してMigration 0005を適用する。旧行はNULLのまま保持する。
- [x] Marketを新releaseへ切り替え、複数周期のartifact/Provider/finality/fundingを確認する。
- [x] monitorを新sourceと実稼働Ranking map/portへ合わせ、残るnative identity差分を診断する。
Expected: schema5、new Market source、継続更新、Ranking/Web/Attentionの既存機能を保全。

## Task 3: Initial reader acceptance

- [x] 実在するBitget一契約/versionを確定し、隔離研究rootへ短い観測を実行する。
- [x] 将来の固定ruleを登録し、bounded 24h観測を管理processとして開始する。
- [x] 初回receipt/payload/hash、実データ種類、品質理由、process、容量/再開条件を記録する。
Expected: 実データ受信・保存が継続し、missingは理由として残る。失敗時に偽のqualifiedを出さない。

## Rollback and acceptance

Rollbackは新reader停止と追加Market/monitor drop-inの退避、daemon-reload、旧Market再起動。
Migrationのnullable列と全DB/研究データ、旧releaseは保全し、自動downgrade/restore/deleteは行わない。
backupは対象DBとlist/hashを検証し、接続設定内容を証拠へ記録しない。

Raw rollout evidence: `/home/tn/.local/share/prep-watchdeck-research-rollouts/20261009-154223`。source・push・稼働反映・初回データ・長期受入を別欄で記録する。

## Observed outcome

Source push and deployment completed. Schema5 and all three Venue finalization writes observed.
Aster interval provenance: 49 at 1h, 333 at 4h, 70 at 8h. Ranking map 1,096 identities match.
Pilot replay_valid=true / qualified_for_ab=false (candle and state gaps); bounded daily capture active.
The remaining 24-hour/30-day acceptance is tracked in GOAL/PLAN and acceptance.json.
