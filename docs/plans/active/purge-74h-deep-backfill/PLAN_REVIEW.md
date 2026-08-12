# 74時間判定・deep backfillパージ計画レビュー

- 作成: `2026-08-12T17:22:12+09:00`
- 更新: `2026-08-12T17:31:25+09:00`
- 状態: `実装計画`

---

## 結論

74時間判定と常駐deep backfillを先にパージする判断は維持する。ただし、この変更だけでscanner高CPUと
snapshot遅延が解消するという前提は棄却する。detail chartは5,885本の1分足をsourceにし、全snapshot
rowのJSONを毎cycle flush/fsyncするため、今回残す最大の負荷候補である。

今回の実装は次に限定する。

1. 常駐deep backfillをproductionから切断する。
2. Candidate consumer/UIを先に切断する。
3. 74時間producer/schema/configを削除する。
4. scanner判定・gap auditの1,915本windowと、chart sourceの5,885本windowを分離する。
5. 変更前後のCPU、RSS、snapshot間隔、row/chart件数を計測する。

detail chartと旧3市場`marketComparison`は、今回の変更へ混ぜず、次の優先削除候補として別EXECPLANで
判断する。

## 確認した事実

| ID | Fact | Evidence |
|---|---|---|
| R-F01 | Candidate rankingは非`NO_TRADE`かつ`user_rule_74h_matched is True`のrowだけを対象にする | `domain/screening/rankings.py` |
| R-F02 | 4時間量倍率に必要な5分足は`288 + 2 * 48 - 1 = 383`本である | `features/volume_ratio.py` |
| R-F03 | 現行snapshotは5,885本1分足相当を読み、DuckDBで5分足へ集計する | `service_snapshot.py`、DuckDB store |
| R-F04 | detail chartは全snapshot rowのJSONを一時fileへ書き、各fileをflush/fsyncして置換する | `chart_artifacts.py` |
| R-F05 | 383本入力では1h/4h/24h chartが概ね32〜33本/8〜9本/2〜3本へ減る | `TIMEFRAME_BARS`とchart aggregation |
| R-F06 | 現行1,177本入力では同chartが概ね99〜100本/25〜26本/5〜6本になる | 同上 |
| R-F07 | snapshotの既定周期は60秒だが、build durationを記録する計測点は現行codeにない | `settings.py`、snapshot publisher |
| R-F08 | 旧`marketComparison`はBitget・Bybit・HyperliquidのBTC/ETH/SOL固定pilotで、`perpVenueComparison`とは別collector・別panelである | market comparison source/Web |
| R-F09 | snapshot rootは追加propertyを拒否するが、row、summary、rankingsは追加propertyを許可する | DTO/generated schema |
| R-F10 | Windows viewの5 script差分は`100755 → 100644`だけで、内容差分は0行。`core.fileMode=false`では表示されない | Git raw/summary/numstat/status |

## 修正した問題

### 1. 383本とchart維持の矛盾

旧計画はsnapshotの共通windowを1,915本1分足へ縮小しながら、detail chartを維持するとしていた。
これはchartの1h/4h/24h履歴を大幅に減らすため両立しない。

修正後は次の二つへ分ける。

```text
scanner/gap audit: 383本5m / 1,915本1m / 31時間55分
chart source:       1,177本5m / 5,885本1m / 98時間5分
```

この分離により短期判定の不要なgap audit負荷は減らせるが、chart用集計とJSON I/Oは残る。

### 2. producerをconsumerより先に削除する順序

旧計画はbackend DTO/schema/generated typeを先に削除し、Svelte consumerを後で削除する順だった。
CP-02直後に型とconsumerが食い違い、checkpoint単独でWebをgreenにできない。

修正後はCandidate UI/API/ranking consumerを先に外し、その後にbackend producer/schemaを削除する。

### 3. Gitのmode-only差分を実装blockerとして扱っていた

