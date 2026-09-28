# prep-watchdeck 現行UIワークフロー

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-12T09:57:08+09:00`
- 検証: `2026-09-12T09:57:08+09:00`
- 状態: `現行`

---

## 主要flow

1. Universeの全instrumentをbase、Venue順で確認する。
2. 検索、Venue、coverage、quality filterで監視対象を絞る。
3. mark、指定したJST時刻基準の約定騰落率、reference種別、funding、OI、24時間出来高、鮮度、provenanceをVenue別に確認する。
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

### 約定騰落率の基準設定

画面上部のnative time inputで日本時間00:00〜23:59を1分単位に設定する。初期値は00:00で、
`prep-watchdeck:daily-change-reference`へHH:mmを保存する。同じBrowserの再読込と別tabの変更を
反映する。不正な保存値は00:00へ戻し、保存拒否時は現在の画面だけに適用したことを表示する。

Desktopの一覧は独立した「約定騰落率」列、MobileはMarkの下へ別label付きで表示する。
選択detailは基準日時・基準価格・約定価格・取得時刻を併記する。設定によってMark値、参考中央値、
Chart時間足や日足の区切り、Universeの並び順を変えない。

選択銘柄とviewport内の行だけを約1分ごとに取得する。Browserは同時2要求までとし、同じ契約をまとめる。
可視外の待機要求と非表示tabの取得は停止する。設定・日次anchor・契約version変更では旧結果を消し、
遅れて届いた応答を適用しない。取得失敗、基準足欠落、最新約定足欠落、最新足期限切れを数値に置換しない。

### 詳細表示の選択

行の選択は視覚state、keyboard focus、collector subscriptionを混同しない。Webは500ms debounce後に
`/api/selection`へ1 commandを送り、その後market serviceの選択処理とartifact更新を待つ。同じ
`groupId + venueInstrumentId`を5分ごとにheartbeatする。primaryを変える時は同じgroupでも新しい
selection revisionとして扱う。

選択対象が次のUniverseから消えた、group membershipが変わった、commandが期限切れになった場合は、
旧detailを有効なまま見せず選択解除またはunavailable理由を表示する。selection POST失敗は
operational warningとして表示し、data quality色へ混ぜない。

## 選択detail

detailは次の順で表示する。

1. primary instrument identity、coverage、指定基準時刻の約定騰落率、quote/settle/collateral、freshness
2. 5m / 15m / 1h / 4h / 1D Chart
3. Venue別depth最大20段
4. group横断の直近100 trades
5. $100 / $500 / $1,000 book walk
6. Past Note

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
JSTの基準時刻は既存のBrowser設定を共用し、保存できない場合はその画面で操作を継続する。

順位外・未対応の表示を有効にすると、欠測・対応確認・対象外の理由を確認できる。比較時刻、
対応数・比較可能数・絞込み後件数を常時示す。名簿更新停止と価格更新停止を別々に表示する。
空の上昇・下落順位を0%の成功値で埋めない。

選択はrow IDで保持し、並び替え・期間変更・毎分更新で他の行へ切り替えない。条件外では選択を残して通知し、
対応表から消えた場合は選択名を残してWidgetを停止する。旧問い合わせの後着結果は破棄する。
アプリの「チャートの足」で選ぶ足間隔は独立したBrowser設定で、ランキングの比較期間とは連動させない。
更新でWidget frameを作り直さない。Widget内部の日付範囲・足操作はアプリ設定へ同期せず、
再生成時はアプリで保存した足間隔を使う。
足・テーマ・選択銘柄の明示的な変更と再読込み操作ではWidgetが再生成される。

Widgetは確認済みの参照契約1つだけを表示する。検索・比較toolbarを無効にし、親pageのURL symbol指定が
参照契約を上書きしない独立frameへ標準embedを配置する。提供元のbrandingとリンクを残す。
未対応は理由を示し、代わりの銘柄を表示しない。Mobileは一覧から選択したChartへscrollし、
390px幅で操作できる。チャート自体の内部表示範囲はWidgetが保持する。
