# Decision 0011: 3 Venue Crypto Perp Universeへ置換する

- 作成: `2026-08-14T22:07:54+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **製品境界は一部superseded:** [Decision 0012](0012-product-evolution-boundary.md)により、
> 3 Venue限定、ranking禁止、新Venue/aggregator禁止、Stocks/RWA禁止、read-only paid/credential API禁止、
> 固定Chart/selection/artifact数等を将来の永久制約とする解釈は置換された。
>
> このDecisionは、現在productionの3 Venue Perp runtimeのarchitecture/data/operations baselineとして有効。

## 決定

Bitget単独scanner、DuckDB snapshot、Candidate/Ranking中心UIを、Bitget、Hyperliquid Core、Asterの
crypto linear perpetualを中立に表示するUniverse Explorerへ置換した。

新runtimeは`apps/market-core`、CLIは`watchdeck-market`。専用Postgres 17を直近データの正本、
confirmed Parquetを期限後履歴の正本、atomic JSONをWeb read modelとする。現行WebはPostgresへ直接接続しない。

これらは現在productionの構成であり、将来のWatchdeck全体をこのarchitectureだけへ固定しない。

## 現行Perp対象とgrouping

現行Perp coreでは各Venueのactive crypto linear perpetualを対象とする。base完全一致、base数量、multiplier 1、
Venue内候補1件を確認できるinstrumentだけを`crypto:<BASE>:linear-perp`へ自動group化する。

現行Perp coreではRWA、HIP-3、synthetic、RFQ、alias、multiplier contract、quantity unit不明、同一Venue衝突を
自動groupへ含めない。これはidentityを推測しないための現行contractであり、別asset-class surfaceや明示的に
検証されたmappingを将来禁止するものではない。

## 現行比較契約

mark、reference price、funding、OI、24時間出来高、quote/settle/collateral、freshness、provenanceを
Venue値のまま保持する。Funding intervalまたはOI unitを確認できない値を推測換算しない。

現行参考mark中央値は、同一groupの2 Venue以上、同一cycle、age 120秒以内、skew 30秒以内、USD-like通貨の
条件を満たすmarkだけを使い、USD/USDC/USDT parityを参考中央値に限定して仮定する。

Decision 0012以後は、意味・単位・時刻・identityを確認できる別featureの正規化、集約、rankingを禁止しない。

## 現行selected detail

現在の実装はlocal single-userでactive selection 1件、primary Venue instrument 1件。500ms debounce、15分TTL、
5分heartbeat、旧subscription 10秒以内解除。選択groupのCLOB instrumentについて最大20段、直近100 trades、
`$100 / $500 / $1,000` book walkを取得する。

book walkは現在受信したdepthからの参考値で、現行schemaではfee、将来impact、注文可否を含まない。

これらのselection数、TTL、heartbeat、depth段数、trade件数、notional、fee/impact機能は現行実装値であり、
将来の永久上限ではない。

## 現行保存と運用

Rawは7日+2時間、normalizedとselected historyは8日保持する。完了UTC日のnormalized datasetをParquetへ書き、
row count、key、timestamp、row digest、SHA-256のreadbackとactive manifestを確認した後だけ対応するnormalizedを
削除する。

現行maintenanceはbounded delete、late-correction guard、専用Postgres、専用systemd user unit、Repo外state、
JustPass資源との隔離を持つ。

retention日数、batch上限、port、unit構成は現行capacity/operationsの値であり、検証を伴って変更できる。

## 製品境界

現在のWatchdeck製品境界はDecision 0012を正本とする。

自動注文、資金移動、無人executionは既定責務に含めない。一方、ranking、score、prediction、direction、
Stocks/ETF/RWA、新Venue、aggregator、read-only paid/credential API、backtest、feature engineering、bounded backfill、
Decision Memo / Trade Journal等をこのDecisionから禁止しない。

## 既存Decisionとの関係

- Decision 0001のlocal-first既定を維持する。
- Decision 0005の自動execution分離を維持する。
- Decision 0003、0004、0006〜0010の旧scanner/DuckDB production契約を、このPerp runtimeについて置換した。
- Decision 0012が、このDecisionに含まれていた将来の製品境界・scope freeze相当の制約を置換する。

## Rollback履歴

この置換時には旧checkout、旧scanner unit、旧DuckDB stateをrollback資産として保持した。
現在の変更作業で旧runtimeを自動削除・復活させる根拠にはしない。

push、merge、live cutover、state削除は各作業の承認と検証に従う。
