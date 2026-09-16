# デイトレランキングの日常利用までのゴール

- 作成: `2026-09-12T15:40:10+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 状態: `実装計画`

## 何を完成させるか

利用者が「対象銘柄を探す → 順位の動き・売買代金の増え方・当日の高安位置を読む →
同じ参照契約のチャートを確認する」という操作を、毎分更新される正確な情報で行え、
停止・履歴不足・未対応を判断しながら翌回も利用できる監視用ランキングを完成させる。

D01〜D04をローカル実装・隔離受入の完成単位、D05を実際の稼働反映の完成単位とする。
利益、予測精度、売買判断の正しさは本ゴールの成功条件にしない。

利用者がD02〜D04の追加範囲を明示承認し、D01〜D04のnative Goalを登録した。
実行範囲は日常利用の準備と分析機能の拡張であり、計算定義は本書を維持する。
当初はD05、commit、push、稼働操作を別承認とした。その後、利用者は本ランキングの完成・
稼働反映に必要な作業を包括許可し、タスクを分解して1件ずつ逐次実行するよう指示した。
以下の当初範囲にある承認待ちの記載より、この追加承認を優先する。
具体的な操作対象・反映先は実物で確定し、根拠不足や未達の受入条件は承認で代替しない。
2026-09-16に資格判定改訂の実装を開始した。再開手順と各時点の実測は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/RESUME.md](RESUME.md)を正本とする。

## 資格判定の改訂と実装チェックポイント

利用者は2026-09-16に旧原則・完了条件の見直しを許可し、続いて実装を指示した。
ランキングの採用資格、元契約の数量換算、Widget対応を別々に判定する。
旧条件でのBLOCKED・実測結果は当時の記録として保持し、新条件のPASSへ読み替えない。

- 行の`verified`は、保持する元契約の原資産同一性と固定参照契約の資格が確認済みであることを示す。
  元契約の`multiplier=null`は許容し、数量換算を未確認のまま保持する。倍率を推測しない。
- 同一性・参照契約が未確認の行は`review`のまま価格取得・順位計算へ進めない。
  全名簿の保持、根拠付き未対応・対象外、固定参照・共通T・確定足・quote turnoverの条件は維持する。
- Widgetの`review`はそのChartだけを利用不可にする。表示時の参照契約一致と独立根拠は必須。
- `--require-ranking-qualified`をランキングの全件照合gateとする。旧`--require-reviewed`は
  原資産・参照・元数量倍率・Widgetの全確認gateとして残し、意味を黙って弱めない。
- mapは`ranking-map-v2`、APIは`ranking-v2`へ更新し、旧世代を暗黙変換しない。
  候補mapを再審査・再生成する。変更前後の順位差は既存のmap変更扱いで比較不可とする。
  SQLiteの足の構造、既存Market Core、既存4 artifact、取得先・計算式は変更しない。

| 順序 | 作業 | 完了条件 |
| --- | --- | --- |
| Q1 | 要求改訂・既存差分保全 | 新基準、対象、互換性、rollbackを明記する。 |
| Q2 | model・CLI・証拠checker・schema・Web表示 | 元倍率nullとWidget reviewがランキングを妨げず、不適格な参照は拒否する。 |
| Q3 | CHEEMS → NEX → RATSの個別再審査 | 一次根拠に結び付いた元identity・参照契約だけを採用し、数量未確認を別記する。 |
| Q4 | 最終source/mapの検証 | Python/Web/E2E・repo必須checkと隔離した実Provider受入を記録し、Widgetの実表示結果は別判定にする。 |

Q1〜Q4と改訂基準のD01〜D04はPASS。検証結果と残る独立未確認は現行の証拠文書へ記録した。
D05の稼働反映は未実施。元数量・Widgetの各3件は確認済みへ昇格していない。

作業branchは`ai/ranking-qualification-v2-20260916-1908`。
編集前272ファイルと元checkoutのhash/indexは
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/baseline.json`へ保存した。
rollbackは
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/source`
から本作業で変更したファイルだけを差分確認して戻す。
旧state・元checkout・他作業の差分は削除・上書きしない。D05の実行はD04と反映対象の確定後に扱う。

## 現在地と要求の正本

定義時の作業場所は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700。
元checkoutは /home/tn/projects/prep-watchdeck であり、そちらのファイル・index・branchは編集しない。
元checkout配下の既存試験artifactは読取り用の証拠として扱う。

- 初期版の要求: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/independent-daytrade-ranking/GOAL.md](../independent-daytrade-ranking/GOAL.md)
- 初期版の証拠: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/independent-daytrade-ranking/EVIDENCE.md](../independent-daytrade-ranking/EVIDENCE.md)
- 銘柄根拠: [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/qualification-evidence.json](../../../../apps/ranking-core/data/qualification-evidence.json)

D01〜D04開始時のmapはversion 4ce42c272921615dbf0b64e5、元1,203契約を692行へ保持し、
対応531・未対応28・要確認12・対象外121。これは今回の出発点であり、将来の固定件数目標ではない。
実行開始時に実物を再確認し、採用範囲や対象名簿を取得失敗に合わせて縮めない。

初期版G01〜G10のうち資格判定は上記改訂を正本とし、その他の計算・分離・復旧条件は維持する。
保存済みのテスト・実Provider・Widget証拠は、観測時点・map・実行sourceとの対応を確認して利用する。
過去のPASSだけで変更後の実装や現在の稼働が確認済みとは扱わない。

## 実装順序と依存関係

| ID | 完成時に利用者ができること | 開始条件 | PASS条件 |
| --- | --- | --- | --- |
| D01 基礎の完成 | 全対象の取扱い・参照契約・対応できない理由を正しく読める | 現行差分と証拠を保全する | 改訂G01〜G10を満たし、原資産同一性・固定参照の要確認が0。元数量換算・Widgetの未確認は独立して報告 |
| D02 順位の変化 | 同じ条件で1分前から順位がどう動いたか分かる | 既存の確定generationと対応済みmapを使える | 下記の比較契約・状態表示・回帰確認が成立 |
| D03 値動きの背景 | 同期間売買代金の平常比とJST当日の高安位置を読める | 既存の確定1分足を使える | 下記の計算契約と欠測時の表示が成立 |
| D04 日常利用の準備 | 空の状態から起動し、遅延や停止を読み分け、専用processを復旧できる | D02・D03を統合する。D01未達中も依存しない準備は進める | D01〜D03、最終sourceの必須check、有限の隔離受入、運用手順がすべて成立 |
| D05 稼働反映 | 承認された通常の起動経路で同じ機能を利用できる | 包括承認済み。D04 PASS、反映先と差分の確定 | 配置したversion、実際の制限、実画面、復旧・切戻しの確認が成立 |

推奨順は現状固定 → D01の未確認調査 → D02 → D03 → D04 → D05。
D01で新しい一次根拠が得られない場合は試行済みの方法と不足を記録し、独立したD02・D03の
実装・検証を進めてよい。D01の状態は未達のまま保持し、D04全体やD05の合格条件を下げない。
D02とD03の実装は順番に行い、同じsourceへの並行writerを増やすことを前提としない。

## 逐次再開のチェックポイント

同時に複数の銘柄判定を書き換えず、1件の根拠確認 → 候補作成 → 検証 → 正本反映 → 記録を閉じてから次へ進む。

| 順序 | 対象 | 状態・次の条件 |
| --- | --- | --- |
| S01 | Aster PROSUSDTを既存Pharos行へ統合 | 対応表反映と個別Widget確認まで完了。最終mapでの全件稼働受入は別途必要。 |
| S02 | Aster AIUSDT | 対応表反映まで完了。Artificial Inu/AIINUのCA、採用先全catalog/指数、Gensyn除外根拠から確認時点の未対応を確定。 |
| S03 | Aster B-MONEY | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S04 | Aster BEN | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S05 | Aster BONER | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S06 | Aster BREW | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S07 | Aster MAX | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S08 | Aster MEMESTOCK | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S09 | Aster PAIR | 完了。一次CA/別名と採用範囲の全件候補照合に基づく未対応を反映。 |
| S10 | Bitget CHEEMS | Q3で原資産・固定参照を確認しランキング採用済み。元数量とChartは未確認を維持。 |
| S11 | Bitget NEX | Q3で原資産・固定参照を確認しランキング採用済み。元数量とChartは未確認を維持。 |
| S12 | Bitget RATS | Q3で原資産・固定参照を確認しランキング採用済み。元数量とChartは未確認を維持。 |
| 最終 | D01〜D04の全件受入 → D05稼働反映 | 最終source/mapで失効した受入をやり直し、既存の完了条件を満たしてから進む。 |

## D01: 初期版を完成させる

開始時の12行を次の論点で照合する。PROSはS01、Asterの残る8行はS02〜S09で対応表へ反映済み。

| 対象 | 確定すべきこと |
| --- | --- |
| BitgetのCHEEMS・NEX・RATS | 原資産同一性と固定参照契約の一次根拠。元数量倍率は独立した未確認項目として保持 |
| Aster PROSUSDT | Pharosか旧Prosperかを区別する公式の資産identity |
| AI・B-MONEY・BEN・BONER・BREW・MAX・MEMESTOCK・PAIR | 指数式の別名を元資産と採用先の契約へ結び付ける根拠 |

原資産・参照契約について、対応、根拠付き未対応、対象外を確定する。
数量換算とWidgetは各機能の確認状態と根拠を別々に記録し、未確認を対応済みへ読み替えない。
symbol prefix、価格の近さ、検索で見つからないことだけで判定しない。
判定変更は元instrument IDを保持し、map versionと証拠を同時に更新する。

完了には全件照合の `--require-ranking-qualified` が終了0となることに加え、改訂G01〜G10の
内容監査を要する。照合checkerの成功だけを根拠の正しさや実データ受入の代わりにしない。
公開一次情報が取得できず原資産・固定参照の正当な判定を作れない行は要確認を保持し、D01を完了としない。
元数量倍率またはWidgetだけの未確認は、対応する機能の未達として報告する。

## D02: 1分前からの順位変化

比較するのは現在の確定世代Tと、直前の分境界T−1分で発行された確定世代である。
同じmap version、metric version、期間、並び順、売買代金下限、JST設定でそれぞれ順位を計算する。
JST基準の比較開始日時が切り替わる世代間は比較しない。

- 順位変化は「前順位 − 現順位」。8位から3位なら `+5`、3位から8位なら `−5`、同順位は `0`。
- 前世代が正しく存在し、前回だけ順位対象外だった銘柄は「新規」。比較元の欠落を「新規」にしない。
- 現在順位外の場合は現在の除外理由を表示し、順位差を計算しない。
- 初回、再起動、世代の欠落、古い結果、map・指標定義の変更では「比較不可」と理由を示す。
- 期間・下限の変更後は、その同じ新条件で両世代を計算する。別条件の順位差を使わない。
- 後着訂正で過去に発行した世代を書き換えない。更新中も異なる世代の行を混ぜない。

変更面は既存の計算・API model・ランキング画面・生成schemaと型・関連testsに限定する。
前世代を保持する方法は既存generationを再利用できる最小構成から選び、
保持世代・設定cacheを有限にする。Browser数や設定数による外部取得の増加は認めない。

確認は手計算fixture、同順位、新規、現在順位外、欠測、日跨ぎ、map変更、
設定切替、再起動、後着訂正、およびDesktop/Mobileでの表示・選択保持で行う。
公開APIから過去の順位を再取得して、過去の発行結果を再現したと扱わない。

## D03: 売買代金の平常比とJST当日の高安位置

本段階の数値定義は以下の承認済み定義に固定する。別の意味の「平常比」への変更は本書を更新してから実装する。

### 同期間売買代金の平常比

対象期間は15分と1時間。確定世代Tの直近24時間を、比較期間wの非重複窓に分ける。
最新の `[T−w,T)` を比較対象Q0とし、それを除く過去窓のUSDT建て売買代金の中央値をBとする。
平常比は `Q0 / B`。15分では過去95窓、1時間では過去23窓を用いる。
この24時間は現行generationが扱う範囲に合わせた仕様案であり、統計的な優位性の主張ではない。

- Q0=200、過去窓の中央値B=100なら `2.0倍`。Q0=0、B>0なら `0倍`。
- 全窓の確定足がそろわない場合は「履歴不足」。一部窓だけの平均やゼロ埋めへ変更しない。
- B=0は「比較基準なし」。無限大や0倍へ置換しない。
- JST可変期間にはこの指標を適用せず、15分・1時間のみ対応と表示する。
- 単位と対象は同じ参照契約の売買代金。市場全体や元3取引所の合計ではない。
- 正確な表示名と説明で「直近24時間内の同期間中央値との比較」と分かるようにする。

### JST当日の高安位置

DをTの属するJST日の00:00とする。`[D,T)` の確定1分足のhigh最大値H、low最小値L、
同じ終了時刻の終値C(T)を使い、`100 × (C(T)−L)/(H−L)` を表示する。
当日は利用者の任意HH:mm基準と区別し、JST 00:00からであると表示する。

- L=80、H=120、C(T)=100なら50%。Lなら0%、Hなら100%。
- T=Dは「開始直後」、H=Lは「値幅なし」、足の欠落は「履歴不足」。数値を作らない。
- 完全な足がそろっているのに範囲外となった場合は入力不整合として数値を無効にし、丸めで隠さない。
- 終値の最大・最小でhigh/lowを代用しない。Widgetからデータを取り出さない。

新指標はランキング行と選択した銘柄の詳細で読めるようにする。
既存3種類の並び順を維持し、新指標による並び順はこの段階には追加しない。
新指標だけが履歴不足の場合も、既存の騰落率・売買代金が有効なら既存順位を維持する。
指標ごとに値の有無と理由を表し、既存の行statusに別の概念を詰め込まない。

現行SQLiteはOHLCを保持するが、generation向けの取得は終値・売買代金が中心である。
必要なhigh/lowを同じ確定入力へ追加し、API読取り時に変化したDBを再参照しない。
保存期間や外部取得先の拡大をこの指標の実装へ混ぜない。

確認は計算fixture、中央値の窓境界、0・欠測・数量倍率、high/lowと終値の区別、
JST日跨ぎ、基準設定、世代固定、追加指標だけの欠測、レスポンスと実画面の一致で行う。
代表契約では同じT・同じ参照APIの確定足を用いた別計算とも照合する。

## D04: 継続利用・起動・復旧の準備

最終sourceとmapで以下を確認する。

1. 新規の隔離stateから起動し、準備中・履歴不足を経て対応済み契約の必要な比較が可能になる。
2. 保存済みの正当な専用stateからの再開も確認し、空state試験と別の証拠を残す。
3. 既存の有限受入手順で通常3連続世代、実WS再接続、75秒停止、復旧3連続世代を検証する。
   空stateの履歴準備と復旧受入は別の有限試験にしてよい。現在のhelperの最大900秒を無断で拡大しない。
4. 共通T・全対応件数・各期間の有効数・除外理由・処理時間・RSS・外部取得量を記録する。
   既存の処理deadline12秒、鮮度150秒、取得・cache上限を維持する。
5. 初回、再読込み、並び替え、期間・下限・JST設定、選択、Widget、遅延・更新停止をDesktop/Mobileで確認する。
6. 名簿の追加・削除・参照revision変更を、候補作成 → 全件照合 → 専用process再起動で反映できる手順をそろえる。
7. 起動・停止・再開・障害判別・切戻しを、入力 → 起きること → 次へ進める条件で説明する。

source、生成型、schemaの整合を保ち、最終diffとrepo必須checkを確認する。
通常テストのfixtureと実Provider／実Widget受入は別々に報告する。
同じhostのcgroup制限を適用した証拠はD05へ分け、templateの存在や手動RSS計測だけで適用済みとしない。

D01未達中も上記の機能確認は進められるが、対応済み範囲だけの成功を全件受入へ読み替えない。
D01〜D03と本段階の必須条件がそろって初めて、ローカル完成をPASSとする。

## D05: 承認された稼働先へ反映する

利用者は本ランキング完成・稼働反映に必要な作業を包括承認済みである。
D04の前にdeploy、unit操作、元checkoutへの統合を始めない。対象を読み取りで確定する準備は先に行える。

実行前に、反映先host・checkout・branch/version・port・state・unit名・Web設定、
最新の他writer・既存差分、具体的な反映差分、検証結果、切戻し対象と手順をread-onlyで確定する。
未知の値を仮置きして実行しない。元checkoutへの統合が必要なら、他writerとの競合を解消してから
対象差分だけを取り込む手順を準備する。既に承認された同じ操作の許可を再度求めない。
対象が確定できない場合は必要な情報を求め、範囲外の変更・新規課金・認証変更を包括承認へ混ぜない。

明示承認された操作だけを実行し、実際の通常起動経路でAPI・Web・Widget・鮮度・保存先・
cgroup等の制限・再開を確認する。配置versionと受入時刻を結び付け、未反映のsourceを稼働中と報告しない。
ローカル完成、commit、push、配置、稼働受入の判定は別々に残す。不要なGit操作を前提条件にしない。

D05までが現在の承認済み最終到達点である。現在の未着手理由はD04未達と反映対象未確定であり、
承認待ちではない。中断依頼中に稼働操作を始めず、再開後に上記の順序を守る。

## 変更対象と検証の入口

以下は現存する入口であり、同じworktree内の関連実装・testsを必要範囲で変更する。
生成物の手編集、別projectの変更、既存API・4 artifactへの意味変更は行わない。

| 作業面 | 入口 |
| --- | --- |
| 計算とAPI型 | [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/ranking.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/ranking.py)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/models.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/models.py) |
| 保存と世代発行 | [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/storage.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/storage.py)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/src/prep_watchdeck_ranking/service.py](../../../../apps/ranking-core/src/prep_watchdeck_ranking/service.py) |
| Web表示 | [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/src/routes/rankings/+page.svelte](../../../../apps/web/src/routes/rankings/+page.svelte)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/src/lib/market/ranking.ts](../../../../apps/web/src/lib/market/ranking.ts) |
| 隔離受入 | [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/run-isolated.py](../../../../scripts/ranking/run-isolated.py)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/accept-live.py](../../../../scripts/ranking/accept-live.py) |
| repo必須確認 | [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/verify-local.sh](../../../../scripts/verify-local.sh)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/current/validation.md](../../../current/validation.md) |
| 操作説明と視覚規範 | [/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/current/user-manual.md](../../../current/user-manual.md)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/current/operations.md](../../../current/operations.md)、[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/DESIGN.md](../../../../DESIGN.md) |

変更に近いpytest・Web unitから始め、Ruff・Pyrefly・型生成・check/build・関連E2Eを
repo規約と変更内容に合わせて実行する。D04では副作用を確認したうえでrepo全体の必須確認を行う。
docsは既存metadata/link checkerと `git diff --check` で確認する。
数値定義は人が再計算できるfixtureと実API比較を使い、実装の分岐を写しただけのtestsを増やさない。

## 証拠・停止・rollback

実装開始時に、この計画と同じdirectoryの証拠台帳
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/EVIDENCE.md` を作成済み。
各checkpointでD番号、source/map version、実行した確認と終了結果、証拠の絶対パス、
残作業、未確認、次の一手を記録する。native Goalの状態と文書上の進捗は区別する。

