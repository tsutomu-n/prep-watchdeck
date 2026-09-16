# prep-watchdeck 現行UIワークフロー

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書は**Repositoryに実装済みのUniverseとランキングUI**の挙動を説明する。
稼働反映の状態と将来のStocks、prediction、journal、複数selection、追加Chart等の製品境界は別に扱う。
製品境界は[`product-boundary.md`](product-boundary.md)を正本とする。

## 現行主要flow

1. Universeのinstrumentを確認する。
2. 検索、Venue、coverage、quality filterで対象を絞る。
3. mark、JST基準の約定騰落率、reference種別、funding、OI、24時間出来高、freshness、provenanceをVenue別に確認する。
4. group化済みinstrumentでは、条件を満たす時だけ参考mark中央値を確認する。
5. 行を選び、primary Venue、Chart、groupの板・約定・book walkを確認する。
6. 後で再確認する文脈をPast Noteへ保存できる。

Universeはbase→Venueの既定順を保ち、外部参照のデイトレランキングは独立した画面で提供する。

## 状態軸

現行UIは次を必要に応じて分離する。

- Data quality: `ready / partial / stale / unavailable`
- Freshness: 観測後の経過と利用可能性
- Coverage: cross-Venue groupingの状態
- Operational state: artifact refresh、selection、service等の動作状態
- Selection: 選択中または未選択

新しいranking/model state等を追加する場合も、data qualityとmodel outputを混同しない。

Market Coreが`stale / unavailable`としてnullにした値を、Webが前回値や0で補わない。

## 更新停止とvalidated snapshot

現行Webは5秒ごとにartifact bundleを再取得する。再取得に失敗し、直前のschema検証済みbundleを表示し続ける
場合は、更新停止であることと最終検証時刻を表示する。

5秒、artifact数、poll方式は現行実装値であり変更可能。

## 品質理由

artifactの`qualityReasons`と`errorCode`は人間向け説明とraw codeを確認できるようにする。
unknown codeを握り潰さない。

新しいranking、prediction、backtest、portfolio等でも、入力dataのqualityや不足理由を表示できる設計を優先する。

## Universe Explorer

現行各行ではbase、Venue、source symbol、group/単独状態、mark、funding、OI、24時間出来高、quality、観測時刻等を
確認できる。

現在のfilterはsearch、Venue、coverage、quality。現在の既定sortはbase→Venue。

将来はranking、custom sort、score、asset class、strategy/model filter等を追加できる。

参考mark中央値はreference valueであり、現在のcontractではexecutable priceではない。将来別のexecution contextを
追加する場合は、その計算前提を別に示す。

## 約定騰落率の基準設定
画面上部のnative time inputで日本時間00:00〜23:59を1分単位に設定する。初期値は00:00で、
`prep-watchdeck:daily-change-reference`へHH:mmを保存する。同じBrowserの再読込と別tabの変更を
反映する。不正な保存値は00:00へ戻し、保存拒否時は現在の画面だけに適用したことを表示する。

Desktopの一覧は独立した「約定騰落率」列、MobileはMarkの下へ別label付きで表示する。
選択detailは基準日時・基準価格・約定価格・取得時刻を併記する。設定によってMark値、参考中央値、
Chart時間足や日足の区切り、Universeの並び順を変えない。

選択銘柄とviewport内の行だけを約1分ごとに取得する。Browserは同時2要求までとし、同じ契約をまとめる。
可視外の待機要求と非表示tabの取得は停止する。設定・日次anchor・契約version変更では旧結果を消し、
遅れて届いた応答を適用しない。取得失敗、基準足欠落、最新約定足欠落、最新足期限切れを数値に置換しない。

## 選択

現行実装では1 instrument/groupを選択し、500ms debounce後にselection commandを送り、5分ごとにheartbeatする。

この`1 selection`、debounce、TTL、heartbeatは現在のruntime値であり永久制約ではない。
将来は複数selection、pinned symbol、ranking shortlist等へ拡張できる。

## Selected detail

現行detailは主に次を表示する。

1. instrument identity、coverage、JST基準の約定騰落率、quote/settle/collateral、freshness
2. `5m / 15m / 1h / 4h / 1D` Chart
3. Venue別depth最大20段
4. group横断の直近100 trades
5. `$100 / $500 / $1,000` book walk
6. Past Note

これらのtimeframe、bar数、depth段数、trade件数、notional、section順は現行値であり変更可能。

Chart、indicator、rankingはcross-Venue group化と別責務として扱える。将来、単独instrumentでもidentityとsourceが
確認できればChart/indicator/rankingを提供できる。

book walk等のexecution contextは、fee inclusion、impact assumption、data age、order availabilityの意味を明示する。
現在の実装がfee/impactを含まないことを、将来も永久禁止とはしない。

## Chart履歴と表示範囲

Chartは選択した`venueInstrumentId`の取引所native時間足を描画する。時間足はローソク足1本の長さであり、
初期選択は15m。銘柄・Venue変更後も選択した時間足を保持する。切替時は旧データを消して読み込み中を
示し、旧要求を中断する。遅れて届いた旧銘柄・旧時間足の応答は表示しない。

初回は最大500本を取得し、最新約120本を表示する。長い時間足も取引所の配信履歴を使い、
過去8日へ制限しない。過去へスクロールするか「さらに過去を読み込む」で履歴を追加する。
上限は1銘柄・1時間足10,000本で、取引所が配信しない期間は補間しない。

