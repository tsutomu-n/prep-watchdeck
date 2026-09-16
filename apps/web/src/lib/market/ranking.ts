import type { RankedRow, RankingResponse } from "$lib/generated/ranking-response";
import { isReferenceTime } from "$lib/market/price-change";

export type RankingPeriod = RankingResponse["period"];
export type RankingOrder = RankingResponse["order"];
export type ChartInterval = "1" | "5" | "15" | "60" | "240" | "D";
export const CHART_INTERVALS: ReadonlyArray<{ value: ChartInterval; label: string }> = [
  { value: "1", label: "1分" }, { value: "5", label: "5分" },
  { value: "15", label: "15分" }, { value: "60", label: "1時間" },
  { value: "240", label: "4時間" }, { value: "D", label: "日足" }
];
export const CHART_INTERVAL_KEY = "prep-watchdeck:ranking-chart-interval";
export const RANKING_MAX_AGE_MS = 150_000;

export function rankingQuery(period: RankingPeriod, reference: string, order: RankingOrder, minimum: number) {
  if (!["15m", "1h", "daily"].includes(period) || !isReferenceTime(reference)
      || !["gainers", "losers", "turnover"].includes(order)
      || !Number.isFinite(minimum) || minimum < 0 || minimum > 1e18) {
    throw new RangeError("ランキング条件が不正です");
  }
  return new URLSearchParams({ period, dailyReferenceJst: reference, order, minTurnover: String(minimum) });
}

export function matchesRankingQuery(value: RankingResponse, query: URLSearchParams) {
  return value.period === query.get("period") && value.dailyReferenceJst === query.get("dailyReferenceJst")
    && value.order === query.get("order") && value.minTurnover === Number(query.get("minTurnover"));
}

export function rankingStateLabel(state: RankedRow["state"]): string {
  return {
    ready: "比較可能", starting: "基準時刻の開始直後", history_missing: "期間内の履歴不足",
    source_delayed: "最新の確定足が未着", source_unavailable: "参照データの取得停止",
    mapping_review: "銘柄の対応を要確認", unsupported: "参照先に対応契約なし",
    out_of_scope: "暗号資産の対象外", filtered: "売買代金の下限未満",
    direction_excluded: "この方向の順位対象外", invalid_data: "データの整合性エラー",
    reference_invalid: "参照契約の変更・取扱い終了"
  }[state];
}

export function referenceLabel(row: RankedRow) {
  return row.reference ? `${row.reference.provider === "bybit" ? "Bybit" : "Binance"} · ${row.reference.symbol}` : "参照契約なし";
}

export function rankChangeLabel(row: RankedRow, expired = false): string {
  if (row.rank === null) return `順位外（${rankingRowStateLabel(row)}）`;
  if (expired) return "比較不可（古い結果）";
  const change = row.rankChange;
  if (change.status === "compared" && change.delta !== null) {
    return change.delta > 0 ? `+${change.delta}` : change.delta < 0 ? `−${-change.delta}` : "0";
  }
  if (change.status === "new") return "新規";
  const reasons: Record<string, string> = {
    no_previous_generation: "初回・再起動後", generation_gap: "前の分の世代なし",
    map_changed: "対応表の変更", metric_changed: "指標定義の変更",
    anchor_changed: "JST基準日の切替", current_stale: "古い結果", previous_stale: "前回が古い",
    previous_row_missing: "前回の行なし"
  };
  return `比較不可（${reasons[change.reason ?? ""] ?? "比較元なし"}）`;
}

export function indicatorLabel(indicator: RankedRow["turnoverRatio"], unit: "倍" | "%"): string {
  if (indicator.status === "ready" && indicator.value !== null) {
    return `${indicator.value === 0 ? "0" : indicator.value.toLocaleString("ja-JP", {
      minimumFractionDigits: 1, maximumFractionDigits: 1
    })}${unit}`;
  }
  return {
    ready: "値なし", history_missing: "履歴不足", no_baseline: "比較基準なし",
    unsupported_period: "15分・1時間のみ", starting: "開始直後", no_range: "値幅なし",
    invalid_data: "入力不整合", reference_unavailable: "参照契約を利用不可"
  }[indicator.status];
}

export function rankingRowStateLabel(row: RankedRow): string {
  if (row.state === "unsupported") {
    switch (row.reason) {
      case "no_adopted_reference_after_identity_audit": return "Bybit・Binanceに同一資産の対応契約なし";
      case "adopted_reference_contract_not_trading": return "参照契約は取扱い終了・清算中";
      case "same_symbol_is_non_crypto_reference": return "同名の参照契約は株式の別資産";
      default: return rankingStateLabel(row.state);
    }
  }
  if (row.state !== "mapping_review") return rankingStateLabel(row.state);
  switch (row.reason) {
    case "quantity_multiplier_unverified": return "数量単位を要確認";
    case "original_identity_conflict": return "同名資産の照合が必要";
    case "original_catalog_missing": return "元の取扱い情報を要確認";
    case "no_exact_reference_alias_review": return "参照先・別名を要確認";
    default: return "同一資産である根拠を要確認";
  }
}

export function rankingTimestamp(value: number): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    hourCycle: "h23"
  }).format(value);
}

export function turnoverLabel(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 2
  }).format(value);
}

export function readChartInterval(storage: Pick<Storage, "getItem">): ChartInterval {
  try {
    const value = storage.getItem(CHART_INTERVAL_KEY);
    return CHART_INTERVALS.find((entry) => entry.value === value)?.value ?? "15";
  } catch { return "15"; }
}

export function approvedWidgetSymbol(row: RankedRow | null): string | null {
  if (!row?.reference || row.mappingStatus !== "verified" || row.widget.status !== "supported"
      || row.state === "reference_invalid") return null;
  const key = `${row.reference.provider}:${row.reference.symbol}:${row.reference.revision}`;
  const symbol = row.widget.symbol;
  return row.widget.referenceKey === key && row.widget.evidence.length > 0 && symbol
    && symbol.startsWith(`${row.reference.provider.toUpperCase()}:`)
    && /^[A-Z]+:[\p{L}\p{N}_]+\.P$/u.test(symbol) ? symbol : null;
}

/** Separate browsing context prevents the public embed loader's URL-symbol override. */
export function widgetDocument(symbol: string, interval: ChartInterval, theme: "dark" | "light"): string {
  if (!/^(BYBIT|BINANCE):[\p{L}\p{N}_]+\.P$/u.test(symbol)
      || !CHART_INTERVALS.some((entry) => entry.value === interval)) throw new RangeError("Invalid Widget contract");
  const configuration = JSON.stringify({
    autosize: true, symbol, interval, timezone: "Asia/Tokyo", theme, style: "1", locale: "ja",
    hide_top_toolbar: true, hide_side_toolbar: false, allow_symbol_change: false,
    withdateranges: true, save_image: false, calendar: false, support_host: "https://www.tradingview.com"
  }).replaceAll("<", "\\u003c");
  const colors = theme === "dark" ? "background:#0f0f0f;color:#b7bdc6" : "background:#fff;color:#373f49";
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>TradingView 参照チャート</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;${colors}}.tradingview-widget-container{height:100%;width:100%}.tradingview-widget-container__widget{height:calc(100% - 32px);width:100%}.tradingview-widget-copyright{height:32px;display:flex;align-items:center;justify-content:center;font:12px sans-serif}a{color:inherit}</style></head><body><div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><div class="tradingview-widget-copyright"><a href="https://www.tradingview.com/" target="_blank" rel="noopener nofollow">TradingView提供のチャート</a></div><script src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>${configuration}</script></div></body></html>`;
}
