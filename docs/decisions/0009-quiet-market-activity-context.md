# Decision 0009: Quiet Market activity context

- 作成: `2026-08-10T23:10:43+09:00`
- 更新: `2026-08-11T05:16:48+09:00`
- 状態: `設計判断`

---

## 決定

15分量倍率の既存計算を、同じ5分sampleとrolling median定義の1時間・4時間windowへ拡張する。
1時間と4時間の値は選択銘柄の文脈表示だけに使い、Candidate、Raw Sort、補正順位、category、
attention scoreを変更しない。公開snapshotは`featureVersion=4`、`rulesetVersion=3`、
`schemaVersion=1`とする。

3つの量倍率から`BURST / EXPANDING / SUSTAINED / COOLING / NORMAL / UNKNOWN`を導く。
判定はUNKNOWN、COOLING、SUSTAINED、EXPANDING、BURST、NORMALの順で行う。activity phaseは
表示専用であり、市場方向や売買推奨を示さない。通常品質と`NORMAL` phaseは一覧で省略し、
異常品質と非通常phaseだけを日本語で明示する。

## VPI discovery lane

既存`summary.vpiLitePlus.targets`だけをCandidate近傍の発見laneへ使う。Benchmark、Watchlist全銘柄、
新しいVPI計算は対象にしない。活動増加と要注意へ分類し、score降順で各5件まで表示するが、scoreは
laneへ表示しない。発見buttonは現在のWatchlist表示条件に含まれ、そのまま選択できるTargetに限定する。
coverageと、対象なし・表示条件該当なし・活動急増なし・データ不足の4つの空状態を明示する。
選択銘柄detailのscore、reason、risk、funding、OI availabilityは維持する。

## 互換性とrollback

`activityPhase`はoptional fieldで、既存readerは追加propertyとして扱える。1h/4h量倍率が欠ける旧snapshotは
phaseを判定不能として安全に表示できる。rollbackはfeature 4 producerとconsumer表示を戻すだけでよく、
DB migration、private API、取引API、保存データの削除は伴わない。
