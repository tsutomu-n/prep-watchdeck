# Visual QA 手順

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## Viewports

| Name | Size |
|---|---|
| Desktop | 1440×900 |
| Narrow desktop | 960×900 |
| Breakpoint | 560×900 |
| Mobile | 390×844 |
| Minimum | 320×800 |

## 確認タスク

1. 候補から3銘柄を選ぶ。
2. Watchlistで1銘柄を選択する。
3. Inspectorで15m / 1h / 4h、phase、OI、74h、警戒理由を読む。
4. 補正順位の元順位と理由を読む。
5. Candidate直下のVPI laneでcoverageを確認し、銘柄を選択する。
6. STALE / PARTIAL fixtureで異常表示を確認する。

## 合格

- DesktopでCandidate 4観点が同時に見える。
- Mobileで1tap切替でき、内部長距離scrollが不要。
- 横scrollなし。
- categoryと異常状態を色なしでも判別できる。
- Scoreより市場事実が先に読める。
- Candidate / Watchlist / Inspectorの主従が明確。
