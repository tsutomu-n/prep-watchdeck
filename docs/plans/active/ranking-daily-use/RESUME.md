# ランキング日常利用の中断記録と再開手順

- 作成: `2026-09-13T16:52:05+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 検証: `2026-09-16T19:56:52+09:00`
- 状態: `実装計画`


## 資格判定v2の実装後の現在地（2026-09-16）

ユーザーは旧原則の改訂とその実装を明示指示した。以下のOSS試行・中断記録より新しい要求と状態である。
作業branchは`ai/ranking-qualification-v2-20260916-1908`。HEADは変更せず、既存差分を保全して実装した。
元checkout /home/tn/projects/prep-watchdeck のsource・HEAD・indexは変更していない。

- `ranking-map-v2`と`ranking-v2`で原資産・固定参照の採用資格、元数量換算、Widget対応を分離した。
  元倍率nullとWidget reviewは独立した未確認として維持する。同一性・固定参照のreviewは取得不可。
- CHEEMS・NEX・RATSを個別に再審査し、map `07bfd5c76b6fc8cbc882aeba`へ反映した。
  元1,203契約/691行を保持し、参照対応534・未対応36・対象外121・行review 0。
  元数量未確認3・Widget未確認3、Widget対応531。元倍率を推測して補完していない。
- `--require-ranking-qualified`は終了0。旧`--require-reviewed`は数量・Widget未確認により終了1。
  この違いは明示的に承認された要件改訂による。旧全確認の成功とは報告しない。
- Repository横断検証は終了0。Q1〜Q4と改訂D01〜D04の隔離実Provider受入もPASS。最終結果は下記の現行証拠を参照する。
  D05の稼働反映、commit、pushはこの改訂作業では未実施。

実装・受入記録は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/EVIDENCE.md](EVIDENCE.md)。
変更前保全と検証artifactは
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841`。
再開時はこのbranch・最終証拠・現行差分を確認し、旧mapの数量定義不足をランキング全体のblockへ戻さない。
数量換算とChartの未確認は、各機能を有効化する根拠が得られるまで保持する。

## OSS試行後の追加判断材料（改訂前の記録）

再開後、ユーザー指定のTradingView関連OSSを独立環境で試行した。
Screenerは固定参照531/531を取得し、TVの1分足からの騰落率はBTCと未解決3契約の8比較で取引所と一致した。
**倍率未確定でも同一契約の騰落率を計算できる**ため、契約単位表示と原資産統合mapの受入を分ける案がある。
一方、Screener指標は進行中の足、相対出来高の定義は別、TV-APIはvolume丸め・quote turnover欠落がある。
既存mapの数量根拠は未解決。今回の指示は技術試行であり、この設計案の製品実装・受入契約変更は未実施。