5 scriptは内容変更ではなくWindows mount上の実行bit差だった。所有者確認を待つ合理性はない。
canonical Linuxで内容差分がないことを再確認し、mode changeをstageしない。内容差分がある場合だけ停止する。

### 4. UI仕様書とADRの更新漏れ

Candidateは`DESIGN.md`、ADR 0007/0008、`docs/current/`の情報構造に組み込まれている。
codeとcurrent docsだけを直すと設計正本が矛盾する。

新ADR 0010でretirementを記録し、ADR 0007/0008の該当部分をsupersedeする。OI 60分契約は維持する。
`DESIGN.md`もCandidateのない情報構造へ同期する。

### 5. schema migrationリスクの再確認

row、summary、rankingsは`additionalProperties: true`である。74時間propertyの明示定義を削除しても、
保存済み旧snapshotの追加fieldはschema上許容される。schemaVersion 1を維持できる。

新producerが74時間fieldを出力しないことと、旧snapshotをreaderが拒否しないことを別々にtestする。

## 現実的な選択肢

| Option | 利点 | 欠点 | 判断 |
|---|---|---|---|
| 現状維持 | 変更リスクがない | 74時間契約、常駐deep backfill、全量処理を維持する | 不採用 |
| 74時間/deep backfillだけ削除し、共通windowを383本にする | 最小実装で読込量が減る | chart履歴が暗黙に減る | 不採用 |
| scanner/gapとchart windowを分離する | 既存chartを壊さず74時間負債を外せる | chartの大きな負荷候補は残る | 今回採用 |
| chartも同時削除する | I/O、依存、98時間sourceを大きく減らせる | user-visible機能、API、ADR、packageへ波及する | 次の別EXECPLANとして推奨 |
| Perp比較専用へ全面転換する | candle stackを削除でき、最も単純 | Watchlist、短期指標、VPI、OI文脈、chartを失う | 製品判断を伴う別計画 |

## 自動反映した改善

- CP-02とCP-03をconsumer-firstへ並べ替えた。
- analysis/gap windowとchart source windowを分離した。
- chart depthを固定するfocused testを追加した。
- featureVersion 5、rulesetVersion 4を明記した。
- 旧snapshot互換性testを追加した。
- `DESIGN.md`と新ADR 0010を文書同期対象へ追加した。
- source変更前後の最低限計測をCP-00/CP-06へ追加した。
- Windows mode-only差分を停止条件から外した。
- detail chartと旧`marketComparison`を次段の削除候補として明記した。

## 今回反映しなかった案

### detail chartの即時削除

製品対象との整合では有力だが、Symbol画面、chart API、artifact publisher、`lightweight-charts`、ADR 0004、
responsive/E2Eへ波及する。74時間パージのGoalを越えるため自動追加しない。

### 旧`marketComparison`の即時削除

Bybitは現行対象外で`perpVenueComparison`と重複するが、CPU寄与は未計測である。削除自体は有力だが、
今回のACへ混ぜず、chartと同じ次段で判断する。

### rolling stateまたはincremental snapshotへの全面変更

74時間パージ後もCPU問題が残る場合の選択肢である。原因計測前に導入すると、複雑性だけを増やす可能性が
あるため今回実装しない。

## 残るリスクと停止条件

- chart用5,885本1分足集計と全row JSON生成が残り、CPU改善が小さい可能性がある。
- fresh stateではscannerが最大31時間55分、現行chart深度が最大98時間5分warm-upする。
- Candidate削除後の探索性が不足する可能性がある。ただし別ランキングを暗黙にCandidateへ置換しない。
- build durationは現行codeで直接測れない。snapshot間隔をdurationとして報告しない。
- canonical Linuxで内容差分が見つかった場合だけ編集を停止する。
- DB migration、別writer、履歴削除、Perp comparison退行が必要になった場合は停止する。

## 次の行動

[`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)に従い、メインスレッドでCP-00を実行する。最初のsource変更は
CP-01の常駐deep backfill切断である。chart削除と旧`marketComparison`削除は、本計画のruntime計測後に
別EXECPLANとして判断する。
