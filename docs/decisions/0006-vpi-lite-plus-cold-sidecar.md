# Decision 0006: VPI-Lite+をCold snapshotの補助sidecarに限定する

- 作成: `2026-07-19T15:39:27+09:00`
- 更新: `2026-07-19T15:39:27+09:00`
- 状態: `設計判断`

---

## 決定

VPI-Lite+ V0は、`watchdeck service`が生成するCold snapshotでだけ計算する。
closed 1分足を入力にし、`summary.vpiLitePlus`を正本、存在するrowの
`display.vpiLitePlus`を表示用の任意複製とする。

VPI scoreとstateを既存main ranking、filter、category、attention scoreへ入れない。
1 symbolの計算失敗は隔離し、既存snapshot発行を止めない。

## 理由

VPIは異常な市場活動を見つける補助情報であり、価格方向や将来収益を予測する主張ではない。
既存scanner判断と更新頻度を変えずに導入し、Cold/Hot laneの責任境界と単一DuckDB writerを
維持する必要がある。

## 帰結

- configはservice起動境界で一度だけ読み込む。
- 5分足集約前のclosed 1分足だけをVPIへ渡す。
- benchmarkはscanner rowがなくてもsummaryへ出せる。
- 内部pressure、diagnostics、raw barsを公開payloadへ含めない。
- config未指定、disabled、通常scanではVPI blockを追加しない。
- UIは高scoreを売買推奨として表現しない。
