# 名簿確認と価格品質の分離

timestamp="2026-10-07(水)_21:19 JST"

- 作成: `2026-10-07T21:19:35+09:00`
- 更新: `2026-10-07T21:19:35+09:00`
- 状態: `実装計画`

## Goal / scope

正常なcatalog取得をL1欠測で拒否する不具合を修正し、名簿の取得不良・変更確認待ち・取引所価格品質を独立表示する。RLC追加とDRV/NULLMASKの版変更は一次根拠と現行定義を確認し、確認できた差分だけを候補mapへ反映する。
起点は本番Webと一致する `8971500`。別branchの単独契約selection変更を混ぜない。

## 完了条件 / 検証

- 新鮮で完全なcatalogと同じ審査済みidentityなら、L1欠測だけでは名簿をstaleにしない。
- catalog不完全・古い・未知の品質警告・identity差分は引き続き拒否し、失敗理由を公開する。
- Ranking応答の名簿診断を型・schema・画面まで接続する。新旧APIの組み合わせを成功扱いしない。
- 3契約差分の根拠を保全し、参照provider/revision・既存数量換算を維持する。未確認を埋めない。
- 関連pytest、Ranking全pytest/Ruff/Pyrefly、schema/map根拠検査、Web unit/check/buildと関連PC/Mobile E2Eを実施する。
- docs/currentへ現行契約・運用条件を反映し、今回の差分だけをcommitする。

## Checkpoint

- [x] 本番とcodeの原因確認。catalog1096件は成功、RLC価格欠測と未審査差分3契約を検出。
- [ ] catalog専用判定・API診断・UI原因別表示。
- [ ] 新規/変更契約の根拠確認と候補map/evidence検証。
- [ ] 統合検証、正本文書更新、commit。

## Rollback / 境界

source・生成schema・map/evidenceを同じcommit組で保全する。稼働DB/state/serviceは変更しない。本番反映時はRankingとWebを同じAPI契約で切り替え、旧release/mapを残す。push・本番反映・unit操作は別の明示指示時に実施する。

## 未解決事項

RLCの公式identity/参照対応、DRV/NULLMASKのversion変更理由は根拠調査中。根拠不足なら要確認を保持する。
