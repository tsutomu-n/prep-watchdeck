# 付録A 変更対象ファイル台帳

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 必須変更候補

| 領域 | 現行path | 変更 |
|---|---|---|
| 74h計算 | `apps/scanner-core/src/prep_watchdeck/domain/features/long_horizon.py` | 三値component、AND composite |
| DTO変換/version/reason | `apps/scanner-core/src/prep_watchdeck/adapters/bitget_live/provider.py` | reason codes、feature/ruleset version |
| Candidate ranking | `apps/scanner-core/src/prep_watchdeck/domain/screening/rankings.py` | timeframe sourceだけ74h gate |
| OI classifier | `apps/scanner-core/src/prep_watchdeck/features/open_interest.py` | 既存分類を維持、必要ならpure resolver補助 |
| Attention Score | `apps/scanner-core/src/prep_watchdeck/screening/priority.py` | UNKNOWN fallback 0 |
| service snapshot | `apps/scanner-core/src/prep_watchdeck/application/service_snapshot.py` | sample/write/load/pass previous map |
| service models | `apps/scanner-core/src/prep_watchdeck/domain/service_models.py` | OI sample record |
| DuckDB store | `rg`で`ticker_latest`所有fileを解決 | table/API/prune |
| Candidate UI | `apps/web/src/lib/components/dashboard/DashboardRankingArea.svelte` | active gate説明 |
| Dashboard wiring | `apps/web/src/routes/+page.svelte`または既存parser | summary.candidateRule74hを局所validationして渡す |
| Symbol UI | `apps/web/src/lib/components/symbol/SymbolMonitoringRail.svelte` | OI 60分状態 |
| label | `apps/web/src/lib/market/labels.ts` | OI state label |
| help | `apps/web/src/lib/market/attention-score.ts` | OI 60分/UNKNOWN説明 |

## 変更しないことを確認するファイル

| Path/領域 | 理由 |
|---|---|
| VPI compute/config | P1と無関係 |
| `smart-rank.ts` | 計算変更なし |
| `DashboardMarketRow.svelte` | Watchlist列追加なし |
| ticker overlay / polling | Hot lane変更なし |
| chart API/components | chart変更なし |
| Past Note repository/API | monitoring annotation変更なし |
| Private/order関連 | 非目標 |

## Test pathの解決

```bash
rg -n "test_74h|compute_74h_features" apps/scanner-core/tests
rg -n "build_rankings|totalEligible" apps/scanner-core/tests
rg -n "classify_open_interest|open_interest_state" apps/scanner-core/tests
rg -n "ticker_latest|CREATE TABLE|initialize" apps/scanner-core/tests
rg -n "build_service_snapshot|snapshot_from_service_store" apps/scanner-core/tests
rg -n "fixture backed dashboard|Smart Rank|Monitoring Rail" apps/web/tests
```

既存test fileがある場合はそこへ最小追加し、同義の新fileを作らない。

## Doc path

- `README.md`
- `docs/current/overview.md`
- `docs/current/architecture.md`
- `docs/current/data-contracts.md`
- `docs/current/ui-workflow.md`
- `docs/current/validation.md`
- `docs/decisions/` 配下の現行命名規則に従うdecision record
- living plan path
