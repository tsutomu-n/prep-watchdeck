# 最新版のmain統合

timestamp="2026-10-02(金)_07:42 JST"
- 作成: `2026-10-02T07:33:51+09:00`
- 更新: `2026-10-02T07:42:14+09:00`
- 状態: `実装計画`

---

## Goal / scope

現在配置済みのsourceと修正を、既存GitHub repositoryのmainへ統合する。
既存変更を保持し、main保護、PR必須、verify必須を迂回しない。
DB・credential・Tailscale ACL・本番serviceは今回のmerge作業では変更しない。

## Checkpoint

- ローカルmainを154a177へfast-forward済み。GitHub mainは4daa37b。
- 隔離gate: repository 18、Market 165、Ranking 124、Web 170、型・buildはpass。
- 初回E2EのMobile 6 failを解消。最終Desktop / Mobile E2E全90件、Web 170件、check/buildがpass。
- ローカルcheckのlog: `/tmp/prep-watchdeck-main-merge-154a177.log`（初回）、`/tmp/prep-watchdeck-main-web-final.log`（修正後）。実DBは触らず、専用の一時Postgresを終了済み。
- source修正は再読込後の履歴正常化、監査index後着時の初期読込。テストのscroll event待ちと詳細遷移も修正。
- GitHubのactive rulesetはPRとverify必須、bypassなし。PR禁止とCI未許可を解消する明示指示が必要。

## 完了条件 / verification

Mobileの失敗原因を修正し、関係するDesktop / Mobile E2EとWeb check/buildを通す。
今回の修正だけをcommit/pushし、ローカルmainとPR候補を同じsourceへ揃える。
PR作成と必須CI利用の許可後、verify成功、通常merge、origin/main照合まで行う。

## Rollback / unresolved

既存release 154a177を保持する。merge作業でdeployしない。
修正は独立commitとし、問題があれば逆差分で戻す。既存branchやuser stateを削除しない。
PR作成・必須CIの利用許可と実スマホ受入は未確認。
