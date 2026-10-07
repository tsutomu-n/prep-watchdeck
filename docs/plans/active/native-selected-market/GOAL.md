# 未group契約の単独板・約定購読

- 作成: `2026-10-07T17:06:00+09:00`
- 更新: `2026-10-07T17:22:00+09:00`
- 状態: `実装計画`

## Goal / acceptance

利用者が取引所別一覧で、単独契約として確認できる未group契約を明示選択し、その1契約の板・約定を確認できる。横断identityの未確認を単独観測の禁止理由にせず、数量不明・倍率不明・不適格契約は拒否する。異なる契約・versionのデータを混在させない。

## Scope / current state

- 起点: `0b510feb87d7448f6b9bb0fc30cbab4bc748f2b2`、開始時clean。専用`ai/native-selected-market-*` branch。
- 現行selection command、controller、Postgres lease・raw保存、artifact、Webを拡張する。group所属がある選択の挙動は保つ。
- 未group targetは`groupId=null`と明示的なinstrument versionで識別する。架空のgroupを作らない。
- 数量は既存のBase単位・倍率1の検証を維持する。元単位表示・未知倍率の換算・新Venue・Full L2・全市場常時収集は対象外。
- source migrationは追加するが、現役DBへの適用・unit操作・deploy・push・PRは行わない。

## Facts / decisions / unknowns

- UI、API、runtime、store、artifactがgroup前提。leaseとrawのgroup FKはNOT NULL。
- Chartは未groupを既に許可。manualに旧説明が残る。
- group化の除外理由にはalias、同Venue衝突、数量/倍率不明が混在する。
- 採用: nullable groupとversionに結び付いた単独selectionを既存bounded laneへ追加。別runtimeや架空groupより変更と運用負担が小さい。
- 前の会話で提示した限定的な実装方針への「実装して」を、この範囲の実装・検証の承認とする。
- 実データの未group件数、稼働反映、実データ受入は未確認であり隔離検証で代用しない。

## Checkpoints

### CP-001: 契約と拒否経路のテスト

- Status: Complete
- Objective: 未group選択と不適格拒否を失敗するテストで固定する。
- Dependencies: read-only調査、branch作成。
- Components: selection/controller/runtime/store、Web repository、関連E2E。
- Actions: version必須・wrong version・他契約混入・未知数量・TTL/heartbeat・group切替を検証。
- Completion: 新しい成功経路が現行実装で失敗し、既存拒否の期待値が明確。
- Validation: focused pytest/Vitest、専用一時Postgres。
- Failure / recovery: fixture不備は修正し、現役stateを使わない。

### CP-002: 一貫した単独selection

- Status: Complete
- Objective: command→購読→保存→artifact→UIを接続する。
- Dependencies: CP-001。
- Components: nullable-group migration、各Python/TS/Svelte、生成schema/型。
- Actions: 安全な単独target解決とversion照合、lease cleanup、監視状態表示。
- Completion: 1契約の板・約定が表示され、unsafe/version違いは拒否される。
- Validation: focused tests、schema再生成、Ruff/Pyrefly、Web check/build/E2E。
- Failure / recovery: 本番反映を行わずbranchの差分を修正する。

### CP-003: 回帰・文書・完了

- Status: In progress
- Objective: 必須gateと最終diffを照合し、今回の差分だけcommit。
- Dependencies: CP-002。
- Components: docs/current、docs/decisions、schema、全変更。
- Actions: repo横断gate、独立レビューが必要なら実施、文書の現行仕様反映、plan削除。
- Completion: 必須検証がpass、重要な未解決なし、scoped commit、worktree状態を報告。
- Validation: scripts/verify-local.sh、metadata/link、diff --check。
- Failure / recovery: gate失敗は原因修正。環境障害は証拠と再開条件を残す。live migration/deployは別承認。

## Progress / evidence

- [x] read-only baseline、製品境界、既存flow・検証設定・DESIGN確認。
- [x] CP-001
- [x] CP-002
- [ ] CP-003

- RED: native focused pytest 9件失敗、Web repository 2件失敗。Nativeの明示選択E2EはDesktop/Mobileとも旧UIで失敗。
- GREEN: focused Market 22件、Web repository 7件、Svelte check、build、追加Desktop/Mobile E2E 4件成功。
- 検証DB: 一時Postgres `prep-watchdeck-native-selected-20261007-1704`、loopback ephemeral port。現役DBへ接続していない。
- 不適格判定のためUniverseにoptional `quantityUnit` / `contractMultiplier`を追加。古いartifactの未group契約はmetadata欠落を未確認として拒否する。
- 独立read-onlyレビューとrepo横断gateを実行中。

## Rollback / stop conditions

本番へ反映しないことが現段階のrollback。追加migrationは既存行を変更せずgroup FKを維持してnullを許可する。本番DB適用、権限緩和、未知単位の推測が必要になれば停止して再判断する。一時DB/container/stateのみ検証終了時に終了する。
