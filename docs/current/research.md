# Research reader・固定比較・品質検査

timestamp="2026-10-09(金)_15:06 JST"
- 作成: `2026-10-09T15:03:11+09:00`
- 更新: `2026-10-09T15:06:54+09:00`
- 検証: `2026-10-09T15:03:11+09:00`
- 状態: `現行`

## 実装範囲と証拠の意味

`watchdeck-market research`はMarket package内の独立CLIである。明示した一契約/versionを
将来観測し、観測したDB行の版をimmutable journalへ保存する。通常のMarket writer、Attention、
Ranking、manual selectionは変更しない。Repositoryの実装と稼働releaseへの反映は別である。

研究readerが実際に読んだ版の再生を扱う。取引所の初回availability、poll間の全producer訂正、
過去の全Universe、未保存の過去OIは再構成しない。旧Fixtureの`point_in_time_replay=false`も維持する。
`observed`と`synthetic`、hash整合、因果時刻の資格、統計的な比較可能性は別の軸である。
自作JSONのhashは真正なProvider観測の証明や第三者timestamp署名にはならない。

## 観測と保存

環境の`PREP_WATCHDECK_MARKET_DATABASE_URL`を利用するのは`observe`だけ。
接続先は専用loopback DB（port 55432、専用DB、Marketまたはreader role）と隔離test DBに限定する。
毎pollで一つの`REPEATABLE READ READ ONLY` transactionを使い、instrument定義・catalog provenance、
local validity、group membership、capability、candle、state/OI、settled fundingを同じsnapshotから読む。
接続5秒、statement 5秒、lock 1秒の上限を持つ。producerへwriteせず、ネットワークProviderを呼ばない。

以下のcommandはRepository rootで実行する。例の`/tmp/watchdeck-research`は研究専用であり、
Market/Ranking/Attention stateと同一・包含関係のroot、repoの`var`、symlinkは拒否する。
`observe`の実行はデータ読取と新しい研究ファイル生成を伴う。常駐unitは作成・起動しない。

```bash
uv run --package prep-watchdeck-market watchdeck-market research --help
uv run --package prep-watchdeck-market watchdeck-market research observe \
  --instrument bitget:BTCUSDT --journal /tmp/watchdeck-research/journal \
  --samples 10 --interval-seconds 60 --lookback-minutes 5
uv run --package prep-watchdeck-market watchdeck-market research export-snapshot \
  --journal /tmp/watchdeck-research/journal --output-dir /tmp/watchdeck-research/snapshots
uv run --package prep-watchdeck-market watchdeck-market research verify-snapshot \
  --snapshot /tmp/watchdeck-research/snapshots/<ID> --cutoff <UTC-ISO>
uv run --package prep-watchdeck-market watchdeck-market research quality \
  --snapshot /tmp/watchdeck-research/snapshots/<ID> --output-dir /tmp/watchdeck-research/quality
```

最初の観測でnative versionを固定し、その後の版変更を自動追従しない。`--version`で既知の版を
明示できる。既定1 sample、interval 60秒、lookback 5分。最大1,440 samples、interval 5–600秒、
lookback 1–60分、capture 24時間。libraryのwindowも最大24時間で、分境界の半開区間に限定する。
一つの入力16 MiB、snapshot合計64 MiB、2,000 receipts、datasetあたり20,000行を上限とする。
大きいcaptureは自動で切り捨てず、別journalで明示的に区切る。

Payloadのdurable publish/readbackを終えてから別receiptを発行する。保守的な
`available_at=max(read_completed_at,payload_readback_completed_at)+clock_error_seconds`を記録する。
既定clock errorは1秒で、実機時計の正確さを証明する値ではない。DB/host clockの差、wall/monotonic差、
poll間隔（最大120秒またはintervalの2倍）、中断と読取失敗を資格理由へ残す。
同じbucketの訂正版は元のbytesを上書きせず、新しいeditionとする。

