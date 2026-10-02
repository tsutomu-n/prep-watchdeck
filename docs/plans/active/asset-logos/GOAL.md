# 銘柄を識別するロゴ表示

timestamp="2026-10-02(金)_21:01 JST"
- 作成: `2026-10-02T20:49:18+09:00`
- 更新: `2026-10-02T21:01:54+09:00`
- 状態: `実装計画`

## goal・scope

一覧・ランキング・お気に入り・選択詳細で同じ原資産を認識しやすくする。
全銘柄に一定幅の表示枠を置き、確認済みの資産だけ実ロゴ、それ以外は中立的な文字表示。
契約ID/versionから既存の審査済み対応表を再利用し、symbolだけでは画像を決定しない。
表示専用のmanifest・ローカル画像・共通Svelte部品を追加する。
価格、数量倍率、参照provider、Widget資格、Market契約版、収集・DBには作用させない。
既存の文字label、取引所、1000等の契約名を保持し、ロゴ色を騰落率で変えない。

## checkpoint・完了条件

1. 実画面・既存map・適用designから表示箇所と安全なidentity resolverを決定。
2. 正式な原資産identityと画像出典・再配信条件を確認した小さな初期logo集合をローカル保存。
   CoinGeckoを第一候補に検討し、利用条件を満たす取得元だけ採用。未確認を残して進める。
3. 一覧20〜24px・詳細32pxの共通部品を導入。未確認、版不一致、画像失敗は同じ大きさの代替。
4. Desktop/Mobileの数値領域、銘柄移動、お気に入り、画像失敗時の通常操作を隔離環境で確認。
5. 差分・関連unit・Web check/build・関連E2E・docs checkを確認し、今回分をcommit。
   PR/CIを使わず、既存の明示承認範囲でmain更新とWebへの反映を行う。

## verification

異名/同名asset、AI、数量倍率未確認、未知ID/version、rankingとnativeの一致を確認。
全ロゴの充足率は完成条件にしない。全表示に枠があり、誤資産を表示せず、外部APIなしで描画。
画像失敗前後のbox/行高/数値位置が同じで、390px等の狭い画面を圧迫しない。
市場source/schema/map/evidenceを変更せず、API収集失敗へ画像機能を結び付けない。

## rollback・未解決

画像・manifest・Web部品は可逆なsource差分。runtimeの市場DB/stateを変更しない。
配置はWebだけの変更を基本とし、旧releaseへ戻せるdrop-inを保存する。
利用条件確認済みのBTC/XMR2asset・3Venue6原契約に限定し、他はneutral fallback。
Web175unit、check0error/0warning、build、Desktop/Mobile6 E2E成功。
独立reviewの混合identity入力の穴とcredit戻り先を修正し、最終delta検証中。
main更新・Webだけの配置・HTTPS稼働確認が未完了。
