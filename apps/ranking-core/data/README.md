# 初期の銘柄対応表

- 作成: `2026-09-12T09:20:26+09:00`
- 更新: `2026-09-12T09:20:26+09:00`
- 状態: `現行`

このdirectoryは価格を含まない、手動照合済みの対応表とidentity根拠を保存する。
現行名簿1,203契約を694行に保持し、529行に固定した参照契約とWidget symbolがある。
44行は要確認、121行は公式catalogで暗号資産以外と判定した対象外。
全件の受入は未完了であり、要確認を未対応に変更していない。

- /home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-map.json: version付きの起動用map。
- /home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-roster.json: 元の3取引所のidentityだけを抽出した名簿。
- /home/tn/projects/prep-watchdeck/apps/ranking-core/data/qualification-evidence.json: 公開catalog、指数構成のidentity、通常Widget検索で確認したmetadata、未解決一覧。指数価格は保存・計算していない。

```bash
cd /home/tn/projects/prep-watchdeck
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json
uv run --package prep-watchdeck-ranking python scripts/ranking/verify-map-evidence.py
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-reviewed
```

最初のcommandは構造と件数を検証する。2つ目は全original ID、参照契約、Widget metadata、
未解決一覧の保存済み証拠との一致を検証する。最後のcommandは要確認が残る場合に終了code 1を返す。
参照契約の数量倍率は、元取引所の指数構成の明示係数、照合した資産metadata、公式の数量説明に
結び付ける。同じbase名や数量らしいprefixだけでは確定しない。Bitgetの指数構成のspotPairには
独自の別名が含まれるため、その文字列だけで別契約へ切り替えない。

名簿更新時は別の出力先へ`export-roster`を実行し、追加・削除・version変更と元の対応表を照合する。
各銘柄のstatus、根拠、数量倍率、固定した参照契約、Widget symbolをレビューした後、`compile-map`
で全instrument IDとversionを照合する。/home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-map.json も`--decisions`として読み込める。
未確認契約へ自動で接尾辞を付ける処理、障害時の自動Provider切替、履歴の連結は行わない。

変更したmapは専用collectorの再起動時に採用する。既存の採用契約はBybit/Binanceのcatalogを
1時間ごとに再確認し、廃止・revision変更を検出した場合は順位とWidgetから外す。
元名簿が24時間以上古い場合は画面で知らせる。元の4 artifactの鮮度は収集継続の条件にしない。
