# prep-watchdeck 現行概要

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-15T11:04:37+09:00`
- 検証: `2026-08-15T11:04:37+09:00`
- 状態: `現行`

---

## 製品の役割

`prep-watchdeck`は、運用資金5,000 USD以下の裁量Perp traderが、複数Venueの市場状態、
鮮度、由来、流動性の概算を同じ画面で確認するためのlocal-first監視アプリである。

対象はBitget、Hyperliquid Core、Asterのactive crypto linear perpetual。base完全一致、
base数量、multiplier 1、単一候補を確認できるinstrumentだけを自動group化する。
同じgroupにできない銘柄もVenue単独instrumentとして表示し、推測でalias変換しない。

## 現行機能

- 3 Venueのcatalogを15分周期、L1を60秒fixed-rateで取得する。
- mark、reference price種別、BBO、funding raw/周期/1時間換算、OI raw/単位、24時間出来高を
  Venue別に表示する。取得不能、stale、単位不明はnullと理由を公開する。
- 検索、Venue、coverage、quality filterでinstrumentを絞る。既定sortはbase、次にVenue。
- 厳格な鮮度と同一cycle条件を満たす2 Venue以上のmarkだけ、USD/USDC/USDT parity仮定を
  明示した参考中央値として表示する。値を変換・合算・rankingしない。
- 選択groupだけ最大20段の板と直近100 tradesを購読し、$100/$500/$1,000の板上概算を表示する。
- 安全にgroup化できた選択instrumentの5m、15m、1h、4h、24h Chartを表示する。
- Past Noteを`venueInstrumentId`単位でローカル保存する。
- Postgresの期限後履歴を、照合済みParquetへ保存してからbounded retentionする。

## 責任範囲外

- 売買推奨、将来価格予測、裁定機会の断定、価格差ranking
- 自動売買、注文、残高、position、Private API、秘密API key
- RWA、HIP-3、synthetic、RFQ、alias、multiplier contract
- 全市場の板・全trade永続化、HFT、深いhistorical backfill

板上概算は現在受信したbookを指定notionalまでwalkした参考値であり、fee、将来impact、
実際の注文可否を含まない。

## 構成

- `apps/market-core`: Python 3.13、CLI `watchdeck-market`
- `apps/web`: SvelteKit 2 / Svelte 5、localhost UIとlocal file API
- `deploy/market-postgres`: 専用Postgres 17 Compose
- `schemas`: Webが読む4つのJSON schema
- `config/systemd`: DB、collector、maintenance、Webのuser unit template

現在値は`watchdeck-market status`、`artifacts/service-state.json`、service log、実画面で確認する。
