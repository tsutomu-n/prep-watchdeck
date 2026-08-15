# Decision 0011: 3 Venue Crypto Perp Universeへ置換する

- 作成: `2026-08-14T22:07:54+09:00`
- 更新: `2026-08-14T22:40:41+09:00`
- 状態: `設計判断`

---

## 決定

Bitget単独scanner、DuckDB snapshot、Candidate/Ranking中心UIを、Bitget、Hyperliquid Core、Asterの
crypto linear perpetualを中立に表示するUniverse Explorerへ置換する。

新runtimeは`apps/market-core`、CLIは`watchdeck-market`。専用Postgres 17を直近データの正本、
confirmed Parquetを期限後履歴の正本、atomic JSONをWeb read modelとする。WebはPostgresへ接続しない。

## 対象と除外

対象は各Venueのactive crypto linear perpetual。base完全一致、base数量、multiplier 1、
Venue内候補1件を確認できるinstrumentだけを`crypto:<BASE>:linear-perp`へ自動group化する。

RWA、HIP-3、synthetic、RFQ、alias、multiplier contract、quantity unit不明、同一Venue衝突は
自動groupへ含めない。4 Venue目、CCXT runtime、Discovery jobはこの置換へ追加しない。

## 比較契約

mark、reference price、funding、OI、24時間出来高、quote/settle/collateral、freshness、provenanceを
Venue値のまま表示する。Funding intervalまたはOI unitを確認できない値は換算しない。

同一groupの2 Venue以上、同一cycle、age 120秒以内、skew 30秒以内、USD-like通貨を満たすmarkだけ、
USD/USDC/USDT parityを参考中央値に限定して仮定する。Venue値の変換・合算、24時間出来高中央値、
価格差ranking、裁定機会、売買推奨へ接続しない。

## 選択detail

local single-userの選択は1 group、primary Venue instrument 1件。500ms debounce、15分TTL、
5分heartbeat、旧subscription 10秒以内解除を契約とする。選択groupだけ最大20段、直近100 trades、
$100/$500/$1,000 book walkを取得する。

book walkは現在受信したCLOB depthの参考値で、fee、将来impact、注文可否を含まない。10秒超、
板不足、非USD-like、単位不明ではnullにする。

## 保存と運用

Rawは7日+2時間、normalizedとselected historyは8日保持する。完了UTC日のnormalized datasetを
Parquetへ書き、row count、key、timestamp、row digest、SHA-256のreadbackとactive manifestを確認した
後だけ対応するnormalizedを削除する。manifest confirm後のlate correctionはretention開始前なら
新generationを作り、開始後なら停止する。

raw marketとselected raw/historyはParquet対象外のephemeral dataとしてage条件で削除する。各DELETEは
最大10,000行。1回の上限はnormalized全target合計180 batch、raw 10 batch、selected 250 batch。
毎時実行し、各dataset/Venueの最古未archive日から重複を除いた最大3日と指定日を処理する。
source更新のないactive manifestは再生成せず、空datasetをarchive成功にしない。

専用DB、collector、maintenance、Webを別systemd user unitとする。専用Postgresはproject
`prep-watchdeck-market`、loopback port 55432、Repo外stateを使い、JustPass資源を共有しない。

## 製品境界

自動売買、注文、残高、position、Private API、秘密API key、売買推奨を追加しない。Past Noteは
`venueInstrumentId`単位の60日監視annotationであり、trade journalではない。

## 既存Decisionとの関係

- Decision 0001のlocal-firstを維持する。
- Decision 0002のpublic API onlyを3 Venueへ拡張して維持する。
- Decision 0005のno automatic tradingを維持する。
- Decision 0003、0004、0006〜0010の旧scanner、DuckDB snapshot、Cold/Hot、Candidate、VPI、
  OI 60分、旧Chart/UIに関するproduction契約を置換する。

旧Decisionは履歴として残すが、現行producer/UIの契約として実装しない。

## Rollback

cutover前は旧checkout、旧scanner unit、旧DuckDB stateを変更しない。installerは既存Web unitを
backupする。cutover後に重大な退行があれば、新Web/market serviceを停止し、backup Web unitと
旧scanner serviceを復元する。新DB/stateは調査用に残し、自動削除しない。

push、merge、live cutover、旧state削除はこのDecisionだけでは承認されない。
