# prep-watchdeck 現行概要

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-10T20:23:57+09:00`
- 検証: `2026-08-10T20:23:57+09:00`
- 状態: `現行`

---

## 製品の役割

`prep-watchdeck`は、Bitgetのpublic market dataから異常な値動きを見つけ、候補を絞り、
risk/contextとdata qualityを確認するlocal-first市場監視watchdeckである。

自動売買Botではない。売買指示、自動発注、Private API、残高・position取得、
注文endpointは実装しない。利用者が保存するのはPast NoteとDashboard view設定だけである。

## 構成

- `apps/scanner-core`: Python 3.13、`uv`、CLI名`watchdeck`
- `apps/web`: SvelteKit、Bun、localhost向けWeb UIとlocal API
- `config/scanner-filters`: scanner filter template
- `schemas/scanner-snapshot.schema.json`: scanner-coreとWeb間のsnapshot契約
- `fixtures`: network不要の決定的な検証入力

## 現行機能

- Bitget public RESTからlive snapshotを作る。
- Bitget public WebSocketの`ticker`と`candle1m`をDuckDBへ保存する。
- 起動時REST seed、recent gap reconcile、任意のdeep backfillを行う。
- Cold snapshot、1秒Hot ticker、detail chartを分離して表示する。
- 5m、15m、1h、4h、24h、74hで候補を確認する。
- Raw Sort、ranking、カテゴリ、data quality、risk tagで候補を絞る。
- Candidate、Watchlist、選択銘柄detail、補正順位の順でDashboardを確認する。
- Symbol画面のMonitoring Railで分類、label、品質、時間軸、ranking位置、movement signal、
  risk tagを確認する。
- Past Noteを銘柄annotationとして保存し、`observedAt`から60日または`expiresAt`到達時に
  月別Archiveへ移す。
- Dashboard view設定をローカル保存する。
- `PREP_WATCHDECK_STATE_DIR`でDB、snapshot、chart、Past Note、Dashboard settings、
  usage events、opsのrootを一括切替する。
- 起動時にscanner-coreとWebの実pathを表示し、個別override不一致では停止する。
- 日次サマリーschema v2を`ops/daily/v2/`へ生成し、schema v1出力を上書きしない。

ranking、score、上昇色、選択状態は「次に確認する候補」を表し、売買推奨ではない。

## 非目標

Attack Ticket、Trade Memo、TRADE / SKIP記録、Weekly Review、Deal Check、Pre-Trade Check、
Position Size Pressureは製品境界から退役済みである。対応するproduction UI、domain、repository、
CSV export、APIは提供しない。旧API pathは全methodで404となる。

## 正本

- 起動と短い利用案内: `README.md`
- 現行仕様index: `docs/README.md`
- UI規則: `DESIGN.md`
- 実装コード、schema、tests

この文書に固定されたruntime件数や市場値は置かない。現在値は
`watchdeck doctor`、state files、実画面で確認する。
