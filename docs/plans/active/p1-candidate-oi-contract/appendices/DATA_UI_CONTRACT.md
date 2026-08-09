# 06 データ・UI契約

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 変更後の責務

### Candidate

- 74h複合条件を満たしたrowだけ。
- active thresholdはsnapshot `summary.candidateRule74h`から表示し、UIへhardcodeしない。
- 4 rankingの内容と時間軸切替は維持。
- 履歴不足rowはCandidateへ出さない。
- 条件を満たさないrowはWatchlistで引き続き確認可能。

### Watchlist

変更しない。

- 新しいOI列を追加しない。
- Hot ticker更新範囲を変えない。
- Raw Sort、view、category、selectionを変えない。

### Selected detail / Symbol Monitoring Rail

次だけを追加する。

```text
OI 60分
増加 / 横ばい / 減少 / 履歴不足
```

label例:

```text
INCREASING -> 増加
STABLE -> 横ばい
DECREASING -> 減少
UNKNOWN -> 履歴不足
```

「強気」「弱気」へ翻訳しない。OI変化は方向予測ではない。

### Attention Score help

```text
15m価格変化、15分出来高倍率、1h売買代金、BTC相対、OI 60分変化、データ品質、risk tagから作る軽量な見る優先度です。OI履歴不足時はOIを加点しません。売買判断ではありません。
```

## Snapshot / schema

既存fieldを利用する。

- `userRule74hMatched`
- `openInterestState`
- `reasonCodes`
- `summary.candidateRule74h`（optional summary metadata）

新しいrequired fieldを追加しない。schemaVersionは維持する。

## Version contract

意味が変わるため、次を必須とする。

```text
featureVersion = 3  # OI 60m feature semantics
rulesetVersion = 3  # 74h AND / Candidate gate semantics
```

## Fail-closed

- Candidate: `userRule74hMatched is True`のみ。
- OI: exact referenceなしはUNKNOWN。
- invalidまたはstaleなcurrent OI sampleは保存しない。
- UIはUNKNOWNを空欄にせず、履歴不足と表示する。
