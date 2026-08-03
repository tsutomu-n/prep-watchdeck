# Decision 0001: Local-firstを維持する

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-02T22:00:39+09:00`
- 状態: `設計判断`

---

## 決定

`prep-watchdeck`は単一利用者向けlocal-first applicationとして維持する。
runtime state、Past Note、Dashboard settingsはlocal filesystemとDuckDBへ保存する。

## 理由

- 個人用の市場監視watchdeckであり、共有accountやserver DBを必要としない。
- 銘柄annotationと表示設定を外部serviceへ送信しない。
- local fileによりbackup、inspection、rollbackを利用者が制御できる。

## 帰結

- Past NoteとDashboard settingsのwrite APIはlocal runtimeだけで有効にする。
- Cloudflare等への移行はfilesystem、command execution、persistenceを別設計にする。
- runtime stateはGit repositoryから分離する。
