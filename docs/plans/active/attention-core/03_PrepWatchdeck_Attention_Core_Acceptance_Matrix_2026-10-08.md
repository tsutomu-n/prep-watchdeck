# Prep Watchdeck Attention Core 受入マトリクス v1.0

timestamp="2026-10-08(木)_23:47 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-08T23:47:49+09:00`
- 状態: `実装計画`


> 作成日: `2026-10-08`  
> 対象: `01_PrepWatchdeck_Attention_Core_Design_2026-10-08.md`  
> 実装計画: `02_PrepWatchdeck_Attention_Core_Implementation_Plan_2026-10-08.md`

---

## 判定

```text
NOT_RUN
PASS
PARTIAL
BLOCKED
FAIL
NOT_APPLICABLE
```

`test green`だけでproduction受入をPASSにしない。

---

## A. Repository / Architecture

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-001 | `apps/attention-core`がuv workspace packageとして独立 | lock check、package tests | NOT_RUN |
| ATT-002 | Attention stateがMarket/Ranking stateと非重複 | hostile path tests | NOT_RUN |
| ATT-003 | Market/Ranking writerへ接続しない | mocks、connection audit | NOT_RUN |
| ATT-004 | Providerへ直接接続しない | request spy、source review | NOT_RUN |
| ATT-005 | manual `selection.json`を書かない | filesystem snapshot/hash | NOT_RUN |
| ATT-006 | actual captureを実装しない | diff review | NOT_RUN |

---

## B. Input consistency

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-010 | service-state前後一致でMarket bundle固定 | unit test | NOT_RUN |
| ATT-011 | bundle変更時1回再試行 | unit test | NOT_RUN |
| ATT-012 | 2回変化でgeneration拒否 | unit test | NOT_RUN |
| ATT-013 | metrics missingをpartialとして保持 | unit test | NOT_RUN |
| ATT-014 | Ranking canonical queryは1回だけ | loopback spy | NOT_RUN |
| ATT-015 | stale/future Rankingを拒否 | unit test | NOT_RUN |
| ATT-016 | read APIでProvider取得なし | integration spy | NOT_RUN |

---

## C. Identity / Time / Provenance

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-020 | exact ID+version join | unit test | NOT_RUN |
| ATT-021 | symbol-only joinなし | hostile test | NOT_RUN |
| ATT-022 | wrong version補完なし | hostile test | NOT_RUN |
| ATT-023 | mapping reviewへ値を補完しない | unit test | NOT_RUN |
| ATT-024 | 各input時刻を個別保持 | contract test | NOT_RUN |
| ATT-025 | `decisionAt`後の値を拒否 | future-time tests | NOT_RUN |
| ATT-026 | input skewを保存 | contract/readback | NOT_RUN |

---

## D. Feature arithmetic

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-030 | mark dispersion手計算一致 | parameterized test | NOT_RUN |
| ATT-031 | spread bps手計算一致 | parameterized test | NOT_RUN |
| ATT-032 | funding max/range一致 | parameterized test | NOT_RUN |
| ATT-033 | OI median一致 | parameterized test | NOT_RUN |
| ATT-034 | zeroとmissingを区別 | unit test | NOT_RUN |
| ATT-035 | stale native値を除外 | unit test | NOT_RUN |
| ATT-036 | `tradeChange`を売買代金と誤用しない | source/test review | NOT_RUN |
| ATT-037 | volume unit不明を合成しない | unit test | NOT_RUN |

---

## E. Components / Ranking

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-040 | midrank percentileが順序不変 | property test | NOT_RUN |
| ATT-041 | tiesが同score | unit test | NOT_RUN |
| ATT-042 | minimum peers未達はunavailable | unit test | NOT_RUN |
| ATT-043 | movement direction保持 | unit test | NOT_RUN |
| ATT-044 | activity欠測を0補完しない | unit test | NOT_RUN |
| ATT-045 | confluenceは4 component必須 | unit test | NOT_RUN |
| ATT-046 | scoreとquality/coverage分離 | contract/UI test | NOT_RUN |
| ATT-047 | policy version変更時rank change無効 | unit test | NOT_RUN |

---

## F. Storage

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-050 | SQLite WAL / foreign keys | unit test | NOT_RUN |
| ATT-051 | generation idempotency | unit test | NOT_RUN |
| ATT-052 | same ID/different content conflict | unit test | NOT_RUN |
| ATT-053 | transaction failureで部分保存なし | fault injection | NOT_RUN |
| ATT-054 | readback hash一致後publish | integration test | NOT_RUN |
| ATT-055 | currentと5分evidenceを分離 | unit test | NOT_RUN |
| ATT-056 | state symlink/escape拒否 | hostile test | NOT_RUN |

---

