# prep-watchdeck 正本ユーザーマニュアル

- 作成: `2026-08-15T11:04:37+09:00`
- 更新: `2026-08-15T11:24:56+09:00`
- 検証: `2026-08-15T11:24:56+09:00`
- 状態: `現行`

---

この文書は、`prep-watchdeck`を使う人が、画面を開き、数字を読み、誤解せずに使うための正本です。

- [人間向け](#人間向け): 初めて使う人から日常利用者までの操作と判断境界
- [AI向け最小参照](#ai向け最小参照codex-cli--01470): Repoを調査・変更するAIが守る最小契約

この文書の「現行」は、このRepositoryに実装された現行仕様を指します。commit、push、merge、
稼働環境への切替は別の状態です。現在hostで動いているversionは、systemd、service log、artifact、
実画面で確認してください。

このマニュアルは利用者向けの要約です。仕様が衝突する場合は、現行code、schema、migration、tests、
CLI help、該当する`docs/current/`の専門文書を優先します。

## 人間向け

| やりたいこと | 読む場所 |
| --- | --- |
| 初めて起動する | 「3. 初回準備と起動」 |
| 銘柄を探す | 「5. Universeを絞り込む」 |
| 数字を読む | 「6. 表示される数字の読み方」「7. 参考mark中央値」 |
| Chart、板、約定を見る | 「8. 銘柄を選んで詳細を見る」 |
| データ異常を判断する | 「9. Qualityを読む」「14. 困ったとき」 |
| noteを残す | 「10. Past Note」 |
| 完全に停止する | 「13. 完全停止」 |
| serviceやDBを操作する | [現行運用](operations.md) |

### 1. このアプリの目的

`prep-watchdeck`は、運用資金5,000 USD以下の裁量Perp traderが、Bitget、Hyperliquid Core、Asterの
public crypto linear perpetualを同じ画面で確認するためのlocal-first監視アプリです。

表示する主な情報は次のとおりです。

- Venue別のmark price、reference price、bid / ask
- 資金調達率、建玉、24時間出来高
- 取得時刻、鮮度、取得元、品質理由
- 条件を満たす複数Venueの参考mark中央値
- 選択した銘柄のChart、板、直近約定、板上概算
- あとで確認するためのPast Note

このアプリは市場を見る材料を整理します。売買判断そのものは出しません。

### 2. できないこと

次の用途には使えません。

- 売買推奨、将来価格の予測、裁定機会の断定、価格差ranking
- 自動売買、注文、残高、positionの確認
- Private APIや秘密API keyを使う処理
- RWA、HIP-3、synthetic、RFQ、alias変換、multiplier contractの比較
- 全市場の板と全tradeの長期保存、HFT、深いhistorical backfill

mark priceは実際に約定できる価格ではありません。参考mark中央値も売買可能価格ではありません。
板上概算にはfee、将来のprice impact、注文可能性が含まれません。

### 用語

| 用語 | このマニュアルでの意味 |
| --- | --- |
| Perp | 満期のない先物契約 |
| Venue | 取引所または取引会場 |
| Instrument | 1 Venueにある1つの契約 |
| Base | 契約の対象となる資産。`BTCUSDT`ならBTC |
| Quote / Settle / Collateral | 価格表示通貨 / 決済通貨 / 証拠金通貨 |
| Group | 同じ対象資産だと安全に確認できたinstrumentの集まり |
| Mark | Venueが配信する、約定価格とは異なる価格 |
| Funding | long側とshort側の間の資金調達額を決める率 |
| OI | まだ決済されていない建玉 |
| Notional | 価格を掛けて表した想定元本 |
| bps | 価格差の単位。1 bpsは0.01% |
| Parity | 異なる通貨を便宜上同価値とみなす仮定 |
| Artifact | Market CoreがWeb表示用に発行するJSON file |
| TTL | 選択監視を有効とみなす期限 |
| Quality | データの取得状態と鮮度 |
| `—` / null | 0ではなく、欠測または適用不能 |

### 3. 初回準備と起動

必要なものはPython 3.13、`uv`、Bun、Docker Composeです。systemd user serviceを使う場合は、
Linuxのuser managerも必要です。3 Venueのpublic market APIへ接続できるnetworkも必要です。

初回だけ、[READMEのDedicated Postgresとsystemd user service](../../README.md#dedicated-postgres)に
従って依存、専用Postgres、credential file、systemd unitを準備します。実際のpasswordをRepository、
issue、文書、terminal logへ貼りません。JustPassなど他projectのPostgresとport 5432は使いません。
installerは実行時のcheckout pathをunitへ書き込むため、実際に起動するcheckoutから実行します。

日常の起動は次の1 commandです。

```bash
bash scripts/start-all.sh
```

ブラウザで`http://127.0.0.1:5173/`を開きます。このURLは同じPCから使うlocalhost画面です。

`/api/health`のHTTP 200はWeb processが動いている証拠にすぎません。市場データが正常かどうかは、
画面の全体（service-state）、Catalog、L1、品質理由、観測時刻を別に確認します。

### 4. 画面を開いたら最初に見る場所

数字を見る前に、画面上部を次の順で確認します。

1. **全体**: service-state上でartifact全体を発行できているか。
2. **Catalog**: 取扱instrument一覧が更新されているか。
3. **L1**: 価格、資金調達率、建玉、出来高などの直近snapshotが更新されているか。
4. **品質理由**: 一部取得、期限切れ、取得不能の理由が出ていないか。
5. **観測時刻**: その数字がいつ取得されたか。

Web画面が開いても、CatalogまたはL1が期限切れなら、表示値を現在値として扱わないでください。
更新失敗時はbannerが表示され、直前の検証済み表示が残る場合があります。banner表示中は、画面上の
全値を現在値として扱いません。

通常の取得周期はCatalogが15分、全市場L1が60秒fixed-rateです。選択groupの板と約定だけをstreamで
取得し、表示中のWebはartifactを5秒ごとに確認します。周期は更新成功の保証ではないため、実際の
ageと品質理由を優先してください。

### 5. Universeを絞り込む

Universeの1行は、1 Venueの1 instrumentです。既定ではbase、次にVenueの順で並びます。

使える絞り込みは次の4つです。

| 絞り込み | 対象 |
| --- | --- |
| 検索 | base、source symbol、`venueInstrumentId`、quote、settle |
| Venue | Bitget、Hyperliquid、Aster |
| Coverage | 複数Venueで安全にgroup化できたinstrument、または単独instrument |
| Quality | 正常、一部取得、期限切れ、取得不能 |

`group`は、active crypto linear perpetual、base完全一致、base数量、multiplier 1、Venue内候補1件を
すべて確認できたinstrumentだけをまとめたものです。aliasや似たsymbolを推測して同一銘柄にしません。

単独instrumentは品質不良を意味しません。「他Venueと安全に同一groupへまとめられなかった」という
意味です。CoverageとQualityを分けて読んでください。

### 6. 表示される数字の読み方

| 表示 | 意味 | 読むときの注意 |
| --- | --- | --- |
| Mark | Venueが配信するmark price | 約定価格ではない |
| Reference | index、oracle、またはなし | Hyperliquid oracleをindexとは表示しない |
| Bid / Ask | 現在受信した買い気配 / 売り気配 | 実際の注文成立を保証しない |
| Funding raw | Venueが配信した資金調達率の原値 | 現画面は周期を表示しないため、Venue横断比較に使わない |
| Funding / h | 周期を確認できた場合だけの1時間換算 | 周期不明時はnull。現行Asterはnull |
| OI raw | Venue由来の建玉原値と単位 | 異なる単位をそのまま比較しない |
| OI notional | base数量と有効なmarkを確認できた場合だけの想定元本 | 算出不能時はnull |
| Volume 24h | Venue由来の24時間出来高 | Venue間の時間窓差を差分率にしない |
| observedAt | このアプリが受信した時刻 | source時刻の代わりではない |
| Source | catalog source、endpoint、payload hashなどの由来 | 値だけでなく由来も確認する |

`sourceAt`が配信されないsourceでは`—`のままです。`observedAt`をsource時刻へ置き換えません。
missing、stale、単位不明を0へ変換しません。

画面の`—`は0ではなく、欠測または適用不能です。「正常」でも、Venueがそのfieldを配信しない場合は
optionalな列が`—`になります。現行adapterではAsterのOI、Hyperliquid Coreのall-market Bid / Askは
明示的にnullです。Hyperliquid Coreのreference price種別はoracleです。

Hyperliquid Coreの標準市場にあるHYPE / PURRは、quote、settle、collateralをUSDCとして扱います。
symbolに`:`を含むHIP-3市場は対象外です。

### 7. 参考mark中央値

参考mark中央値は、次の条件をすべて満たしたmarkだけで計算します。

- 同じ安全なgroupに属する。
- 同じcollector cycleである。
- 2 Venue以上が参加する。
- Qualityが正常で、有限のmarkが存在する。
- 各値のageが120秒以内である。
- Venue間の時刻差が30秒以内である。
- quote、settle、collateralがすべてUSD-likeである。

この計算だけ、`USD / USDC / USDT`のparityを仮定します。Venue別の値を変換、合算、rankingする
ための仮定ではありません。参加Venue数と算出不能理由を必ず一緒に確認してください。

### 8. 銘柄を選んで詳細を見る

Universeの行を選ぶと、Webは500msのdebounce後に選択commandを送ります。その後、market serviceの
選択処理とartifact更新を待ってdetailが表示されます。安全にgroup化できた銘柄では、選択監視を
5分ごとに更新し、15分TTLの1 groupだけを購読します。

詳細は次の順で確認します。

1. primary instrument、quote、settle、collateral、鮮度
2. 5m / 15m / 1h / 4h / 24h Chart
3. Venue別の板。最大20 bids / 20 asks
4. group横断の直近100 trades
5. $100 / $500 / $1,000の板上概算
6. Past Note

Chartは選択した`venueInstrumentId`だけを表示し、各timeframeは最大500 barsです。artifactは
`confirmed`と`derived_final`を保持しますが、現画面はfinalityを識別表示しません。欠落bar、
instrument version境界、不完全barは推測で埋めません。

板上概算は、現在受信した板を指定notionalまで歩いた平均価格とtop-of-bookからのbpsです。板が10秒超、
板不足、非USD-like、単位不明の場合は数値を出さず、理由を表示します。

単独instrumentでは、安全なgroupを前提とするChart、板、約定購読を要求しません。
板は各Venueの詳細、約定はgroup横断の「直近約定」を開いて確認します。MobileではUniverse表の
OI notionalと24時間出来高を隠すため、行を選びdetailで確認してください。ThemeとFontの選択は
同じbrowserに保存されます。

### 9. Qualityを読む

| 画面表示 | 意味 | 利用者の扱い |
| --- | --- | --- |
| 正常 | 現在の契約と鮮度条件を満たす | 観測時刻と由来を確認して参照する |
| 一部取得 | 一部の値またはVenueだけ取得できた | 取得できた範囲と品質理由だけを使う |
| 期限切れ | 鮮度条件を超えている | 現在値として扱わない |
| 取得不能 | 取得または安全な算出ができない | 0や前回値で補わない |

一部Venueが失敗しても、取得できたVenueは残ります。空欄、null、理由表示は、データが0という意味では
ありません。

### 10. Past Note

Past Noteは、あとで再確認するためのローカルannotationです。trade journalではありません。

- 保存先は`venueInstrumentId`単位です。
- reasonまたは本文が必要です。
- reasonが空の場合は`過去注記`として保存します。
- 同じreasonで再保存すると、そのinstrumentの同じreasonの既存noteを新しいnoteで置き換えます。
- 別instrumentのnoteへ自動移行しません。
- 60日を過ぎたnoteは再表示しません。

「この銘柄を買うべき」のような推奨をアプリが生成する機能ではありません。利用者自身が観測した文脈を
残すために使います。

### 11. 実務での基本手順

1. 全体、Catalog、L1、品質理由、観測時刻を確認する。
2. 検索とfilterで調べたいbaseまたはVenueを絞る。
3. CoverageとQualityを分けて確認する。
4. group化済みならVenue別の値と参考mark中央値を確認する。
5. 1行を選び、Chart、板、約定、板上概算の品質理由を確認する。
6. 再確認する理由がある場合だけPast Noteへ残す。
7. 売買判断は、このアプリが扱わないfee、注文条件、position、riskも含めて利用者自身で行う。

### 12. 日常の状態確認

```bash
journalctl --user -u prep-watchdeck-market.service --since '-15 min' --no-pager
curl --fail http://127.0.0.1:5173/api/health
bash scripts/update-live.sh
```

`curl`成功と市場データの正常は別です。`update-live.sh`、画面、service logを合わせて確認します。
`update-live.sh`は名前に反して収集を実行せず、現在の4 artifactを読み取る状態確認commandです。

停止、maintenance、backup、restoreはデータやservice状態を変更します。日常の閲覧手順と混ぜず、
[現行運用](operations.md)の対象確認と停止条件に従ってください。restoreは破壊的操作です。

### 13. 完全停止

browserを閉じてもsystemd unitは動き続けます。完全停止では、最初に毎時timerを止め、実行中の
maintenanceがないことを確認します。

```bash
systemctl --user stop prep-watchdeck-market-maintenance.timer
systemctl --user show prep-watchdeck-market-maintenance.service \
  -p ActiveState -p SubState
```

`ActiveState=active`ならここで停止し、maintenanceの終了を待ちます。`ActiveState=inactive`を確認した
後だけ、次を実行します。

```bash
systemctl --user stop prep-watchdeck-web.service
systemctl --user stop prep-watchdeck-market.service
systemctl --user stop prep-watchdeck-market-db.service
```

### 14. 困ったとき

| 症状 | 最初に確認すること | 判断 |
| --- | --- | --- |
| `unit is not installed` | installerの`--dry-run`、`--apply`、`--check` | 起動前にunitをinstallする |
| credential fileを拒否する | owner、mode 0600、専用URL | 実secretを出力せず設定を直す |
| 画面が開かない | `systemctl --user show`、`/api/health`、Web unit | Web processとmarket dataを分けて調べる |
| 画面は開くが古い | Catalog / L1 age、品質理由、service log | 期限切れ値を現在値にしない |
| あるVenueだけ空 | そのVenueのquality、error、observed time | 他Venueの値まで無効とは限らない |
| 参考中央値がない | 参加Venue数、120秒、30秒、USD-like条件 | 条件を緩めて推測計算しない |
| Funding / hがない | funding interval | 周期不明ならrawだけを読む |
| OI notionalがない | OI raw unitとmark | base数量を確認できない値を換算しない |
| 選択detailが出ない | group状態、選択品質、artifact待ち理由 | 単独instrumentを推測でgroup化しない |
| 板上概算がない | depth age、板不足、通貨、単位 | nullを流動性0とは扱わない |
| DB targetを拒否する | user / database、`127.0.0.1:55432` | production overrideで回避しない |
| `start-local.sh`でデータが出ない | 既存artifactと表示されたport | Webだけを起動し、collectorは起動しない |
| systemd Webが起動を繰り返す | port 5173の使用状況 | systemd Webは別portへ自動退避しない |

次の場合は表示を判断に使うのをやめます。[現行運用](operations.md)で稼働版とrollback候補のunitを
確認し、停止対象を特定してから操作します。

- CatalogまたはL1が2周期続けて鮮度条件を外れる。
- serviceがrestartを繰り返す。
- 継続429、cycle overlap、backlog、DB lock、connection leakが発生する。
- Parquetのrow count、key、timestamp、digest、file SHA-256照合に失敗する。
- JustPassなど他projectのDB/stateへ接触した疑いがある。
- 値の意味、単位、finality、identityを推測しないと続けられない。

詳しい状態確認、完全停止、maintenance、backup、restore、rollbackは[現行運用](operations.md)、
検証の合否条件は[現行検証](validation.md)を参照します。既定state rootは
`~/.local/share/prep-watchdeck-market`です。

## AI向け最小参照（Codex CLI >= 0.147.0）

この章のversion条件はAI作業環境の条件であり、`prep-watchdeck` runtimeのversionではありません。

OpenAI Docsの[Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md/)に
従い、Codexは作業前に適用対象の`AGENTS.md`を読みます。globalからRepo root、作業directoryへ
instruction chainを構成し、作業地点に近い指示を優先します。

### 指示の優先順位

上位指示を守り、globalから作業directoryまでの`AGENTS.md` / `AGENTS.override.md`を読み、近い指示を
優先します。外部変更、禁止事項、検証、完了判定はroot [AGENTS.md](../../AGENTS.md)を正本とします。

### 事実の参照順

1. 現行code、schema、migration、tests、CLI help
2. 利用者の操作と解釈はこのマニュアル
3. UI挙動は[ui-workflow.md](ui-workflow.md)
4. field、単位、schema、APIは[data-contracts.md](data-contracts.md)
5. processとstorageは[architecture.md](architecture.md)
6. state変更とrollbackは[operations.md](operations.md)
7. gateと合否は[validation.md](validation.md)
8. visual contractは[DESIGN.md](../../DESIGN.md)

`docs/plans/active/`をdirectory名だけで現行仕様とみなしません。[docs index](../README.md)から
リンクされたplanを候補とし、codeと現在差分へ照合します。

作業はread-only確認から始め、対象codeと正本を照合し、値、単位、finality、identityを推測しません。
変更は最小・可逆にし、変更箇所に近い検証を行います。test green、HTTP 200、単一artifact、commit、
pushを、data quality、merge、live cutoverの証拠として扱いません。
