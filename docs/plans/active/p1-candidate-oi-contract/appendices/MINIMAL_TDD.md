# 07 必要最小限TDD・検証方針

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 方針

このwaveでは、P1の意味を固定する最小testだけを先に追加する。

```text
テストを先に追加
→ 意図した理由でredを確認
→ 最小実装
→ focused green
→ full gateを最後に1回
```

新しいtest framework、property-based framework、benchmark基盤、mock serverは追加しない。

## Test set

### T-01 74h truth table

既存long-horizon testへparameterized testを1本追加。

| price | turnover | expected |
|---|---|---|
| pass | pass | True |
| pass | fail | False |
| fail | pass | False |
| fail | fail | False |
| available | unknown | None |
| insufficient | insufficient | None |

### T-02 reason codes

- price only → price codeのみ
- turnover only → turnover codeのみ
- both →両code

### T-03 Candidate gate

fixture row:

- matched=True
- matched=False
- matched=None
- matched=True + NO_TRADE

確認:

- timeframe rankingsへ入るのはmatched=Trueかつ既存eligibleのみ
- snapshot rowsは4件残る
- noTrade diagnosticは維持

### T-04 OI resolver

parameterized pure test:

- current=103, previous=100 → INCREASING（threshold 3%を境界含む）
- current=97, previous=100 → DECREASING
- current=100, previous=100 → STABLE
- referenceなし → UNKNOWN
- current/reference <=0、NaN → UNKNOWN

### T-05 DuckDB store

- table initialize idempotent
- same symbol/bucket upsert replaces, duplicatesしない
- multiple symbols一括load
- exact target bucketのみ返す
- retention cutoffより古いrowをprune
- existing tables/recordsを変更しない

### T-06 service snapshot integration

- current sampleと60分前sampleをstoreへ用意
- snapshot rowの`openInterestState`が期待値
- referenceなしはUNKNOWN
- stale current tickerはsampleされずUNKNOWN
- store queryがper-symbol N回にならないことをspy/call-countで確認できるなら1assert追加

### T-07 priority score

- UNKNOWN OIと未知文字列のOI contributionが0
- INCREASING / STABLE / DECREASINGの現行weightは維持

### T-08 focused E2E

既存Dashboard E2Eへ小さいassertを追加。

- Candidate条件のhelp textがsnapshot summaryの閾値を表示し、summary不正時は一般説明へfallback
- Candidateにmatched fixtureだけ出る
- Watchlistにはunmatched fixtureも残る
- Symbol Monitoring RailにOI 60分状態

## Red evidence

実装前に、少なくともT-01、T-03、T-06、T-08が現行挙動で失敗することを記録する。

記録形式:

```text
command:
working_directory:
exit_code:
failing_test:
expected_failure_reason:
HEAD:
```

## Focused commands

現行test名・fileを`rg`で解決してから実行する。

```bash
cd apps/scanner-core
uv run pytest -q \
  tests/<long-horizon-test>.py \
  tests/<ranking-test>.py \
  tests/<open-interest-test>.py \
  tests/<service-store-test>.py \
  tests/<service-snapshot-test>.py

cd ../web
bunx playwright test tests/e2e/<dashboard-test>.ts \
  --grep "74h candidate|OI 60m"
```

placeholder pathのまま実行しない。

## Final gate

Repo root:

```bash
bash scripts/verify-local.sh
```

この変更では、Hot polling、row rendering、chart lifecycleを変更しないため、performance/1h soakは必須にしない。

次の場合だけ追加実行する。

- Watchlist row DOMを変更した
- ticker pollまたはsnapshot refreshを変更した
- full gateで性能・timer・heapに疑義が出た

```bash
cd apps/web
bun run test:performance
SOAK_DURATION_MS=3600000 bun run test:soak
```

## 禁止

- 既存thresholdをtestに合わせて緩和
- broad snapshot更新でgoldenを無批判に上書き
- red確認を省き、後付けtestだけ追加
- 同じ意味をunitとE2Eで過剰重複
- unrelated test cleanup