## G. Outcomes

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-060 | input cutoff barをoutcomeへ含めない | unit test | NOT_RUN |
| ATT-061 | horizon全bar不足はpending/unscorable | unit test | NOT_RUN |
| ATT-062 | interior gapを0-returnにしない | unit test | NOT_RUN |
| ATT-063 | revision changeで履歴連結なし | unit test | NOT_RUN |
| ATT-064 | max absolute/close return一致 | hand-calculated test | NOT_RUN |
| ATT-065 | correctionはnew edition | version test | NOT_RUN |

---

## H. Candidate-family validation

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-070 | candidate family固定 | mutation rejection test | NOT_RUN |
| ATT-071 | Recall/Precision/NDCG手計算一致 | fixture | NOT_RUN |
| ATT-072 | minute rowsをiid扱いしない | block test | NOT_RUN |
| ATT-073 | exact duplicateで証拠強化なし | hostile test | NOT_RUN |
| ATT-074 | chance winnerをsupportしない | simulation fixture | NOT_RUN |
| ATT-075 | stable edgeを検出 | simulation fixture | NOT_RUN |
| ATT-076 | day/6h sensitivity矛盾はinconclusive | fixture | NOT_RUN |
| ATT-077 | block不足はnot_estimable | fixture | NOT_RUN |
| ATT-078 | coverage regressionを棄却 | fixture | NOT_RUN |
| ATT-079 | MDE/powerはplanning only | contract test | NOT_RUN |

---

## I. Shadow allocation

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-080 | top-K deterministic | unit test | NOT_RUN |
| ATT-081 | hysteresis buffer/hold | timeline test | NOT_RUN |
| ATT-082 | cost-aware switch抑制 | unit test | NOT_RUN |
| ATT-083 | stale assetを選ばない | unit test | NOT_RUN |
| ATT-084 | manual selectionを変更しない | filesystem/API test | NOT_RUN |
| ATT-085 | added/removed/retained/churn保存 | contract test | NOT_RUN |
| ATT-086 | map/policy変更で比較不可 | unit test | NOT_RUN |

---

## J. API / Web

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-090 | loopback APIのみ | server test | NOT_RUN |
| ATT-091 | unknown query拒否 | server test | NOT_RUN |
| ATT-092 | schema validation | API/Web unit | NOT_RUN |
| ATT-093 | no-store | API test | NOT_RUN |
| ATT-094 | unavailable reason表示 | component test | NOT_RUN |
| ATT-095 | scoreを利益確率と表示しない | copy review/E2E | NOT_RUN |
| ATT-096 | favoritesがmarket rankを変更しない | unit/E2E | NOT_RUN |
| ATT-097 | keyboard/focus | Playwright | NOT_RUN |
| ATT-098 | 390px横overflowなし | Playwright | NOT_RUN |
| ATT-099 | stale warning | Playwright | NOT_RUN |

---

## K. Regression / Operations

| ID | 条件 | 必須証拠 | 初期状態 |
|---|---|---|---|
| ATT-100 | Market Core全pytest | command/log | NOT_RUN |
| ATT-101 | Ranking Core全pytest | command/log | NOT_RUN |
| ATT-102 | Attention Core全gate | command/log | NOT_RUN |
| ATT-103 | Web unit/check/build | command/log | NOT_RUN |
| ATT-104 | Desktop/Mobile E2E | command/log | NOT_RUN |
| ATT-105 | full `verify-local.sh` | command/log/hash | NOT_RUN |
| ATT-106 | docs metadata/link | command/log | NOT_RUN |
| ATT-107 | no production state write | state hash/audit | NOT_RUN |
| ATT-108 | no systemd/deploy operation | operation log | NOT_RUN |
| ATT-109 | rollback: Attention停止で既存画面継続 | isolated runtime evidence | NOT_RUN |

---

## L. Production / Actual Capture

以下はF0–F7のsource完成ではPASSにしない。

| ID | 条件 | 初期状態 |
|---|---|---|
| ATT-120 | production unit install | BLOCKED |
| ATT-121 | production capacity | BLOCKED |
| ATT-122 | 30日prospective evidence | BLOCKED |
| ATT-123 | family-adjusted candidate superiority | BLOCKED |
| ATT-124 | actual multi-capture design | BLOCKED |
| ATT-125 | actual multi-capture live acceptance | BLOCKED |
| ATT-126 | user daily-use acceptance | BLOCKED |

---

## 完了判定

### Source implementation PASS

ATT-001〜ATT-109のうち対象項目がすべてPASS。

### Product validation PARTIAL

Source implementation PASSかつATT-122/123が未完了。

### Production attention PASS

別承認されたproduction deployment、capacity、rollback、日常利用まで証拠化した場合だけ。

### Actual capture PASS

別Decisionのsecurity/capacity/lease/rollback契約と実受入が完了した場合だけ。
