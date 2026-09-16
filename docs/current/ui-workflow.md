# prep-watchdeck 現行UIワークフロー

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 検証: `2026-09-16T19:56:52+09:00`
- 状態: `現行`

---

## 主要flow

1. Universeの全instrumentをbase、Venue順で確認する。
2. 検索、Venue、coverage、quality filterで監視対象を絞る。
3. mark、reference種別、funding、OI、24時間出来高、鮮度、provenanceをVenue別に確認する。
4. group化済みinstrumentでは、条件を満たす時だけ参考mark中央値を確認する。
5. 行を選び、primary Venue、Chart、groupの板・約定・book walkを確認する。
6. 後で再確認する文脈だけPast Noteへ保存する。

Universe Explorerは売買方向、期待収益、裁定機会、推奨Venue、価格差ランキングを表示しない。
外部参照による騰落率・売買代金ランキングは独立した画面で扱う。

## 状態軸

UIは次の状態を混ぜない。

- **Data quality**: `ready / partial / stale / unavailable`
- **Freshness**: 観測後の秒数と許容時間
- **Coverage**: `3 Venue / 2 Venue / 単独 / 未group`
- **Operational state**: artifact refresh失敗、selection失敗、pending、heartbeat
- **Selection**: 選択中または未選択

Data qualityはそれぞれ`正常 / 一部取得 / 期限切れ / 取得不能`と表示する。Coverageが単独または
未groupであることは品質不良ではないためneutralに表示する。selectionやWeb refreshの操作失敗も
market data qualityへ読み替えない。

Market Coreが`stale / unavailable`としてnullにした値を、Webが前回値や0で補わない。ageがない場合は
`取得時刻なし`と表示する。

## 更新停止とvalidated snapshot

Webは5秒ごとに4 artifactを再取得する。すでにschema・generation・freshnessを検証済みのbundleを
表示している状態で再取得に失敗した場合、既存DOMを消さず次を表示する。

> 更新停止
> 最新データを取得できません。以下は最後に検証できたsnapshotです。

これはartifact statusへ新しい値を追加するものではなくWebのoperational stateである。表示中の
`ready / partial / stale / unavailable`を勝手に変更しない。bannerには`service-state.generatedAt`を
最終検証時刻として併記し、再取得成功時にbannerを消す。5秒pollごとに強いalertを反復しない。

## 品質理由

artifactの`qualityReasons`と`errorCode`はWeb presentation layerで人間向け日本語へ変換する。通常表示は
理由の意味を示し、raw codeは展開可能な`技術情報`へ残す。未知codeを握り潰さず、未定義理由として
raw codeを表示する。

Chart、参考mark中央値、selected depth、book walkにも同じ規則を適用する。`partial`は原因ではなく
集約結果なので、可能な範囲で子statusまたはreasonを併記する。

## Universe Explorer

各行は少なくともbase、Venue、source symbol、group/単独状態、mark、funding、OI、24時間出来高、
quality、観測時刻を識別できるようにする。quote、settle、collateral、reference price kind、
source endpointは詳細またはprovenance表示から確認できる。

検索はbase、source symbol、`venueInstrumentId`、quote、settleを対象にする。filterはnative
input/selectを使い、labelを常時表示する。絞り込みで値のないitemを黙って除外する場合は、適用中filterと
件数を示す。

group coverageとdata qualityは別軸である。単独instrumentは「品質不良」ではなく未group、
stale/unavailableはcoverageに関係なく品質状態として示す。

参考mark中央値には次を併記する。

- 参加Venue数
- cycle/freshness条件
- `USD/USDC/USDT parityを参考中央値だけに仮定`
- executable priceでも売買推奨でもないこと

## 選択

行の選択は視覚state、keyboard focus、collector subscriptionを混同しない。Webは500ms debounce後に
`/api/selection`へ1 commandを送り、その後market serviceの選択処理とartifact更新を待つ。同じ
`groupId + venueInstrumentId`を5分ごとにheartbeatする。primaryを変える時は同じgroupでも新しい
selection revisionとして扱う。

選択対象が次のUniverseから消えた、group membershipが変わった、commandが期限切れになった場合は、
旧detailを有効なまま見せず選択解除またはunavailable理由を表示する。selection POST失敗は
operational warningとして表示し、data quality色へ混ぜない。

## 選択detail

detailは次の順で表示する。

1. primary instrument identity、coverage、quote/settle/collateral、freshness
2. 5m / 15m / 1h / 4h / 24h Chart
3. Venue別depth最大20段
4. group横断の直近100 trades
5. $100 / $500 / $1,000 book walk
6. Past Note

Chartは選択した`venueInstrumentId`だけを描画する。artifactは`derived_final`と`confirmed`を保持するが、
現画面ではfinalityを識別表示しない。欠落bar、version境界、不完全barを埋めず、timeframe変更で
選択instrumentを変えない。partial/incomplete理由は人間向け文言とraw codeの両方を確認できる。

book walkはbuy/sellを分け、平均価格とtop-of-bookからのbpsだけを表示する。10秒超、板不足、
非USD-like、単位不明では数値の代わりに理由を表示する。常に次を明記する。

> 現在受信した板だけの概算。fee、将来impact、実際の注文可否を含まない。

## Past Note

Past Noteは`venueInstrumentId`単位の監視annotationで、trade journalではない。reasonまたは本文を
必須とし、保存中の重複submitを防ぐ。選択が変わっても別instrumentのdraft、feedback、noteを
混在させない。reasonが空なら`過去注記`とし、同じreasonで再保存した場合は同じinstrumentの既存noteを
新しいnoteで置き換える。60日を過ぎたnoteは再表示しない。

## Qualityと障害

- missing、partial、stale、invalidを空文字や0へ変換しない。
- source timestampがない場合は「なし」とし、observed timeへ置き換えない。
- Web process healthとmarket data qualityを同じbadgeにしない。
- 一部Venue障害では取得できたVenueを残し、失敗Venueと理由を表示する。
- artifact schema不一致やrefresh失敗では更新停止bannerを表示する。直前の検証済みDOMが残る場合も、
  その全値を現在値として扱わない。

## Responsiveとaccessibility

Desktop 1440pxはUniverseとdetailを同時に走査できる密度を保つ。Mobile 390pxはfilter、行、
selected detailを縦方向へ並べ、横overflowで主要操作を隠さない。tap targetは44px以上、主要actionは
48pxを目安にする。

semantic table/list、native form control、可視focus、keyboard操作、status textを使う。
色だけでmovement、quality、coverage、selectionを表さない。検索IME composition中にfilterを確定しない。
自動scroll、点滅、常時animation、hover必須操作を追加しない。自動refresh失敗はpolite status、
明示的なselection操作失敗だけ必要に応じてalertを使う。

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
