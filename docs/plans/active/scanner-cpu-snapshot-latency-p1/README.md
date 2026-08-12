# Scanner CPU・snapshot遅延 P1計測計画

- 作成: `2026-08-12T22:32:36+09:00`
- 更新: `2026-08-13T00:42:02+09:00`
- 状態: `完了`

---

## 結論

本計画は限定改善を採用して完了した。snapshot buildが支配区間だと確認し、DBの5分足集計をscanner対象銘柄と
BTC基準銘柄だけに限定した。最終live 3周期ではbuild 23.573/37.506/39.5秒、artifact 6.6〜7.3秒、
公開間隔は約107〜110秒だった。Bitget scan、Perp比較、OI、chart、single writerは維持した。

CPU高負荷は未解決である。最終20秒sampleはCPU 76.60%、RSS 425,041 KiBで、reconcile実行中だった。
約2分のsnapshot更新を実用上許容し、追加のprofiler、長時間観測、微最適化、再起動は行わない。

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

1. `publish_service_snapshot_once`へ`buildMs`と`artifactPublishMs`だけを出す1行の低overhead logを追加する。
2. 同じworkerの2周期で、区間時間、公開間隔、CPU/RSS、row/chart件数を対応付ける。
3. 最大寄与が2周期で一貫する場合だけ、その区間を最小変更で修正する。
4. snapshot外でもCPUが1 core相当続く場合はthread CPUと既存loopだけを1回確認し、明白なhot pathだけを修正する。
5. 修正後は関連test/lint/typecheckとlive 2周期で、snapshot、Perp比較、OI、single writerを確認する。

## 対象外

- detail chart削除、旧3市場比較削除、rolling state導入
- DB migration、別writer、現役DBへのprofiler用writer接続
- 関数ごとの詳細計測、外部profiler、3周期以上の研究的計測
- scheduler変更、72時間soak、注文・秘密API、製品機能の全面変更

## 完了条件

- 2 cycleで`buildMs`と`artifactPublishMs`、worker CPU/RSS、公開間隔を取得する。
- 最大寄与区間を数値で特定する。2周期で一貫しない場合は実装修正せず停止する。
- 修正する場合、変更前後の2周期で支配区間または公開間隔が改善する。
- Bitget scan、Perp比較、OI 60分、reconcile、single writerを維持する。
- OIが全件`UNKNOWN`の場合を正常データとして数えず、ticker鮮度切れ、exact reference欠損、処理障害を
  区別できる証拠を残す。

## 停止条件

- 計測のために現役DBへ別writerを接続する必要がある。
- snapshot、Perp比較、Web healthが退行する。
- 計測overheadで通常cycleの判断ができない。
- 2周期で支配区間が一致しない、または修正がDB schema・別writer・chart契約変更へ広がる。

## Checkpoint

- CP-01 完了: `service_snapshot.py`へ2区間の成功時logを追加した。
- CP-02 完了: live 2周期でbuildがartifactの3.6〜5.5倍と確認した。
- CP-03 完了: scanner対象銘柄だけを5分足集計する変更は維持した。CPU hot path修正は停止条件で中止した。
- CP-04 完了: final diff、数値、revert、残リスクを本書と`.codex/SP_STATE.md`へ記録した。

## 開始時判断

2026-08-12 23:29 JSTのartifactでは335 chart JSONのmtime幅は2.731秒だった一方、snapshotの
`generatedAt`から`latest.json`公開までは約171秒だった。buildまたはchart変換開始までが主因と推定するが、
mtimeだけでは区別できないためCP-01の2区間計時を実施する。reconcileは746件中558件で継続中のため、
CPU単独sampleを定常状態とは扱わない。

## 実装結果

最終差分は次の4点に限定した。

1. snapshot成功時に`runId`、row数、`buildMs`、`artifactPublishMs`を1行logへ出す。
2. snapshotで必要な5分足を、scanner対象銘柄とBTC基準銘柄だけDuckDBから集計する。
3. 既存window分離testで、DBへ渡す銘柄集合を固定する。
4. 実DuckDBのregression test 1件で、指定外銘柄を5分足集計から除外することを固定する。

変更前live 2周期はbuild 32.204/49.166秒、artifact 8.938/8.993秒だった。最終live 3周期は
build 23.573/37.506/39.5秒、artifact 6.6〜7.3秒、公開間隔は約107〜110秒だった。変更前との
先頭2周期の比較ではbuildが約27%/24%短縮した。ただしcycle内の外部API・reconcile位相は完全には同一でなく、
将来周期へ同率の改善を保証しない。

## Revertした試行

正常時stream healthのthrottleとDuckDB root connection・thread-local cursorの再利用を組み合わせた試行は、
WS開始後のperiodic buildを186.401〜242.356秒へ悪化させたため全てrevertした。
thread sampleと周期差はWS取込みとDB lock競合の関与を示すが、各試行を独立比較していないため個別変更との
因果は未確認である。DB schema、ticker runtime契約、Webは変更していない。

## 最終runtime

- scanner: MainPID 3372491、worker 3372511、`active/running`、`NRestarts=0`
- Web: MainPID 3867001、`active/running`、`NRestarts=0`、health OK
- DuckDB opener: worker 3372511の1プロセス
- snapshot: 334 rows / 334 charts、`snapshotStatus=OK`
- Perp比較: 161件すべて`ready`
- OI: sampled 746 / references 745
- reconcile: 746件中49件、error 0で実行中
- CPU/RSS 20秒平均: 76.60% / 425,041 KiB

restartは進行中snapshotの終了待ちで52〜92秒を要し、一部試行はsystemdの90秒timeoutでSIGKILLされた。
最終構成へのrestartは52.1秒で完了し、以後restart loopはない。停止遅延も未解決である。

## 終了判断

snapshot buildは小幅に改善したが、CPU高負荷は未解決である。現状の約2分更新でPerp比較を実用できるため、
本計画ではこれ以上CPUを追わない。約2分更新が製品上の問題になった場合だけ、60秒sleep後にbuildを始める
scheduler契約を別の製品判断として扱う。scheduler変更はCPU負荷を上げ得るため、本P1へ混ぜない。
