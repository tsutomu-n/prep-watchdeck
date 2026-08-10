# Quiet Market Instrument 受入条件

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## Mandatory Acceptance Criteria

### AC-QMI-001

- 必須: `はい`
- 条件: 現行専用branch、baseline HEAD、clean working tree、適用AGENTS/DESIGNを証拠付きで固定する。
- 検証: git status、branch、HEAD、適用文書一覧
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-002

- 必須: `はい`
- 条件: IMPLEMENTATION_PLAN.mdとAI JSONがRepo schemaへ適合し同期する。
- 検証: plan validatorまたはstrict JSON parseと差分監査
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-003

- 必須: `はい`
- 条件: production dependency、Private API、trade/order機能を追加しない。
- 検証: manifest/lock/diff/scope監査
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-004

- 必須: `はい`
- 条件: 既存15m出来高倍率のfixture/golden値が変更されない。
- 検証: 既存testと追加golden test
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-005

- 必須: `はい`
- 条件: 1h・4h出来高倍率が同長rolling中央値比で計算され、不足・不正時Noneになる。
- 検証: focused unit tests
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-006

- 必須: `はい`
- 条件: 1h・4h倍率はAttention Score、category、Candidate rankingへ影響しない。
- 検証: ranking regression tests
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-007

- 必須: `はい`
- 条件: activity phaseが定義済み優先順で一義的に算出される。
- 検証: parameterized truth table
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-008

- 必須: `はい`
- 条件: featureVersion=4、rulesetVersion=3、schema/fixture/generated typesが同期する。
- 検証: schema/type/fixture tests
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-009

- 必須: `はい`
- 条件: 正常なdata qualityは常時表示されず、非正常は具体的日本語で表示される。
- 検証: unit/E2E/visual evidence
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-010

- 必須: `はい`
- 条件: STALE/MISSINGがCandidateへ入らず、既存gateがある場合は重複実装しない。
- 検証: pipeline/ranking regression testとdiff review
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-011

- 必須: `はい`
- 条件: Desktop Candidateが一つのsurfaceとして4観点を同時表示する。
- 検証: 1440px screenshot/E2E
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-012

- 必須: `はい`
- 条件: Mobile Candidateがaccessible tabsで4観点を切替え、selection/timeframeを保持する。
- 検証: 390/320px E2E、keyboard test
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-013

- 必須: `はい`
- 条件: Watchlist rowにcategory、15m倍率×、activity phaseが表示され、横scrollしない。
- 検証: responsive E2E/visual evidence
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-014

- 必須: `はい`
- 条件: Inspectorに15m/1h/4h、phase、OI 60m、74h、警戒理由が連続sectionで表示される。
- 検証: component/E2E/visual evidence
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-015

- 必須: `はい`
- 条件: VPI laneが既存対象数を明示し、指定stateだけを正しく分類・sort・limitする。
- 検証: unit/E2E tests
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-016

- 必須: `はい`
- 条件: VPIは主ranking/filter/category/Attention Scoreへ影響せず、補正順位計算も変更しない。
- 検証: regression testsとdiff review
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-017

- 必須: `はい`
- 条件: check、build、E2E、performance、scripts/verify-local.shが成功する。
- 検証: command、cwd、exit code、log
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。

### AC-QMI-018

- 必須: `はい`
- 条件: DESIGN/current docs/ADR/living plansが実装結果へ同期し、未解決P0/P1と残作業がない。
- 検証: document gates、final diff、plan final_result
- AC状態: `passed`
- 証拠: `IMPLEMENTATION_PLAN.md`と`IMPLEMENTATION_PLAN.ai.json`の対応ACを参照。
