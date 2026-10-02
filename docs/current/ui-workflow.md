# prep-watchdeck 現行UIワークフロー

timestamp="2026-10-02(金)_12:33 JST"
- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-10-02T12:33:24+09:00`
- 検証: `2026-10-02T12:33:24+09:00`
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

`/`は参照市場の24時間・売買代金順を既定とする共通Markets workspace。`/rankings`は従来の15分・上昇率順を入口として維持する。取引所別Universeは`/?mode=native`で開き、参照行の確認済みoriginalのID/versionが現行Universeに一致するときだけnative詳細へ進める。戻るリンクは比較期間、並び順、指定JST時刻、検索・sort、平常比期間/下限・当日位置上下限・表示列を復元する。再取得後に選択行のfocusと表内scrollを復元する。

Universeはbase→Venueの既定順。groupのないactive契約も単体詳細へ選択できる。追加metricsは現行ID/version一致時だけ結合し、欠損・障害は元のUniverseやRankingを停止しない。数量OIと確定終値の表示には別々の鮮度上限を使い、選択板のBBOを全市場のL1 spreadへ代入しない。

お気に入りと名前付きviewはstate rootのuser-workspaceへatomic保存する。最近見た対象は端末localStorage、未保存メモは銘柄/version別にsessionStorageへ保存し、利用不可時は画面内保持を知らせる。メモPOSTはread token一致時だけ成功し、古い応答で編集後の下書きを消さない。参照詳細の観測メモでは保存先の取扱い契約を選び、任意で参照の出所・比較時刻・値を添付できる。native初期表示やURL復元はselectionをPOSTせず、明示選択後のheartbeatは同一tokenのまま5分ごとに送り、hidden中は停止する。L1品質はBrowser時計でも120秒超で期限切れにする。

## 共通メニュー・設定と表示条件

参照一覧の「目的別の表示」は、実際の条件から選択状態を判定します。市場全体は24h/turnover/標準列、短期の値動きは15m/gainers/値動き列、売買代金の増加は15m/turnover/値動き列＋15分平常比降順、お気に入り監視は24h/turnover/標準列＋favoritesOnlyです。平常比順でも全体順位は売買代金順のままです。固定の数値しきい値は追加しません。切替は検索・下限・追加filter・行順固定・保存view選択を解除し、venue・選択ID・Chart足・JST設定を保持します。

Desktopでは条件controlと一覧を左側、選択詳細を右側の上端から配置します。参照詳細のChart前に参照契約と確認先のnative linkを並べ、削除済み選択ではlinkを停止します。確認先はactiveかつID/version一致の契約だけです。取引所別詳細はデータ元・契約・品質・時刻と主要4指標をChart付近に表示し、基準価格の詳細はChart下へ置きます。数量OIの観測時刻はendObservedAtのみを使い、配信時刻やbucket時刻で補完しません。参考Mark中央値とL1契約情報は折り畳みとし、算出不能や品質・取得失敗の警告は可視維持します。

共通メニューは「ランキング」「取引所別」「設定」。テーマ・フォント・騰落率のJST基準時刻は`/settings`で変更し、同じBrowserの各市場ページへ適用する。設定はBrowser単位で、端末間同期は行わない。JST基準設定は騰落率の計算基準であり、Chart表示時刻のJST、取引所日足のJST 09:00区切りとは別である。

ランキングは比較期間・並び順・検索・お気に入りを一覧近くに置く。追加の絞り込みは「ランキング条件」、長い指標説明は「指標の読み方」、名前付きviewの保存・削除は「表示条件を保存／管理」を開いて操作する。閉じた状態でも適用条件・比較時刻・件数を示し、更新停止・欠測の警告を隠さない。スマホは順位・銘柄・騰落率・売買代金を主列とし、参照終値と追加指標は詳細でも確認できる。

PCは一覧と詳細を左右に表示する。スマホは一覧と詳細を切り替え、詳細の戻る操作で位置とfocusを復元する。詳細は主要数値、Chart、追加指標・観測メモ・出典の順に確認する。表示条件と選択ID、Chartの足間隔、メモ下書きはレイアウト切替だけで破棄しない。一覧で明示選択した参照銘柄IDまたは取引所契約のID/versionをURLへ保持する。再読込時は、現行データで一致する対象の詳細を復元する。

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
共通メニューの「設定」（`/settings`）で日本時間00:00〜23:59を1分単位に設定する。初期値は00:00で、
`prep-watchdeck:daily-change-reference`へHH:mmを保存する。同じBrowserの再読込と別tabの変更を
反映する。不正な保存値は00:00へ戻し、保存拒否時は再読込まで同じ閲覧中のページ移動に適用し、保存できなかったことを表示する。

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
JSTの基準時刻は設定ページからBrowserに保存する。保存できない場合も同じ閲覧中のページ移動へ適用し、再読込では保持されないことを知らせる。

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
未対応は理由を示し、代わりの銘柄を表示しない。Mobileは一覧から選択した詳細へ切り替え、「一覧へ戻る」で表内位置・ページ位置・選択行のfocusを復元する。
再読込後に詳細を開く場合も、現在の一覧状態を履歴へ記録してから詳細を追加するため、一度の戻る操作で一覧へ戻る。
390px幅でも主要列を横scrollせず比較できる。チャート自体の内部表示範囲はWidgetが保持する。


順位の下に1分前からの変化、売買代金の下に平常比、騰落率の下にJST当日の高安位置を置く。
スマホ一覧の順位変化が「—」の場合は比較不能で、理由は銘柄詳細で確認できる。0（同順位）とは区別する。
選択詳細にも同じ3指標を表示する。順序は上昇率・下落率・売買代金の3種類を維持し、
新指標は追加の並び順にしない。

新しい条件を取得中は旧条件の行を混ぜず、選択契約とWidgetを保持する。新しい応答を一括採用した
時点で指標も切り替える。比較元のない初回・再起動後は「比較不可」、正当な前世代で順位外だった
銘柄は「新規」、現在順位外は現在の理由を表示する。取得停止後はBrowser clockでも比較を無効化する。

平常比の0倍と欠測・基準なしを区別し、JST可変期間では15分・1時間のみ対応と表示する。
当日位置は任意HH:mmではなくJST 00:00基準と説明する。追加指標の欠測で既存順位を外さない。

## 取得元・品質と保存足照合

取引所別一覧の保存足badgeから選択契約の「取得元・品質」を開く。現在L1、Catalog、Recovery、Auditを
別の段として表示し、それぞれの観測・対象期間・取得状態を混ぜない。index/Recoveryは画面が見えている
間だけ60秒間隔で単一の更新を行い、取得失敗時は前回表示を更新停止として示す。

Audit詳細は選択契約のIDとversionに結び、最新runを開いた後は閲覧中のrunへ固定する。
パネルを先に開いてからindexが届いた場合も、最初の対象runを読み込む。
新runが発行されたら明示的な切替buttonを表示する。A→B→Aや遅延応答で別契約の詳細を採用しない。
保存Chartの印は既定オフで、照合bucketを表示時間足へ集約し、読込済みbarと一致する時間だけ付ける。
印の切替はChartの表示範囲を変えない。詳細行からの移動で足が未読なら理由を表示する。
