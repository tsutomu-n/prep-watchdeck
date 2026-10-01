# 最新版のmain統合

timestamp="2026-10-02(金)_08:03 JST"
- 作成: `2026-10-02T07:33:51+09:00`
- 更新: `2026-10-02T08:03:03+09:00`
- 状態: `実装計画`

---

## Goal / scope

現在配置済みのsourceと修正を、既存GitHub repositoryのmainへ統合する。
PR作成とCI実行はユーザーが明示禁止。既存変更を保持して統合する。
GitHub mainのPR必須・verify必須を一時変更する場合は、設定変更への明示許可を得てから行う。
DB・credential・Tailscale ACL・本番serviceは今回のmerge作業では変更しない。

## Checkpoint

- ローカルmainと既存作業branchを5c51126へfast-forward済み。GitHub mainは4daa37b。
- 隔離gate: repository 18、Market 165、Ranking 124、Web 170、型・buildはpass。
- 初回E2EのMobile 6 failを解消。最終Desktop / Mobile E2E全90件、Web 170件、check/buildがpass。
- ローカルcheckのlog: `/tmp/prep-watchdeck-main-merge-154a177.log`（初回）、`/tmp/prep-watchdeck-main-web-final.log`（修正後）。実DBは触らず、専用の一時Postgresを終了済み。
- source修正は再読込後の履歴正常化、監査index後着時の初期読込。テストのscroll event待ちと詳細遷移も修正。
- 独立したUI/securityレビューとquality/schema/DBレビューにsourceのマージ阻害事項なし。
- GitHubのProtect main（20273827）はactive、PR/verify必須、bypassなし。
- PR/verifyの2条件だけを一時解除し、更新後に元へ戻す案と復元payloadを`/tmp/prep-watchdeck-direct-main-review/`へ準備済み。GitHub設定は変更していない。

## 完了条件 / verification

Mobileの失敗原因を修正し、関係するDesktop / Mobile E2EとWeb check/buildを通す。
今回の修正だけをcommit/pushし、ローカルmainと既存GitHub作業branchを同じsourceへ揃える。
main保護設定変更の明示許可後、[skip ci]付きHEADを使ってCIを起動せずfast-forward pushし、保護復元とorigin/mainを照合する。
PR作成・CI実行・force push・保護の恒久解除は行わない。

## Rollback / unresolved

既存release 154a177を保持する。merge作業でdeployしない。
修正は独立commitとし、問題があれば逆差分で戻す。既存branchやuser stateを削除しない。
未完了はGitHub mainの更新。保護2条件の一時変更許可と実スマホ受入は未確認。
CI skipは通常のpush/pull_request workflowに適用するため、write直前にworkflow triggerを再照合する。