```text
journal/
  journal.json
  observations/<ID>/payload.json + SHA256SUMS
  receipts/<ID>/receipt.json + SHA256SUMS
snapshot/<ID>/
  manifest.json + SHA256SUMS
  observations/<ID>.json
  receipts/<ID>.json
```

Receiptはsequenceと前receipt hashで連結する。exportはwriter lockを取得し、hash、連鎖、membership、
identity/version、context、単位、OHLC、時刻、finalityをoffline再検証する。
Payloadだけ残った中断、孤立receipt、欠けた連鎖、schema不正、特殊ファイル、hash不一致は拒否する。
元のjournalを消して修復しない。原因を保全・確認し、新しい研究rootから再開する。
cutoffより後のeditionをsignalへ入れない。破損した将来ファイルを含むbundle全体の完全性も検査する。

## 固定A/Bと有限口座

Aは連続した2本の確定足から価格returnとnotional activity比を判定する。
BはAに固定OI増加条件を追加する。両者は同じprice/activity/OIの有効cohort、時刻、holding、
notional、fee/slippage、funding仮定を使う。Aのsignal値にOIを使わず、OI欠測・単位不明は双方から除外する。
Aster OIを0、別Venue、推測倍率で埋めない。`derived_final`は一次比較のconfirmed足へ昇格しない。

[/home/tn/projects/prep-watchdeck/config/research-trial.example.json](../../config/research-trial.example.json)を研究rootへコピーし、未来のdecision開始時刻、
train/validation/test境界、閾値、資金と費用根拠を設定する。例の費用は説明用scenarioであり料金確認ではない。
[/home/tn/projects/prep-watchdeck/schemas/research-trial-rules.schema.json](../../schemas/research-trial-rules.schema.json)を満たす必要がある。
登録時刻がdecision開始より後なら拒否する。CLIに過去の登録時刻を指定するオプションはない。

```bash
uv run --package prep-watchdeck-market watchdeck-market research register-trial \
  --rules /tmp/watchdeck-research/rules.json --output-dir /tmp/watchdeck-research/registrations
# 観測終了・snapshot export後に入力bytesを固定する。
uv run --package prep-watchdeck-market watchdeck-market research bind-trial \
  --registration /tmp/watchdeck-research/registrations/<ID> \
  --snapshot /tmp/watchdeck-research/snapshots/<ID> --output-dir /tmp/watchdeck-research/trials
uv run --package prep-watchdeck-market watchdeck-market research evaluate \
  --trial /tmp/watchdeck-research/trials/<ID> --snapshot /tmp/watchdeck-research/snapshots/<ID> \
  --output-dir /tmp/watchdeck-research/results
```

Rule、evaluator/validator source群、registration、snapshotのhashを固定する。
source更新後は新規registrationが必要。過去resultを上書きしない。評価後に都合のよい閾値を採用する
探索用ループはない。結果には除外・no-trade・failureも保存する。

約定はsignalの研究availabilityより後に読めた、signal後の足のcloseを使うproxyである。
long-only、単一position、現金で全額を賄う単位数量を扱い、fee/slippageと資金不足を計上する。
実際のperpetual margin、leverage、清算、queue fill、実約定を模擬した主張はしない。
Decimal精度50桁を使い、入力の文字数・指数・桁数を制限する。cash controlは無金利現金保有。
train/validation/testを時系列で固定し、次区間へentry/exit availabilityがはみ出すlabelをpurgeする。

Fundingの正値はlong支払という明示仮定を使い、settlementではその時点にreaderが知った最新closeを
reference priceとする。同時刻はfunding→exit→entryの順。entry前のfundingを課さず、同じeventを二度課さない。
`require_observed_events`ではintervalとanchorと根拠を固定し、必要eventの不足・余分なevent・cadence不一致を
比較不能とする。rateはstudy終了までに観測したsettlement outcomeで、signalには使わない。
現在のinstrument intervalだけで過去scheduleが確認済みとは扱わない。
`explicit_zero_scenario`はfundingゼロ感度scenarioであり、観測された費用として扱わない。

