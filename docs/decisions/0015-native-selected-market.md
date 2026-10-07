# Decision 0015: group比較と単独契約の板・約定観測を分離する

- 作成: `2026-10-07T17:24:00+09:00`
- 更新: `2026-10-07T17:38:27+09:00`
- 状態: `設計判断`

## 決定

group所属を単独板・約定の観測資格と同一視しない。未groupでも現行の単独契約検証を通るものは、
明示選択した1契約だけを既存のselected stream/writer/storage/artifactで観測する。
製品境界は[Decision 0012](0012-product-evolution-boundary.md)を維持する。

## 契約と品質

- 単独selectionは`groupId=null`、契約ID、正の現行versionで識別する。架空groupを作らない。
- active linear CLOB、USD-like quote/settle/collateral、Base数量、倍率1の確認を維持する。
- group化のalias・同Venue衝突等の判断を、別のVenue商品の同一性承認へ置き換えない。
- command/heartbeat/lease/イベント/表示を契約versionに結び付け、退役versionや他契約のイベントを拒否する。
- Universeの数量metadataはoptional。古いartifactの欠落は未確認として扱い、購読資格を推測しない。
- 数量換算が未確認の契約の元単位表示は別の拡張で扱う。今回、未知数量・未知倍率の概算は出さない。
- 既存group commandは維持し、選択数・TTL・cleanup・depth/trade上限・収集範囲を拡大しない。

## 採用理由と代替案

UIの条件だけを外す案はAPI・store・artifactのgroup前提を満たさない。
架空groupは比較identityを誤認させる。別collector/artifactの追加は同じbounded収集の運用負担を増やすため、
nullable groupとversion固定で既存laneを拡張する。

## 検証と反映

隔離Postgresのstore/runtime試験で、1契約の保存、他Venue・不適格数量・wrong versionの拒否と購読解除を確認する。
Web repositoryでversion/tokenの競合、Desktop/Mobile E2Eで明示選択・単独表示・数量未確認表示を確認する。
購読開始前のCatalog退役はselection commandの拒否として扱い、サービス全体を停止しないことを検証する。
schema再生成、型検査、lint、build、全体gateを使用する。
稼働DBへのmigrationとMarket Core/Webの反映・実データ受入は別工程であり、source検証の完了と区別する。
