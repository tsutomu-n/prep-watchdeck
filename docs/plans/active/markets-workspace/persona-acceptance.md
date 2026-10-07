# MKT-003 / MKT-004 代理操作と実データ受入

timestamp="2026-10-07(水)_19:06 JST"

- 作成: `2026-10-01T20:20:15+09:00`
- 更新: `2026-10-07T19:06:07+09:00`
- 検証: `2026-10-01T20:31:46+09:00`
- 状態: `実装計画`

---

## 結果と完了境界

代理操作はPASS、実データは欠測・不一致を含む観測済み、今回の総合判定はPARTIAL。
原台帳のMKT-003/004は未達（blocked）を保持し、OS実IME・物理端末と本番M6の全条件を残した。
Chromium入力4件、実データ操作4件、候補Webの新規processからの復帰2件、送信境界2件、合計12件がDesktop1440/390幅で通過した。
本番M6の配置、unit操作、本番メモ/selectionへの書込、DB変更、map修復は実施していない。
現役はMarket `dc2a8d7`、Web/Ranking `d1c44d5`。Ranking v2、新metrics HTTP404。
候補の製品sourceは`1a0a1b7`で、今回は受入script・Playwright・台帳だけを変更した。

正式な集計とhashは[/home/tn/projects/prep-watchdeck/docs/plans/active/markets-workspace/persona-acceptance.json](persona-acceptance.json)に記録する。

## ペルソナと操作

| 担当 | 主な操作 | 確認 |
| --- | --- | --- |
| P01 日本語で記録する比較担当 | 保存待ちA→B→A、変換候補置換、応答到着中の入力、確定・取消、参照→native→再訪 | 本文、銘柄別下書き、focus、保存先ID/version、実参照値、観測context |
| P02 キーボードと狭い画面で確認する担当 | Tab/Space/Enter、条件・scroll復元、3Venueのnative、取得元、メモ、次銘柄 | 1440/390、横はみ出しなし、欠測維持、契約version、保存・再訪 |
| P00 送信境界 | 自分の一時HTTP serverへGET/POST | GETは到達、隔離4178以外へのPOSTは送信前に遮断 |
| P03 中断後に再開する担当 | 候補Webを終了し別processで起動 | 起動前snapshotと保存メモ/workspaceの完全一致、favorite、保存した表示 |

CDP `Input.imeSetComposition`と`Input.insertText`を使った。preedit/candidateのcompositionstart/update・inputはtrustedで、input.isComposing=true。
このChrome153ではCDPによるcompositionend.isTrusted=falseを空HTMLでも観測した。終端data、本文、回数を検証し、全イベントtrustedという誤った期待を修正した。
OS候補窓・物理日本語キーボード・Mobile OSキーボード・本人の使用感は未確認。

## 現役の実データ

- PF01: active1,216契約、map691行/1,203元契約。ID/version一致789、不一致408、消失6、currentのみ追加19。map内crypto570行、参照対応534行。
  最終Top20は15m/turnover/min0、20行/56元契約の48一致・8version不一致。cutoff/generation/map hashと前後一致をJSONに保存した。
  691行を全部cryptoと数えず、元契約数と資産行数を分けた。PEPEの旧Bitget導線が出ず、現行Aster導線が出ることをBrowserでも確認した。
- PF02: 専用127.0.0.1:55432 DB、既存app資格をREAD ONLY session/短いtransactionに限定。1接続、各Venue BTC/ETH/SOLの最大3契約、5秒以上、6分73samples。
  2,796件のavailable計算が元Decimal端点と一致し、489件のmissing/nullを維持した。SQL読取の中央値2.250ms、p95 4.973ms、最大5.871ms。
  Aster OIは全73回で0/3、Bitget SOLの足端点は一時欠測。他のVenue/windowは219/219 available。
  最新snapshotはAster OI以外が3/3。値の不足を前version・0・推測で補わない。
- 新着足: 前回の不在確認がある24件の保守的到着区間は、下限p50 9.596秒/p95 94.597秒、上限p50 14.601秒/p95 99.599秒。
  初回から存在する32件には下限を付けない。query開始/終了の区間でありDB commit時刻やProvider公開時刻ではない。180秒lag/300秒上限の長期保証にはしない。
