# Identity・履歴診断・50件開始gateの根本修正

timestamp="2026-10-10(土)_22:14 JST"
- 作成: `2026-10-10T21:25:20+09:00`
- 更新: `2026-10-10T22:14:35+09:00`
- 検証: `2026-10-10T22:14:35+09:00`
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
- [x] imnのAPI field一次証拠を調査。意味は未確認で、hash除外・互換扱い・ID自動置換をせず未受入を維持する。
- [x] 確認した不具合に限定した修正、開始前拒否、関連回帰。
- [x] source / host-local helper / 本番未反映 / 実データ未受入を分け、下記に記録。

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

PEARLのimmutable native map候補は下記の追加実装で作成したが、本番採用は未実施。
固定窓の旧99欠損は保存済みとなったが、旧版PEARLの欠損・分途中境界を未解決のまま保持する。
endpoint固定基準時刻の全件保証と全Venue完全性を達成したとは判定しない。
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

## 追加調査を受けた実装（ユーザー指示: 実装）

前回回答の4不備と契約審査・履歴保証境界を実装対象にする。local実装/検証/commitは承認済み。
本番deploy、map採用、unit操作、live DB書込、Provider回復、2時間観測、push/CI/PRは別操作として未実施。

### 設計と担当境界

- 回復証拠: 完了時刻を一度確定。全対象ID/version/definition hashを表示上限とは別に保持し、
  現在rosterと一致させる。実行中と最新完了証拠を分離し、後続失敗・版変更・期限で失効させる。
- 測定判定: warningを個別対象/理由/期間/上限/根拠で審査し、新理由・対象・範囲拡大を拒否する。
  最終監査は正常終了・child結果・同一policy・証拠hashを必須とする。旧helper/evidenceは保全し新版を作る。
- 固定履歴診断: 既存writerを増やさず、read-onlyで固定窓と交差する全契約版をscanする。
  欠損キーと境界帰属未確定を保存し、再scanでも窓移動・契約切替で未解決を消さない。
- PEARL: 現行raw/DB/rosterを必要最小限read-onlyで照合し、旧版互換を主張せず参照未採用の新map候補を作る。
  imnの意味・無害性は推定しない。候補は本番へ配置しない。

### 実装順・完了条件

- [x] T1 回復状態/検査: advancing clock正常終了、同件数の版差替え、missing proof、後続失敗を検証。
- [x] T2 測定helper: 新warning理由/対象/増加、期限切れ、異常終了、policy不一致を拒否し正常系を受入。
- [x] T3 固定窓監査: 旧版欠損・分途中切替・同じ欠損キーの再scanを隔離DBで確認。
- [x] T4 PEARL新map候補: 未確認reference/multiplierを維持しvalidatorと全roster照合。
- [x] T5 統合: schema再生成、関連pytest/Ruff/Pyrefly、docs checks、変更箇所の独立review、対象だけcommit。

### 検証・rollback

再現済み4不具合を先に失敗するtestで固定し、修正後に通す。DBを使うtestは専用の一時Postgresのみ。
外部IOを置換する場合も判定本体は実コードを動かす。schema変更はgeneratorから生成し手編集しない。
今回のsource commitと新版helper/map候補だけがrollback対象。旧証拠・旧map・runtimeはそのまま保全する。
本番未反映と未実施の実データ受入をsource PASSへ読み替えない。

### 追加実装の実データ診断と候補

- 22:05:56 JST、同じ15:12–21:12 JST窓をread-only/RRで1147ID・1148契約版scan。
  以前の99欠損は同じID/version/hash/bucketで全件保存済みと照合。
- 全version scanではPEARL旧9921の17:29 JST足1本が欠損、17:30 JST分の版切替が
  `boundary_unresolved` 1件。新台帳はcomplete=false。現契約だけのscanで見えなかった問題を保持する。
- PEARL現9981のnative map候補9b411d5e754a467908524948を作成しvalidatorと全roster照合PASS。
  reference未採用・multiplier未確認・旧版互換未確認を維持。他617行を保持。
  baselineのreview40/quantityReview4/widgetReview43は残り、qualificationComplete=false。
- 新しい観測helper policyはapproved=false / warningExceptions=[]。警告例外は勝手に承認しない。
- 証拠と候補は `/home/tn/watchdeck-local-archive/acceptance-evidence-20261010-2154`、
  helperは `/home/tn/watchdeck-local-archive/mexc-100-scale-20261010-1025/reobserve-stage50-evidence-20261010-2154`。
  旧helper・旧証拠・旧mapは保全。今回のProvider照会とDB変更は0。
- 独立reviewでdefinitionHashがdigestの自己整合に留まる点を検出。UniverseはID/versionだけのため、
  開始/終了helperのread-only DB roster snapshotで全definitionHashを別途照合する。

- 周期dataopsの通常modeにはrunning warningが残るため、受入用strict drop-in templateを別途用意。
  既定unitは維持。未installであり、新release/採用map/承認済みpolicyと一緒に運用側で適用・確認する。
  通常modeでのタイミング次第の拒否を、warning例外の無断追加で回避しない。

### 追加実装の最終検証

- PASS: 専用隔離Postgres17、関連90 pytest、skip0（旧版/境界を含む実SQL、producer→checker）。
- PASS: 新helper36 unittest、実checker strict→周期journal gate、launcher DRY_RUN、全source pin。
- PASS: Web 266 Vitest、check 0 errors/0 warnings、build。変更はrecovery型生成のみでinteraction変更なし。
- PASS: 変更Python Ruff/check-format、Market Pyrefly 0 errors（既存設定でtests除外）、schema --check。
- PASS: 任意strict drop-inを展開したsystemd-analyze offline verify、docs metadata/links、diff check。
- PASS: 独立reviewで追加されたdefinitionHash照合を再reviewし、確認findingは解消。
- Source/helper/candidate作成は完了。新helperはGit管理外で別manifest、sourceはこのbranchでlocal commit。
- not_run: 全体release gate、実systemd配置smoke、map本番採用、新50件7200秒観測、100件昇格、CI/push/PR。

### 再開条件

新releaseを具体化する段階で全体release gateを実行し、候補mapの既存未確認事項と採用判断、
個別warning例外の根拠/有効期間/上限、新release・strict周期設定・map・recoveryNotBeforeを固定する。
その具体的な運用変更と新50件測定を承認後に適用し、元の観測期間は合算しない。
旧版PEARL1本と境界1件は未解決のまま追跡する。許可なしの旧足付替え・補間・hash除外は行わない。
この未完了の運用/実データ境界があるためplanはactiveに残す。