正当な情報が得られない、隔離できない、外部制約で取得できない、資源上限を満たせない、
他writerの変更を安全に分離できない場合は、その依存作業を止めて根拠を残す。
依存しない許可済み作業を終え、試した方法・不足・必要な最小入力を報告する。
期限・token・待機の終了や一部のPASSを、全体の完成へ読み替えない。
検証の失敗条件を緩めたり、無関係なprovider・新規課金・認証を追加したりして解消しない。

追加機能を切り離すときは初期版の有効な表示・APIへ戻せるよう差分を保ち、
新しい保存形式が必要な場合も専用stateの互換性と復旧方法を実装前に検証する。
既存stateの不可逆migration、広い削除、他人の差分の破棄は行わない。
新しい指標のために旧履歴を削除したり、別契約の履歴をつなぎ直したりしない。

完了後は現行仕様と採用済み判断を対応する正本へ反映してからactive planを閉じる。
D01の旧planを閉じる際は、本書から必要な要求・証拠を参照できるようリンク先を更新し、
未commitの要求・証拠を失わせない。commit等は包括承認の対象だが、対象差分と品質条件を確定してから実行する。

## 今回の範囲外

上位滞在時間、ミニチャート、市場全体指標、通知、短期スイング指標は次の別ゴール候補とする。
追加する場合は期間・閾値・保存上限・欠測時の意味・通知先等を定義してから採用する。
D02の順位変化を、上位滞在時間まで実装したことにしない。

