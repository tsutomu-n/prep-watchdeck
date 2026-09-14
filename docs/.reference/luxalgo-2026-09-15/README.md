# LuxAlgo参照・Watchdeck完成実装パック

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `参考`

---

## このパックで完成させるもの

既存Watchdeckへ「説明可能な銘柄発見 → 判断時点の記録 → 過去の条件付き発生率の検証」を実装する。LuxAlgo製品群の複製ではない。現在のPerp実データで動く完成機能と、実データ契約に接続したFed公表情報の補助表示を対象とする。

計算関数だけ、CLIだけ、fixtureだけ、見た目だけ、既定OFFの未接続コードで完了としない。契約・保存・producer・Web API・UI・再起動・異常系・運用手順を接続する。収益性や将来の勝率は保証せず、機能完成と収益性の実証を別に扱う。

## 読む順序

| 資料 | 内容 |
| --- | --- |
| [00-CODEX-IMPLEMENTATION.md](00-CODEX-IMPLEMENTATION.md) | 実行指示、権限境界、中断再開、終了条件 |
| [01-REPOSITORY-MAP.md](01-REPOSITORY-MAP.md) | 確認済み既存コードと新設候補の対応 |
| [02-AUDIT-AND-DECISIONS.md](02-AUDIT-AND-DECISIONS.md) | 上流の反例、採否、前回答の訂正 |
| [03-PRODUCT-ACCEPTANCE.md](03-PRODUCT-ACCEPTANCE.md) | 今回の完成範囲とユーザーフロー |
| [04-DATA-AND-STORAGE.md](04-DATA-AND-STORAGE.md) | identity、時刻、永続化、成果物の契約 |
| [05-RANKING.md](05-RANKING.md) | 計算式、入力窓、欠測、順位と比較可能性 |
| [06-HISTORICAL-STUDIES.md](06-HISTORICAL-STUDIES.md) | 分母、結果、打切り、区間、選択バイアス |
| [07-PUBLIC-EVIDENCE.md](07-PUBLIC-EVIDENCE.md) | 実際のFedデータ形式、取得、改訂、利用条件 |
| [08-API-AND-UI.md](08-API-AND-UI.md) | API、ジョブ、画面、保存、アクセシビリティ |
| [09-IMPLEMENTATION-SEQUENCE.md](09-IMPLEMENTATION-SEQUENCE.md) | 全作業単位、依存、成果物、完了証拠 |
| [10-OPERATIONS.md](10-OPERATIONS.md) | 移行、容量、実データ検証、復旧、展開境界 |
| [11-TEST-MATRIX.md](11-TEST-MATRIX.md) | 要求ID別の受入試験 |
| [12-SOURCES.md](12-SOURCES.md) | 固定参照・一次資料・未確認事項 |
| [13-DELIVERY-VERIFICATION.md](13-DELIVERY-VERIFICATION.md) | 資料自体の検証範囲と配置事情 |
| [sources.lock.json](sources.lock.json) | 確認したrevision・blob・範囲 |
| [fixtures/acceptance-cases.json](fixtures/acceptance-cases.json) | 人工入力による独立した数値例 |
| [verify_reference.py](verify_reference.py) | 文書リンク・metadata・数値例の検査 |

表の全資料が対象。参照先URLだけで実装内容を推測せず、本パックの具体的契約を読む。

## 基準と配置

対象 `tsutomu-n/prep-watchdeck`、調査基準HEAD `9b83b5313271e7a76a53e3a06241ee010446f58e`。資料は `docs/.reference/luxalgo-2026-09-15/` 内に集約する。古い会話の仮定より、開始時の実コードと現行文書を再確認する。

`main`はPR必須・連携のbypass不可。今回の資料は `ai/luxalgo-reference-20260915-0837` へ直接コミットし、PR・保護設定変更・本番変更は行わない。これはリポジトリへの実書込みであり、mainへの反映ではない。

## 用語

「要求」は今回実装する契約。「既存」は基準HEADで確認したもの。「新設候補」は未作成の配置案。「未確認」は実行・取得していないもの。分割作業番号やschemaのversionは互換性管理であり、プロトタイプ止まりを認める意味ではない。