結果と再現入口: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/oss-probe-20260913-170518/REPORT.md`。
従来どおり全銘柄統合mapを完成させる場合の次入力は公式数量根拠のまま。
契約単位ランキングを先行させる場合は、表示単位・欠測・統合行との関係を設計してから実装する。

## 再開後の現在地（R0確認・R1調査）

ユーザーの再開依頼により、指定worktreeで再開した。以下は中断時の記録より新しい観測。

- canonicalのcheck-resumeはrestart-ready。作業treeのbranch/HEAD、18 tracked modified・66 untracked・stageなしは記録どおり。
- 保存manifestの作業tree272ファイル・元checkout266ファイルは全hash一致、両Git indexも一致。
  元checkoutのbranchだけは現在main。変更理由は未確認だがsource/indexに差はなく、branchを戻さない。
- 作業tree内CWDのprocessは今回の確認用shell/Pythonだけを観測。全hostのwriter不在は保証しない。
- 現役Web/MarketのWorkingDirectoryとMainPIDの実CWDは
  `/home/tn/releases/prep-watchdeck/dc2a8d7/apps/web`、
  `/home/tn/releases/prep-watchdeck/dc2a8d7/apps/market-core`。
  配置HEADはdc2a8d70f8247f8f49827f410e55170e37d95204、配置treeはclean。
- Webは127.0.0.1:5173でLISTEN。Web/Marketの実効state設定は
  `/home/tn/.local/share/prep-watchdeck-market`。DBの接続や内容確認は行っていない。
- user unitにランキングは未設置。8769/18769にLISTENなし。
  `/home/tn/.local/share/prep-watchdeck-ranking`は未作成であり、専用stateの候補にできる。
  空きportは実行直前に再確認する。WebにはPREP_WATCHDECK_RANKING_PORTのunit環境指定なし。
- 将来の反映案は、最終検証版の別releaseにランキングを配置して専用state/APIを使用し、
  Webをそのreleaseへ切り替えて専用APIへ接続する。Market/DB/maintenanceは現役releaseに保持する。
  新releaseの正確なpathは最終commit前なので未確定。deployは未実施。
- 切戻し対象は現行Webのunitとdrop-in、および現行release。現行unitは
  `/home/tn/.config/systemd/user/prep-watchdeck-web.service`
  （SHA256 55abf3701bb2005d1583c483f303e62e4380407cc018ceff41beeeef6176ccc1）、
  drop-inは`/home/tn/.config/systemd/user/prep-watchdeck-web.service.d/tailscale-host.conf`
  （SHA256 a971368b18f761d954a72373a6467288b913a33b28c8ff5e71302bfb4e2b0228）。
  反映直前に内容保全とhash再照合が必要で、今回backup/書換えは未実施。
  失敗時はWebを旧releaseへ戻し、新ranking unitを停止する。専用stateは削除しない。
- 配置版から作業版のtracked差分は75ファイルで、Market修正や過去文書整理も含む。
  未追跡66ファイルはこのdiff統計に含まれない。一括反映をランキング差分だけと呼ばず、
  最終releaseの対象manifestと既存Chart差分の扱いをD04後に確定する。
- 現mapの構造checkerを再実行し1,203契約/691行/verified531/unsupported36/review3/out_of_scope121を確認。
  reviewed gateは終了1、数量定義3件・Widget review3は未解消。
- 利用可能toolにメール送信またはメールconnectorの探索機能なし。照会は未送信、回答なし。
  同じ検索の反復や倍率推測は行っていない。

R0は確認済み。R1は現役対象・切戻し対象を確定したが、最終release/反映manifestは未確定のためPARTIAL。
次の必要入力はBitget 1MCHEEMSUSDT/10000NEXUSDT/1000RATSUSDTの公式数量・価格単位の回答、
または準備済み照会を送信できる接続。回答取得後はR3から一件ずつ検証する。
D01 BLOCKED、D04 PARTIAL、D05未実施を維持。製品code、Git index、branch、稼働serviceは変更していない。

## 最初に読む結論

ユーザーの依頼で一時中断する。D01〜D05の全体はPARTIAL、D01は数量定義3件でBLOCKED、
D02/D03は記録したsource・旧mapの範囲でPASS、D04はPARTIAL、D05は包括承認済み・未実施。
次の実作業は「稼働先・反映差分・切戻し対象をread-onlyで確定する」一作業である。
Bitgetの回答待ちでもこの準備はできる。中断記録の作成中に稼働準備の実行・製品変更を再開していない。

実装を再開する作業場所は[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700](../../../..)。
元checkoutの`/home/tn/projects/prep-watchdeck`には別の未commit変更が残る。元checkoutで実装を続けない。

新しいCodex CLIを起動する操作は以下。実際のファイル確認とAction Queueは作業treeのcanonicalに従う。

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700
codex resume-handoff
```

元checkoutから起動した場合は、元checkoutのcanonicalが上記worktreeへ案内する。
既にCodexが起動中なら、以後のtoolのCWDを上記worktreeへ切り替え、同CWDで次の再開検査を先に行う。
検査に失敗したら理由を確認し、HANDOFFの削除やvalidatorの迂回で続行しない。

```bash
python3 /home/tn/.agents/skills/session-handoff/bin/handoff_atomic_write.py --check-resume /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/.ai_memory/HANDOFF.md
```

