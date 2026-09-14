# Test suite streamlining plan

- 作成: `2026-09-14T19:57:55+09:00`
- 更新: `2026-09-14T19:57:55+09:00`
- 状態: `実装計画`

---

## Goal

現役のデータ整合性・DB安全性テストを維持しつつ、旧P0移行専用、見た目の固定、source文字列固定、重複E2Eを整理する。
PRでは変更範囲に近いgateだけを実行し、main pushでは全系統を実行する。

## Scope

- 旧P0 shadow / capacity qualification testと専用実装の退役
- retired-record archive test/toolの退役
- Webのsource文字列固定test削除
- theme/font contract testの統合と固定個数/順序assert削除
- chart theme / product boundary / web-port testの縮小
- docs metadata/link unit testの統合
- Playwright defaultをdesktop smokeへ縮小し、full時だけmobileも実行
- GitHub Actionsをpath-awareなPR gateへ変更
- `verify-local.sh`、validation docs、READMEを新構成へ整合

## Keep

- Market Coreの現役catalog/L1/candle/funding/store/artifact/selection/archive/retention test
- schema validation、stale/missing/finality/provenance test
- install-user-services、Postgres restoreの事故防止test
- CSS semantic role / contrast accessibility test
- atomic write / lock / artifact coherence test

## Checkpoints

1. legacy-only test/toolを削除し、参照を除去する。
2. brittle Web/docs testを統合・縮小する。
3. Playwrightをdesktop smoke + opt-in fullへ変更する。
4. CIを変更範囲別に分割し、main pushだけfullにする。
5. focused gateとfull gateを通し、削除によるcoverage holeがないかdiff reviewする。

## Completion

- PRのdocs-only変更でPostgres/Chromium/全pytestを要求しない。
- core変更ではPostgres integrationを含むMarket Core gateが動く。
- Web変更ではunit/check/buildとdesktop E2Eが動く。
- ops変更ではinstall/restore等の安全testが動く。
- main pushではdocs/core/web/opsの全gateが動く。
- 旧DuckDB/scanner shadow testがdefault gateから消える。
- 現役data integrity / DB safety testは維持される。

## Rollback

このbranchをmergeしなければmainへ影響しない。merge後にcoverage不足が見つかった場合は、削除したtestをGit履歴から復元するか、現行contractに合わせたfocused testとして再導入する。

## Unresolved

なし。ユーザー承認済み方針に従って実装する。
