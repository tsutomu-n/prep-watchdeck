# 0014 Chartの時間足と履歴取得を分離する

- 作成: `2026-09-10T22:32:18+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
- 検証: `2026-09-11T14:21:29+09:00`
- 状態: `設計判断`

## 判断

画面のChartには、選択したVenueが配信する時間足ごとの履歴を使用する。
Web serverのread-only APIが検証済みUniverseから銘柄を解決し、最大500本ずつ取得する。
過去の追加取得を認め、collectorの8日保持を画面の履歴上限にしない。
日足は`1D`と表示し、ローソク足1本の長さと実際に表示している期間を区別する。

## 理由と代替案

既存の1分足集約は入力が過去8日で、DBの通常保持も8日である。WHERE条件の撤廃だけでは
日足履歴は増えない。Parquetを加えても収集開始前の履歴はなく、長期の日足を毎分作るために
大量の1分足を展開する必要がある。Venueのnative時間足を使えば、当該Venueの配信範囲で
長期履歴を直接取得できる。別Venueの価格で欠損を埋めない。

## 境界

既存のPostgres・Parquet・4 artifactの意味とcollectorの取得・保存処理を維持する。
native履歴は表示専用で、collectorのSCD2 version判定、`confirmed` / `derived_final`を
表す履歴ではない。Market Coreのデータ品質へnative履歴の取得結果を混ぜない。
Chartの接続失敗はChart内に表示し、最後の取得値をfreshとして扱わない。

時間足の選択はページが保持する。同じ銘柄・時間足の更新では表示位置を戻さず、
履歴の追加では足のindex移動を補正して同じ範囲を保つ。銘柄・時間足変更時は旧要求を中断し、
古い応答を表示しない。チャートと周辺時刻はJST、日足のUTC境界はJST 09:00として示す。

## 指定時刻の約定騰落率への適用

ユーザーごとのJST日次基準は、同じWeb表示用の取得経路で1分足を少量取得して計算する。
Collectorは全active契約の1分足を対象とするが、現行artifactは全契約・任意基準時刻の価格を配信しない。
設定をCollectorへ伝えて新artifactを追加する方式は、Browserごとの設定と発行契約まで広がるため採用しない。
可視行だけを取得し、基準価格の日次cacheと最新価格の短期cacheを分ける。ChartのBitget取得間隔を共用する。
現在値・基準値とも同じ契約の約定価格を使い、Markと混合しない。

## 参照

- [現行UI契約](../current/ui-workflow.md)
- [Chart履歴API契約](../current/data-contracts.md)
- [TradingViewの時間足の説明](https://www.tradingview.com/support/solutions/43000747934-time-intervals-a-quick-introduction-and-tips/)
- [Lightweight Chartsの過去履歴追加](https://tradingview.github.io/lightweight-charts/tutorials/demos/infinite-history)
- [Bitgetの時間粒度列挙](https://www.bitget.com/docs/uta/enum)
- [HyperliquidのcandleSnapshot](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#candle-snapshot)
- [Asterのローソク足API](https://asterdex.github.io/aster-api-website/futures/market-data/#klinecandlestick-data)
