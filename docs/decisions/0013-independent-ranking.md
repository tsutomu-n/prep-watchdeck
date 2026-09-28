# 独立した外部参照ランキング

- 作成: `2026-09-12T09:20:26+09:00`
- 更新: `2026-09-12T09:20:26+09:00`
- 検証: `2026-09-12T09:57:08+09:00`
- 状態: `設計判断`

元の3取引所の全銘柄ランキングを、既存の可視行向け価格取得・artifact鮮度判定・保存先から分離する。
Pythonの独立workspace、専用SQLite、loopback読取りAPIを採用した。元名簿のidentityだけを
手動で照合・exportし、Bybitを主、Binanceを補助とする固定した参照契約を銘柄ごとに持つ。
同名だけの統合、障害時のProvider切替、元の3取引所からの価格補完は行わない。

WSで確定1分足を継続取得し、RESTで初期履歴と欠測を補う。同じ分境界Tと入力履歴を固定した
generationから、15分・1時間・任意JST基準の騰落率とquote売買代金を計算する。
Browser数・基準時刻の変更では外部取得を増やさず、32件の計算cacheを使う。
Bybit/Binanceの公開配信を531候補について180秒観測し、3周期の全候補配信を確認した。
観測の遅延から発行猶予8秒、処理deadline 12秒を採用した。これはidentity照合とは別の証拠である。

元の名簿には株式・ETF等も含まれる。公式catalogの分類でcrypto以外を対象外として保持し、
欠落させない。BTCDOMは公式説明とAsterの参照指数によりcrypto indexとして個別に採用する。
一般のINDEX分類を包括許可しない。元の名簿が24時間古くても保存済みmapで取得を続け、
取扱いの再確認が止まっていることを表示する。

単一のTradingView標準Widgetを専用のsrcdoc frameへ置く。通常embedに対する親URLの
`tvwidgetsymbol`による銘柄上書きを実観測したため、検索・比較を隠す設定と別閲覧contextを併用する。
Widgetの価格・出来高や非公開APIをランキングへ取り込まない。足間隔はアプリが保持し、
毎分のランキング更新ではframeを再生成しない。

起動wrapperはhost filesystemを読取り専用にし、新規stateだけを書込み可能にする。
既存stateの権限やservice設定は変更しない。systemd templateは作成までとし、installや本番反映は別操作。
銘柄mapの要確認を残す間は全件受入を完了としない。進捗と未解決は
[/home/tn/projects/prep-watchdeck/docs/plans/active/independent-daytrade-ranking/EVIDENCE.md](/home/tn/projects/prep-watchdeck/docs/plans/active/independent-daytrade-ranking/EVIDENCE.md)
で管理する。
