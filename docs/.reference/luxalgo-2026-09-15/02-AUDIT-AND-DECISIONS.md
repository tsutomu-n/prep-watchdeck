# LuxAlgo監査結果と採否

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `参考`

---

## 前提の訂正

公開式、determinism、良い文書、star数だけでは統計的妥当性や本番品質を立証しない。過去回答の「Historical Edge 68%、N=417」等は説明用の架空例であり成果ではない。Watchdeckにはquality/provenance/atomic publishの方針が既にある。追加frameworkを正当化する材料にしない。

参照URLとrevisionは12とsources.lock.json。以下の計算例は人工入力で、実相場の成績ではない。

| ID | 確認・推論 | 今回の決定 |
| --- | --- | --- |
| A01 | whale `computeScore`は欠測成分を除いて重みを再正規化する。重み0.2の0点成分を欠測にすると、残り満点の例で80→100となる | 寄与・元入力の公開は採用。異なる入力集合の総合点比較は採用しない |
| A02 | edge `stabilitySplit(10,8,10,4)`は区間の重なりでagree=trueとなる | 重なりを「安定」と表示しない。非棄却と同等性を区別する |
| A03 | edge executorのoverall guardとperYear/groups/recencyの出力経路は同一でない | すべての表示・exportへ共通の最小標本guardを適用 |
| A04 | recencyWindowは条件一致後のrow_numberで切る | 「直近N日」と「直近N一致事例」を型・query・UIで区別 |
| A05 | 終日の発生率を途中時刻からの到達確率と読むのは別の問い | decision-timeの条件とforward horizonを固定。未完成結果は打切り |
| A06 | 過去の監査ではsyncError後もlive評価が継続する経路が指摘された。今回live全経路の再実行はしていない | upstream固有不具合と断定せず、Watchdeckの鮮度・通知抑止試験として採用 |
| A07 | producerのmanifestにあるstaleは生成時の判定。現在の時間経過を更新しない | consumer側で生成・最終sync時刻を再判定。古いfalseを信じない |
| A08 | 公開dumpはingestion-day deltaで、snapshot/深いarchiveは別。過去年ファイルの存在だけでは完全性を保証しない | latestだけで全履歴を表現しない。欠けた期間・coverageを返す |
| A09 | Senate利用条件には商業利用の制限、CC0は他の権利等の解消を保証しない | Congressの自動取得・加点は採らない。利用条件確認はsourceごと |
| A10 | FINRA daily short volumeはshort interest残高ではない | 空売り圧力・squeeze確率へ無検証変換しない |

## 採用する範囲

whaleからは「成分、入力、欠測理由」を、edgeからは「分母・分子、query定義、個々の事例へ戻る」仕組みを、market-trackersからは「原典・改訂・取得時点・source health」を借りる。実装は既存Python/Polars基盤へ合わせる。上流コードの全コピー、上流scoreの移植、上流UIの置換はしない。

PineTS/AGPL、VelaのNOTICE、brokerのcredential/約定照合、journalのexecution lifecycleは別の採用判断。ネットワーク分離やadapter化だけでライセンス義務が消えるとは扱わない。今回これらを導入しなくても本パックの完成条件は満たせる。

## 仮説と出荷条件を混ぜない

既定の重み・閾値は説明可能性と実装の確定性を優先した設計値であり、利益最大化を検証した値ではない。これを明示した発見機能は出荷できる。収益優位を主張する変更は、時系列holdout、固定した比較対象、手数料・funding・slippage、探索回数を別途検証してから行う。
