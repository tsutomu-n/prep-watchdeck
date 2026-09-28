# Perp会場Universeと追加データ源の再評価

- 作成: `2026-08-14T08:50:37+09:00`
- 更新: `2026-08-14T08:50:37+09:00`
- 観測基準時刻: `2026-08-13T22:07:23+09:00`
- 状態: `検証記録`

---

## 結論

主要Perp DEXを市場数だけで順位付けし、そのまま`prep-watchdeck`の追加データ源として採用しては
ならない。添付された「主要Perp DEX 7選」の再評価には妥当な訂正が含まれる一方、Live APIに反する
記述と、総掲載数・現役市場数・流動性のある市場数の混同が残っている。

現行の対象者をBitgetまたはHyperliquidで取引する裁量トレーダーに限定するなら、Bitgetをscannerの
主系、Hyperliquid Coreを選択銘柄の会場比較sidecarとする現状を維持する。新しい会場を追加するだけでは
製品価値は増えず、表示密度、障害経路、契約識別、運用負荷が増える。

株式、指数、金属、原油などのRWA Perpへ製品範囲を広げる場合は、次の順で限定検証する。

1. **Aster**を第3会場候補とする。公開V3 API、USDT建てPerp、CLOB、Crypto/RWA双方の市場幅が理由である。
2. **Variational Omni**は会場中央値へ混ぜず、選択銘柄について1,000ドルnotionalのindicative bid/askを
   表示する補助候補とする。
3. **Orderly**は株式、指数、金属、原油、FXを含む統一CLOB候補として、その後に評価する。
4. **Aevo**はOptions、Pre-Launch、RWA Perpの限定用途で評価する。全体Universeの主系にはしない。
5. **ApeX OmniとdYdX**はRWA対応を確認できるが、現時点で上記3会場より先に追加する根拠はない。
6. **Synthetix**は現行10市場であり、市場幅を目的とする候補から外す。

全7会場を常時収集する実装、ticker名だけの自動統合、異なる契約や市場モデルを用いた中央値、長期履歴の
無期限保存は行わない。

## 目的と現行境界

`prep-watchdeck`は、Bitgetのpublic market dataから監視対象を絞り、risk、context、data qualityを確認する
local-firstの市場監視アプリである。自動売買、注文、Private API、残高・position取得、売買推奨は対象外で
ある。

現行の`summary.perpVenueComparison`は、Bitgetの取引中・非RWA・USDT無期限契約とHyperliquid Coreの
非delisted標準Perpを対象とする。契約同等性を説明できる銘柄だけを選択中symbolに表示し、USDTとUSDCを
換算・合算せず、rankingや売買判断へ接続しない。取得周期は300秒で、DBへ長期履歴を保存しない。

今回の評価目的は、この境界を無条件に拡張することではない。運用資金5,000ドル以下の裁量トレーダーに
とって、追加会場の情報が実際の確認・執行判断を改善するかを見極めることである。

## 観測方法

2026-08-13 22:07 JSTまでに、各会場の公開一次仕様とLive public APIをread-onlyで確認した。市場数は
各APIの状態fieldで絞り、可能な場合は24時間出来高が正数の市場数も分けた。API応答は保存しておらず、
この文書は当該時点の観測記録である。

主な判定条件は次のとおりである。

| 会場 | 現役市場の判定 |
| --- | --- |
| Bitget | `symbolType=perpetual`、`symbolStatus=normal`、`quoteCoin=USDT` |
| Hyperliquid | Core/HIP-3の`isDelisted`が真でない契約 |
| Aster | `status=TRADING` |
| Variational | `/metadata/stats`の`listings` |
| Aevo | `instrument_type=PERPETUAL`かつ`is_active=true` |
| dYdX | `status=ACTIVE` |
| Orderly | `status=ACTIVE` |
| Synthetix | 現行公式Markets文書のlisted markets |

`ACTIVE`または`TRADING`は流動性、約定可能性、API SLAを保証しない。24時間出来高も各会場の定義と
報告値であり、会場横断で同一条件の数値とは確認していない。

## Live Universeの確認結果

