# 独立ランキングの継続作業・証拠

- 作成: `2026-09-12T07:46:31+09:00`
- 更新: `2026-09-12T12:05:33+09:00`
- 状態: `実装計画`

## 現在地

全体はPARTIAL。G01の要確認12行が残る。元checkoutとは分離し、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700 で開発を継続する。
branchはai/ranking-continuation-20260912-115700、HEADは8d12fa6979700f3ed281f06262a91cb25faa635c。
元の未commit差分78ファイルを保全し、このworktreeへ検証済みmap2ファイルと文書8件を統合した。
元checkoutのファイル・branch・indexを変更せず、worktree用のGit管理情報を追加した。

このworktreeのmap versionは4ce42c272921615dbf0b64e5。元1,203契約を692行に保持し、
参照APIとWidget対応531（Bybit480/Binance51）、未対応28、要確認12、対象外121。
元名簿とID/versionが一致し、参照revision・Widget metadata・未解決台帳の整合検証はPASS。
照合完了gateは12要確認と12未確認Widgetにより終了1であり、全体完了とは扱わない。

## G01〜G10

| ID | 判定 | 証拠・制限 |
| --- | --- | --- |
| G01 | PARTIAL | 12行の一次根拠が不足。未確認を未対応へ付け替えない。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/candidate-map-verification.json` |
| G02 | PASS | 元stateを隠した専用processとSQLite。書込み経路・状態重複拒否の証拠を照合。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/candidate-seed-provenance.json` |
| G03 | PASS | PONS/CAT/Binance牛来の実API3期間・計9比較がPASS。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/candidate-live-value-comparison.json` |
| G04 | PASS | 通常・75秒停止後とも3周期連続で全531契約・3期間が一致。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/live-acceptance-summary.json` |
| G05 | PASS | Web156 unit、全32 E2E。期間・方向・下限・設定保存不可・古い値を検証。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/validation-summary.json` |
| G06 | PASS | 531 metadata整合、追加4実描画、frame保持、削除済み選択の回帰確認。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/actual-widget-acceptance.json` |
| G07 | PASS | Desktop/Mobile画像確認。対象外symbolへ移動せず、別資産未対応はWidgetなし。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/actual-widget-acceptance.json` |
| G08 | PASS | 既存Chart等9主要ファイルを保全。Market78、Web156、E2E32がPASS。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/existing-feature-preservation.json` |
| G09 | PASS | 有限受入後に追加した入力guardを含むsourceでも、全3期間531/531を確認。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/final-source-live-smoke.json` |
| G10 | PASS | このworktreeへ現行文書と進捗を統合。詳細な証拠・制限・失敗を保持。 `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/CLOSURE_REPORT.md` |

全件受入の観測は2026-09-12 10:17〜10:34 JST。現在の稼働・本番反映とは別である。
先行する隔離SQLiteの履歴を利用したためcold startではない。WS再接続2,003ms、最大generation処理456ms、
最大RSS288,812KiB。実Widgetはケース別確認であり、全531契約の個別描画ではない。
入力guard追加後のRanking全91件がPASSし、分離後も同91件を再確認した。
Repo全体gateは銘柄・Widgetの未確認により失敗している。これを他のtest成功で置き換えない。

## 未達12行

- CHEEMS/NEX/RATS: Bitgetの1MCHEEMS/10000NEX/1000RATSの数量換算を定義する一次情報。
- Aster PROSUSDT: Pharosか旧Prosperかを区別する公式project identity・CA。
- AI/B-MONEY/BEN/BONER/BREW/MAX/MEMESTOCK/PAIR: 指数式の元資産と参照先aliasを結び付ける一次根拠。

個別記事・metadata・一般数量規約・全catalog/index・公式上場説明を調査したが、上記を確定できなかった。
指数式を比較不能なtickerへ変換していた8行の未対応候補は独立監査で撤回し、要確認を維持した。
詳細は [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/qualification-evidence.json](../../../../apps/ranking-core/data/qualification-evidence.json) のunresolvedDetailsを参照する。

## 再開と保全

引継ぎsnapshot: `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/continuation-20260912-115700/snapshot-manifest.json`。
元checkout保全確認: `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/continuation-20260912-115700/overlay-verification.json`。
map・文書の統合: `/home/tn/projects/prep-watchdeck/var/tmp/ranking/closure-hc5s0g9d/continuation-20260912-115700/candidate-integration.json`。

このセッションではこのworktreeを編集する。元checkoutへ統合する際は、別Codexの終了と最新差分を確認する。
元checkout内の保存済み検証artifactは、worktree外の実測記録として元の絶対パスで参照する。
これらの参照先は存在を別途検証した。既存service・DBへ接続して開発しない。
commit、push、PR、deploy、既存unit、live DB操作は未実施。G01解消までactive planを維持する。
