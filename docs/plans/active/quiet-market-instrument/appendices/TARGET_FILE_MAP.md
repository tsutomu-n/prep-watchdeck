# 対象ファイルマップ

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## 実装前に存在確認する対象

### Scanner

```text
apps/scanner-core/src/prep_watchdeck/features/volume_ratio.py
apps/scanner-core/src/prep_watchdeck/screening/pipeline.py
apps/scanner-core/src/prep_watchdeck/domain/enums.py
apps/scanner-core/src/prep_watchdeck/domain/dto.py
apps/scanner-core/src/prep_watchdeck/adapters/bitget_live/provider.py
apps/scanner-core/src/prep_watchdeck/application/service_snapshot.py
apps/scanner-core/src/prep_watchdeck/config/filter_config.py
config/scanner-filters/balanced.toml
config/scanner-filters/aggressive.toml
config/scanner-filters/conservative.toml
schemas/scanner-snapshot.schema.json
```

### Web

```text
apps/web/src/routes/+page.svelte
apps/web/src/lib/components/dashboard/DashboardRankingArea.svelte
apps/web/src/lib/components/dashboard/DashboardMarketRow.svelte
apps/web/src/lib/components/dashboard/DashboardWatchlist.svelte
apps/web/src/lib/components/dashboard/SelectedSymbolOverview.svelte
apps/web/src/lib/components/dashboard/SmartRankControl.svelte
apps/web/src/lib/components/dashboard/DashboardVpiExperimentPanel.svelte
apps/web/src/lib/components/dashboard/SelectedSymbolVpiDetail.svelte
apps/web/src/lib/components/symbol/SymbolMonitoringRail.svelte
apps/web/src/lib/market/labels.ts
apps/web/src/lib/market/smart-rank.ts
apps/web/src/lib/generated/scanner-snapshot.d.ts
```

### Tests / docs

```text
apps/scanner-core/tests/test_domain_features.py
apps/scanner-core/tests/test_rankings.py
apps/scanner-core/tests/test_vpi_compute.py
apps/web/src/lib/market/labels.test.ts
apps/web/src/lib/market/smart-rank.test.ts
apps/web/tests/e2e/home.e2e.ts
apps/web/tests/e2e/realtime-dashboard.e2e.ts
DESIGN.md
docs/current/ui-workflow.md
docs/current/data-contracts.md
docs/current/validation.md
docs/decisions/0009-quiet-market-instrument.md
```

ファイル名や責務が現行Repoと異なる場合、推測で新規重複fileを作らず、現行責務へmapして両planに記録する。