| 会場 | 確認結果 | 補足 |
| --- | ---: | --- |
| Bitget | 非RWA 469、RWA 279 | 取引中USDT無期限契約 |
| Hyperliquid | Core 177、HIP-3 133 | HIP-3は4 deploymentに現役契約があり、総数は動的 |
| Aster | `TRADING` 536 | 24h出来高10万ドル以上124、100万ドル以上35 |
| Variational | 537 | 24h出来高が正数485、1,000ドルquoteあり537 |
| Aevo | 有効Perp 89 | Crypto 59、Equity 25、Commodity 5 |
| dYdX | `ACTIVE` 99 | `FINAL_SETTLEMENT` 197、24h出来高が正数75 |
| Orderly | `ACTIVE` 132 | 公式market listで明示されたRWA 11 |
| Synthetix | 10 | 全てEthereum MainnetのUSDT建てPerp |

### Hyperliquid

Hyperliquid Coreは177件が非delistedだった。`perpDexs`が返した9つの名前付きHIP-3 deploymentのうち、
観測時点で現役契約があったのは`xyz` 94、`hyna` 18、`para` 19、`mkts` 2の計133件だった。

したがって、「100+ native系にHIP-3の動的市場が加わる」という説明は妥当である。一方、CoreとHIP-3を
区別せず単一の固定市場数として扱うのは不適切である。HIP-3はbuilderごとにcontract、oracle、margin、
流動性条件が異なるため、Coreの完全一致規則を一般化できない。

### Aster

Aster V3 `exchangeInfo`では536契約が`TRADING`だった。AAPL、TSLA、NVDA、GOOGL、QQQ、XAU、XAG、
CLなどが応答に含まれ、株式、ETF、商品を表すsubtypeを確認した。24時間tickerでは536件すべての
quote volumeが正数だったが、10万ドル以上は124件、100万ドル以上は35件だった。

「市場総数は未確認」という添付文の記述はLive APIで解消できる。ただし、536という数だけで全市場を
実用的と評価してはならない。Asterは公開V3 APIを新規統合の正本とし、旧V1 APIを新規実装の前提に
しない。

### Variational Omni

Variational公式APIは537市場を返し、そのうち485市場で24時間出来高が正数だった。全537市場に
1,000ドルnotionalのbid/ask quoteが含まれていた。NVDA、AAPL、TSLA、XAU、XAGなどのRWAも実応答で
確認した。

約500市場という説明は観測結果と整合する。ただし、OmniはCLOBではなく、Omni Liquidity Providerが
唯一のmarket makerとしてRFQを提示するモデルである。表示quoteはindicativeで、発注時のfirm quoteと
一致する保証はない。公式仕様上、公開APIのquoteは最大600秒cacheされる場合がある。

そのため、Variationalのmark、spread、1,000ドルquoteをBitget、Hyperliquid、Asterの板価格と同じ意味の
値として中央値へ混ぜない。利用する場合は`marketModel=RFQ`、`quoteType=indicative`、`updatedAt`を
明示する。

### Aevo

添付文の「NVDA、TSLA、SPYなどの株式/ETF Perpは現行公式情報で確認できない」という記述は誤りで
ある。Aevo公式Live APIは有効なPerpを89件返し、内訳はCrypto 59、Equity 25、Commodity 5だった。

実応答には次のRWA Perpが含まれていた。

- `NVDA-PERP`
- `TSLA-PERP`
- `SPY-PERP`
- `QQQ-PERP`
- `XAU-PERP`
- `XAG-PERP`
- `WTIOIL-PERP`

Aevoについて、Option contract数をPerp underlying数へ加算してはならないという指摘は妥当である。
しかし、株式・ETF Perpを削除する訂正はLive APIに反する。

### dYdX

dYdX公式サイトは`220+ Markets`と表示している。一方、公式Indexerの`perpetualMarkets`応答は全296件で、
`ACTIVE` 99、`FINAL_SETTLEMENT` 197だった。ACTIVE 99件のうち、24時間出来高が正数だったのは75件、
10万ドル以上は4件、100万ドル以上は2件だった。

PAXG、XAG、WTIのRWA Perpと、Instant Market Listingの仕組みは確認できる。しかし、`220+`を現在取引
可能な市場数として使ってはならない。マーケティング上の市場数、Indexer内の全履歴market、ACTIVE、
出来高のある市場を分ける必要がある。

