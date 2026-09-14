# 資料の検証範囲と配置

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `検証記録`

---

## 調査と実変更の区別

GitHub連携で基準HEAD、既存コードの関係範囲、AGENTS、現行文書、上流の固定revisionを読んだ。範囲はsources.lock.json。既存ソースの全面監査や全機能試験をしたものではない。

今回の変更は `docs/.reference/` 内の文書・参照lock・人工数値例・資料検査スクリプトのみ。アプリ、依存、既存schema、migration、root規約、CI、本番DB/serviceを変更しない。資料に示した新module/API/profileは、Codexが実装する要求であり実装済み機能ではない。

## 資料検査

`python docs/.reference/luxalgo-2026-09-15/verify_reference.py` は次だけを検査する。

- 16 MarkdownのH1、先頭metadata、相対リンク、行末空白
- JSONの読込み、固定hash形式、34受入IDとの一致
- 独立した人工入力によるscore 6例、Wilson 2例、guard 6例
- 重み欠測の80→100と、80%/40%の区間重複という算術反例

実行結果は検査コマンドがJSONで出力する。資料の独立した数値照合であり、LuxAlgoの原コード実行でもWatchdeckの34実装試験の実行でもない。実装担当は同じfixtureを実製品の入口/出口でも検証する必要がある。

GitHubからのcloneはこの検証環境のDNS解決に失敗したため、repo全体の公式Bun文書gate、pytest、build、E2Eは今回未実行。隔離した資料stagingでリンク・metadata・数値例とGitの差分空白を検査する。実市場の収益性、長期統計、本番運用は検証していない。

## ブランチ

調査時 `main` のruleset `20273827` はPRとverifyを要求し、連携はbypass不可。mainを直接更新したり保護を解除したりせず、`ai/luxalgo-reference-20260915-0837` へ資料を直接コミットする。PRは作成しない。mainに反映済みと報告しない。

Codex開始時は資料ブランチ上か、資料の取り込み済み作業treeかを確認する。未コミット変更があるtreeへforce checkout/resetしてはならない。資料を読むだけならGitHubの当該branchから取得できる。本番反映や以後のcommit/pushの許可は、今回の資料配置への許可から自動継承しない。
