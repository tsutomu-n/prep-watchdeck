# Decision 0008: Candidate 74h ANDとOI 60分契約

- 作成: `2026-08-09T20:30:00+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 状態: `設計判断`

---

> **一部superseded:** Candidate、74h AND、該当summary/ranking/UI/versionの記述は
> [Decision 0010](0010-retire-74h-candidate-deep-backfill.md)により置換された。
> OI 60分、5分bucket、24時間retention、失敗境界の決定は引き続き有効である。

## 決定

Candidateのtimeframeランキングは、`userRule74hMatched is True`かつ`NO_TRADE`でないrowだけを
対象にする。Watchlist、Raw Sort、Smart Rank、snapshot全rowsは広い監視面として維持し、
`rankings.noTrade`診断は全rowsから生成する。74h履歴が温まるまでCandidateが空でも正常である。

74h価格componentと24h USDT売買代金componentはそれぞれ`bool | null`とする。どちらかが
`null`なら複合結果も`null`、両方が既知の場合だけANDを評価する。履歴不足、比較不能、
zeroまたはnonfinite baselineは`null`とし、未一致`false`と混同しない。

## OI履歴

Bitget public tickerの`holdingAmount`をcoin単位のOpen Interest、row内の`ts`をsource data時刻
として扱う。これはBitget公式のWebSocket tickerとREST all-tickers仕様に基づく。

- [WebSocket ticker仕様](https://www.bitget.com/api-doc/classic/contract/websocket/public/Tickers-Channel)
- [REST all-tickers仕様](https://www.bitget.com/api-doc/classic/contract/market/Get-All-Symbol-Ticker)

`source_ts_ms`を5分floorしたbucketへ、`(symbol, bucket_ts_ms)`を主キーとして保存する。
同bucketは新しい`source_ts_ms`だけが更新できる。24時間より古いsampleを削除し、境界ちょうど
24時間は保持する。比較にはcurrent bucketから設定済みlookbackを引いたexact bucketだけを使う。
現在の表示・分類・retention契約はOI 60分に固定されているため、設定値も`60`だけを許容する。
`60`は正数かつ5分の倍数というbucket境界を満たす。

currentとpreviousは有限かつ正数、ticker source/update時刻はsnapshot生成時刻から2分以内を
必須とし、満たさない場合は`UNKNOWN`とする。`UNKNOWN`はattention scoreへ加点しない。

## 失敗境界

DuckDB DDL/init失敗はservice startupを失敗させる。個別snapshot cycleのOI保存・読込・prune失敗は
全OIを`UNKNOWN`、OI加点を0とし、`summary.oiDiagnostics`へdegraded diagnosticを出して
snapshot発行自体は継続する。

## 表示とversion

Candidate見出し下へ有効なAND条件と`eligible/notMatched/unknown`件数を表示する。不正なsummaryは
数値を推測せず、条件metadataを取得できないこととsnapshot更新後の再確認を案内する。
旧snapshotのランキングへ現行gate済みという説明は付けない。OI `UNKNOWN`は「不明」、
74h `null`は「判定不能」と表示する。
VPI-Lite+固有のOI availability表示は別契約として維持する。

`featureVersion`と`rulesetVersion`は`3`、`schemaVersion`は`1`を維持する。

## 帰結とrollback

- 旧snapshot readerは追加summary propertyと`rankings.noTrade`を許容する既存schemaの範囲で動作する。
- `open_interest_samples`はadditive tableであり、rollback時もDROPせずconsumer停止だけで安全に戻せる。
- exact 60分、retention、out-of-order防止、restart再利用はseed済み一時DuckDB testで証明する。
- finite live smokeは接続・保存の初期適格性だけを証明し、60分経過の代用にしない。