### Orderly

Orderly公式APIは132件すべてを`ACTIVE`として返した。公式Supported MarketsはCryptoに加え、次の
RWA 11市場を明示している。

- S&P 500、NASDAQ 100
- Gold、Silver
- GOOGL、TSLA、NVDA
- Brent Crude、WTI Crude
- EUR/USD、USD/JPY

全contractはUSDC建て・USDC決済で、複数DEX frontendが単一orderbookを共有する。frontendごとに掲載
市場を選べるため、「Orderlyで有効」と「対象frontendで利用できる」を区別する。WOO XはCEXであり、
Orderlyを利用するDEX frontendはWOOFi Proである。

### ApeX Omni

ApeXのRWA APIと、AAPL-USDT、TSLA-USDTなどの株式Perpは公式資料で確認できる。RWA moduleは通常の
contract accountとは別のsub-accountと認証contextを使用する。

今回、public market APIによる現役市場総数と流動性分布は確認していない。そのため、ApeXの正確な
市場数、既存会場との重複、公開データだけで取得できるRWA fieldは未確認とする。Private API、account、
注文、RWA用認証は`prep-watchdeck`の製品境界外である。

### Synthetix

2026-02-24更新の現行公式Markets文書は、BTC、ETH、SOL、XRP、DOGE、ZEC、FARTCOIN、1000PEPE、
XMR、PUMPの10市場だけを掲載している。100+市場、Gold、Silver、Oil、FXを現行Synthetixの説明として
使うことはできない。市場幅を目的とする候補から外す判断は妥当である。

## DeFiLlamaの位置付け

観測時点のDeFiLlama Perpsページでは、Normalized Volume 24hはHyperliquid約62.8億ドル、Aster
約14.26億ドル、Lighter約11.52億ドルで、Hyperliquidが1位だった。HyperliquidのOpen Interestは
約114.01億ドルだった。

この値はvenue全体の規模を把握する参考情報であり、銘柄別のmark、funding、OI、spread、depth、
contract identityの一次データではない。venue選定の補助には使えるが、`prep-watchdeck`の銘柄別比較や
rankingの入力には使わない。順位と数値は変動するため、この文書の値を現行値の正本にしない。

## 添付文の評価

### 妥当な部分

- AsterとVariationalを別会場として扱う。
- 市場数、underlying数、instrument数を分ける。
- Option contract数をPerp市場数へ加算しない。
- Hyperliquid CoreとHIP-3を分離する。
- WOO XとWOOFi Proを区別する。
- Synthetixを市場幅の候補から外す。
- 固定記事よりLive Universeを正本とする。

### 修正が必要な部分

- Aevoの株式・ETF Perpを削除する判断はLive APIに反する。
- dYdXの`220+ Markets`を現役市場数として扱っている。現行IndexerではACTIVE 99件である。
- Asterの市場総数を未確認としている。公開V3 APIから`TRADING` 536件を確認できる。
- 市場数が多いことを流動性、API取引可能性、利用価値と結び付ける箇所がある。
- 「TradFi商品の種類が最も多い」「Long-tail探索に最適」などの順位は、共通の分類規則、出来高閾値、
  spread/depth条件を適用していないため確定できない。

## 製品判断の比較

| 選択肢 | 利点 | 欠点 | 判断 |
| --- | --- | --- | --- |
| 現状維持 | 対象利用者、障害境界、UI密度を維持できる | RWAと第3会場は見えない | 現行対象者のままなら推奨 |
| Aster限定追加 | Crypto/RWAの幅、公開V3 API、USDT建てCLOB | 契約registry、表示追加、source障害が増える | RWA範囲を承認した場合の第一候補 |
| Variational限定追加 | 1,000ドルnotional quoteが小口利用者に直接有用 | RFQ、indicative quote、最大600秒cache | 選択銘柄の補助表示だけ候補 |
| Orderly限定追加 | 指数・金属・原油・FX、統一CLOB | frontendごとの掲載差、USDC建て | Aster後の候補 |
| 7会場同時追加 | 市場発見範囲は広がる | 契約識別、障害、UI、運用、DB負荷が急増 | 採用しない |

