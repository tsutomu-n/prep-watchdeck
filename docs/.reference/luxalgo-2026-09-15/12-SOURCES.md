# 参照元・利用条件・証拠の限界

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `参考`

---

## 固定したコード参照

以下は実際に取得したrevision。取得範囲・blob SHAはsources.lock.jsonに記録。最新mainと同じかは実装開始時に確認し、差があれば対象箇所だけ再評価する。star数や更新頻度は採否の根拠にしない。

- [LuxAlgo/edge-stats / packages/core/src/stats/stats.ts](https://github.com/LuxAlgo/edge-stats/blob/7cfa6d52f561e2c764ba900252e80356b03af9fe/packages/core/src/stats/stats.ts)
- [LuxAlgo/edge-stats / packages/core/src/query/execute.ts](https://github.com/LuxAlgo/edge-stats/blob/7cfa6d52f561e2c764ba900252e80356b03af9fe/packages/core/src/query/execute.ts)
- [LuxAlgo/whale-options / packages/core/src/score/score.ts](https://github.com/LuxAlgo/whale-options/blob/11f9c072827426f100193102a64451278787825b/packages/core/src/score/score.ts)
- [LuxAlgo/market-trackers / docs/market-trackers-data.md](https://github.com/LuxAlgo/market-trackers/blob/9bf1045b6953e42a56f112445481d411a92261c9/docs/market-trackers-data.md)
- [LuxAlgo/market-trackers / packages/core/src/schema/datasets.ts](https://github.com/LuxAlgo/market-trackers/blob/9bf1045b6953e42a56f112445481d411a92261c9/packages/core/src/schema/datasets.ts)
- [LuxAlgo/market-trackers / packages/core/src/schema/fed-communication.ts](https://github.com/LuxAlgo/market-trackers/blob/9bf1045b6953e42a56f112445481d411a92261c9/packages/core/src/schema/fed-communication.ts)

Watchdeck基準は [9b83b531のtree](https://github.com/tsutomu-n/prep-watchdeck/tree/9b83b5313271e7a76a53e3a06241ee010446f58e)。具体的な既存path/blob/読取り範囲はsources.lock.json。今回確認していない既存の細部は01でその旨を区別した。

## 公式の意味・条件

- [Senate eFD利用条件](https://efdsearch.senate.gov/search/home/)：商業目的等への利用制限の表示を確認。報道等の例外をすべてのランキングサービスへ拡張解釈しない。
- [FINRAのshort-sale volume説明](https://www.finra.org/rules-guidance/notices/information-notice-051019)：short interestではなく、off-exchangeのカバレッジ等にも注意が必要。
- [CC0 legal code](https://creativecommons.org/publicdomain/zero/1.0/legalcode.en)：付与者が保有する権利の範囲と、他の制限を区別する。

法的適法性を保証する資料ではない。使用目的と適用条件が未確定のsourceを、OSSライセンスだけで有効化しない。

## 検証区分

実施：GitHub API経由の既存コード/文書/schema/ruleset読取り。今回の資料へ採用する数値反例の独立計算。新規資料のmetadata/link/fixture検査。

未実施：全上流テスト、全Watchdeckテスト、実市場の収益性、本番サービス状態、当日のFed配布物の稼働保証。環境からGitHub cloneはDNS解決に失敗したため、ソース確認にはGitHub連携を使用した。

過去回答のsandbox検証結果やcitation番号を唯一の根拠にしない。今回のfixturesは仕様の人工例であり、上流を実行したログでもWatchdeck完成試験でもない。特定の古いmanifest時刻を永久の障害判定として固定せず、「期限経過を受信側で再計算する」という要件を残す。

## 再利用方針

このパックは独自の要件・設計・数値例であり、上流の全文ソースや有償指標を同梱しない。実装担当がコードをコピーする場合は対象revisionのLICENSE/NOTICEを確認し、必要な表記を保持する。PineTSを別processへ置くだけでAGPL義務を回避できるとは考えない。
