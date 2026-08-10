# OSS参照方針

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## Production

新規依存なし。既存`tradingview/lightweight-charts`を維持する。

## 開発ツール

- `microsoft/playwright-cli`: agentによるvisual QAとscreenshot
- `responsively-org/responsively-app`: 複数viewport同時確認

Repo dependencyへ追加しない。

## 設計参考

- `Abdenasser/neohtop`: 高密度監視table、選択状態、realtime更新
- `ln-dev7/circle`: 主一覧 + Inspector、連続surface
- `satnaing/shadcn-admin`: keyboard、filter、responsive操作だけ
- `grafana/grafana`: Inspector、data state、progressive disclosure

外観、CSS、React/Tailwind、AGPL codeはコピーしない。
