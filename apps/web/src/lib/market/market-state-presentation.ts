export type ArtifactStatus = "ready" | "partial" | "stale" | "unavailable";

const STATUS_LABELS: Record<ArtifactStatus, string> = {
  ready: "正常",
  partial: "一部取得",
  stale: "期限切れ",
  unavailable: "取得不能"
};

const REASON_LABELS: Record<string, string> = {
  artifact_write_failure: "表示用データの一部を書き込めませんでした",
  catalog_partial: "Catalog取得が一部成功です",
  catalog_stale: "Catalogが許容時間を超えて更新されていません",
  catalog_unavailable: "Catalogを取得できていません",
  collector_run_missing: "collectorの実行記録がありません",
  collector_time_in_future: "collectorの時刻が現在より未来です",
  contains_non_ready_instruments: "正常でないinstrumentを含みます",
  depth_observed_in_future: "板の観測時刻が現在より未来です",
  depth_older_than_10_seconds: "板が10秒以上更新されていません",
  depth_unavailable: "有効な板を取得できていません",
  fewer_than_two_venues_same_cycle: "同じ取得周期で2 Venue以上のmarkがそろっていません",
  incomplete_source_window: "集約元の1分足が不足しています",
  insufficient_depth: "指定額を計算できるだけの板がありません",
  insufficient_venues: "参考中央値に必要なVenue数がありません",
  instrument_version_boundary_omitted: "契約仕様の版境界を跨ぐbarを除外しました",
  l1_missing: "L1データを取得できていません",
  l1_observed_in_future: "L1観測時刻が現在より未来です",
  l1_older_than_120_seconds: "L1データが120秒以上更新されていません",
  l1_partial: "L1取得が一部成功です",
  l1_stale: "L1が許容時間を超えて更新されていません",
  l1_unavailable: "L1を取得できていません",
  mixed_finality: "確定方法が異なる1分足を集約しています",
  no_active_selection: "現在有効な選択groupがありません",
  no_candles: "選択instrumentのローソク足がありません",
  no_current_instruments: "現在有効なinstrumentがありません",
  no_selected_instrument: "Chart対象のinstrumentが選択されていません",
  non_finite_chart_bar_omitted: "有限値でないbarを除外しました",
  non_finite_numeric_value: "有限値でない数値を公開対象から除外しました",
  observation_skew_exceeds_30_seconds: "Venue間の観測時刻差が30秒を超えています",
  selected_group_has_no_current_instruments: "選択groupに現在有効なinstrumentがありません",
  selection_expired: "選択監視の期限が切れています",
  selection_not_found: "選択監視を確認できません",
  source_status_partial: "取得元が一部取得状態です",
  source_status_stale: "取得元データの期限が切れています",
  source_status_unavailable: "取得元データを利用できません",
  unavailable_depth: "有効な板がありません",
  unknown_quantity_unit: "数量単位を安全に確認できません",
  unmapped_instrument: "他Venueと安全に同一groupへ対応できません",
  unsupported_execution_model: "板上概算に対応しない市場方式です",
  unsupported_quote_asset: "板上概算に対応しないquote assetです"
};

export function statusLabel(status: ArtifactStatus | string) {
  return STATUS_LABELS[status as ArtifactStatus] ?? status;
}

export function reasonLabel(code: string) {
  const known = REASON_LABELS[code];
  if (known) return known;
  if (code.startsWith("source_error_")) {
    return `取得元エラーが発生しました（${code.slice("source_error_".length)}）`;
  }
  if (code.startsWith("buy_")) {
    return `買い側を算出できません（${code.slice(4)}）`;
  }
  if (code.startsWith("sell_")) {
    return `売り側を算出できません（${code.slice(5)}）`;
  }
  return `未定義の品質理由（${code}）`;
}

export function technicalReasonCodes(
  reasons: readonly (string | null | undefined)[],
  extraCode?: string | null
) {
  return [...new Set([...reasons, extraCode].filter((value): value is string => Boolean(value)))];
}

export function reasonLabels(
  reasons: readonly (string | null | undefined)[],
  extraCode?: string | null
) {
  return technicalReasonCodes(reasons, extraCode).map(reasonLabel);
}

export function reasonSummary(
  reasons: readonly (string | null | undefined)[],
  extraCode?: string | null,
  limit = 3
) {
  const labels = reasonLabels(reasons, extraCode);
  if (labels.length === 0) return "なし";
  const visible = labels.slice(0, limit);
  return labels.length > limit ? `${visible.join(" / ")} ほか${labels.length - limit}件` : visible.join(" / ");
}

export function formatAgeSeconds(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "取得時刻なし";
  return `${new Intl.NumberFormat("ja-JP", { maximumFractionDigits: value < 10 ? 1 : 0 }).format(value)}秒`;
}
