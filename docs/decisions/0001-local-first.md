# Decision 0001: Local-firstを維持する

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

## 決定

`prep-watchdeck`はlocal-firstを既定とする。

runtime state、annotation、settings、market dataの主要な正本・read modelは、利用者が制御できるlocal storageを
基本とする。特定のDB engine、file format、port、path、single-device構成へ永久固定しない。

## 理由

- 裁量トレーダーがmarket data、annotation、設定、履歴を自分でbackup、inspection、rollbackできる。
- account dataや判断記録を必要なく第三者serviceへ送らない。
- external service障害やSaaS lifecycleから中核runtimeを切り離せる。

## 現行実装

現行Perp runtimeは専用Postgresをcurrent/recent truth、confirmed Parquetを期限後履歴正本、atomic JSONを
Web read model、local filesystemをPast Note/control/stateに使用する。

過去のDuckDB、snapshot layout、Dashboard settings等は当時の実装履歴であり、このDecisionの不変条件ではない。

## 将来拡張

remote access、multi-device、server component、cloud storage、read-only account connector等を追加できる。
導入時はauthentication、authorization、encryption、secret handling、conflict、backup、rollbackを別途設計する。

local-firstは`localhostしか許可しない`や`単一利用者を永久固定する`という意味ではない。
