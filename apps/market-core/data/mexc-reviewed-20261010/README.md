# MEXC 100銘柄の固定審査bundle

timestamp="2026-10-10(土)_10:44 JST"

- 作成: `2026-10-10T10:44:00+09:00`
- 更新: `2026-10-10T10:44:00+09:00`
- 状態: `検証記録`

このbundleは2026-10-10の公式bulk catalog/ticker各1回の取得と公式asset page審査に基づく。
既存10銘柄を保持し、取得時点のMEXC `amount24`降順で追加90銘柄を選定した。
採用境界までの161候補は既存10、追加90、除外61。株式・金属・IPO等の非crypto underlying、
正確な先物bindingがないページ、同名別資産の説明不一致、未解決alias等を除外した。
ONDO・XDP・CT・CHIPはprotocol tokenとしての根拠を持ち、tokenized securityや原資産の
価格を契約に割り当てていない。SPXはSPX6900 meme tokenであり株価指数ではない。

`catalog.json`と`ticker.json`は取得応答の原bytesで、URL・UTC・件数・SHA-256は
`snapshot.json`へ記録する。`reviewed-evidence.json`は90銘柄それぞれの公式asset page、
取得UTC、HTML hash、native token identifier、project/explorer、先物binding、分類所見を保持する。
長い紹介文を複製せず、原文hashと短い審査所見を保存した。
`selection-decisions.json`は採用境界までの順位と除外理由を保持する。

`registry-10.py`は開始時のsource registryをそのまま保存したもの。
`registry-50.py`と`registry-100.py`はこれを順に拡大する固定sourceであり、runtime activation flagや
自動入替はない。各`manifest-*.json`がsource hash、順序、対応するmap用審査入力を指定する。
`identity-reviews-*.json`の追加銘柄はnative-onlyで、固定Bybit/Binance参照の未審査理由を保持する。
`contractSize`はcontracts→base quantity換算係数であり、asset price multiplierは別の1である。

Repo rootで以下のoffline検証を実行できる。

```bash
uv run --no-sync --package prep-watchdeck-market python scripts/market/verify-mexc-registry.py
```

10→50→100のsource適用と稼働切替は各段階gateの後に行う。この文書とmanifestは適用済み・稼働済みを
主張しない。各切替後に専用DBのread-only captureから実際のcontractVersion IDを採取し、
`prepare-mexc-map.py`で直前の完全なrosterへ追加する。架空ID、隔離test ID、過去の本番IDを
currentの根拠として使わない。既存version/定義が変われば別の再審査が必要である。
同一captureを再処理しても既存審査日時・qualification・map versionは変更しない。

追加90銘柄の固定参照とWidgetは未審査のままで、mapの`status=review`と`reference=null`を保持する。
既存source mapのquantity 3件・Widget 3件のunknownも維持する。
このbundleの審査は当該ledgerを変更しない。`validate-map --require-reviewed`は
これらが残る間は想定どおり失敗する。Offline source検証、map検証、本番反映、live更新受入は別である。
