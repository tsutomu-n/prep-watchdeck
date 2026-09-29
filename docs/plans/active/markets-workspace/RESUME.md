# 再開位置

- 作成: `2026-09-28T20:00:00+09:00`
- 更新: `2026-09-29T06:55:18+09:00`
- 状態: `実装計画`

---

開発受入は`PARTIAL`。AC全30件はpass 27、partial 2（AC20・AC21）、M6 not_run 1（AC22）。実データ受入は別欄でnot_run。
各ACの試験名・command・結果・対象版は`/home/tn/projects/.ai-worktrees/prep-watchdeck-markets-20260928/docs/plans/active/markets-workspace/acceptance.json`を正とする。

## 対象版と保全

- worktree: `/home/tn/projects/.ai-worktrees/prep-watchdeck-markets-20260928`
- branch: `ai/markets-workspace-20260928-2000`
- 台帳の計測起点HEAD: `380941c13407ecf11c5cbbab3c94eacebecb211e`。開始時点ですでに未commitのレビュー修正があった。台帳のsource/log hash一致を確認して保全し、続きだけを追加した。
- 台帳の計測対象source snapshot: `ec68a76c87488a7d962bc1959168d4876a033ae08a71ff71a1be36035a673942`。算出規則と変更source hashは台帳に記録。計測時点では追加commit/push/merge/PR/本番unit操作/deploy/現役data書込はしていない。
- その後、開発チェックポイント`57d0ff5`をPRなしで`main`へfast-forwardした。保護ルールは取り込み中のみ変更し、直後に元のPR・`verify`必須設定へ復元。初回`main` CIでは作業端末固有リンクと試験用ブリッジの型検査が失敗したため、本差分で修正する。台帳の計測結果を修正後CIの合格証拠へ読み替えない。
- 稼働releaseの前回読取記録はMarket `dc2a8d7`、Web・Ranking `d1c44d5`。今回の開発gateを本番反映の証拠にしない。

## 380941cからの修正

参照→native→一覧で、平常比期間/下限・当日位置上下限・表示列を保存し、応答後の選択focusと縦横scrollも復元する。破損metricsは専用lock下で原本byteを保全・fsync/readbackして正常DB snapshotから再生成する。未知schema、権限、保全失敗、並行writerは上書きしない。開始時に存在したこの2修正も最終gateで再確認した。

今回追加: 投影全体を10秒で止められる子process、参照メモの出所/時刻/5指標context、Browser時計によるL1品質失効、Funding周期・次回時刻の不明/経過表示、Widget取得失敗表示。5秒更新がheartbeatの5分タイマーを作り直す不具合をprimitive version依存へ修正した。future selection token拒否も未commit差分に含む。

## 検証結果

`env -u TEST_DATABASE_URL bash scripts/verify-local.sh` は最終差分で終了0。Market Core 103、Ranking Core 124、Web unit 160、Desktop/Mobile E2E 72件。schema/型・Ruff・Pyrefly・Svelte check・build・repo contract・文書検査も通過。log: `/tmp/markets-m5-accepted-gate.log`。

不足ケースだけを追加: A保存応答がB表示中に到着、初期URL無POST/hidden heartbeat、POST応答abort後のserver保存、HTTP500/XSS/非有限context、過去chartページとmetricsの旧応答をversion変更の前後で解放、Funding欠損/経過、L1/OIの120秒境界、Providerへの実HTTP要求を監視したRanking反復20 GET。

隔離DBではversion切替/OI不明単位、実statement timeout、read-only repeatable-read、接続1、足保存失敗の通知抑止、timeout子processの終了・回収・lock解放を確認。worker→artifact→API→Browserで後着・同cutoff訂正・旧応答・停止/復帰・破損復旧、DB timeoutとWidget失敗中の他lane操作継続を両viewportで確認。書込応答完了から表示まで 4.516〜5.022 秒。COMMIT要求前/応答後をclient時刻で囲んだ測定であり、正確なDB commit時刻や一般的な遅延保証ではない。

同時障害試験の最初の失敗はselected fixtureの15秒失効。通常4 artifactの独立更新をfixtureへ加え、最終gateで解消。初回再現・途中失敗も台帳に残した。

旧Webへのrollback試験は前回の隔離v1復元/v2別保全/hash不変の証拠を再利用。現役stateの切戻しは未実施。

## 残る阻害要因と再開条件

- AC20: OSの実日本語IME・実機focusが未確認。この環境にはDISPLAY/WAYLAND_DISPLAY、ibus/fcitx5がない。GUI/IMEがある隔離端末で未保存メモ・銘柄切替・保存応答中のcompositionとfocusを確認する。Browser模擬IME/keyboard/focusは通過。
- AC21: AC20未達のためPARTIAL。実装不足や、この環境で実行できる隔離試験の調査待ちは残していない。
- PF01: 現役名簿/mapの同時copyと接続率は未確認。
- PF02: 専用read-only資格未特定。現役DB/実Providerの到着遅延分布は未確認。180秒lag/300秒上限は設計初期値。
- PF03/M6/AC22: 本番UI・現役負荷・本人の日常利用受入は未実施。

同じworktree・branchで開発受入を継続する。`main`へのsource取り込みは本番反映ではない。実IME・実機focusと実データ受入は未確認のまま維持する。