自動売買、注文、残高、ポジション、秘密API keyは対象外。
D01〜D04のローカル受入と、Git上の保存・公開、D05の稼働反映を別々に記録する。
ランキング完成に必要な許可済み操作を実行できるが、任意のPR/merge、他用途の外部message、
新規課金・credential/account変更・無関係なlive DB操作まで対象を広げない。
別project、特にJustPassのPostgres、port 5432、container、volume、database、roleへ接触しない。

## 当初登録したゴールの履歴

下記はD01〜D04開始時に登録した文面の保存であり、再投入する現在用promptではない。
中断記録時のnative Goalはblockedである。後の包括承認は本書冒頭とD05節に反映済み。
履歴中のD05/Git等の禁止文を現在の追加承認より優先せず、文書更新でnative Goalを変更したとも扱わない。
再開だけを理由に新規Goal登録・再登録・完了化を行わない。

~~~text
/goal /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/GOALS.md を正本として、D01〜D04のローカル完成を実装・検証する。開始時に現行source・Git差分・map・証拠を確認し、既存差分と元checkout・稼働データを保全する。全件照合、1分前からの順位変化、定義済みの同期間売買代金平常比とJST当日高安位置、継続利用と復旧の順に進める。D01が一次情報不足でも依存しないD02・D03・D04の準備は進め、未確認を未対応へ付け替えず、D01未達のまま全体を完了にしない。各段階の計算契約・欠測時の表示・回帰・隔離した実Provider／Widget受入を証拠付きで確認し、変更で無効になった検証をやり直す。checkpointごとに同directoryのEVIDENCE.mdへ現在地・確認結果・残作業・阻害条件を記録する。失敗に応じて最小修正か許可済み代替を選び、根拠なく同じ調査を反復しない。解消不能な依存作業は不足する一次根拠・試行済み方法・再開条件を報告し、完成とはしない。D01〜D04の全条件を監査してからローカル完成とする。D05の稼働反映、commit・push・PR・merge、既存unit・live DB操作、課金、後続候補の追加は実行しない。
~~~

承認状態: ランキング完成と稼働反映に必要な作業は包括承認済み。1件ずつ準備・検証・反映・記録を閉じる。
実行状態: 中断、全体PARTIAL。S01〜S09反映済み。現mapは1ee6cd08e257dc1a90fff0e6、元1,203契約/691行、
対応531・未対応36・要確認3・対象外121。S10〜S12はBitgetの公式数量定義が不足し、照会文は未送信。
現mapのreviewed gateは終了1。全repo gateの最終logは旧map/12件での停止履歴であり、
現mapによる全repo gateと全件実受入は未実施。D05未実施。native Goalは別管理のblocked。