`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/.ai_memory/HANDOFF.md`が短い再開入口、本書が中断時の詳細、
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/GOALS.md](GOALS.md)が完了条件、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/EVIDENCE.md](EVIDENCE.md)が段階別証拠である。
会話履歴の再読を前提にしない。記録時刻と次回の実測が違う場合、差の原因を確認して記録を更新する。

## 目的・確定した契約・対象外

毎分更新のランキングで対象を探し、順位の動き、売買代金の増え方、当日の高安位置を読み、
同じ参照契約のチャートを確認し、停止・履歴不足を判断して翌回も再開できる監視機能を完成させる。
利益や予測精度は成功条件に含めない。

ランキングは元Bitget/Hyperliquid Core/Asterの名簿を保持し、対応を確定したBybit/Binanceの
USDT linear perpetualの確定1分約定足から計算する。独立process、専用SQLite、専用API、
固定した参照契約、共通UTC分境界Tを使う。元Market Core、Postgres、Parquet、4 artifactへ書き戻さない。
TradingView Widgetは閲覧用で、ランキングへの数値供給元ではない。

D02は「前順位−現順位」。直前に発行済みの連続1分世代と、同じmap/metric/期間/並び順/下限/JST設定で比較する。
初回、再起動、世代欠落、map変更、日次anchor変更は比較不可。前世代を最大1世代、cacheを32条件/世代・最大2世代に制限する。

D03の平常比は最新wの売買代金/直近24時間内の最新窓を除く非重複w窓の中央値。
15分は過去95窓、1時間は23窓。全足が必要で、基準0は比較基準なし、欠測は履歴不足。
JST可変期間には適用しない。当日位置はJST00:00以後の確定足high最大H/low最小Lから
100×(C(T)−L)/(H−L)。開始直後、H=L、欠測は数値なし。追加指標だけの欠測で既存順位を外さない。
metricVersionはtrade-close-quote-turnover-analysis-v2。新規migrationや保存期間拡大は行っていない。

通知、上位滞在時間、ミニチャート、短期スイング指標、新規Provider、
自動売買・注文・残高・ポジション・秘密API keyは今回の対象外。
別project、特にJustPassのPostgres/5432/container/volume/database/roleへ接触しない。

## 承認と中断の扱い

ユーザーは「明示的にすべてを許可する」と、ランキング完成・D05稼働反映に必要な作業を包括承認した。
その後「作業やタスクは分解して逐次的に一つずつ」と指示した。既に承認済みの同じ操作について再承認を求めない。
対象と反映先を実物で確定し、D04 PASS後にD05へ進む。承認を根拠不足・品質未達の代わりにしない。
commit/push等も必要な対象差分についての許可はあるが、今回まだ実施していない。
任意のPR/merge、無関係な相手へのmessage、新規課金・credential/account変更・既存データ削除を推測で追加しない。

最新指示は中断資料の作成である。今回は資料を更新して終え、製品実装・問い合わせ送信・稼働操作は始めない。
次回は再開指示に従い、準備→検証→反映→記録を一件ずつ閉じる。

native Goalは本記録作業で読み取り、blockedを確認した。
登録されたobjectiveは当初のD01〜D04・D05対象外という文面のまま。これは履歴であり、追加承認を取り消すものではない。
文書とnative Goalは別管理。資料更新でGoalを再登録・完了・再開したとは扱わず、再開だけを理由に新規Goalを作らない。

## Git・環境・processの中断時点

観測時刻: **2026-09-13T16:45:18+09:00**。hostはubuntu、Ubuntu環境、shellはzsh。

| 項目 | 作業用worktree | 元checkout |
| --- | --- | --- |
| 場所 | /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700 | /home/tn/projects/prep-watchdeck |
| branch | ai/ranking-daily-use-20260912-2119 | ai/independent-daytrade-ranking-20260912-0736 |
| HEAD | 8d12fa6979700f3ed281f06262a91cb25faa635c | 8d12fa6979700f3ed281f06262a91cb25faa635c |
| 中断資料編集前 | tracked変更18、untracked65、計83 | tracked変更18、untracked60、計78 |
| stage | 0 | 0 |

