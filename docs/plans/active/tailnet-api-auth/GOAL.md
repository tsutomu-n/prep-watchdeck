# Tailscale API 403 修正計画

timestamp="2026-10-02(金)_21:41 JST"
- 作成: `2026-10-02T21:27:36+09:00`
- 更新: `2026-10-02T21:41:56+09:00`
- 検証: `2026-10-02T21:41:56+09:00`
- 状態: `実装計画`

## Goal / scope

既存のスマホ向けHTTPS URLでランキング・workspace APIが403になる原因を特定し、
既存のユーザー端末認証を維持しながら、このサーバー自身からも安全に表示できるようにする。
対象はWebの共通認証判定・対応route・関連tests・operations文書・Web releaseのみ。
Market、Ranking、DB、Tailscale ACL・タグ・Funnel・公開先を変更しない。
PR・CIは使用しない。承認済みのmain更新とWeb反映まで実行する。

## 原因と確認済みcheckpoint

- HTML200、loopbackランキング200、同じサーバーからHTTPSのランキング・workspace403を再現。
- 実際のproxy接続はloopback、HostとHTTPS情報は設定URLと一致するがuser-login headerがない。
- Tailscale Selfはタグ付き端末。公式Serve仕様ではタグ付き端末にuser identityを付与しない。
- 共通判定がuser-loginを無条件に必須とするため拒否する。
- local tailscaledのread-only status / WhoIsをWebユーザーで取得でき、WhoIs StableIDとSelf IDの一致を確認。

## 実装順序

1. remote trustの既存条件を保ち、identityがない接続だけlocal tailscaledで自端末と確認する。
   loopback、設定済みauthority、proxyのHTTPSとHost、単一のforwarded IPを確認。
   statusのRunning・Self DNS/IPとWhoIs StableIDが一致するタグ付き自端末だけ許可する。
   Funnel・未知端末・偽装header・daemon取得失敗は拒否する。外部API・credential追加は行わない。
2. 非同期の認証結果を全該当routeでawaitし、readLocalJsonのsame-originを維持する。
3. 関連unit・全Web unit・check・build、独立reviewと隔離proxy検証を行う。
4. 検証済みcommitをmainへ反映し、Webだけ新releaseへ切り替える。
5. 同じHTTPS URLでDesktop/390pxの実ブラウザー、GET API、CSRF拒否を確認。
   実機スマホの本人確認は別の未実施項目として扱う。

## 完了条件 / validation

- HTTPSのranking/workspace GETが200になり、実ブラウザーで一覧・お気に入り状態を表示できる。
- 従来のuser identityとlocalhostが通り、未確認端末・不正authority・cross-origin・Funnelが拒否される。
- local tailscaledのtimeout、不正response、別nodeはfail closed。
- ロゴとmobile数値表示を維持し、live workspace / selection / noteを書き換えない。
- mainと配信source一致、GitHub保護設定復元、PR/CI未使用。
- Market / Ranking / DBの稼働状態を保つ。

## Rollback

Web切替前のdrop-inをprivate archiveへ保全し、WebのWorkingDirectoryだけを元releaseへ戻す。
source修正は個別commitで戻せる。状態DB・保存JSON・Tailscale設定は変更しない。

## 未解決

- 実装修正、独立review、隔離release gateはPASS。main更新、Web切替、live受入は未完了。
- スマホ実機の操作は未実施。

## Source checkpoint

- 関連認証26 tests、実daemon Self IPv4 / IPv6許可・未知IP / 別host拒否、独立review PASS。
- 必須release gate PASS: Market196 / Ranking131 / Web188、check / build、Desktop / Mobile100 E2E。
- 一時Postgresは専用の動的portで隔離し、終了後に当該containerだけを削除した。
- Core、schema、package/lock、生成型の差分なし。
- main反映とWeb切替後、実HTTPSブラウザーで200と表示復旧を確認する。
