# Identity・履歴診断・50件開始gateの根本修正

timestamp="2026-10-10(土)_21:40 JST"
- 作成: `2026-10-10T21:25:20+09:00`
- 更新: `2026-10-10T21:40:21+09:00`
- 検証: `未検証`
- 状態: `実装計画`

## Goal / scope

現行50件source c805056を基点に、不整合を見逃した原因を再現し修正する。
ユーザーの「根本的に直していきたい」をlocal実装・検証・commitの指示として扱う。
本番map採用、deploy、unit操作、DB書込、Provider recovery、再測定、push/CI/PR、100件昇格は未承認。
元checkoutのdirty4、100件候補worktree、過去evidenceは変更しない。
保存済み再開計画の順序（現状照合→契約版審査→固定窓欠損診断→開始gate→新50件2h判定）を維持する。

## Checkpoint / root cause investigation

- [x] c805056の隔離worktreeと専用branch。既存diff非混入。
- [x] 旧supervisor.initial_checksはMEXC50 identity/Fundingのみ。全roster/dataopsを開始前に確認しない。
- [x] recovery状態のdetailsが128件で切られ、残欠損100 bucketでも表示detailsに残欠損がない実例を確認。
- [x] endpointはrunning書込みで前回完了結果が見えなくなる。null/0を完了証拠にしない。
- [x] 全roster/versionと同じ固定windowの全欠損をread-onlyで保存・診断する。
- [ ] imnのAPI field一次証拠を調査し、不明ならhash除外・ID自動置換を行わず未受入を維持する。
- [x] 確認した不具合に限定した修正、開始前拒否、関連回帰。
- [ ] source / host-local helper / 本番未反映 / 実データ未受入を区別して報告する。

## Validation / completion

関連pytest、Ruff check/format、Market Pyrefly、docs metadata/links、diff check。
実DBを使う検証は専用隔離DBのみ。運用診断は専用Marketへのread-only transactionと保存artifactだけ。
全体release gateは本番releaseを具体化する段階で実施する。
50件の新7200秒観測と総合判定は本番操作範囲の明示後に実施し、判定後停止。

## Rollback / open items

local差分と新しいhelper copyだけを戻せる。旧evidence・旧map・DB履歴は保全する。
契約版の承認根拠、Provider履歴の可用性、現在のdrift、本番反映の許可範囲は未解決。

## 今回の実装・直接観測

- 全native1147、Aster PEARL map9921/current9981を再確認。未知raw fieldは引き続き新versionに分ける。
  Aster公式の[Exchange Information](https://asterdex.github.io/aster-api-website/futures-v3/market-data/#exchange-information)と
  [公式API原文](https://github.com/asterdex/api-docs/blob/master/V3%28Recommended%29/EN/aster-finance-futures-api-v3.md)を確認したが、
  `imn` fieldの意味は確認できず。一般の[Funding説明](https://docs.asterdex.com/astherusex-orderbook-perp-guide/funding-rate)を
  当該fieldの仕様証拠に代用しない。hash除外、map自動承認、過去ID復元は未実施。
- 21:26 JSTのrepeatable-readで15:12–21:12 JSTの固定窓を全件列挙。残99 bucketは
  HMSTR8、NOT73、SAGA4、SOPH3、TNSR11。全てHyperliquid。期間・version/hashを保存した。
- 公開`candleSnapshot`へ計5 HTTP requestsで照合（DB書込0）。84 bucketが返り、TNSR11は照合時の応答に不在。
  HMSTR4は1ページの診断上限により未照会で、Provider不在とは扱わない。
  [公式仕様](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#candle-snapshot)の直近5000足範囲内。
  原文応答を保存し、Providerが返したtradeCount=0の足と、存在しない足の0補完を区別した。
- 21:35 JSTに同じ99キー・同じ契約版を再scanし、88本が既存定期回復で保存済み、TNSR11が残欠損。
  窓移動で欠損が外れただけの判定ではない。今回writerの追加・手動回復・DB変更は0。
  公開APIが返らなかった理由は未確認であり、恒久不在・無取引確定とはしない。
- source修正: 両recoveryの詳細を未解決優先にする。dataopsへ完了・鮮度・全scan・固定窓・既知件数を
  確認する`--require-complete-recovery`と`recoveryAcceptanceBlockers`を追加。既定の監視exit契約は維持。
- 新supervisor copy: collectorより先にstrict dataops、最新完了maintenance/dataopsのsystemd状態＋同一invocationのjournal、
  DB全roster照合を要求する。証拠採取中のinvocation変更・古い成功も拒否。終端の期間内gateは保持。
  新しいmap採用時刻`recoveryNotBefore`より前の回復結果は使わない。launcherはdraft policyでunitを起動しない。
- 新しいpolicyは`approved=false`、`recoveryNotBefore=null`。旧観測期間の合算・旧driverの再起動はしていない。既存gate関数はhash固定して再利用する。
  本番切替・再測定・push/CI/PR・100件昇格は未実施。現在のstrict実データ診断はexit1で正しく開始を拒否。

host-local証拠とhelper（Git管理外）:

```text
evidence=/home/tn/watchdeck-local-archive/identity-recovery-rootfix-20261010-2125
snapshot=fixed-window-snapshot.json
provider=provider-comparison-reviewed.json
same_window_rescan=fixed-window-rescan.json
live_gate=live-strict-dataops.json
helper=/home/tn/watchdeck-local-archive/mexc-100-scale-20261010-1025/reobserve-stage50-rootfix-20261010-2125
```

## 残作業と本番前条件

PEARL現契約の根拠付き審査とimmutable map候補、TNSR等の取得可否・遅延の追跡、
endpoint固定基準時刻の個別欠損診断は未完了。全Venue完全性を達成したとは判定しない。
必要なsourceだけを50件releaseへ組み立てる前にrelease gateを実行する。
本番map採用・対象unit操作・必要な限定回復・新50件7200秒測定は具体的操作の承認後。
現在はlocal修正の検証・commitまで。旧100件候補を直接deployしない。

## Local validation

- PASS: 隔離Postgres 17（本番55432/JustPass5432以外）で関連35 pytest、skip0。
- PASS: host-local helperの既存27＋開始前拒否等3 = 30 unittest。unit起動はなし。
- PASS: 変更PythonのRuff check/format、Market Pyrefly（0 errors、既存設定によりtestsは除外）、recovery schema --check。
- PASS: 局所docs metadata/links、git diff --check。launcherはDRY_RUN。
- Live read-only: strict dataopsはexit1。PEARL版不一致と両recovery未受入を保持することを確認。
- not_run: 全体release gate、新版の本番配置、実systemd新helper smoke、新しい7200秒観測、100件/24h/容量受入。
- helperの全source hashと未承認policyは同directoryの`source-manifest.json`、`policy.json`に保存。
  Git commitの対象はrepo source/docsのみ。host-local helperは別成果物でありGitへ混入しない。
