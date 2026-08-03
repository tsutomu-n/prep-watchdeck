# Decision 0007: 市場監視専用の製品境界

- 作成: `2026-08-02T22:00:39+09:00`
- 更新: `2026-08-02T22:00:39+09:00`
- 状態: `設計判断`

---

## 決定

`prep-watchdeck`のproduction surfaceを市場監視へ限定する。Cold snapshot、Hot ticker、
detail chart、Candidate、Watchlist、選択銘柄detail、Smart Rank、Symbol Monitoring Rail、
VPI-Lite+補助表示、Past Note、Dashboard settingsを維持する。

Attack Ticket、Trade Memo、TRADE / SKIP memo、Quick SKIP、Full SKIP、Weekly Review、
Deal Check、Pre-Trade Check、Position Size Pressureは退役させる。対応するproduction UI、
domain、repository、CSV export、state path、API routeを置かない。旧API
`/api/trade-memos`、`/api/attack-tickets`、`/api/weekly-review`は全methodで404となる。

## Past Noteの境界

Past Noteは取引記録の代替ではなく、銘柄、観測理由、観測日時、有効期限、短い注記を持つ
monitoring annotationである。作成時の`expiresAt`は60日後で、`observedAt`から60日経過または
期限到達時に月別Archiveへ移す。localhost write boundary、atomic write、lockを維持する。

## 表示契約

scanner snapshotの内部category `NO_TRADE`はschema、fixture、filter、過去snapshotとの互換性のため
変更しない。利用者向け表示だけを`監視除外候補`へ統一する。ranking、score、上昇色、VPI、
選択状態は確認順または市場状態であり、売買推奨ではない。

## Stateと履歴

active state layout v2はDB/WAL、snapshots、past-notes、dashboard-view-settings、usage-events、
opsだけを持つ。retired recordは新しいactive targetへcopyせず、source全体を検証付きRepo外Archiveへ
保持する。sourceは自動削除しない。version markerがない既存Archiveはlayout v1として検証でき、
未知versionはfail-closedにする。

日次サマリーはschema v2としてmonitoring stateだけを読み、`ops/daily/v2/`へ出力する。
過去のschema v1出力とlegacy usage eventは履歴として保持し、現行機能へ再昇格させない。

## 理由

市場監視と取引ライフサイクル管理を同じ製品に持たせると、監視signalがexecution判断に見え、
UI、API、state、review責務が過大になる。監視に必要なannotationと表示設定だけを残すことで、
市場dataの発見・絞り込み・context確認へ責任を限定できる。

## 帰結

- 取引journal、損益集計、position sizing、注文連携を新規実装しない。
- 旧機能を戻す場合はこのDecisionを置換する新しいADR、state migration、API/UIの再設計、
  Archiveからの明示的restore手順が必要である。
- Archiveの存在だけをproduction機能復活の根拠にしない。
