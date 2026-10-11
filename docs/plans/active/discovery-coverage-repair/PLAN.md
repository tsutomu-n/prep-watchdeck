# Discovery coverageと対応表不一致の修復

timestamp="2026-10-11(日)_12:03 JST"
- 作成: `2026-10-11T11:52:00+09:00`
- 更新: `2026-10-11T12:03:05+09:00`
- 検証: `2026-10-11T12:03:05+09:00`
- 状態: `実装計画`

---

## Goal / Scope

PEARLの現行契約と採用対応表のversion差を証拠で確認し、未対応を維持して更新する。
Discoveryは全対象の条件判定済み件数、対象確認待ち、比較値確認不能、その他の確認待ちを
同じsummary generationから表示する。partialやstaleをreadyへ変更せず、実Venueの鮮度と区別する。
Providerの価格補完、参照先変更、quantity推定、手動selection変更、DB migrationは含めない。

## Checkpoint

- baseline: source `3d257b3`、旧対応表 `445f6cdfe65120105530afa1`。
- 既存workspaceの4差分、manual保存state、既存unit、旧対応表をhashで保全。
- 実装、候補作成、検証、commit、push、配置、稼働確認の順で進める。
- PEARLの正規化定義は不変。raw `imn`のみ変化。候補は未対応・参照なし・倍率未確認を維持。
- UIの新しい回帰caseはPC/スマホでPASS。release gateもPASS（E2E 169 pass / 1 skip）。

## 完了条件 / 検証

- 現行roster全件とreadonly定義監査、完全な公式catalogを候補へbindingする。
- PEARL以外の採用identity、固定参照、倍率、statusは維持し、資格を昇格しない。
- schema、map evidence、既存資格gate、Webのtest/check/build、関連desktop/mobile E2Eが通る。
- releaseはtracked sourceから作成し、repository release gateを1回実行する。
- 本番monitorの不一致が解消し、終了statusとDiscoveryの内訳を直接確認する。
- 既存差分と保存stateのhashを照合し、source/commit/push/runtime/残るpartialを別に報告する。

## Rollback / 未解決事項

旧releaseと旧対応表を保持する。今回追加するunit drop-inだけを識別して戻し、
対象serviceを旧構成へ戻す。DBと保存stateは変更・削除しない。
契約identityが変わっていれば候補採用を止め、独立した審査へ戻す。
比較値の取得不能、未対応、対象確認待ちによるpartialは有効な状態として残す。