この資料が新しいuntracked1件になり、資料追加後の作業treeは計84件と確認した。
canonicalはGit-ignored。最終件数とsource/index保全は`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/final-audit.json`で確認する。
差分には以前からのChart等の変更も含まれ、この中断記録作業の自作差分としてstage/commitしない。
Git remoteのlive状態・push状況・本番配置版は今回未測定。HEAD一致は最新実装がcommit済みという意味ではない。

Python 3.13.12、bun 1.3.14、uv 0.12.3を本記録時に実測。
既存Pythonは/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/.venv/bin/python。引継ぎの文書検査だけのためにuv syncや依存再installをしない。
再開時の実装検証はrepoのuv/bun/lockfileに従い、環境が変わっていたらまず理由を確認する。

CWD限定のprocess観測では作業treeに本記録用Python以外のprocessなし。
元checkoutにはPID 942428/942431/942481/942482の既存Chrome DevTools関連processを観測した。
これをactive writerと断定せず、停止もしていない。全hostのwriter不在を保証する観測ではない。
以前の有限試験port 53243/54459にLISTENはなく、4173/5173等には別listenerがある。
固定portを空きと仮定して再利用しない。service/unit、実効Web設定、正式稼働state、配置versionは今回未確認。

中断記録時のsource、Git status、両index hashは`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/before.json`、
processは`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/processes.json`、toolchain/旧受入source照合は`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/prior-acceptance-and-toolchain.json`に保存。

## 現在の対応表と残る3件

正本は[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/initial-map.json](../../../../apps/ranking-core/data/initial-map.json)、根拠は[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/qualification-evidence.json](../../../../apps/ranking-core/data/qualification-evidence.json)。
mapVersionは**1ee6cd08e257dc1a90fff0e6**。

| 区分 | 数 |
| --- | ---: |
| 元契約 | 1,203 |
| 行 | 691 |
| 対応 verified | 531（Bybit 480 / Binance 51） |
| 根拠付き未対応 unsupported | 36 |
| 要確認 review | 3 |
| 対象外 out_of_scope | 121 |
| Widget supported / review | 531 / 3 |

map SHA256: `d56970b51f1062b52d8d5909fd8c1be9a47942778b74c2a3debeb69de89f2522`。
qualification SHA256: `17db9a9d2ee7846544e37cead89913128c944b70fb81b2232829a7a9edae84bb`。

| 順番 | 行 | 未確認の元契約 | 不足する一次根拠 |
| --- | --- | --- | --- |
| S10 | crypto:CHEEMS | Bitget 1MCHEEMSUSDT | 数量1を原資産CHEEMS何枚として扱うか、その価格単位・適用日 |
| S11 | crypto:NEX | Bitget 10000NEXUSDT | 数量1を原資産NEX何枚として扱うか、その価格単位・適用日 |
| S12 | crypto:RATS | Bitget 1000RATSUSDT | 数量1を原資産RATS何枚として扱うか、その価格単位・適用日 |

理由はいずれもquantity_multiplier_unverified。対象Bitget originalのmultiplierはnull、行referenceは未確定、Widgetはreview。
同じ行の他Venueの倍率、prefix、価格比、注文刻み、countMultiplier、最小数量だけで補完しない。
単なるAPI成功や上場記事の銘柄名も数量定義の代わりにしない。元instrument ID/versionを保持する。

## 今回までに閉じた9件

S01〜S09は各件で根拠→候補→検証→正本反映→記録を順番に実施した。

