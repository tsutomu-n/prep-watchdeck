# 外部参照によるデイトレ向け統合ランキング初期版のゴール

- 作成: `2026-09-12T07:22:08+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 状態: `実装計画`

初期版の要求・完了条件を記録する。資格判定は2026-09-16の改訂を反映したG01を適用し、
最新の実装・受入状況と後続のD01〜D05は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/GOALS.md](../ranking-daily-use/GOALS.md)
および同計画の証拠文書を正本とする。以下の導入時件数は当時の記録である。
作業場所は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700。別Codexが稼働する元checkoutと分離し、未commit差分を保全して引き継いだ。
このworktreeへ531対応・12要確認のmapと文書を統合した。G01未達のため全体はPARTIAL。
進捗と証拠は同directoryのEVIDENCE.mdに記録する。稼働サービスへの反映は対象外。

## 1. 達成する状態

デイトレ利用者が、Bitget・Hyperliquid Core・Asterの対象crypto linear perpetualを
取引所ごとに分断されない一覧で確認し、外部の公開perpsデータから毎分更新される
騰落率・同期間の売買代金を使って注目銘柄を発見し、選択した参照契約を単一のTradingView Widgetで
確認できる初期版を、既存の重要な収集・保存データから独立させて実装する。

完成は、sourceと必要なテストがそろい、隔離環境で実際の外部データを使った取得・計算・更新と
Widget連携の受入証拠がそろった状態とする。本番deployや既存unitの変更はこのゴールに含めない。

このゴールで完成させるのは、次の必須5項目である。

1. 15分・1時間・ユーザー指定JST時刻からの上昇率／下落率ランキング。
2. 同期間の売買代金、売買代金順への切替、売買代金下限による絞込み。
3. 全対象を扱う毎分の比較と、鮮度・欠測・対応範囲の表示。
4. 正確な共通銘柄map、固定した参照契約、元の3取引所での取扱い表示。
5. 単一TradingView Widgetへの連動と、更新時の選択・表示設定の維持。

## 2. 利用者が完遂できる操作

1. ランキング画面を開くと、既定の比較期間15分について、比較時刻と対象件数が分かる。
2. 上昇率、下落率、売買代金の順に切り替え、同じ比較期間の騰落率と売買代金を読める。
3. 1時間またはJST基準時刻からの比較へ切り替えられる。JST基準は既定00:00で、
   HH:mmを1分単位で設定でき、Browser単位で保存される。
4. 売買代金の下限を変えると対象が絞られ、絞込み後の順位であることが分かる。
5. 各銘柄について、外部の参照取引所・契約と、Bitget・Hyperliquid Core・Asterでの取扱いを区別できる。
6. 行を選ぶと同じ参照契約のChartへ進める。Widget未対応の場合は、その理由が分かる。
7. 毎分の更新、並び替え、期間切替でも選択銘柄をIDで維持する。
   選択銘柄が絞込み対象外になった場合も、別の銘柄へ無言で切り替わらない。
   Chartの足間隔はアプリが保持できる設定として提供し、ランキングの比較期間と分ける。
   毎分のランキング更新のためにWidgetを再生成し、表示範囲を初期化しない。
8. 取得遅延、履歴不足、未対応を実際の0%や売買代金0と区別できる。
   データ更新が止まった場合は、最後の比較時刻と更新停止が分かる。

## 3. 範囲と保護する境界

### 実装対象

対象Repositoryは /home/tn/projects/prep-watchdeck に限定する。

| 対象 | 許可する変更 |
| --- | --- |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/ | 作成済み。専用収集、銘柄map、保存、計算、読み取りAPI、tests。Pythonと既存toolchainを使用する。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/src/ | ランキング用の取得・表示、既存JST設定の再利用、単一Widget、必要なエラー表示。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web/tests/e2e/ | ランキングとChart選択の回帰検証。通常のE2Eは外部APIとWidgetを隔離する。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/schemas/ | 新しいランキング契約に必要な独立schema。既存4 artifactの意味を変更しない。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/config/systemd/ | 必要な新規unitのtemplate作成まで。install、enable、start、stop、restartは含めない。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ | 専用の隔離検証と既存検証への組込みに必要な範囲。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/pyproject.toml と /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/uv.lock | 専用moduleをworkspaceへ追加するための必要最小限の変更。 |
| /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/DESIGN.md と /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/ | 実装した挙動、境界、操作、検証方法を正本へ反映する変更。 |

上記の範囲で実装を行った。Python独立workspace、既存aiohttp/Pydantic、SQLiteを採用した。
変更の実績と既存差分の保全確認は証拠台帳に記録する。不要な新規dependencyや汎用基盤を追加しない。

### 元データとの分離

- ランキング用の価格・売買代金は、Bitget・Hyperliquid Core・Aster以外の採用済み公開perps APIから取得する。
  最初の採用候補はBybitとBinance。取得不能を元の3取引所からの自動補完で隠さない。
- 既存側から参照するのは、対象銘柄とそのidentity・取扱いを決めるための情報だけとする。
  専用mapに取得元とversion・確認時刻を残す。
- 既存の騰落率APIは元のartifactの利用可能性に依存しているため、全銘柄ランキングの取得経路へ流用しない。
  元の複数artifactの鮮度をランキング更新の必須条件にしない。
- 別process、別保存先、別設定で動かす。既存Postgresへの接続情報をランキング側へ渡さない。
  元のPostgres、Parquet、4 artifact、選択制御、Past Noteへ書き戻さない。
- 起動時に保存先を解決し、元stateと同一・内包関係にある保存先を拒否する。
  書込み制限は新規側の起動設定で設け、既存保存先や他serviceの権限を変更しない。
  source上の書込み経路がないことと、稼働時の制限が実際に適用されたことは別々に検証する。
- 既存stateの既定位置は /home/tn/.local/share/prep-watchdeck-market である。
  実装開始時には実効設定を再確認する。ランキングstateの候補は
  /home/tn/.local/share/prep-watchdeck-ranking であり、現時点では未作成。
- SQLiteを専用保存の第一候補とする。Webはランキング側の読み取りAPIから結果を受け取る。
  Browserごとにランキング用の外部APIを呼び出す構成にしない。
  Widgetから価格・出来高を取り出してランキングの取得元にする構成にも変更しない。
- 元の収集停止時も、保存済みの正当なmapでランキングの取得を継続できるようにする。
  対象一覧の更新停止は表示し、現在の全取扱いを再確認できたとは扱わない。
- 同じhostの資源競合は残るため、接続数、queue、再試行、保存量、処理時間に上限を設ける。
  上限はCP0の対象数・提供元の制約・実測から決定し、証拠を残す。

### このゴールに含めないもの

- 平常比、順位変化・上位滞在、ミニチャート、当日の高安位置、市場全体の指標、通知。
  これらは推奨の後続機能とし、未実装でも本ゴールの未達とはしない。
- 7日など短期スイング向けのランキング、自動売買、注文、残高、ポジション、秘密API key。
- commit、push、PR、merge、本番deploy、既存unit操作、live DB操作、maintenance、
  backup、restore、旧state削除、課金、認証・権限・account変更、第三者へのmessage送信。
- 他projectの変更。特にJustPassのPostgres、port 5432、container、volume、database、roleには接触しない。

## 4. 銘柄mapと取得先の採用条件

### 対象と参照契約

- 対象は元の3取引所のactiveなcrypto linear perpetualから構成する。
  表示対象を採用した外部取引所の全銘柄へ広げない。
- 元の全対象instrumentをmapまたは明示的な要確認・未対応項目へ対応させる。
  名前が似ていることだけを根拠に統合しない。元のgroupIdやbase名は照合材料であり、
  倍率、別名、同名別資産の経済的同一性を保証するものとして扱わない。
- 同一資産と確認できた対象は1行へまとめ、元のinstrument IDと取扱い取引所を保持する。
- 参照契約について、提供元、symbol、perpetualかどうか、取引状態、原資産、数量倍率、
  quote・settle、価格・売買代金の単位を確認する。比較通貨は初期案としてUSDTを優先する。
  異なる通貨を根拠なく1:1で混ぜない。
- 参照契約は銘柄ごとに固定する。障害時の無言の取引所切替や、異なる契約の履歴の連結をしない。
  契約変更時はmap versionを更新し、比較に必要な新しい履歴がそろうまで対象から外す。
- TradingView symbolは別fieldで確認し、文字列に接尾辞を付けただけで対応済みとしない。
  価格API対応とWidget対応を別々に分類する。

### 対応範囲の扱い

「全対象」とは対象名簿に欠落がないこと、「全対応銘柄のランキング」とは採用した取得先で
正確に対応付けられ、選択条件に必要なデータがそろった全銘柄を比較することを指す。
外部に対応契約のない銘柄まで、数値やChartを生成できるという意味ではない。

CP0で、対象数、価格API対応数、Widget対応数、両方対応数、未対応数、未確認数と理由別内訳を記録する。
固定の対応率を実測なしに設定しない。対応可能な銘柄を負荷対策のために無言で対象から落としたり、
未確認を未対応へ付け替えたりして完了扱いにしない。

採用範囲はCP0で理由とともに固定し、後の取得失敗に合わせて合格条件を縮めない。
実測から利用目的を満たす参照範囲を確立できない場合は、採用を保留して代替候補と不足を提示する。
全銘柄へ数値・Chartを必ず付ける仕様への変更、外部取得先の大幅な追加、有料サービスの採用は
この定義だけで自動承認されたものとしない。

## 5. 計算・更新契約

### 時刻と価格

- 全行の比較終了時刻を同じUTCの分境界Tへそろえる。表示はJSTとし、Browserのtimezoneに依存させない。
- C(t)は時刻tで終了する確定1分足の約定終値とする。Mark、Index、板、参考中央値を代入しない。
- 比較幅wが15分または1時間の場合、騰落率は (C(T) / C(T-w) - 1) × 100 とする。
- JST基準時刻からの比較は、T以下で最も新しい設定HH:mmをAとし、
  (C(T) / C(A) - 1) × 100 とする。設定時刻より前は直前日に到来した基準を使う。
  T=Aの場合は開始直後と表示し、観測窓のない順位を作らない。
- T、A、期間、map versionを計算結果に結び付ける。日付・基準・契約が変わった旧要求を
  新しい計算へ再利用しない。
- 正の有限価格、時刻、OHLCの整合、重複・順序・契約一致、足の確定条件を検証する。
  表示の丸めを順位計算へ先に適用しない。同値の場合の安定した順序を定義する。

### 売買代金と順位

- 同期間 [T-w,T) または [A,T) の確定1分足のquote建て売買代金を合計する。
  24時間移動窓の出来高差分や、終値とbase数量の単純な積を同期間売買代金の代用にしない。
- 提供元が明示した実際の0と、未取得・欠測・単位不明を区別する。補間やゼロ埋めをしない。
- 初期版の順位対象は、その比較期間の価格境界と売買代金がそろい、mapが有効で、
  指定された売買代金下限を満たす銘柄とする。
- 上昇率は正の騰落率を大きい順、下落率は負の騰落率を小さい順、
  売買代金は大きい順とする。0%や該当銘柄なしの場合の表示も定義・検証する。
- 画面に見えている行だけを取得・比較しない。ページングや仮想表示があっても順位は全対象から計算する。
- 「参照取引所の当該契約の売買代金」と表示する。市場全体や元の3取引所の合計として扱わない。

### 毎分の発行と失敗時

- 取得は継続し、順位の発行を60秒gridで行う。正常時は連続する周期で新しい比較結果を発行する。
- 足の到着を待つ猶予と周期内のdeadlineは、提供元の確定通知・配信遅延をCP0で測って定める。
  一部銘柄の遅延で次周期まで処理を重ね続けない。
- 1つのsnapshotは、共通T、生成時刻、map version、指標定義version、対象数、
  対応数、有効数、除外理由を持つ。異なる世代の行を混ぜず、一括で切り替える。
- snapshotの計算入力を固定し、後着データの補完や訂正は次世代に反映する。
  同じsnapshotに対するHH:mm別の計算で、後から更新された履歴を混ぜない。
- 失敗時は前回値を新しい生成時刻で再発行しない。最後の結果を残す場合は古い状態と表示する。
- JST設定の変更は同じ確定snapshotの保存済みデータから計算する。
  HH:mm別の結果は上限付きでcacheし、利用者や設定変更の数だけ外部取得を増やさない。
- WebSocketを継続取得、RESTを初期履歴・切断後の補完に使う構成を第一案とする。
  採用方式は対象数、提供元仕様、負荷実測から決め、方式自体を成果と取り違えない。
- 履歴不足、source遅延、source障害、map不一致、通貨・単位不明、未対応を区別して記録・表示する。

## 6. 必須の完了条件と証拠

| ID | 完了時に真であること | 必須の確認面 |
| --- | --- | --- |
| G01 | 全対象名簿を照合し、原資産同一性・固定参照契約と対応状態を正確に確定している。 | version付きmap、全件照合、重複・漏れ・参照倍率・未対応理由、採用根拠。同一性・参照の未確認は未達。2026-09-16の要求改訂により元数量換算・Widgetの未確認は各機能の制限として独立報告する。 |
| G02 | ランキングに元データへの書込み経路がなく、既存の価格取得や鮮度判定にも依存しない。 | source/configの境界確認、重なる保存先の拒否、隔離stateでの書込み先検証、既存側利用不能時の継続試験。稼働設定の適用は実施した範囲を明記する。 |
| G03 | 15分・1時間・JST設定からの騰落率と同期間売買代金が契約どおりである。 | 手計算可能なfixture、実APIとの照合、時刻境界・欠測・0・重複・契約変更のtests。 |
| G04 | 全対応銘柄を同じTで比較し、正常時に毎分snapshotを発行できる。 | 全対象の連続観測log、周期・遅延・件数・除外理由、切断と復旧、Browser数と外部取得量の分離。 |
| G05 | 必須の並び替え・期間・下限・JST設定保存と、状態の読み分けができる。 | Web unit、実装済み画面、操作E2E、設定保存不可の場合の継続動作。 |
| G06 | Widget対応済み銘柄の選択が同じ参照契約へ反映され、選択状態を維持できる。 | mapの全件整合検証、契約種別・倍率・文字種などのケース別の実Widget表示証拠、未対応・遅延切替試験。 |
| G07 | 主なDesktop/Mobile操作が成立し、対象外銘柄へ無言で移動しない。 | 既存Playwright設定でのE2Eと実画像確認。Widgetの検索・比較・URL指定など対象外への導線も確認する。 |
| G08 | 既存の重要な収集・保存・選択・Chart利用に意図しない回帰がない。 | 最終diffと既存回帰検証。元データの意味や既存4 artifactの契約が変わっていないこと。 |
| G09 | 実データの取得と更新を確認し、fixtureだけで受入済みにしていない。 | 隔離した専用processでの有限の実Provider受入、通常周期・欠測・再接続・再開を示す証拠。 |
| G10 | 必要なdocs、起動・停止・復旧手順、未確認事項、検証結果が再開可能な形でそろっている。 | 現行docsとの照合、証拠一覧、必須checkの終了結果、本ゴール全項目の最終監査。 |

G06/G07では、銘柄名が表示されたことだけでデータの表示成功としない。
実際の足・価格の描画、契約一致、エラーの有無を確認する。
通常E2EのWidget fixture成功と、TradingViewの実表示成功を別の証拠として扱う。
Widgetの制御に制約があり要求を実現できない場合は、無関係な契約の表示や非公開API依存で取り繕わない。

## 7. 実装checkpoint

| checkpoint | 作業と予定する成果 | 次へ進める条件 |
| --- | --- | --- |
| CP0: 現状・取得先・対応範囲 | 未commit差分を保全し、現行source・実効state・公開API仕様を再測定する。全件名簿、候補の対応表、Widget map、取得予算、有限の観測計画を作る。 | 採用範囲と制約が記録され、未解決のidentityや実現性の問題を実装済み扱いしていない。 |
| CP1: 分離と契約 | 専用module、state、map・minute data・snapshotの契約、読み取りAPI、境界テストを作る。SQLiteと既存HTTP実装を第一案として必要な配置を確定する。 | 元データへの書込み経路がなく、元のartifact bundleの鮮度に依存しないことを検証できる。 |
| CP2: 収集・保存 | 初期履歴、継続取得、足の確定、保存、重複防止、再接続、上限を実装する。 | 契約・単位・時刻を検証し、欠測を区別して全採用対象を扱える。 |
| CP3: 計算・順位・配信 | 同じsnapshotから期間別指標、順位、下限、JST基準、状態を返す。 | G03/G04の計算と更新・競合条件が成立する。 |
| CP4: 画面・Widget | 必須5機能を接続し、Desktop/Mobile、保存、選択保持、未対応表示を完成させる。 | G05〜G07の操作・実表示が成立する。 |
| CP5: 統合・実データ受入・文書 | 隔離環境で全対象を観測し、復旧、回帰、負荷、証拠、現行docsをまとめる。 | G01〜G10の全項目を実際の証拠から監査できる。 |

実装開始時に関連AGENTSと作業差分を確認し、
Repository規則に従ってai/independent-daytrade-ranking-20260912-0736 branchを作成した。
未commit差分の破棄、無断stash、他の作業のstageやcommitはしない。

checkpointの順序は依存関係を守る範囲で調整できる。各checkpoint後に、
現在地、満たしたG番号、証拠、残作業、未確認・阻害要因を短く記録する。
具体的な証拠台帳は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/independent-daytrade-ranking/EVIDENCE.md
に作成済みであり、CP0〜CP5とG01〜G10の実績・未達を記録している。

失敗した場合は、原因をsource・実測から絞り、最小の修正または許可済み範囲の代替を選ぶ。
変更に近い確認からやり直し、無変更での同じ失敗の反復や、合格後の無目的な検証拡大をしない。

## 8. 検証の進め方

実装と検証に使うruntime stateは現役serviceから隔離する。
初回の試験stateは /home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/runtime-qualified、
追加差分後の受入は /home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6 を使用した。
実行ごとに専用の子directoryと空きloopback portを確保し、他projectや現役serviceを操作しない。

- 新規Python module: 対応するpytest、Ruff check/format、Pyreflyを既存toolchainに合わせて実装・実行する。
  新規moduleの検証は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/verify-local.sh へ必要な範囲で組み込む。
- Web: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/web をCWDとして、
  `bun run test`、`bun run check`、`bun run build`、関連する `bun run test:e2e`。
- 生成型は既存の生成手順に組み込み、生成物を手で修正しない。
- Repo横断の最終確認は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/verify-local.sh を使う。
  一時Postgres、型生成、build、E2Eの副作用を先に確認し、現役DBへ接続しない。
- docsは既存metadata/link checkerと `git diff --check` で検証する。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/DESIGN.md を変更した場合は既定lintも実行する。
- 実Provider・実Widgetの受入は通常の自動testsと分離し、公開symbolだけを送る。
  raw priceの限定した証拠と観測時刻を残し、secretやprivate codeを外部送信しない。

実データの観測計画はCP0で対象、終了条件、時間上限を先に記録する。
毎分の連続更新、欠測、切断後の復旧が判断できる有限の観測とし、結果を見て合格条件を下げない。
JST日跨ぎや基準切替の境界は制御したclockのtestsで必ず確認する。
試験で使った時刻を実市場をその時間だけ観測した証拠と取り違えない。

数値の対応率、性能閾値、観測時間、メモリ上限に未測定値を断定で書かない。
CP0で実測・提供元仕様に結び付けて確定する。Userの指定がないtoken budgetは追加しない。

## 9. 未達・停止・rollback

次の場合は完了としない。

- 対応範囲、契約・倍率・単位、Widget対応を推測で補っている。
- 画面に見える一部銘柄の成功だけで全対象の処理を完了と扱っている。
- 異なるT、未確定足、古い値、異なる参照契約を同じ順位へ混ぜている。
- tests、build、HTTP 200、銘柄ラベル表示だけで、実Provider・実Widget受入を代替している。
- 必須機能の代わりに推奨機能を作っている。
- 取得失敗を理由に採用済み対象を削ったり、許可されていないsourceへ切り替えたりしている。
- 未実行の必須検証がある、または元のデータ・サービスを守る境界を検証できていない。

提供元の地域制約、必要な契約・履歴の不在、許可範囲で解決できないWidget制約、
既存差分との責任境界の不明、課金や稼働操作を必要とする変更が出た場合は、
依存しない許可済み作業を先に終え、試した方法・証拠・阻害条件・必要な最小の入力を報告する。
要求、対応範囲、完了条件を独断で変更しない。
checkpointの未達・阻害の記録と、Codexのnative Goal状態の操作は区別し、
native Goalの状態変更はそのsessionの実効ルールに従う。

rollbackはランキングの表示切替と専用processの停止で切り離せる構成にする。
既存データのmigrationや巻戻しを必要としない。稼働unitを実際に操作する必要がある場合は別の実行範囲とする。
試験stateや証拠を広いglobで削除せず、既存の未commit差分を復元対象として上書きしない。

## 10. 完了報告の形式と文書の閉じ方

最終報告には以下を含める。

- G01〜G10ごとのPASS／PARTIAL／BLOCKED、対応する証拠の絶対パス、必要な説明。
- 対応名簿のversion・確認時刻、価格APIとWidgetの対応範囲、未対応理由、未確認の残り。
- 実装・unit/E2E・実Provider/Widget受入・稼働反映を分けた状態。
- 実行したcheck、失敗したcheck、未実行の必須check、重大な残存制約。
- branch、commit・push・本番反映の実施有無と、稼働へ反映する際に必要な操作。

必須項目をすべて満たす場合だけ、このローカル実装ゴールをPASSとする。
本番未反映は対象外として明示し、本番稼働が確認済みであるとは報告しない。
時間・token上限、機能の一部完成、見た目の完成を全体完了の根拠にしない。

完了時は現行仕様を /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/current/ へ、
採用済み判断を /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/decisions/ へ反映した後、
Repositoryのlifecycleに従ってactive planを閉じる。
未commitの計画を削除する場合も、必要な要求と検証根拠が引き継がれずに失われないようにする。
このために無断commitを追加しない。

## 11. 現時点の確認と未確認

- このworktreeのmap: 元1,203契約を692行へ保持。参照API・Widget対応531行（Bybit480、Binance51）、
  未対応28行、要確認12行、crypto以外の対象外121行。versionは4ce42c272921615dbf0b64e5。
- 実装済み: 独立collector、SQLite、固定参照契約、共通Tの毎分generation、専用API、ランキング、単一Widget。
  REST上限・異常応答・削除済み選択保持・銘柄とWidgetの照合gateを修正した。
- 受入: 2026-09-12 10:17〜10:34 JSTの隔離試験で全531契約の全3期間を通常3周期・復旧3周期で確認。
  実WS切断、75秒停止、読取り数と取得数の分離を実測。cold startや現在の本番受入とは扱わない。
- 実Widget: 従前の通常・数量・文字種・indexのケースに加え、PONS/CATのDesktop/Mobile4ケースを確認。
  全531契約を一つずつ描画した証拠ではない。
- 回帰: Ranking91 pytest、Web156 unit、全E2E32がPASS。分離後もRanking91件とmap整合を確認。
  全件照合gateは未確認12行により終了1。回帰成功と全件照合完了を区別する。
- 未達G01: CHEEMS/NEX/RATSのBitget数量倍率、Aster PROSの同一性、
  AI/B-MONEY/BEN/BONER/BREW/MAX/MEMESTOCK/PAIRの指数式と参照先aliasの照合。一次根拠を要する。
- 元checkoutのmap・文書には未統合。元checkoutへ戻す際は別Codexの終了と最新差分を確認する。
- commit、push、PR、deploy、既存unit・live DB操作は未実施。実データ受入の試験processは終了済み。

## 12. 登録したゴール

Userの開始指示により以下の目的でゴールを登録した。全条件を満たすまで完了扱いにしない。
CLIの機能を有効化したり、Codexの内部状態・設定を書き換えたりすることは本書の対象外である。

```text
/goal /home/tn/projects/prep-watchdeck/docs/plans/active/independent-daytrade-ranking/GOAL.md を完了条件の正本として、既存の重要な収集・保存データから独立した、外部公開perpsデータによる毎分更新のデイトレ向け統合ランキング初期版を実装・検証する。必須5機能とG01〜G10を満たし、CP0〜CP5で対応名簿、契約・時刻・売買代金の計算、単一TradingView Widget、分離、復旧、回帰、隔離した実Provider/Widget受入を証拠付きで確認する。開始時に現行source・AGENTS・Git差分を再確認し、既存差分を保全する。未対応・欠測・古い値を推測で補わず、採用範囲や完了条件を独断で縮めない。各checkpointで証拠と残作業を記録し、失敗原因に応じて最小の修正または許可済み代替を選ぶ。許可範囲で解決できない阻害があれば必要な入力と証拠を報告し、全条件を満たすまで完了としない。推奨の後続機能、commit、push、PR、本番deploy、既存unit・live DB操作は含めない。最後にゴール全体を監査し、source完了、実データ受入、稼働反映を区別して報告する。
```

Approval status: approved by user
Execution status: partial (isolated worktree ready; G01 has 12 unresolved rows; native Goal state is not changed by this document)
