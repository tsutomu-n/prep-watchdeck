# 完成範囲とユーザー受入条件

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

## 必須の完成フロー

ユーザーがWatchdeckの発見画面でprofileとVenueを選ぶ。実データから計算された順位と理由が表示される。行から入力窓、値、取得時刻、欠測・除外理由を確認し、既存Chartへ移動できる。判断をsnapshotとして保存し、再起動後も同じ当時値を読み戻せる。過去検証では、そのprofileの明示された条件が成立した観測と、その後1時間の結果を確認し、分母や除外事例へ戻れる。

補助情報としてmarket-trackersのFed公表情報を実際の契約で取得・保存・表示する。cryptoへの因果関係や方向点は付けない。feed停止時もnative rankingは使えるが、古い補助情報を新材料として表示しない。

## 完成に含むもの

RANK：momentum-1h-up/downとattention-15m。全対象instrumentを評価し、単独instrumentも対応。既定の比較単位はVenue/quote/asset/market typeが一致するscope。cross-Venueの一括点数化はしない。

RECORD：自動の毎時snapshotと、ユーザーの判断保存。後からデータや式が変わっても過去の表示値・根拠は改変しない。

STUDY：固定された3 profile対応の結果定義、日時・instrument・最近期間filter、共通sample guard、明示した区間推定、個別事例表示、JSON/CSV export。

EVIDENCE：Fed adapter、local dump import、原典URL、time precision、revision、terms/freshness/transport health、旧値保持時の注意表示。

DELIVERY：migration、再起動、容量制限、失敗隔離、文書、全主要フローのdesktop/narrow viewport試験。

## 今回含めないもの

株価データ契約と市場identityが未確定のStocks ranking、オプションflow、自動発注、口座鍵、Trade Journal全体、ML予測、任意Pine、任意SQL/DSL、外部通知配信、収益性の保証。これらは永久禁止ではなく、現在確認できるデータと今回の要求から切り分けた別作業である。後続追加のためだけの空実装は作らない。

## 受入判定

1. 全必須profileで、本物のcollector入力→計算→保存→API→UIが接続する。データ不足時は理由付き除外で、人工値へfallbackしない。
2. 正常、欠測、stale、source失敗、schema不一致、部分書込み、再起動の結果が11の期待と一致する。
3. 履歴照会は未来情報を条件へ漏らさず、NとCIをすべての出口で同じ方針にする。
4. 保存snapshotのdigestを照合し、訂正データ・後日の再計算と当時記録を区別する。
5. 実データを使った隔離smokeとrestore検証を証拠付きで終える。接続不能をfixture成功で代用しない。

少数標本で推定値がnullとなること自体は正しい完成状態。ただし全profileが恒常的に未接続でnullになる実装は未完成である。使える機能、入力待ちの機能、本番未反映をUIと終了報告で区別する。
