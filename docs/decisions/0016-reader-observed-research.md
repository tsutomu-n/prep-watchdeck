# Decision 0016: Reader-observed research and fixed comparison

timestamp="2026-10-09(金)_15:03 JST"
- 作成: `2026-10-09T15:03:11+09:00`
- 更新: `2026-10-09T15:03:11+09:00`
- 状態: `設計判断`

研究はMarket package内の独立CLIと隔離stateで扱う。既存DBを一つのread-only REPEATABLE READで
観測し、exact payload bytesのpublish/readback後に保守的availabilityを別receiptへ保存する。
Attentionのimmutable edition・freeze設計を参照するが、AttentionのDB・常駐収集・manual selectionへ
研究責務を重ねない。全producer訂正や取引所初回availabilityの保証は行わない。

固定A/Bは共通cohort、時系列split/purge、有限cashと明示費用の小さなlong-only proxy evaluatorを使う。
ルールとevaluatorをdecision開始前に固定し、入力snapshotを評価前にbindする。
fee/fundingとM2Mの算術を契約に合わせて実装し、別研究repository全体をruntime依存へ追加しない。
失敗・no-trade・不足sampleを保存し、収益性/B優位を実装の合格条件としない。

Hyperliquid候補のreceiptとfinality decisionをnullable `finalized_at`で分離する。
旧行の不明時刻を遡及補完しない。Aster intervalは公式configの観測・版として扱い、過去scheduleへ外挿しない。

既存Polarsを品質診断へ再利用し、CCXT照合とhftbacktest入力準備は任意adapterとする。
未確認OI・疎な板を補完して実行可能に見せない。Provider取得契約、完全feed、production map採用、
長期データ・runtime/統計受入は別工程。操作・保存・復旧の現行契約は[/home/tn/projects/prep-watchdeck/docs/current/research.md](../current/research.md)に記す。
