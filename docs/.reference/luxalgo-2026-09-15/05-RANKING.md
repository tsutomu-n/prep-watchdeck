# ランキングの確定仕様

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## R01: 比較対象

各active instrumentを独立評価する。group化されていないことだけで除外しない。同じVenue、quote、asset class、market type、価格basis、profile/windowのscope内で順位付けする。USD/USDT/USDC換算、Venue間OI足し合わせ、同名symbol統合はしない。scopeを変えてもscore値の意味は固定、rankはscope内の順序である。

## R02: 完了足と窓

windowEnd=tは完了した分境界。p(t)は `[t-1m,t)` の終値。r60=p(t)/p(t-60m)-1には `[t-61m,t)` の61本を要求。r15には `[t-16m,t)` の16本を要求。全足が同じinstrument versionで連続し、OHLC整合、正価格、許容finality、observedAt<=asOfを満たすこと。missing minuteを前値・線形補間・0で埋めない。

相対出来高はcurrent=sum(base volume, `[t-15m,t)`)を、直前20個の非重複15分volume窓の中央値で割る。比較期間は `[t-315m,t-15m)`、現在窓を含めない。全315本のvolumeが既知・非負・同単位でbaseline median>0のときのみ有効。baseline=0は無限大・満点ではなくunavailable。

許容finalityは確認済みconfirmed/derived_final。raw feedが違う価格basisを混ぜる場合は別scope。足数だけで連続性を判定せずtimestamp重複・穴を検査する。

## R03: 計算式

`c(x)=min(1,max(0,x))`。以下は経験的優位を推定した係数ではなく、固定の説明可能な設計値。

| profileId | 必須入力 | score（0〜100） |
| --- | --- | --- |
| momentum-1h-up | r60 | 100*c(r60/0.05) |
| momentum-1h-down | r60 | 100*c(-r60/0.05) |
| attention-15m | r15、volumeRatio | 50*c(abs(r15)/0.02)+50*c((volumeRatio-1)/2) |

attentionのcomponentはprice/volumeそれぞれ最大50点。momentumの逆方向は有効な0点であり欠測ではない。scoreは並べ替え前には丸めず、UIだけ小数1桁。RANKの算術はDecimalか誤差境界を検証した一貫実装を使い、JSONは有限数値に限定する。

profile revisionには式、係数、足basis、必要本数、finality、鮮度、sampling policyを含めhash化する。schemaVersionとcalculationVersionは別概念。

## R04: 欠測と順位

必要入力が一つでもmissing/stale/invalid/未確認単位ならscore=null、rank=null、reason付き。残った重みへ再配分しない。必要でないOI/Funding欠測を理由に価格profileまで除外しない。成分の使用可否はfield-levelで評価し、rowのpartialだけで一括排除しない。

有効score降順の競技順位（100,100,80なら1,1,3）。同点内の表示順はvenueInstrumentIdの辞書順で固定する。score同点に浮動小数の偶然が影響しないようDecimal表現または定義したcanonical quantizationを使い、採った方法を計算versionに記録する。

catalogやsource失敗でscopeの対象集合が確定できない場合、個別の参考scoreは表示できるがrankはnull、comparisonComplete=falseとする。通常の履歴不足除外はeligibleCount/activeCountを示して、適格集合内の順位として表示する。この2種類の不足を区別する。

## R05: 更新停止

期限切れ・future clock・producer failure時は新しい順位として表示しない。最後の検証済みsnapshotを参考として残す場合は「更新停止・保存時点」を近接表示し、数値を現在値に見せない。古いscoreで新着強調・新規候補イベントを作らない。

## R06: 保存と検証

入力窓の端、used values、source payload/row hashes、asOf、calculation definitionをimmutable snapshotに含める。価格方向・候補順位は注文命令ではない。比較理由を表示するために勝率の捏造やLLM採点を加えない。数値例はfixtures、境界試験は11参照。