画面下の「表示期間」は実際に見えている範囲を表す。ズーム・ドラッグで範囲を変え、
「最新へ」はズームを保って最新へ移動、「全体表示」は読み込み済み全体へ合わせる。
同じ銘柄・時間足の定期更新、配色・Font変更、resizeで範囲を全体へ戻さない。
過去ページの追加では見ていた足と倍率を維持する。最新足を追っている時だけ新しい足へ進める。
銘柄または時間足を変更すると、その選択の最新約120本から表示する。

チャート軸・カーソル・周辺日時はJST固定。1Dは1日足で、UTC 00:00＝JST 09:00の区切りを明示する。
未終了の足は未確定本数として示す。取得失敗時、同じ選択の取得済みデータには更新停止の注意を付ける。
native履歴にcollectorの`confirmed` / `derived_final`やSCD2 version境界判定を付け替えない。

## Notes / Journal

現行Past Noteは`venueInstrumentId`単位の観測annotationで、現在は60日後にread時pruneする。
60日は現行policyであり変更可能。

将来、Past Noteとは別にDecision Memo、Trade Journal、review workflowを追加できる。
annotation、decision、execution recordを同一概念へ無理に統合しない。

## Ranking / Prediction

将来のUIはAttention Rank、Momentum、Volume、Breakout、LONG/SHORT候補、prediction等を表示できる。

追加時は可能な範囲で次を示す。

- rank/scoreの意味
- timeframe
- component / reason
- data-as-of
- data quality
- model/ruleset version
- insufficient-data reason

高rankや方向評価を自動注文と同義にしない。

## Qualityと障害

- missing、partial、stale、invalidを空文字や0、前回値へ変換しない。
- source timestampがない場合は勝手にsource timeを捏造しない。
- Web process healthとmarket data qualityを混同しない。
- 一部source障害では成功データと失敗理由を区別する。
- schema不一致やrefresh失敗を黙って正常表示しない。

## Responsive / Accessibility

- Desktopとnarrow viewportの双方で主要flowへ到達できる。
- semantic table/list/form control、可視focus、keyboard操作、status textを使う。
- 色だけでmovement、quality、coverage、selection、ranking stateを表さない。
- IME compositionを壊さない。
- reduced-motionを尊重する。

旧版の固定breakpoint、row height、layout、animation禁止等はdesign defaultとして変更できる。

## デイトレランキング

Universe Explorerのリンクから `/rankings` へ進む。比較期間、上昇率・下落率・売買代金順、USDT建ての
下限を変更すると全対応銘柄を再計算する。行の検索と50件ずつの追加表示は取得・順位の母集団を減らさない。
JSTの基準時刻はBrowserに保存し、保存できない場合はその画面で操作を継続する。

順位外・未対応の表示を有効にすると、欠測・対応確認・対象外の理由を確認できる。比較時刻、
対応数・比較可能数・絞込み後件数を常時示す。名簿更新停止と価格更新停止を別々に表示する。
空の上昇・下落順位を0%の成功値で埋めない。未対応は、同一資産の対応契約なし、参照契約の
取扱い終了・清算中、同名の参照先が株式の別資産である場合を一覧と選択詳細で読み分ける。
未定義の理由は汎用の未対応表示とし、推測で理由を補わない。

対応範囲の詳細では元契約の数量換算未確認数とChart対応未確認数を分けて示す。
元数量倍率がnullの行でも、原資産・固定参照が確認済みで必要な足がそろえば順位と指標を表示する。
選択詳細は数量換算未確認を知らせ、Widget reviewではChartを停止して独立した状態説明を示す。
原資産・参照がreviewの行は従来どおり数値と順位を作らない。

選択はrow IDで保持し、並び替え・期間変更・毎分更新で他の行へ切り替えない。条件外では選択を残して通知し、
対応表から消えた場合は選択名を残してWidgetを停止する。削除済みの判定は表示用ランキング応答と
分けて保持し、期間・並び順・下限変更で応答を読み直す間や取得失敗後も旧Widgetを復活させない。
取得に成功した新しい対応表、または利用者による有効な行の選択で判定を更新する。
旧問い合わせの後着結果は破棄する。
アプリの「チャートの足」で選ぶ足間隔は独立したBrowser設定で、ランキングの比較期間とは連動させない。
更新でWidget frameを作り直さない。Widget内部の日付範囲・足操作はアプリ設定へ同期せず、
再生成時はアプリで保存した足間隔を使う。
足・テーマ・選択銘柄の明示的な変更と再読込み操作ではWidgetが再生成される。

Widgetは確認済みの参照契約1つだけを表示する。検索・比較toolbarを無効にし、親pageのURL symbol指定が
参照契約を上書きしない独立frameへ標準embedを配置する。提供元のbrandingとリンクを残す。
未対応は理由を示し、代わりの銘柄を表示しない。Mobileは一覧から選択したChartへscrollし、
390px幅で操作できる。チャート自体の内部表示範囲はWidgetが保持する。


順位の下に1分前からの変化、売買代金の下に平常比、騰落率の下にJST当日の高安位置を置く。
選択詳細にも同じ3指標を表示する。順序は上昇率・下落率・売買代金の3種類を維持し、
新指標は追加の並び順にしない。

新しい条件を取得中は旧条件の行を混ぜず、選択契約とWidgetを保持する。新しい応答を一括採用した
時点で指標も切り替える。比較元のない初回・再起動後は「比較不可」、正当な前世代で順位外だった
銘柄は「新規」、現在順位外は現在の理由を表示する。取得停止後はBrowser clockでも比較を無効化する。

平常比の0倍と欠測・基準なしを区別し、JST可変期間では15分・1時間のみ対応と表示する。
当日位置は任意HH:mmではなくJST 00:00基準と説明する。追加指標の欠測で既存順位を外さない。