- Artifact配送: 6分72回のうち71回成功、market-data HTTP503が1回。実時刻・欠測・失敗を保存し、source時刻を書き換えて鮮度を通していない。
  AsterのsourceAtは古いlast-trade時刻、Hyperliquid sourceAtはnullとして記録した。observedAtとの違いを保持する。
- 参照値: 現役v2と隔離候補v3で、BTC/ETH/PEPE/BTCDOMの4契約×15m/1h/JST daily、各12照合が公開RESTの別Decimal計算と一致。
  候補は採用mapからその4行だけを抜き、独自sample versionを付けた。現役v2をv3に偽装せず、元ID/version/倍率を変えず実公開RESTで計算した。
- PF03: 実数値のAPI応答をmockせず、時計を変更せず、隔離候補Webで操作。保存は専用state、selection書込は4178だけ。全personaに送信前のwrite guardを適用し、TradingView telemetry POSTの試行は遮断済みとして記録した。

## 証拠と検証

証拠rootは`/tmp/prep-watchdeck-persona-20261001`。raw market data、DB資格情報はGitへ追加しない。

- `/tmp/prep-watchdeck-persona-20261001/ime-final-results`: 入力イベントJSON・PNG、4PASS。
- `/tmp/prep-watchdeck-persona-20261001/operation-guard-results`: 実データ操作API/PNG/trace、4PASS。
- `/tmp/prep-watchdeck-persona-20261001/persona-guard-restart.log`: 別候補Web processで2PASS。
- `/tmp/prep-watchdeck-persona-20261001/native/summary.json`: 実端点・availability・到着区間。raw/capture-sourceと元派生結果を保全し、到着下限を前回query開始から再集計。
- `/tmp/prep-watchdeck-persona-20261001/live/summary.json`: 整合copy・全体/Top20・配送失敗。

Ruff check/format、Web check（0errors/0warnings）、fresh build、文書metadata/link、diff checkは通過。CI・全suite・本番操作は今回の検証に含めない。
最終guard確認の追加観測はnative 120秒24samples、artifact 180秒36回中35回成功/HTTP503が1回。正式6分datasetへ混ぜず保存した。
初回の試験失敗はCDP終端のtrusted期待、thを除いたtd列番号、scroll反映前のpointer操作、同理由メモの意図した置換、mirror停止後の15秒鮮度失効だった。
本文や数値期待を緩めず、契約に沿った入力・表示待ち・起動前snapshot比較に修正した。遮断されたtelemetry試行を送信完了と誤分類した試験記録も修正し、failure codeを保持して確認した。検出した製品source不具合はない。

## 再実行と残る条件

[/home/tn/projects/prep-watchdeck/scripts/market/run-persona-acceptance.sh](../../../../scripts/market/run-persona-acceptance.sh)は明示した採用map・既存env file・新しい専用run rootを使う。
隔離RankingはRepo内var/tmpを使い、bubblewrapの/tmp隠蔽を避ける。artifact mirrorは候補Web再起動まで継続する。
次のcommandは現役の読取りと隔離stateへの書込を行う。対象release/map/envの確認後に実行する。

```bash
bash /home/tn/projects/prep-watchdeck/scripts/market/run-persona-acceptance.sh \
  --mapping /home/tn/releases/prep-watchdeck/d1c44d5/apps/ranking-core/data/initial-map.json \
  --env-file /home/tn/.config/prep-watchdeck-market/postgres.env \
  --run-root /tmp/prep-watchdeck-persona-NEW
```

launcherの構文、引数拒否、実孫processを使ったown PID/PGIDの終了・回収は通過した。launcherによる全工程再実行は未実施。構成要素の上記実測をその再実行証拠に読み替えない。
rollbackは自分が起動した隔離processを終了すること。証拠を残し、本番stateやサービスを戻す操作は不要。
未完了はOS実IME/端末/本人使用感、本番M6配置・本番起動復帰・本番日常利用受入、実データ欠測/map不一致の解消である。