| status / field | 意味 |
| --- | --- |
| `FAILED` | 資金・数値・整合性等の実行失敗。新規resultに理由を保持する |
| `NOT_ESTIMABLE` | 因果入力、不足event、exit、共通test episode数等が不十分 |
| `ESTIMABLE_DESCRIPTIVE` | 固定条件下で記述比較可能。収益性やB優位の認定ではない |
| `ab_test_equity_change_difference` | 主比較。test区間のnet equity変化のB−A |
| `ab_final_equity_difference` | 全期間の参考差。主比較と区別する |
| `evidence_kind` | syntheticかreader-observedか。statusと別に読む |

非重複episodeは統計的独立を証明しない。24時間のデータや件数を満たしただけで優位性を断定せず、
事前設計した複数日の検証・capacity・実データ受入は別工程とする。

## 品質・archive・funding検査

`quality`はPolarsでlocal validity内の期待分数、candle/state欠損、同じprice/activity/OI cohort、
UTC日単位の件数を出力する。retrospective診断を戦略signalやsurvivorship-free Universeへ読み替えない。

`reconcile-archives --manifest <JSON> --output-dir <DIR>`はSHA付きParquetを読み、native versionのOHLC・base/notional volume・trade count・finalityを照合する。
Manifestは`instrument_id`, `version_id`, `definition_hash`, `window_start`, `window_end`, `valid_from`,
nullable `valid_to`, `sources`を持つ。各sourceは`dataset="candles"`, absolute `path`, `sha256`と
同じ3つのidentity値を持つ。Parquetはnative `venue_instrument_version_id`, `bucket_at`,
`open_price/high_price/low_price/close_price`列を使う。activity/trade_count/finalityの欠測と0を区別し、
同じOHLCでも売買代金等が異なれば差分fieldを報告する。最大32 files、合計64 MiB。
値の矛盾と不足時刻を新しいreportへ残す。候補だけを出し、自動backfillや原本変更を行わない。
古いOI、初回availability、訂正履歴の復元はできない。

`inspect-funding --manifest <JSON> --output-dir <DIR>`は既存Bitget研究collectorの`.csv.gz`を扱う。
Manifestは`venue="bitget"`, `category="USDT-FUTURES"`, `symbol`, `window_start`, `window_end`, `sources`。
各sourceはabsolute `path`, `sha256`、任意`row_count`。CSVは`venue`, `category`, `symbol`,
`funding_time_ms`, `funding_rate`, `current_instrument_fund_interval_hours`列を持つ。
identity/SHA/件数/有限rate/同時刻の矛盾を検査し、実際のfirst/last eventとlineageを報告する。
現行intervalを履歴全体へ適用せず、coverageは`observed_rows_only`とする。

## CCXT照合とhftbacktest入力

既存依存のPolarsを利用し、CCXT/NumPy/hftbacktestを通常runtime依存へ追加しない。
`ccxt-capabilities --venue <bitget|hyperliquid|aster>`は明示的に導入されたCCXTの`has`をofflineで検査する。
未導入は`research_optional_ccxt_unavailable`。必要ならisolated uv環境で
`uv run --with ccxt --package prep-watchdeck-market watchdeck-market research ccxt-capabilities --venue aster`
を実行する。これはProviderへの取得要求を送らず、`has`もProvider契約の証明ではない。

`compare-ccxt --snapshot <DIR> --reference <JSON> --output-dir <DIR>`は明示した照合結果を比較する。
Referenceは`schema_version=1`, `source="ccxt"`, `exchange_id`, native `native_symbol`,
`ccxt_version`, UTC `captured_at`, `volume_unit="base"|"notional"`, `has`, `ohlcv`。
各OHLCVは`[epoch_ms,open,high,low,close,volume]`。照合時刻・native identity・OHLC・volume単位を確認し、
referenceのcanonical hashと差分を残す。標準symbolの文字列だけで契約を推測せず、欠測を補完しない。

