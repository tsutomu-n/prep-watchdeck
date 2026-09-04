# prep-watchdeck ユーザーマニュアル

- 作成: `2026-08-15T11:04:37+09:00`
- 更新: `2026-09-04T21:23:29+09:00`
- 検証: `2026-09-04T21:23:29+09:00`
- 状態: `現行`

---

`prep-watchdeck`は、3つの取引会場が公開している暗号資産の無期限先物データを、
1台のPC上でまとめて確認する監視アプリです。売買を行うアプリではありません。

初めて使う人は、まず「[1. これは何か](#1-これは何か)」から
「[4. 使い方](#4-使い方)」まで読んでください。すでに起動できる人は、
「[4.4 画面の基本操作](#44-画面の基本操作)」から始められます。

| やりたいこと | 読む場所 |
| --- | --- |
| 初めて準備・起動する | 「4.1 必要なもの」から「4.3 systemd unitをinstallして起動する」 |
| 日常的に市場を見る | 「4.4 画面の基本操作」から「4.8 日常の状態確認」 |
| 表示値の意味を確認する | 「4.5 表示値の読み方」「4.6 参考Mark中央値の読み方」 |
| 完全に停止する | 「4.9 完全に停止する」 |
| 問題を切り分ける | 「7. 困ったときの確認事項」 |

この文書の「現行」は、このRepository（codeと文書を一緒に管理する場所）に実装されている仕様を
指します。実際に動いている版、現在取得できる銘柄数、各Venueの稼働状況は、画面と
「[4.8 日常の状態確認](#48-日常の状態確認)」でその都度確認してください。Repository上の仕様と
現在の稼働状態は同じものではありません。

## 1. これは何か

### 1.1 目的

`prep-watchdeck`は、運用資金5,000 USD以下の裁量Perp traderが、Bitget、Hyperliquid Core、Asterの
public crypto linear perpetualを同じ画面で確認するためのlocal-firstな
「Perp Universe Explorer」です。

- **裁量**: プログラムではなく、人が最終判断する運用方法です。
- **Perp（perpetual futures）**: 満期日のない先物契約です。
- **linear perpetual**: 対象資産そのものではなく、Quote / Settle assetで価格と損益を表すPerpです。
- **Venue**: 取引所または取引会場です。
- **Universe Explorer**: 対象となる全銘柄を一覧にし、検索・絞り込み・詳細確認を行う画面です。
- **local-first**: 収集結果、画面、設定を利用者のPC上で管理する方式です。市場データの取得には
  各Venueのpublic APIへ接続できるnetworkが必要なので、offline専用という意味ではありません。
- **public API**: 秘密API keyを使わずに公開データを取得できる接続口です。

このアプリの役割は、Venueごとに意味や単位が異なる公開データを、由来と品質を残したまま
見比べやすくすることです。価格の予測や売買判断は行いません。

### 1.2 最初に知っておく用語

| 用語 | このマニュアルでの意味 |
| --- | --- |
| Instrument | 1つのVenueにある1つの契約 |
| `venueInstrumentId` | Instrumentを一意に表すID。形式は`<venue>:<sourceSymbol>` |
| Source symbol | VenueがそのInstrumentへ付けている銘柄名 |
| Base | 契約の対象資産。`BTCUSDT`ならBTC |
| Quote / Settle / Collateral | 価格表示通貨 / 決済通貨 / 証拠金通貨 |
| Group | 同じ対象資産の契約だと安全に確認できたInstrumentの集まり |
| Mark | VenueがMarkとして配信する価格。実際の約定価格とは異なる |
| Reference | Venueが種別をindexまたはoracleとして配信する参照価格。該当値なしの場合もある |
| Bid / Ask | 現在受信した最良買い気配 / 最良売り気配 |
| Funding | Long（買い持ち）側とShort（売り持ち）側の間で行う資金調達の率 |
| OI（Open Interest） | まだ決済されていない建玉 |
| Notional | 数量に価格を掛けた想定元本 |
| bps（basis points） | 価格差の単位。1 bpsは0.01% |
| Parity | 異なる通貨を便宜上、同じ価値とみなす仮定 |
| Quality | データの取得状態と鮮度 |
| Catalog | Venueが扱うInstrumentと契約仕様の一覧 |
| L1 | 価格、最良気配、Funding、OI、出来高などの直近snapshot |
| Snapshot | ある時点で取得したデータ一式 |
| Chart / bar | 時間ごとの値動きを表すChart / その1区間分の記録 |
| Artifact | Market CoreがWeb表示用に発行するJSON file |
| TTL（Time To Live） | 選択監視を有効とみなす期限 |
| `—` / `null` | 0ではなく、欠測または適用不能 |

## 2. 何ができるか

### 2.1 3 Venueの全体を確認する

Bitget、Hyperliquid Core、Asterの対象Instrumentを一覧表示できます。各行では主に次を確認できます。

- Mark、Bid / Ask
- 1時間換算できる場合のFunding
- OIの想定元本
- Venue由来の24時間出来高
- データのQualityと経過秒数
- 同じGroupに属するVenue数

検索、Venue、Coverage、Qualityの4条件で絞り込めます。Coverageは「何Venueで同じGroupを
構成できたか」、Qualityは「データを正常に取得できているか」です。この2つは別の意味です。

### 2.2 Venue別の値を詳しく読む

1行を選ぶと、選択したInstrumentについて次を確認できます。

- Mark、Reference、Bid / Ask
- Fundingの原値と1時間換算値
- OIの原値、単位、想定元本
- 24時間出来高と単位
- Quote、Settle、Collateral
- 受信時刻、source時刻、取得元endpoint（APIの取得先）、payload hash（応答内容を識別する要約値）
- 値を利用できない理由

### 2.3 安全に対応付けられたGroupを比較する

同じBaseのInstrumentを、条件を満たす場合だけGroup化します。Group化済みの銘柄では次を表示できます。

- 2 Venue以上のMarkから求めた参考中央値
- `5m / 15m / 1h / 4h / 24h`のChart。各時間軸は最大500 bars
- Venueごとの板。最大20 bids / 20 asks
- Group横断の直近100 trades
- `$100 / $500 / $1,000`を板上で処理すると仮定した平均価格と、最良気配からの差

この板上概算には手数料を含みません。将来のprice impact（注文による価格への影響）を予測しません。
表示価格で注文できることも保証しません。

### 2.4 観測メモを残す

Past Noteは、選択した`venueInstrumentId`に紐づくローカルメモです。理由または短い本文を入力すると、
同じPCのstate directory（実行中のデータ保存先）へ保存されます。保存期間は60日です。
取引履歴や売買日誌ではありません。

## 3. 全体の仕組み

### 3.1 データが画面に届くまで

```text
Bitget / Hyperliquid Core / Aster のpublic API
                         │
                         ▼
        Market Core（収集・検証・Group化）
                         │
                         ▼
               専用Postgres（直近データ）
                    │              │
                    │              └─ maintenance ─→ confirmed Parquet
                    ▼
             4つのJSON artifact
                    │
                    ▼
            localhostのWeb画面
```

- **Market Core**は、公開市場データを収集する常駐serviceです。
- **Postgres（PostgreSQL）**は、直近データを保存する専用databaseです。
- **Parquet**は、履歴を列形式で保存するfile formatです。Row数、key、timestamp、
  digest（内容の要約値）、fileのSHA-256をreadbackで照合し、manifest（archiveの確認記録）を
  confirmしたParquetが期限後履歴の正本です。
- **JSON artifact**は、Webが読むために再生成できる表示用fileです。
- **localhost**は同じPC自身を表す接続先です。既定URLは`http://127.0.0.1:5173/`です。

WebはPostgresへ直接接続しません。次の4 artifactをschema（データ構造の規則）で検証して読みます。

| Artifact | 主な内容 |
| --- | --- |
| `universe-snapshot.json` | Instrument一覧、Venue別の値、Group、Quality |
| `market-chart.json` | 選択InstrumentのChart |
| `selected-market.json` | 選択Groupの板、約定、板上概算 |
| `service-state.json` | Catalog、L1、artifact発行の状態 |

既定のstate root（実行中のデータをまとめて保存するdirectory）は
`~/.local/share/prep-watchdeck-market`です。主な保存先は次のとおりです。

```text
~/.local/share/prep-watchdeck-market/
  postgres/
  archive/
  artifacts/
  control/selection.json
  past-notes/<venueInstrumentId>.json
```

### 3.2 操作を入力すると何が起きるか

| 利用者の入力 | 起きること | 得られる結果 |
| --- | --- | --- |
| 検索文字や絞り込み条件を変更する | Browser上で現在のUniverseを絞り込む | 条件に合う行だけが残る。市場収集条件は変わらない |
| Universeの行を選ぶ | 500ms後にlocalhostの選択commandを書き、Market Coreが1 Groupの詳細監視を切り替える | Chart、板、約定、板上概算が更新される |
| 同じ行を開いたままにする | Browserが5分ごとに選択監視を更新する | 15分TTLの選択監視が継続する |
| Past Noteを保存する | 選択中の`venueInstrumentId`単位でローカルfileへ保存する | そのInstrumentのメモ一覧に表示される |
| `bash scripts/update-live.sh`を実行する | 現在の4 artifactを読み取る。新しい収集は行わない | artifactごとのstatusと`generatedAt`がterminalへ出る |

単独または未GroupのInstrumentを選んでも、安全なGroupを前提とするChart、板、約定の購読は
開始しません。似た名前の銘柄を推測で同一視しないためです。

### 3.3 更新周期とQuality

- Catalog（取扱Instrument一覧）は15分周期で更新します。30分を超えると期限切れです。
- 全市場L1は60秒の固定周期で更新します。120秒を超えると期限切れです。
- Webは表示中かつtabが見えている間、5秒ごとにartifactを確認します。
- 選択中の詳細artifactは5秒周期で更新します。

周期は更新成功を保証しません。画面では次のQualityと経過秒数を優先してください。

| 画面表示 | 意味 | 利用者の扱い |
| --- | --- | --- |
| 正常 | 現在の契約と鮮度条件を満たす | 観測時刻と由来も確認して参照する |
| 一部取得 | 一部の値またはVenueだけ取得できた | 取得できた範囲と理由だけを使う |
| 期限切れ | 鮮度条件を超えた | 現在値として扱わない |
| 取得不能 | 取得または安全な算出ができない | 0や前回値で補わない |

取得失敗時には、最後に検証できたsnapshotを残して「更新停止」と表示することがあります。
その表示中は、画面上の値を現在値として扱わないでください。

## 4. 使い方

以下のcommandは、特記がない限りRepositoryのroot directoryで実行します。
このRepositoryを取得するURLや配布手順は現行資料で確認できません。ここからは、Linux PC上に
Repositoryのcheckout（作業用コピー）があり、必要なtoolをinstallできる状態を前提にします。

### 4.1 必要なもの

- Python 3.13と`uv`（Pythonのpackage・実行環境管理tool）
- Bun（Web側で使うJavaScript runtimeとpackage管理tool）
- Docker Compose（専用Postgresをcontainerで動かすtool）
- Linuxのsystemd user manager（利用者単位でbackground serviceを管理する仕組み）
- 3 Venueのpublic APIへ接続できるnetwork

依存packageとWeb用の型を準備します。

```bash
uv sync --all-packages
cd apps/web
bun install
bun run generate:types
cd ../..
```

### 4.2 専用Postgresを設定する

このアプリ専用のstate directoryとcredential fileを作ります。

```bash
install -d -m 0700 "$HOME/.config/prep-watchdeck-market"
install -d -m 0700 "$HOME/.local/share/prep-watchdeck-market/postgres"
touch "$HOME/.config/prep-watchdeck-market/postgres.env"
chmod 0600 "$HOME/.config/prep-watchdeck-market/postgres.env"
```

`~/.config/prep-watchdeck-market/postgres.env`へ次を設定します。
`POSTGRES_PASSWORD`にはローカル専用の十分に長い値を使います。URL内のpasswordはpercent-encode
してください。percent-encodeとは、URLで特別な意味を持つ文字を `%` から始まる表記へ変換することです。

```text
POSTGRES_DB=prep_watchdeck_market
POSTGRES_USER=prep_watchdeck_market
POSTGRES_PASSWORD=<local-secret>
PREP_WATCHDECK_MARKET_DATABASE_URL=postgresql://prep_watchdeck_market:<url-encoded-secret>@127.0.0.1:55432/prep_watchdeck_market
```

このfileをcommitしたり、実際のsecretをissue、文書、共有logへ貼ったりしないでください。
専用Postgresは`127.0.0.1:55432`を使います。他projectのPostgres、port 5432、container、volume、
database、roleを再利用しません。

### 4.3 systemd unitをinstallして起動する

systemd unitは、各serviceをどのdirectoryとcommandで動かすかを定義する設定です。
最初に、実際に起動するcheckoutから差分を確認します。

Installerが既定で確認する実行fileは`/usr/bin/systemctl`、`$HOME/.local/bin/uv`、
`$HOME/.local/share/bun/bin/bun`、`/usr/bin/docker`です。実際のinstall先が異なる場合は、
`bash scripts/ops/install-user-services.sh --help`で対応するpath optionを確認し、実在する絶対pathを
明示します。

```bash
bash scripts/ops/install-user-services.sh --repo-root "$PWD" --dry-run
```

表示されたpathと差分が正しい場合だけ、installして一致を確認します。

```bash
bash scripts/ops/install-user-services.sh --repo-root "$PWD" --apply
bash scripts/ops/install-user-services.sh --repo-root "$PWD" --check
```

`--apply`は既存unitをtimestamp付きでbackupし、unitを有効化しますが、この時点ではserviceを
startまたはrestartしません。日常の4 unitを起動します。

```bash
bash scripts/start-all.sh
```

このcommandは専用Postgres、Market Core、Web、毎時maintenance timerを依存順に起動します。
Market Coreの起動前に未適用のdatabase migration（database構造の更新）も適用します。
成功時はURLと、各unitの`ActiveState`、`SubState`、process ID、restart回数が表示されます。

起動直後は、画面が開くことだけで正常と判断しません。「全体」「Catalog」「L1」の状態と最終検証時刻が
更新されるまで確認します。正常化までの所要時間は、このRepositoryの資料から固定値として確認できません。

### 4.4 画面の基本操作

1. Browserで`http://127.0.0.1:5173/`を開きます。
2. 画面上部の「全体」「Catalog」「L1」「最終検証」を確認します。
3. 「更新停止」「運用上の注意」「品質理由」がある場合は、値を見る前に内容を確認します。
4. 検索、Venue、Coverage、品質でUniverseを絞ります。
5. 行のMark、Bid / Ask、Funding / h、OI notional、24h volume、Quality、ageを確認します。
6. 1行を選び、右側の詳細を確認します。
7. Group化済みなら、参考Mark中央値、Chart、Venue別の板、直近約定、板上概算を確認します。
8. 後で再確認したい事実がある場合だけPast Noteを保存します。

Mobile表示ではUniverse表のOI notionalと24時間出来高が隠れます。行を選び、詳細で確認してください。
ThemeとFontの選択は同じBrowserに保存されます。

初回表示では、現在有効な選択があればその行を選びます。有効な選択がなければ、現在の既定順で
先頭にある取扱中の行を選びます。既定順はBase、Venue、source symbolの順です。

| 入力 | 対象 |
| --- | --- |
| 検索 | Base、source symbol、`venueInstrumentId`、Quote、Settleに含まれる文字列 |
| Venue | Aster、Bitget、Hyperliquid、またはすべて |
| Coverage | 2 Venue以上、単独 / 未Group、またはすべて |
| 品質 | 正常、一部取得、期限切れ、取得不能、またはすべて |

Chartは選択した`venueInstrumentId`だけを描画します。時間軸を変えても選択中のInstrumentは変わりません。

### 4.5 表示値の読み方

| 表示 | 意味 | 注意点 |
| --- | --- | --- |
| Mark | Venueが配信するMark price | 注文できる価格ではない |
| Reference | index、oracle、またはなし | Hyperliquid Coreはoracle。indexとは表示しない |
| Bid / Ask | 最良買い気配 / 最良売り気配 | 実際の注文成立を保証しない |
| Funding raw | Venueが配信した資金調達率の原値 | 現画面は周期を表示しないため、そのままVenue横断比較しない |
| Funding / h | 周期を確認できた場合だけの1時間換算 | 周期不明時は`—`。現行Asterは`—` |
| OI raw | Venue由来の建玉原値と単位 | 単位が異なる値をそのまま比較しない |
| OI notional | Base数量と有効なMarkを確認できた場合の想定元本 | 算出できなければ`—` |
| 24h volume | Venue由来の24時間出来高 | Venue間の時間窓差を差分率にしない |
| `observedAt` | このアプリが値を受信した時刻 | Venue側の発生時刻とは限らない |
| `sourceAt` | Venueが配信したsource時刻 | 配信されない場合は`—` |

`—`は0ではありません。「正常」でも、Venueが任意項目を配信しなければ`—`になります。
現行の取得処理では、AsterのOIとHyperliquid Coreの全市場Bid / Askは明示的に`null`です。

### 4.6 参考Mark中央値の読み方

参考Mark中央値は、次の条件をすべて満たす場合だけ計算します。

- 同じ安全なGroupに属する。
- 同じcollector cycle（1回の収集単位）である。
- 2 Venue以上が参加する。
- Qualityが正常で、有限のMarkがある。
- 各値のageが120秒以内である。
- Venue間の観測時刻差が30秒以内である。
- Quote、Settle、CollateralがすべてUSD-likeである。

**USD-like**は、このアプリでは`USD / USDC / USDT`を指します。この3通貨を同価値とみなすParity仮定は、
参考Mark中央値の計算だけに使います。Venue別の値の変換、合算、rankingには使いません。

参考Mark中央値は売買可能価格ではありません。値だけでなく、参加Venue数と算出不能理由も確認します。

### 4.7 Past Noteを保存する

1. UniverseでInstrumentを選びます。
2. 画面下部のPast Noteで「理由」または「短い観測メモ」を入力します。
3. 「注記を保存」を押します。
4. 保存メッセージと、メモ一覧に追加された内容を確認します。

保存規則は次のとおりです。

- 理由と本文の少なくとも一方が必要です。
- 理由が空なら`過去注記`として保存します。
- 同じInstrumentで同じ理由を再保存すると、古いメモを新しいメモで置き換えます。
- 別Instrumentへ自動移行しません。
- 60日を過ぎたメモは、次に読み取るときに除外します。
- 選択commandとPast Noteの書込みはlocalhost requestだけに許可されます。

### 4.8 日常の状態確認

```bash
systemctl --user show \
  prep-watchdeck-market-db.service \
  prep-watchdeck-market.service \
  prep-watchdeck-web.service \
  prep-watchdeck-market-maintenance.timer \
  -p Id -p ActiveState -p SubState -p MainPID -p NRestarts

journalctl --user -u prep-watchdeck-market.service --since '-15 min' --no-pager
curl --fail http://127.0.0.1:5173/api/health
bash scripts/update-live.sh
```

`/api/health`がHTTP 200を返すことは、Web processが動いている証拠にすぎません。市場データが正常かは、
画面のCatalog / L1、Quality、`update-live.sh`、service logを合わせて判断します。

正常なWeb processでは`/api/health`が`{"ok":true,"service":"prep-watchdeck-web"}`を返します。
`update-live.sh`は4 artifactそれぞれのstatusと生成時刻を表示します。どちらも新しい市場データを
収集するcommandではありません。

Database接続とmigration状態を直接確認する場合は、専用database URLを設定して実行します。

```bash
cd apps/market-core
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' uv run watchdeck-market status
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' uv run watchdeck-market health
```

### 4.9 完全に停止する

Browserを閉じてもserviceは動き続けます。完全停止では、最初に新しいmaintenanceの開始を止めます。

```bash
systemctl --user stop prep-watchdeck-market-maintenance.timer
systemctl --user show prep-watchdeck-market-maintenance.service \
  -p ActiveState -p SubState
```

`ActiveState=active`なら、ここで止まり、maintenanceが終了するまで待ちます。
`ActiveState=inactive`を確認した後だけ、次を実行します。

```bash
systemctl --user stop prep-watchdeck-web.service
systemctl --user stop prep-watchdeck-market.service
systemctl --user stop prep-watchdeck-market-db.service
```

## 5. 具体例: BTCをVenue横断で確認する

この例は操作方法を示すものです。BTCが現在のUniverseに存在することや、各Venueのデータが現在正常で
あることは保証しません。

1. 画面上部で「全体」「Catalog」「L1」が「正常」か確認します。
2. 検索欄へ`BTC`と入力します。
3. 複数Venueの比較だけを見たい場合は、Coverageを「2 Venue以上」にします。
4. 正常な行だけを見る場合は、品質を「正常」にします。
5. 表示された各行でVenue、source symbol、Mark、Bid / Ask、Funding / h、OI、ageを見比べます。
6. 1行を選びます。500ms後に「詳細データを要求しました」と表示されます。
7. 「参考Mark中央値」で値、参加Venue数、算出不能理由を確認します。
8. Chartの時間軸を選び、Venue別の板、直近約定、`$100 / $500 / $1,000`の板上概算を確認します。
9. 板が10秒以上古い、指定額に足りない、USD-likeでない、数量単位が不明などの理由が出た場合は、
   欠けた数値を自分で0や前回値に置き換えません。
10. 後で流動性を再確認したい場合は、Past Noteの理由へ`流動性を再確認`、本文へ観測した事実を入力し、
    保存します。

検索入力から得られるのは該当Instrumentの一覧です。行選択から得られるのは監視中の詳細データです。
どちらの操作からも、売買推奨、予測、注文は生成されません。

## 6. 注意点・制約

### 6.1 売買機能ではない

次の機能はありません。

- 売買推奨、将来価格の予測、裁定機会の断定、価格差ranking
- 自動売買、注文、残高、positionの確認
- Private APIや秘密API keyを使う処理
- Feeを含む執行見積りや、将来のprice impact予測

### 6.2 対象市場は限定される

対象はBitget、Hyperliquid Core、Asterのpublic crypto linear perpetualです。次は対象外です。

- RWA、HIP-3、synthetic、RFQ市場
- Alias変換（別名の銘柄を同一視する処理）や`1000X`などのmultiplier contractを使う比較
- 全市場の板と全tradeの長期保存
- HFT（高頻度取引）や深いhistorical backfill（過去データの遡及取得）

Asterは公開Catalogの`underlyingType`と`underlyingSubType`を使い、既知のcrypto tagまたは空tagだけを
採用します。株式、ETF、商品、pre-launch、未知tag、tag欠落は対象外として除外し、Symbol名から
cryptoかどうかを推測しません。HIP-3、synthetic、RFQも対象外の市場区分として扱います。

Group化は、取扱中、crypto、linear perpetual、Base完全一致、契約1単位に対応するBase数量、
multiplier 1、Venue内候補1件をすべて確認できた場合だけ行います。単独または未GroupはQuality不良
という意味ではありません。

Hyperliquid Coreの標準市場にあるHYPE / PURRはQuote、Settle、CollateralをUSDCとして扱います。
Symbolに`:`を含むHIP-3市場は対象外です。

### 6.3 数値を推測で補わない

- Markと参考Mark中央値は約定可能価格ではありません。
- `null`、`—`、stale、単位不明を0に変換しません。
- `sourceAt`がない場合に`observedAt`をsource時刻として扱いません。
- 24時間出来高はVenueごとに時間窓が異なり得るため、差分率を作りません。
- Chartの欠落bar、Instrument version境界、不完全barは補間しません。
- Chart artifactは`confirmed`と`derived_final`を保持しますが、現画面では両者を識別表示しません。

### 6.4 運用上の安全境界

- 現役stateへ複数のMarket Core writerを接続しません。
- `scripts/start-local.sh`はWebだけをforegroundで起動する開発用commandです。Collectorは起動しません。
- `update-live.sh`も収集を行いません。
- systemd unitにはinstall時のcheckout pathが入ります。Checkoutを移動した場合は、起動前に
  installerの`--dry-run`と`--check`でpathを確認します。
- Maintenance、backup、restoreは日常の閲覧とは別の運用です。Restoreは破壊的操作です。
  [現行運用](operations.md)の対象確認と停止条件に従ってください。
- 旧state、rollback release、unit backupを整理目的で削除しません。

### 6.5 現行資料だけでは確定できないこと

次は環境や実行時点に依存し、現行のRepository資料だけでは確定できません。

- Repositoryの配布URLと取得時の認証方法
- Python、`uv`、Bun、Docker、systemdをOSへinstallする具体的な手順
- Linux以外のOSでの常用運用手順
- 対応Browserの製品名とversion範囲
- 起動後、全データが正常になるまでの所要時間
- 現在稼働中のsource version、現在のInstrument数、各Venueの現在の接続可否

これらを推測で補わず、利用するPCの管理者情報、実際の画面、state確認commandで確認してください。

## 7. 困ったときの確認事項

最初に「Webが動いているか」と「市場データが正常か」を分けて確認します。

| 症状 | 最初に確認すること | 判断・対処 |
| --- | --- | --- |
| `unit is not installed` | Installerの`--dry-run`、`--apply`、`--check` | 起動前に正しいcheckoutからunitをinstallする |
| `required binary is not executable` | `systemctl`、`uv`、Bun、Dockerの実際のpath | Installerへ対応する絶対path optionを渡す |
| Credential fileを拒否する | Owner、mode `0600`、専用URL | Secretを出力せず設定を直す |
| 画面が開かない | `systemctl --user show`、`/api/health`、Web unit | Web processと市場データを分けて調べる |
| 画面は開くが古い | Catalog / L1 age、Quality、service log | 期限切れ値を現在値にしない |
| 「更新停止」が出る | 最終検証時刻、`update-live.sh`、service log | 表示中の全値を現在値として扱わない |
| あるVenueだけ空 | そのVenueのQuality、error、observed time | 他Venueまで自動的に無効とは限らない |
| 参考中央値がない | 参加Venue数、120秒、30秒、USD-like条件 | 条件を緩めて推測計算しない |
| Funding / hがない | Funding interval | 周期不明ならrawだけを読む |
| OI notionalがない | OI rawの単位とMark | Base数量を確認できない値を換算しない |
| 選択詳細が出ない | Group状態、選択Quality、artifact待ち理由 | 単独Instrumentを推測でGroup化しない |
| 「選択監視を更新できません」と出る | localhost接続、選択中の行、service log | 市場Qualityではなく選択操作の失敗として調べる |
| 板上概算がない | Depth age、板不足、通貨、数量単位 | `null`を流動性0と扱わない |
| Past Noteを保存できない | localhost接続、理由または本文、`venueInstrumentId` | 売買データの異常とは分けて調べる |
| DB targetを拒否する | User / database、`127.0.0.1:55432` | Production overrideで回避しない |
| `start-local.sh`でデータが出ない | 既存artifactと表示されたport | このcommandはWebだけを起動する |
| systemd Webが再起動を繰り返す | Port 5173の使用状況 | systemd Webは別portへ自動退避しない |

次の場合は画面の値を判断材料に使うのをやめ、対象serviceを特定してから対処します。

- CatalogまたはL1が2周期続けて鮮度条件を外れる。
- Serviceがrestartを繰り返す。
- HTTP 429（取得要求過多）が継続する、収集cycleが重なる、処理待ちが蓄積する、DB lockまたは
  connection leak（接続の未解放）がある。
- Parquetのrow count、key、timestamp、digest、file SHA-256照合に失敗する。
- 他projectのDBやstateへ接触した疑いがある。
- 値の意味、単位、finality（値の確定方法）、identity（どの契約か）を推測しなければ続けられない。

詳しいservice操作、maintenance、backup、restore、rollbackは[現行運用](operations.md)、
fieldとAPIの契約は[現行データ契約](data-contracts.md)、検証の合否条件は[現行検証](validation.md)を
参照してください。
