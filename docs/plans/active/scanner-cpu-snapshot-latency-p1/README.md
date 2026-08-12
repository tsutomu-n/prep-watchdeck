# Scanner CPU・snapshot遅延 P1計測計画

- 作成: `2026-08-12T22:32:36+09:00`
- 更新: `2026-08-12T22:56:57+09:00`
- 状態: `実装計画`

---

## 結論

74時間Candidateと常駐deep backfillのパージ後も、scanner workerのCPU高負荷は残った。次のP1は
推測でchartや旧3市場比較を削除せず、同じlive workerのsnapshot cycleを対象に、処理区間別の時間と
CPUを計測して最大寄与を特定する。

このP1は性能改善の実装計画ではなく、削除・最適化対象を一つに絞るための原因計測計画である。

## 現在の証拠

| 項目 | パージ前 | パージ後 |
|---|---:|---:|
| `pidstat -r -u -p worker 1 20` CPU平均 | 78.95% | 93.25% |
| 同RSS平均 | 2,512,282 KiB | 572,110 KiB |
| 連続snapshot公開間隔 | 194.810秒 / 220.894秒 | 105.225秒 / 126.055秒 |
| row / chart件数 | 329/329、329/329、327/327 | 337/337、336/336、336/336 |
| Perp比較 | 各161件 | 各161件ready |

CPUの20秒sampleは上がり、RSSとsnapshot公開間隔のsampleは下がった。ただし変更後sampleはreconcile
実行中で、cycle内の位相を揃えていない。悪化・改善率や機能差との因果は判定できない。現行codeには
snapshot build durationの区間計測がない。

## 対象

1. worker全体のCPU duty cycleを、snapshot、reconcile、stream/ticker、Perp/旧3市場collectorへ分ける。
   パージ後の20秒sampleはreconcile実行中だったため、CPUをsnapshotだけへ帰属させない。
2. snapshot cycleを、DuckDBからのchart source集計、analysis row生成、gap audit、OI、VPI、
   schema/DTO構築、chart JSON生成、snapshot writeへ区切って経過時間を記録する。
3. 同じworker PIDで、reconcile実行中/停止後を分けた複数cycleのprocess CPU time、RSS、公開間隔、
   row/chart件数を対応付ける。
4. Perp collectorと旧3市場`marketComparison`は別周期・別network処理として時間を記録し、snapshot CPUと
   混同しない。
5. ticker refreshの最終成功時刻・失敗、OI `sampled/references`も同じ時系列へ記録する。Bitget ticker更新が
   2周期失敗した場合の`sampled=0`と、exact 60分前bucket欠損による`sampled>0 / references=0`の両方で、
   OIは全件`UNKNOWN`だが`oiDiagnostics.status="ok"`だった。CPU計測中のデータ状態を誤認しないために
   両者を区別する。
6. 最大寄与が再現した区間だけを、削除・SQL化・incremental化の次計画候補にする。

## 対象外

- 計測前のdetail chart削除、旧3市場比較削除、rolling state導入
- DB migration、別writer、現役DBへのprofiler用writer接続
- 72時間soak、注文・秘密API、製品機能の全面変更

## 完了条件

- 同一条件の3 cycle以上で区間別時間、worker CPU time差分、RSS、公開間隔を取得する。
- 最大寄与区間を数値で特定するか、特定不能なら不足する計測点を明記する。
- Bitget scan、Perp比較、OI 60分、reconcile、single writerを維持する。
- 改善実装へ進む場合は、対象区間と期待効果を限定した別checkpointを作る。
- OIが全件`UNKNOWN`の場合を正常データとして数えず、ticker鮮度切れ、exact reference欠損、処理障害を
  区別できる証拠を残す。

## 停止条件

- 計測のために現役DBへ別writerを接続する必要がある。
- snapshot、Perp比較、Web healthが退行する。
- 計測overheadで通常cycleの判断ができない。

## 最初にやること

まず既存logとservice stateでreconcile実行中/停止後のCPU duty cycleを各3分だけ比較する。その差だけで
説明できない場合に、`application/service_snapshot.py`と`application/chart_artifacts.py`の既存処理境界へ
低overheadなduration logを追加し、同じworkerの3 cycleだけ採取する。広いprofilerや全面refactorから
始めない。