`prepare-hft --metadata <JSON> --output-dir <DIR>`は連続L2とaggressor side付きtradeを検査する。
Metadataは`schema_version=1`, `instrument_id`, `version_id`, `definition_hash`, `quantity_unit="base"`,
`tick_size`, `lot_size`, absolute `source_path`, `source_sha256`, `feed_kind="continuous_l2_and_trades"`,
`sequence_scope="exchange"|"combined_capture"`, `capture_complete=true`, `aggressor_side_verified=true`。
完全性とside検証はcallerの宣言であり、reportの`provider_completeness_verified`はfalseのまま。

Source JSONはevent配列。全eventに正整数`sequence`, `exchange_ns`, `local_ns`が必要。
最初は`kind="snapshot"`と`bids/asks=[[price,quantity],...]`、以後は`kind="depth"`の
`side="bid"|"ask"`または`kind="trade"`の`side="buy"|"sell"`、`price`, `quantity`を使う。
連続sequence、単調なexchange/local time、local>=exchange、tick/lot grid、交差しない両側bookを要求する。
periodic snapshot・欠sequence・side不明を連続feedへ偽装しない。

生成物は[hftbacktest公式event dtype](https://github.com/nkaz001/hftbacktest/blob/master/py-hftbacktest/hftbacktest/types.py)
のfield/flagと元のinput bytesを含む。`export-hft-npz --prepared <DIR> --output-dir <DIR>`は全hashと
sourceからの再計算を確認し、任意NumPyで`data.npz`を生成する。
未導入は`research_optional_numpy_unavailable`。isolated環境は`uv run --with numpy ...`で選べる。
完全feedのProvider実証、latency/queueモデルの選定、hftbacktest engineでの検証は別受入である。
現在の一分足や選択市場の最近の板・tradeだけでは条件を満たさない。

## 終了コードと復旧

成功は0、入力・schema・hash・DB・filesystem・任意依存の失敗は2、snapshot不適格または比較不能/失敗resultは3、
Ctrl-Cは130。commandの引数syntax誤りはTyperのusage errorとなる。通常結果はJSON、observeはreceiptごとの
JSON行と最後のsummaryを出す。安全なerror codeだけを返し、DSN、認証値、raw exception本文を出さない。

DB timeout/unavailableはgap receiptを可能な範囲で保存して停止する。容量・権限・receipt publish自体の
失敗では記録できない場合があるため、孤立payloadもoffline検査で検出する。
lock競合は同時writerを停止してから再試行する。hash不一致や孤立版を消して成功扱いにしない。
read-only研究CLIはDB migration、service install/start/restart、ranking map採用、productionへの配置を実行しない。

## Schemaと検証

Python modelsを正本とし、Repository rootで以下を実行する。Web APIへ露出しないためWeb型生成は不要。

```bash
uv run --package prep-watchdeck-market python scripts/market/generate-research-schema.py --check
```

[/home/tn/projects/prep-watchdeck/schemas/research-payload.schema.json](../../schemas/research-payload.schema.json)、[/home/tn/projects/prep-watchdeck/schemas/research-receipt.schema.json](../../schemas/research-receipt.schema.json)、
[/home/tn/projects/prep-watchdeck/schemas/research-registration.schema.json](../../schemas/research-registration.schema.json)、[/home/tn/projects/prep-watchdeck/schemas/research-trial.schema.json](../../schemas/research-trial.schema.json)
を含む。Schema単独ではnative行・因果時刻・hash・経済計算の資格を証明しない。
隔離Postgresでread-only/RRとmigration、synthetic journalで未来版/改変/中断、固定評価でcash/funding/
訂正/分割purgeを検証する。実観測24時間、30日evidence、稼働map回復は別の受入として残る。