| 段階 | 反映内容 | 重要な判定根拠 |
| --- | --- | --- |
| S01 PROS | Aster PROSUSDTを既存Pharos行へ統合。692行から691行へ | Asterの資産情報、PharosのCA、Bybit参照identity。元ID/倍率/固定参照を保持 |
| S02 AI | 採用範囲内の未対応 | Artificial Inu/AIINUのCAを固定。AIGENSYN候補はGensynの異なるCAにより除外 |
| S03 B-MONEY | 採用範囲内の未対応 | BMONEY別名と同一CAを一次情報で照合 |
| S04 BEN | 採用範囲内の未対応 | 同一CAと採用先全対象の候補を照合 |
| S05 BONER | 採用範囲内の未対応 | Robinhood側CAを照合 |
| S06 BREW | 採用範囲内の未対応 | BSC側CAを照合 |
| S07 MAX | 採用範囲内の未対応 | MAXのCAを固定。GIGGLE候補はGiggle Fundの異なるCAにより除外 |
| S08 MEMESTOCK | 採用範囲内の未対応 | プロジェクトCA、別名、指数構成を照合。GME等のquoteを原資産aliasにしない |
| S09 PAIR | 採用範囲内の未対応 | Robinhood側CAを照合 |

8件の未対応理由は既存のno_adopted_reference_after_identity_audit、Widgetはno_eligible_reference_contract。
これは観測時点の採用2社・対象USDT crypto perpetual・保存catalog/指数の範囲での判定であり、
全市場・未発見alias・将来の上場まで不存在と断定するものではない。
元1,203契約、全固定参照531件、対象外の行、数量倍率を保持した。
Bybit519/Binance526の全1,045参照指数のidentity fields・元response hash・観測時刻をqualificationに保存。
価格をqualificationへ取り込まず、観測日時を後の時刻に書き換えない。

S01証拠: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031`。Pharosの実Widgetを1440/390pxの個別harnessで確認。
S02証拠: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/ai-qualification-20260913-083008`。
S03〜S09と総合監査: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential`。
各銘柄directoryにbefore/candidate/decision-audit/validationがある。全9件のURL・CAと失敗経過は既存EVIDENCEを参照する。

補助scriptのone-row/promote-oneは完了済みartifact directoryを再作成しない設計。
新しい数量判定へ無検討に転用しない。README件数の単純部分文字列置換で誤記が発生し、最終照合で修正済み。
以後もvalidator成功とは別に意味と件数を実mapから確認する。

## Bitgetへの照会と不足する入力

公式窓口 https://www.bitget.com/promotion/contact-us のCustomer service操作で、
2026-09-13の調査時にsupport@bitget.comを確認した。送信先の確認と照会文作成までで、**未送信・回答なし**。
公開仕様照会に使えるメール送信用接続と送信元が、当時の利用可能toolに存在しなかった。
許可不足を理由に止めたものではない。利用可能な送信手段、またはユーザー側からの送信が必要。

照会文: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/bitget-unit-inquiry.txt`。
受付操作と未送信状態: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/bitget-inquiry-status.json`。
文面は公開3契約の仕様だけで、private repo、顧客情報、認証、注文情報を含まない。
送信できた場合は宛先・送信時刻・受付IDを記録し、未送信のまま回答待ちと報告しない。
回答取得後も送信者の公式性、契約symbol、数量/価格単位、適用日時、引用可能な仕様を確認する。
あいまいな回答ではreviewを維持する。新しい根拠や入力なしに同じ検索を反復しない。

## 検証済みと未実施を区別する

| 証拠層 | 実施結果 | 限界 |
| --- | --- | --- |
| D02/D03 source検証 | Ranking109 pytest、Web158 unit、check 0 errors/warnings、関連E2E12・全Web E2E34、Ruff/Pyrefly等を記録 | 2026-09-12時点の実行。今回再実行していない |
| 旧mapの実データ | 実API3契約×3期間の独立9比較、空stateの全531契約、保存state復旧を確認 | map 4ce42c272921615dbf0b64e5 |
| 旧mapの復旧 | 通常3世代、WS再接続約2003ms、75秒停止、復旧3世代。最大世代985ms、RSS約456MiB | 12秒deadline/150秒鮮度を確認。実hostのcgroup適用証拠ではない |
| 実Widget | 旧8ケース＋S01 PharosのDesktop/Mobile個別表示 | 全531契約の個別描画、現mapの全product route受入ではない |
| 現mapの構造・根拠 | 本中断時にchecker終了0、元1,203契約/691行を再確認 | checkerは公式数量定義そのものの正しさを自動証明しない |
| 現mapのreviewed gate | 本中断時に終了1、review3/Widget review3 | 未達を確認する期待終了値であり、製品PASSではない |
| 全repo gate | 最終保存logは旧mapの12reviewで終了1 | 現mapでの全体再実行は未実施 |
| 現mapの最終受入/D05 | 未実施 | 対応表確定、必要な最終check、隔離受入、稼働先確定後に行う |

旧受入一式: `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909`。
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/cold-run.json`、`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/recovery-run.json`に完全な実行argv・source hash・port・seed provenanceがある。
記録対象sourceと現在を照合し、違うのはmapだった。旧cold/recoveryの保存mapも旧versionであることを確認した。
古いstateや証拠を上書き・削除せず、新しい専用state、または停止済みの正当な専用stateの新しいコピーを使う。
SQLiteのコピーはprocess/lock/sidecarを確認してから行い、稼働中ファイルを単純コピーしない。

