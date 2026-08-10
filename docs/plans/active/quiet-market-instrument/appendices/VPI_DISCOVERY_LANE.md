# VPI 活動発見レーン契約

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## 目的

VPI-Lite+の既存計算結果を、選択後の詳細だけでなく、発見用の狭いlaneへ出す。

## 境界

- 対象symbol、Score、threshold、state計算を変更しない。
- `VPI対象 N / Watchlist M銘柄`を明示する。分母不明時だけ`VPI対象 N銘柄`とする。
- 市場全体のcoverageと表現しない。
- Candidate ranking、Attention Score、filter、categoryへ入れない。

## 表示

### 活動増加

- EARLY_ACTIVITY
- ACTIVE_MOVE
- score降順、最大5件

### 要注意

- THIN_VOLATILITY
- SINGLE_BAR_SUSPECT
- score降順、最大5件

CALMとdata error stateは銘柄listへ出さず、Inspectorで確認する。valid対象があり該当0件なら`活動急増なし`、対象0件または全件invalidなら`VPI判定対象なし / VPIデータ不足`と表示する。

## 操作

rowを選ぶと既存selected symbolだけを更新する。新しいnavigation、alert、trade actionは追加しない。
