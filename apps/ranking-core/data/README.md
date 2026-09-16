# 初期の銘柄対応表

- 作成: `2026-09-12T09:20:26+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 状態: `現行`

このdirectoryは価格を含まない、手動照合済みの対応表とidentity根拠を保存する。
初期map version `07bfd5c76b6fc8cbc882aeba`（`ranking-map-v2`）は元名簿1,203契約を691行に保持する。
暗号資産の対象570行のうち534行に固定参照契約がある（Bybit 482、Binance 52）。Widget対応は531行。
36行は根拠を確認した未対応、原資産・参照の要確認は0行。別に121行を公式catalogの分類に基づく
暗号資産以外の対象外として保持する。元数量換算とWidgetの未確認はそれぞれ3件であり、
ランキングの採用資格と別に管理する。取得・連続更新の実データ受入は対応表照合と別の証拠である。

未対応36行は、採用したBybit/Binanceに同一資産の対応契約がない33行、参照契約の取扱い終了・
清算中1行、別資産として確認した元契約に参照契約がない1行、同名の外部参照が株式の別資産である1行。
各判断は保存済みのidentity・catalog根拠に結び付ける。
Aster AIはArtificial InuのCAとMEXC別名AIINUを確認し、採用2社の全catalog/指数から
抽出したGensyn候補を別CAで除外して、確認時点の採用範囲では未対応とした。
MEXC Meme+等の他市場や未文書化の別名まで不存在とする判断ではない。

元数量換算が未確認の3契約は次の一次情報が不足している。詳しい根拠と不足は
/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/qualification-evidence.json の
`unresolvedDetails`へ記録する。

CHEEMSはBitgetのCheems metadataとBinanceの同じBSC CA、NEXはBitgetのNexus metadataと
Bybit公式告知、RATSはBitget当該契約画面のBRC-20 RATS説明を各社の指数構成へ照合した。
RATS画面の説明はCoinMarketCap/CoinGecko由来であり、取引所の数量定義とは区別する。
固定参照はBinance 1000CHEEMSUSDT、Bybit 10000NEXUSDT、Bybit 1000RATSUSDT。
参照側倍率は各社の明示した指数係数で確認し、Bitget元契約の倍率はnullを維持した。
独立した採用根拠を`rankingQualification`、数量未確認のinstrumentを`quantityUnverified`へ記録する。
3行のWidgetは`review`を保持し、Chartを描画しない。

| 対象 | 不足している根拠 |
| --- | --- |
| CHEEMS、NEX、RATS | Bitgetの1MCHEEMS・10000NEX・1000RATSについて、原資産1単位への数量倍率を定義する一次情報。symbol prefixや注文数量の係数だけでは確定しない。 |

Aster PROSUSDTは、公式画面のPharos identity・chain/CA、取引中の元契約catalog、
Bybit PHAROSUSDTのproject名とPROS指数構成を照合し、既存のPharos行へ統合した。
Bitget/Asterの元instrument IDと数量倍率、参照契約、Widget symbolを保持している。
Aster画面の説明metadataはCoinMarketCap由来であり、独自の公式契約仕様とは区別する。

- /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/initial-map.json: version付きの起動用map。
- /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/initial-roster.json: 元の3取引所のidentityだけを抽出した名簿。
- /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/qualification-evidence.json: 公開catalog、指数構成のidentity、通常Widget検索で確認したmetadata、未解決一覧。指数価格は保存・計算していない。

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json
uv run --package prep-watchdeck-ranking python scripts/ranking/verify-map-evidence.py
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-ranking-qualified
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-reviewed
```

最初のcommandは構造と件数を検証する。2つ目は全original ID、参照契約、Widget metadata、
行・数量の未解決一覧との一致を検証し、3種類の確認状態と`qualificationComplete`を返す。
参照APIへ対応した行でWidgetを未対応と確定する場合は、理由と根拠も検証する。
構造・証拠の一致だけでは根拠の内容監査や実データ受入を代替しない。3つ目は行の要確認が0なら
終了0となり、Repository横断検証のランキングgateに使う。最後のcommandは行・元数量・Widgetの
未確認が1件でも残る場合に終了1となる。現mapでは数量3件・Widget3件により終了1を維持する。
参照契約の数量倍率は、元取引所の指数構成の明示係数、照合した資産metadata、公式の数量説明に
結び付ける。同じbase名や数量らしいprefixだけでは確定しない。Bitgetの指数構成のspotPairには
独自の別名が含まれるため、その文字列だけで別契約へ切り替えない。

名簿更新時は別の出力先へ`export-roster`を実行し、追加・削除・version変更と元の対応表を照合する。
各銘柄のstatus、根拠、数量倍率、固定した参照契約、Widget symbolをレビューした後、`compile-map`
で全instrument IDとversionを照合する。/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/initial-map.json も`--decisions`として読み込める。
未確認契約へ自動で接尾辞を付ける処理、障害時の自動Provider切替、履歴の連結は行わない。

変更したmapは専用collectorの再起動時に採用する。既存の採用契約はBybit/Binanceのcatalogを
1時間ごとに再確認し、廃止・revision変更を検出した場合は順位とWidgetから外す。
元名簿が24時間以上古い場合は画面で知らせる。元の4 artifactの鮮度は収集継続の条件にしない。