本中断記録作業ではmetadata/link、canonical書込み/再開、hash/差分保全、現mapの軽いread-only確認を行う。
製品tests、build、実API/WS受入、ブラウザー試験を再実行していない。検査の最終結果は本書末尾の成果物を参照する。

## 再開後の逐次キューと完了条件

| 順番 | 一作業として閉じる内容 | 次へ進む条件 |
| --- | --- | --- |
| R0 | canonical検査、両Git状態・index・新writerを再確認し、本書と最終auditとの差を理解する | 正しいworktreeと既存変更を保全できる |
| R1 | 稼働host/checkout/version、unit、port、専用state、Web設定、反映差分、切戻し対象をread-onlyで確定 | 推測値のない実行案。未解決項目を記録。稼働操作はまだしない |
| R2 | 利用可能なBitget照会送信手段を確定し、送信またはユーザーによる送信記録を受け取る | 未送信/送信済み/回答受領を区別。回答なしでもR1の独立準備は進めてよい |
| R3 | S10 CHEEMSを公式回答で確定→候補map/根拠→検証→反映→記録 | 当該数量の一次根拠と元ID保持を確認 |
| R4 | S11 NEXを同じ手順で閉じる | 当該数量の一次根拠と元ID保持を確認 |
| R5 | S12 RATSを同じ手順で閉じる | 当該数量の一次根拠と元ID保持を確認 |
| R6 | 最終mapの全件照合・必要な回帰/必須gate・有限の空state/再開/復旧・画面を確認 | G01〜G10、D01〜D04が証拠付きPASS。review0だけで代替しない |
| R7 | 確定した差分のGit保存/必要な公開と、承認済み稼働先への反映、実稼働受入 | 配置version・実際の制限・鮮度・実画面・再開・切戻しを確認しD05 PASS |

R1で他writer、稼働先不明、異なる用途のDB等を見つけたら、該当操作を止めて対象を解決する。
D04未達のままdeploy/unit操作/元checkoutへの統合を始めない。
公式数量根拠が得られない場合、3件を検索不在による未対応へ変更してR6を通さない。

## 安全な確認commandと副作用境界

最初のGit確認。出力が中断時と違ってもreset/clean/stash/checkoutで合わせない。

```bash
git --no-optional-locks -C /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700 status --short --branch --untracked-files=all
git --no-optional-locks -C /home/tn/projects/prep-watchdeck status --short --branch --untracked-files=all
git -C /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700 diff --cached --stat
git -C /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700 worktree list --porcelain
```

R1のunit名を知るための入口は以下。出力確認後、実在する対象のLoadState/ActiveState/FragmentPath/
WorkingDirectory/MainPID等を読み、必要な設定値だけを取得する。環境全体やcredentialを出力しない。
user serviceに存在しない場合だけsystem側の対象を調べる。serviceのstart/stop/restartはこの段階で行わない。

```bash
systemctl --user list-units --all --no-pager 'prep-watchdeck*'
systemctl --user list-unit-files --no-pager 'prep-watchdeck*'
```

