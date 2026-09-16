# ランキングとチャート改修の統合・稼働反映

- 作成: `2026-09-16T21:17:38+09:00`
- 更新: `2026-09-16T21:42:34+09:00`
- 検証: `2026-09-16T21:42:34+09:00`
- 状態: `実装計画`

## 目的と承認

利用者は提示計画の実行を指示した。ランキングと既存チャート改修の統合、commit/push、1件のPR、
CI成功後のmainへのmerge、専用ランキングunitの設置と稼働、既存Webだけの切替・復旧を含む。
元checkout・ランキング作業treeの既存差分、Market Core・DB・maintenanceの稼働を保全する。
元数量換算3件・TradingView対応3件の未確認を解消したとは扱わず、その機能制限を維持する。

## 作業先と入力

- 作業先: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117`
- branch: `ai/ranking-chart-release-20260916-2117`
- main基点: `9b83b5313271e7a76a53e3a06241ee010446f58e`
- ランキング入力: `006983931df3b2ff0646474ecd9b441b761c97c7`
- チャート入力: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700` の未commit差分。
  独立した市場調査メモを除き、native履歴・表示範囲・JST基準騰落率とその検証・説明だけを取り込む。
- 保全と検証artifact: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/var/tmp/ranking-chart-release`

## 順序とcheckpoint

1. [x] main、公開済みcommit、両作業tree、現役unit/portを再確認して別worktreeを作る。
2. [x] 最新mainの製品方針・CI整理を保ってランキングとチャートを統合する。
   チャートDecisionは0014へ改番し、ランキング専用CI gateを追加する。
3. [x] focused tests、実BTC APIの有限照合、統合版の必須検証とDesktop/Mobileを確認する。
4. [ ] 1件のPRへ公開し、CI成功後にmergeする。main CI成功後のSHAを配置版として固定する。
5. [ ] 専用release・state・unitを準備し、ランキングを先に起動する。3期間・3連続世代、
   再開、資源制限を確認してからWebを切り替える。
6. [ ] 通常画面、既存Marketの継続、切戻しと再切替を確認し、運用正本へ結果を反映する。

## 検証と完了条件

統合版のlocal full gate、PR CI、merge後CI、配置SHA、実unitの制限、実APIと画面を別の証拠とする。
Chartの時間足・ズーム・過去追加・遅延応答・JST境界・欠測、設定保存失敗と共用を検証する。
ランキングの計算・mapが不変なら既存の実Provider受入をhashで照合し、稼働unitでの受入を追加する。
通常時とランキング再起動後、全534参照・3期間の有効な3連続世代を要求する。
初回準備と再開の観測は各900秒を上限とし、未達のままWebを切り替えない。
すべて成立した時点でD05をPASSとし、source公開だけで稼働完了にしない。

## 配置と切戻し

配置先は `/home/tn/releases/prep-watchdeck/` 配下のmerge SHA先頭7桁directory（未作成）。
専用stateは `/home/tn/.local/share/prep-watchdeck-ranking`（未作成）、APIは127.0.0.1:8769。
実行直前に衝突・symlink・稼働writerを再確認する。専用unitは `prep-watchdeck-ranking.service`。
Webは既存の起動command、5173 port、Market state、Tailscale host設定を保持し、専用drop-inで
WorkingDirectoryとランキングportだけを変更する。

切替前のunit/drop-inの内容・hash・enabled/active状態を保全する。Webの切戻し先は
`/home/tn/releases/prep-watchdeck/dc2a8d7`。追加drop-inを外すか保存内容へ戻し、daemon-reloadと
Webの再起動後に旧画面のhealthを確認する。新ranking unitは停止するが専用stateは削除しない。
全unitを更新する既存installerを流用せず、Market/DB/maintenanceを再起動しない。

## 現在の未達

統合とlocal検証は完了。公開・配置・稼働受入は未実施。

- full gate: maintenance 18、Market 77、Ranking 122、Web 147、Desktop/Mobile E2E 36が成功。
  型・lint・format・build・schema・文書検査も成功。CIの変更経路8ケースを確認した。
- 実API: 3 VenueのBTCで15分/日足の最新と過去、計12ページを確認。JST基準価格も
  各Venueの確定1分足と照合した。PC 1440px/Mobile 390pxの実描画と設定共有も成功。
- 初回のBitget過去日足502は有限の再確認で再現せず、原因は未確定。試験artifactの更新間隔に
  起因する503は試験側で修正した。製品の判定・鮮度条件は緩めていない。
- ランキングsource/mapは入力commitと同一。元2checkoutのsource/index/HEADも保全した。
- 詳細は上記artifact内の verification.json、ci-routing.json、chart-canary.json、chart-live-ui.json。
