# prep-watchdeck 現行UIワークフロー

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書は**現在実装済みのPerp Universe UI**の挙動を説明する。
将来のranking、Stocks、prediction、journal、複数selection、追加Chart等を禁止する製品境界ではない。
製品境界は[`product-boundary.md`](product-boundary.md)を正本とする。

## 現行主要flow

1. Universeのinstrumentを確認する。
2. 検索、Venue、coverage、quality filterで対象を絞る。
3. mark、reference種別、funding、OI、24時間出来高、freshness、provenanceをVenue別に確認する。
4. group化済みinstrumentでは、条件を満たす時だけ参考mark中央値を確認する。
5. 行を選び、primary Venue、Chart、groupの板・約定・book walkを確認する。
6. 後で再確認する文脈をPast Noteへ保存できる。

現在の画面はbase→Venueの既定順でありranking UIは未実装。ただしranking、score、direction等は製品境界内で
追加できる。

## 状態軸

現行UIは次を必要に応じて分離する。

- Data quality: `ready / partial / stale / unavailable`
- Freshness: 観測後の経過と利用可能性
- Coverage: cross-Venue groupingの状態
- Operational state: artifact refresh、selection、service等の動作状態
- Selection: 選択中または未選択

新しいranking/model state等を追加する場合も、data qualityとmodel outputを混同しない。

Market Coreが`stale / unavailable`としてnullにした値を、Webが前回値や0で補わない。

## 更新停止とvalidated snapshot

現行Webは5秒ごとにartifact bundleを再取得する。再取得に失敗し、直前のschema検証済みbundleを表示し続ける
場合は、更新停止であることと最終検証時刻を表示する。

5秒、artifact数、poll方式は現行実装値であり変更可能。

## 品質理由

artifactの`qualityReasons`と`errorCode`は人間向け説明とraw codeを確認できるようにする。
unknown codeを握り潰さない。

新しいranking、prediction、backtest、portfolio等でも、入力dataのqualityや不足理由を表示できる設計を優先する。

## Universe Explorer

現行各行ではbase、Venue、source symbol、group/単独状態、mark、funding、OI、24時間出来高、quality、観測時刻等を
確認できる。

現在のfilterはsearch、Venue、coverage、quality。現在の既定sortはbase→Venue。

将来はranking、custom sort、score、asset class、strategy/model filter等を追加できる。

参考mark中央値はreference valueであり、現在のcontractではexecutable priceではない。将来別のexecution contextを
追加する場合は、その計算前提を別に示す。

## 選択

現行実装では1 instrument/groupを選択し、500ms debounce後にselection commandを送り、5分ごとにheartbeatする。

この`1 selection`、debounce、TTL、heartbeatは現在のruntime値であり永久制約ではない。
将来は複数selection、pinned symbol、ranking shortlist等へ拡張できる。

## Selected detail

現行detailは主に次を表示する。

1. instrument identity、coverage、quote/settle/collateral、freshness
2. `5m / 15m / 1h / 4h / 24h` Chart
3. Venue別depth最大20段
4. group横断の直近100 trades
5. `$100 / $500 / $1,000` book walk
6. Past Note

これらのtimeframe、bar数、depth段数、trade件数、notional、section順は現行値であり変更可能。

Chart、indicator、rankingはcross-Venue group化と別責務として扱える。将来、単独instrumentでもidentityとsourceが
確認できればChart/indicator/rankingを提供できる。

book walk等のexecution contextは、fee inclusion、impact assumption、data age、order availabilityの意味を明示する。
現在の実装がfee/impactを含まないことを、将来も永久禁止とはしない。

## Notes / Journal

現行Past Noteは`venueInstrumentId`単位の観測annotationで、現在は60日後にread時pruneする。
60日は現行policyであり変更可能。

将来、Past Noteとは別にDecision Memo、Trade Journal、review workflowを追加できる。
annotation、decision、execution recordを同一概念へ無理に統合しない。

## Ranking / Prediction

将来のUIはAttention Rank、Momentum、Volume、Breakout、LONG/SHORT候補、prediction等を表示できる。

追加時は可能な範囲で次を示す。

- rank/scoreの意味
- timeframe
- component / reason
- data-as-of
- data quality
- model/ruleset version
- insufficient-data reason

高rankや方向評価を自動注文と同義にしない。

## Qualityと障害

- missing、partial、stale、invalidを空文字や0、前回値へ変換しない。
- source timestampがない場合は勝手にsource timeを捏造しない。
- Web process healthとmarket data qualityを混同しない。
- 一部source障害では成功データと失敗理由を区別する。
- schema不一致やrefresh失敗を黙って正常表示しない。

## Responsive / Accessibility

- Desktopとnarrow viewportの双方で主要flowへ到達できる。
- semantic table/list/form control、可視focus、keyboard操作、status textを使う。
- 色だけでmovement、quality、coverage、selection、ranking stateを表さない。
- IME compositionを壊さない。
- reduced-motionを尊重する。

旧版の固定breakpoint、row height、layout、animation禁止等はdesign defaultとして変更できる。