現対応表をネットワークなしで確認するcommand。前者は終了0、後者は未解消3件のため終了1が記録時の期待値。
既存環境を直接使い、依存同期やbytecode生成を避ける。

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700
PYTHONDONTWRITEBYTECODE=1 /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/.venv/bin/python /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/verify-map-evidence.py
PYTHONDONTWRITEBYTECODE=1 /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/.venv/bin/python -m prep_watchdeck_ranking.cli validate-map /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/initial-map.json --require-reviewed
```

[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/accept-live.py](../../../../scripts/ranking/accept-live.py)の有限受入は300〜900秒。
collector wrapperの最大86400秒と混同しない。既存900秒上限、12秒deadline、150秒鮮度、cache/取得上限を緩めない。
隔離は既存bwrap手順を利用し、元stateをread targetにも使わない受入条件を維持する。
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/recovery-run.json`のargvは具体例であり、古いport/stateをそのまま再実行しない。

[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/verify-local.sh](../../../../scripts/verify-local.sh)は一時Postgres、型生成、build、Playwrightを含む出力生成処理。
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/current/operations.md](../../../current/operations.md)の起動例にはuv syncとcollector起動がある。
いずれもread-onlyのR0/R1に使わず、R6以降で副作用と隔離先を確認して行う。
Pyreflyは正しいmodule CWDと--use-ignore-files=false/明示file指定でtestsを含める。
生成schema/typeは既存生成手順を使い、手編集しない。json2tsがない場合は既存lockで依存を確認する。

## 再開時に必要な実装の入口

- 対応判定: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/mapping.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/mapping.py)。
- 計算: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/ranking.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/ranking.py)。
- 世代・API公開: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/service.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/service.py)。
- 永続化: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/storage.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/storage.py)。
- 型・状態: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/models.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/models.py)。
- 画面: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/src/routes/rankings/+page.svelte](../../../../apps/web/src/routes/rankings/+page.svelte)。
- Web側整形: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/src/lib/market/ranking.ts](../../../../apps/web/src/lib/market/ranking.ts)。
- Widget: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/src/lib/components/ranking/ReferenceChart.svelte](../../../../apps/web/src/lib/components/ranking/ReferenceChart.svelte)。
- 近いtests/型生成/必須checkの全入口: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/GOALS.md](GOALS.md)。
- 配置template: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/config/systemd/prep-watchdeck-ranking.service.in](../../../../config/systemd/prep-watchdeck-ranking.service.in)。templateの存在は実hostへの適用を示さない。

## 保全・切戻し・最終資料検査

今回の記録開始時の未commit83 source filesを`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/uncommitted-source-before.tar.gz`へ保全。
hash/件数は`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/source-archive.json`。Git管理対象・未追跡sourceだけで、ignored実データ/DB/環境設定を含まない。
これを稼働バックアップや別hostへのバックアップと呼ばない。復元が必要なら新しい候補先へ展開して差分を照合し、
現worktreeへ一括上書きしない。開始前のdocsは`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/docs-before`、両canonicalの旧版も同artifactに保存。

Git index・branch・HEADは変更しない。元checkoutで更新するのはGit-ignoredのcanonical案内だけ。
新旧canonicalの書込みは既存atomic writerで行い、両CWDのcheck-current/check-resumeを確認する。
旧rootの2026-09-08調査は現在のランキング作業に優先する指示ではない。必要な履歴は保存済み旧canonicalを参照する。

変更後source manifest、文書差分、canonical hashと保全判定は`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/final-audit.json`、
検査command・exit結果は`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/validation.json`。
両canonicalのcheck-current/check-resume、metadata/link、git diff --checkは成功した。
独立の文書内容reviewもPASS。本文外の元checkoutへのリンクはrepo外リンク検査で一度失敗し、
絶対パスの平文へ修正して再検査に成功した。canonical候補の出力解析も一度修正し、旧正本を保ったまま書込みを完了した。
記録した一時失敗と最終結果はvalidationの履歴で区別する。
metadata/link/canonicalが通っても、数値根拠・実Provider・実Widget・本番稼働を新たに検証したことにはならない。

本書作成で、D01〜D05を完了にせず、active planを削除しない。稼働配置・commit・push・問い合わせ送信は未実施。
