# 過去検証の確定仕様

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## H01: 測る問い

研究対象は毎時のdecision-time snapshot。同一instrument/version、profile revision、scopeで集計する。既定の結果は取引損益ではない。

| profile | 条件 C | 1時間後の結果 Y |
| --- | --- | --- |
| momentum-1h-up | 保存時r60>=0.01 | p(s+60m)>p(s) |
| momentum-1h-down | 保存時r60<=-0.01 | p(s+60m)<p(s) |
| attention-15m | 保存時score>=70 | abs(p(s+60m)/p(s)-1)>=0.01 |

条件のtはsnapshotのwindowEnd。条件にはsnapshotのasOfまでに採用された値だけを使う。結果の開始sはasOf以上の最初の分境界（ceilMinute、ちょうど境界ならその時刻）とし、outcomeStartAt/outcomeEndAt=s/s+60mを保存する。遅れて取得できたsnapshotの過去windowEndから結果を測り始めない。p(s)とp(s+60m)を含む `[s-1m,s+60m)` の61本の連続完了足を要求し、query asOfまでに観測されたrevisionを固定する。開始価格p(s)は結果側の観測基準であり、意思決定時点の約定可能価格とは主張しない。同値はmomentumのsuccess=false。価格到達の途中経路、損切り、約定、コストを測っていないので「勝率」と呼ばない。

## H02: 分母と欠損

母集団＝指定期間内の予定毎時観測。取得できたsnapshot数、入力適格数、条件一致数、結果resolved数、success数、censored数、理由別除外数を返す。主推定は条件一致かつresolvedのk/n。horizon未終了、結果足不足、version変更を失敗0として入れない。

欠けた結果がある推定は完全母集団の結果とは言えない。resolved coverageを表示し、入力/結果欠測が偏り得る注意を付ける。query asOfを過去へ戻しても未来の結果が混入しない試験を必須にする。

比較基準は同じ期間・instrument・sampling・結果取得条件を満たす条件なしの母集団。条件ありだけ新しく、baselineだけ全期間という比較はしない。baselineには条件あり群も含まれるので独立2群検定と扱わない。

## H03: 時点の再現

過去足からの後付け再計算は `reconstructed`、当時保存したsnapshotは `observed` と区別し、同じ集計へ混ぜない。今回の本番既定はobserved。履歴不足を補うため、過去timestampをfirstSeenAtへ偽装しない。遡及研究用reconstructedを後日追加するときも別contractとする。

足訂正は結果側dataRevisionを変える。過去runを再計算で上書きしない。queryHashは正規化queryを、resultIdはqueryHashとdataRevisionを含む。再現に必要な結果のused values/hashも結果に保持する。

## H04: 共通標本guard

overall、baseline、年別、前半/後半、recency、group、CSV/JSONのすべてに同じ関数を使う。n<10ではestimate/全interval=null、件数と理由だけ返す。10<=n<30は推定値を表示しlow_sample警告。n>=30でも自動的に「安定」「優位」としない。thresholdは設定・version管理する。production経路にguardを外すforceは設けない。

Wilson参考区間はz=1.959963984540054、0<=k<=nの整数を検証。系列依存未補正の二項近似として表示し、次の依存調整区間と区別する。

## H05: 系列依存と区間

毎時観測は独立と仮定しない。sの遅延変動によるhorizonの部分重複もあり得る。主な不確実性表示としてcalendar-day moving-block bootstrapを実装する。時系列の全UTC日（欠測日を含む）を順序付きで保持し、各日のk/nを持つ。連続7日blockを重複可で選び、元日数に切り詰める。条件一致後の行だけを並べ替えてbootstrapしない。

既定2,000 resamples、seed=42をqueryへ固定し、2.5/97.5 percentile（明示したlinear interpolation）を返す。元期間が28日未満、resolvedがある日が28日未満、または有効resampleが90%未満ならこの区間はnullと理由。n=0のresampleは比率を捏造せず無効数へ計上する。Wilsonだけになった場合は依存調整未確認と表示する。

7日blockも普遍的に正しい値ではない。連続性・regime変化等の仮定を明示し、必要なら別block長の感度を研究用に扱う。最良の見栄えだけを選んで報告しない。

## H06: 期間比較と探索

前半/後半は要求期間のcalendar midpointで分け、条件一致件数の半分で切らない。区間overlapは `intervalOverlap` と表示しstableとは呼ばない。recencyは今回 `calendarDays` の直近30日。全履歴と期間が同じなら重複表示を省くが定義は返す。

queryはallowlist済みprofile、instrument、期間、recency、presetだけ。初期上限は365日・10,000観測・1 job同時実行、resource budgetを超える要求は明示拒否。SQL/任意コード/任意の予測式は受けない。複数profileを探索したことを記録し、最高値を選んだ結果を未探索の95%保証と扱わない。

## H07: 事例へ戻る

集計に使った全sampleのid、windowEnd、条件値、結果値、resolved/censored/reasonをpageで読める。上限による省略を「全件」と呼ばない。exportは集計と同じquery/dataRevision、件数とdigestを付ける。結果CSVは注釈textのformula injection対策を行う。
