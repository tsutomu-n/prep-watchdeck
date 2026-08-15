# prep-watchdeck 現行UIワークフロー

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-14T22:07:54+09:00`
- 検証: `2026-08-14T22:07:54+09:00`
- 状態: `現行`

---

## 主要flow

1. Universeの全instrumentをbase、Venue順で確認する。
2. 検索、Venue、coverage、quality filterで監視対象を絞る。
3. mark、reference種別、funding、OI、24時間出来高、鮮度、provenanceをVenue別に確認する。
4. group化済みinstrumentでは、条件を満たす時だけ参考mark中央値を確認する。
5. 行を選び、primary Venue、Chart、groupの板・約定・book walkを確認する。
6. 後で再確認する文脈だけPast Noteへ保存する。

売買方向、期待収益、裁定機会、推奨Venue、ランキングは表示しない。

## Universe Explorer

各行は少なくともbase、Venue、source symbol、group/単独状態、mark、funding、OI、24時間出来高、
quality、観測時刻を識別できるようにする。quote、settle、collateral、reference price kind、
source endpointは詳細またはprovenance表示から確認できる。

検索はbase、source symbol、`venueInstrumentId`を対象にする。filterはnative input/selectを使い、
labelを常時表示する。絞り込みで値のないitemを黙って除外する場合は、適用中filterと件数を示す。

group coverageとdata qualityは別軸である。単独instrumentは「品質不良」ではなく未group、
stale/unavailableはcoverageに関係なく品質状態として示す。

参考mark中央値には次を併記する。

- 参加Venue数
- cycle/freshness条件
- `USD/USDC/USDT parityを参考中央値だけに仮定`
- executable priceでも売買推奨でもないこと

## 選択

行の選択は視覚state、keyboard focus、collector subscriptionを混同しない。500ms debounce後に
`/api/selection`へ1 commandを送り、同じ`groupId + venueInstrumentId`を5分ごとにheartbeatする。
primaryを変える時は同じgroupでも新しいselection revisionとして扱う。

選択対象が次のUniverseから消えた、group membershipが変わった、commandが期限切れになった場合は、
旧detailを有効なまま見せず選択解除またはunavailable理由を表示する。

## 選択detail

detailは次の順で表示する。

1. primary instrument identity、quote/settle/collateral、freshness
2. 5m / 15m / 1h / 4h / 24h Chart
3. Venue別depth最大20段
4. group横断の直近100 trades
5. $100 / $500 / $1,000 book walk
6. Past Note

Chartは選択した`venueInstrumentId`だけを描画する。`derived_final`を`confirmed`と同じ表示にせず、
欠落bar、version境界、不完全barを埋めない。timeframe変更で選択instrumentを変えない。

book walkはbuy/sellを分け、平均価格とtop-of-bookからのbpsだけを表示する。10秒超、板不足、
非USD-like、単位不明では数値の代わりに理由を表示する。常に次を明記する。

> 現在受信した板だけの概算。fee、将来impact、実際の注文可否を含まない。

## Past Note

Past Noteは`venueInstrumentId`単位の監視annotationで、trade journalではない。reasonまたは本文を
必須とし、保存中の重複submitを防ぐ。選択が変わっても別instrumentのdraft、feedback、noteを
混在させない。60日を過ぎたnoteは再表示しない。

## Qualityと障害

- missing、partial、stale、invalidを空文字や0へ変換しない。
- source timestampがない場合は「なし」とし、observed timeへ置き換えない。
- Web process healthとmarket data qualityを同じbadgeにしない。
- 一部Venue障害では取得できたVenueを残し、失敗Venueと理由を表示する。
- artifact schema不一致では旧DOMや前回値をfreshとして残さない。

## Responsiveとaccessibility

Desktop 1440pxはUniverseとdetailを同時に走査できる密度を保つ。Mobile 390pxはfilter、行、
selected detailを縦方向へ並べ、横overflowで主要操作を隠さない。tap targetは44px以上、主要actionは
48pxを目安にする。

semantic table/list、native form control、可視focus、keyboard操作、status textを使う。
色だけでmovement、quality、selectionを表さない。検索IME composition中にfilterを確定しない。
自動scroll、点滅、常時animation、hover必須操作を追加しない。
