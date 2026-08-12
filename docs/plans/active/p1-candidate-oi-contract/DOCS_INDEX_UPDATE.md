# docs index更新手順

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

> **適用禁止:** 以下は完了当時のindex更新案であり、現在の`docs/README.md`へ再適用しない。
> Candidate・74hは[Decision 0010](../../../decisions/0010-retire-74h-candidate-deep-backfill.md)により
> supersede済みで、OI 60分だけを現行機能として扱う。

`docs/README.md`の「実装・検証計画」節を、次の内容へ更新する。

```markdown
## 実装・検証計画

- P1 Candidate / OI契約修正: `plans/active/p1-candidate-oi-contract/README.md` — 74h Candidate条件、OI 60分変化、最小UI・テスト・初期runtime qualificationの進行中living plan。

監視専用化の完了計画と過去検証証拠はRepo外Archiveへ退避し、現行仕様は`docs/current/`、有効な判断はADR 0007を正本とする。
```

既存文言が異なる場合は機械的置換せず、現行indexの構造を保ったまま同リンクを追加する。実装完了後は、このactive planをRepo規約に従ってArchive/正本へ反映し、indexを再更新する。