## 最小の追加案

RWA拡張を承認する場合でも、最初から全市場を常時保存しない。

1. Asterのpublic V3 APIからcontract catalogを低頻度で取得する。
2. `status=TRADING`で、asset classとcontract identityを説明できる市場だけ登録する。
3. 現在選択中の銘柄に対応する時だけ、Asterのmark、funding、OI、24h volume、bid/ask、観測時刻を
   第3列へ表示する。
4. Variationalは同一underlyingを確認できる時だけ、1,000ドルindicative bid/askを別枠に表示する。
5. market dataは最新snapshotだけを置換し、長期履歴DBは追加しない。
6. 既存のBitget scanner、Smart Rank、Watchlist、Hot ticker、chart、売買非推奨の意味を変更しない。

## 必要な契約識別

ticker完全一致だけでは同一商品を判定できない。例えば`SPX`は、AsterとVariationalではSPX6900系
Memeを表す一方、OrderlyのS&P 500は`SPX500`である。

追加会場のregistryには少なくとも次を保持する。

```text
venue
sourceSymbol
canonicalInstrumentId
assetClass
underlyingName
marketModel          # CLOB | RFQ
quote
collateral
contractStatus
tradingSession
observedAt
sourceAt
```

同一性を確認できないcontractは自動mappingせず、比較対象外とする。

## 失敗経路と停止条件

次の場合は実装を広げない。

- 追加会場の利用者を製品対象に含める判断がない。
- ticker以外にunderlyingまたはcontract identityを確認できない。
- quote、collateral、倍率、funding interval、OI単位を確認できない。
- CLOBとRFQ、indexとmark、CryptoとRWAを同一指標として集約する必要が生じる。
- 選択銘柄限定ではなく、全会場全市場の常時収集やDB migrationが必要になる。
- 新sidecarが既存Bitget scanner、snapshot発行、service shutdownを退行させる。
- UI追加によってstale、missing、partial、quote種別、取引時間を判別できなくなる。
- Private API、wallet、account、position、注文、秘密情報が必要になる。

## 未確認事項

- 各会場の市場データ利用規約、再配布条件、商用利用条件。
- 公開APIの長期可用性、SLA、障害率、rate limitの実運用余裕。
- 会場ごとの24時間出来高、OI、Funding、mark、indexの定義差。
- Aster、Orderly、Aevo、Variationalの同一notionalに対する実約定slippageの継続比較。
- ApeXのpublic market APIによる現役市場数とRWA市場の公開field。
- 地域制限、取引時間、休日、oracle停止時のRWA contractごとの挙動。

これらを推測で埋めず、採用候補になった会場だけ実装前に一次仕様とLive responseで確認する。

## 一次情報

- [Bitget Get Contract Config](https://www.bitget.com/api-doc/contract/market/Get-All-Symbols-Contracts)
- [Hyperliquid Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Hyperliquid HIP-3](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals)
- [Aster V3 Market Data](https://asterdex.github.io/aster-api-website/futures-v3/market-data/)
- [Aster Stock Contracts](https://docs.asterdex.com/product/aster-pro/stock-contracts)
- [Variational Omni](https://docs.variational.io/omni/about-omni)
- [Variational Public API](https://docs.variational.io/technical-documentation/api)
- [Variational Quoted, Index, and Mark Prices](https://docs.variational.io/omni/trading/quoted-index-and-mark-prices)
- [Aevo GET /markets](https://api-docs.aevo.xyz/reference/getmarkets)
- [dYdX Indexer API](https://indexer.dydx.trade/docs/)
- [dYdX Instant Market Listings FAQ](https://help.dydx.trade/en/articles/240150-instant-market-listings-faq)
- [Orderly Trade on Orderly](https://orderly.network/docs/introduction/trade-on-orderly/trade-on-orderly)
- [Orderly Supported Markets](https://orderly.network/docs/introduction/trade-on-orderly/supported-markets)
- [ApeX Omni RWA API](https://api-docs.pro.apex.exchange/)
- [Synthetix Markets](https://docs.synthetix.io/trading/markets)
- [DeFiLlama Perps](https://defillama.com/perps)
