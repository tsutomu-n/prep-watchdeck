# Watchdeck v1 P0 スコープと完成条件

- 作成: `2026-08-18T22:00:00+09:00`
- 更新: `2026-08-18T22:00:00+09:00`
- 検証: `2026-08-18T22:00:00+09:00`
- 状態: `現行`

---

## 結論

Watchdeck v1は、Bitget、Hyperliquid Core、Asterのpublic crypto linear perpetualを継続観測し、
値の意味、単位、時刻、取得元、品質を失わずに保存・表示するlocal-firstの市場監視アプリである。

P0の完成は、Repository内の実装・契約・検証が完成した状態と、実hostへinstall・migration・cutoverして
日常運用を確認した状態を分けて扱う。前者だけで後者を完了扱いしない。

## 責務

Watchdeckが所有する責務:

- 3 Venueのinstrument catalogとcapability
- 60秒L1 market state
- 確定または導出確定した1分足
- 精算済みFunding event
- 選択中1 groupのdepthとtrade
- current Postgres、confirmed Parquet、Web read model
- data quality、freshness、coverage、source provenanceの表示
- archive、bounded retention、backup、restoreの安全な運用入口

Watchdeckが所有しない責務:

- 売買推奨、BUY / SELL、価格予測、alpha score
- backtest、strategy adoption、TimesFMその他のforecast model
- 注文、残高、position、wallet、Private API
- Copy Tradingの委任管理、Grid / Botの自動停止・制御
- 全市場のfull depth・全tradeの長期保存
- 深いhistorical backfill

研究、予測、戦略検証はMarketLens Strikeへ分離する。

## Data Plane

### 長期正本

| Dataset | 内容 | 正本 |
| --- | --- | --- |
| `market_state_1m` | mark、reference、BBO、current Funding、OI、24h volume、quality | confirmed Parquet |
| `candle_1m` | OHLC、base/notional volume、trade count、finality | confirmed Parquet |
| `funding_events` | 精算時刻、精算済みrate、確認できるinterval、観測時刻 | confirmed Parquet |
| instrument version | 契約定義、単位、tick/step、capability、SCD2有効期間 | Postgres |

Postgresはcurrent/recent truth、confirmed Parquetは期限後の履歴正本、4つのJSON artifactは
再生成可能なWeb read modelである。JSONをDBまたはParquetへ書き戻さない。

### Funding境界

- currentまたはestimated Funding rateは`market_state_1m`へ保存する。
- 精算済み履歴だけを`funding_events`へ保存する。
- 初回および停止復帰時の自動catch-upは現在時刻から最大48時間に限定する。
- catalog version開始以前のeventを自動採用しない。
- 同一instrument version・同一精算時刻の同率はidempotent、異率はfail-closedで停止する。
- intervalが確認できないVenueではrate per hourを推測せずnullにする。
- source failureはVenue / instrument単位で隔離し、成功したsourceのeventは保存する。
- deep historical backfillはMarketLens側の責務とする。

### 短期データ

選択中1 groupのdepth、trade、raw selected eventは短期保持する。板上概算は現在受信した板からの派生値で、
fee、将来impact、注文可能性を含まず、長期履歴正本にしない。

## UI完成条件

画面は次を混同しない。

- Data Quality: `ready / partial / stale / unavailable`
- Freshness: 値が現在値として利用できるか
- Coverage: 安全なcross-Venue groupに属するか
- Operational state: Web、artifact、collectorの動作状態
- Selection state: 選択groupのTTL、depth、tradeの状態

更新失敗時は直前のschema検証済みsnapshotを残していることを明示し、画面上の値を現在値と誤認させない。
stale / unavailableの値を表示用に復活させず、nullを0へ変換しない。raw reason codeは技術情報として
確認可能にし、主要画面では人間向け説明を表示する。

Coverage、参考mark中央値、色、並び順を売買推奨または裁定機会として表現しない。

## 運用完成条件

Repository実装完了の必須条件:

1. isolated Postgres 17を使う全integration testがskipなしで成功する。
2. Python test、Ruff、format、Pyreflyが成功する。
3. Web type生成、unit test、Svelte check、build、Desktop/Mobile Playwrightが成功する。
4. docs/ops test、metadata、link、lockfileが成功する。
5. secret、Private API、注文、予測model、不要dependencyを追加していない。
6. mainへmergeする前に差分と未実行項目が明示されている。

実host運用完了の必須条件:

1. 専用Postgres、collector、maintenance timer、Webが対象checkoutから起動する。
2. 3 Venue catalog/L1/candleとFunding同期を実APIで確認する。
3. 完了UTC日を跨ぎ、archive readback、manifest confirm、retentionを確認する。
4. backupを作成し、隔離targetでrestore手順を確認する。
5. rebootまたは明示再起動後に重複writerなしで復帰する。
6. 日常利用でUniverse、選択、Chart、depth、trade、quality、Past Noteを確認する。

Repository gate成功はlive cutover、actual runtime、将来の継続稼働を証明しない。

## 利用者レビュー境界

v1は主に次の意思決定を支援する。

- 発見: 今、どの市場を詳しく見るか
- 選別: data quality、freshness、liquidity contextを踏まえて見送るか
- 反証: Funding、OI、volume、Venue差から一方向の解釈を疑うか
- 検証: 表示値の由来、時刻、単位を再確認できるか

Copy Tradingの委任リスク管理とGrid / Botの自動化管理は、v1の責務外である。

## Scope freeze

P0完了前後に次を追加しない。

- TimesFM、Chronos、ML、forecast overlay
- 新Venue、aggregator、deep-capture lane
- 全市場depth/trade長期保存
- portfolio、execution、private account data
- MarketLens向けfeature engineering

P0後の追加はv1.1以降の独立判断とし、Watchdeck内部を将来の研究用途の想像だけで汎用化しない。
