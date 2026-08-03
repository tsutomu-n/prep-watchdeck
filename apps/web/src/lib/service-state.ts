export type ServiceStateSnapshot = {
  schemaVersion?: number;
  generatedAtMs?: number;
  dataAsOfMs?: number | null;
  productType?: string;
  streamSymbols?: number;
  streamChannels?: number;
  streamShards?: number;
  diagnostics?: {
    tickerCount?: number;
    candle1mCount?: number;
    latestCandle1mTsMs?: number | null;
  };
  backfill?: ServiceProgress | null;
  reconcile?: ServiceProgress | null;
  deepBackfill?: ServiceProgress | null;
};

export type ServiceProgress = {
  status?: string;
  completedSymbols?: number;
  pendingSymbols?: number;
  targetSymbols?: number;
  requestedSymbols?: number;
  errorCount?: number;
  latestError?: string | null;
};

export type ServiceStateView = {
  status: "ok" | "stale" | "backfilling" | "error" | "unreadable";
  label: string;
  dataLagSeconds: number | null;
  stateLagSeconds: number | null;
  streamShards: number;
  streamSymbols: number;
  backfillText: string;
};

const staleThresholdSeconds = 120;

export function summarizeServiceState(state: ServiceStateSnapshot, nowMs = Date.now()): ServiceStateView {
  const stateLagSeconds = secondsSince(state.generatedAtMs, nowMs);
  const dataLagSeconds = secondsSince(state.dataAsOfMs ?? state.diagnostics?.latestCandle1mTsMs ?? null, nowMs);
  const progress = state.deepBackfill ?? state.backfill ?? state.reconcile ?? null;
  const hasError = hasCurrentError(progress);
  const isStale =
    (stateLagSeconds !== null && stateLagSeconds > staleThresholdSeconds) ||
    (dataLagSeconds !== null && dataLagSeconds > staleThresholdSeconds);
  const isBackfilling = progress?.status === "running";
  const status = hasError ? "error" : isStale ? "stale" : isBackfilling ? "backfilling" : "ok";

  return {
    status,
    label: serviceStateLabel(status),
    dataLagSeconds,
    stateLagSeconds,
    streamShards: Number(state.streamShards ?? 0),
    streamSymbols: Number(state.streamSymbols ?? 0),
    backfillText: progressText(progress)
  };
}

export function unreadableServiceStateView(): ServiceStateView {
  return {
    status: "unreadable",
    label: serviceStateLabel("unreadable"),
    dataLagSeconds: null,
    stateLagSeconds: null,
    streamShards: 0,
    streamSymbols: 0,
    backfillText: "-"
  };
}

export function serviceStateLabel(status: ServiceStateView["status"] | "missing") {
  const labels = {
    ok: "Service OK",
    stale: "Service 遅延",
    backfilling: "Service 補完中",
    error: "Service エラー",
    unreadable: "Service 状態エラー",
    missing: "Service 状態なし"
  };
  return labels[status];
}

export function formatLag(seconds: number | null) {
  if (seconds === null) return "-";
  if (seconds < 60) return `${seconds}秒前`;
  return `${Math.floor(seconds / 60)}分前`;
}

function secondsSince(valueMs: number | null | undefined, nowMs: number) {
  if (typeof valueMs !== "number" || !Number.isFinite(valueMs) || valueMs <= 0) return null;
  return Math.max(0, Math.floor((nowMs - valueMs) / 1000));
}

function hasCurrentError(progress: ServiceProgress | null) {
  if (!progress) return false;
  if (progress.status === "completed" && Number(progress.pendingSymbols ?? 0) === 0) {
    return false;
  }
  return Boolean(progress.latestError) || Number(progress.errorCount ?? 0) > 0;
}

function progressText(progress: ServiceProgress | null) {
  if (!progress) return "補完なし";
  const completed = Number(progress.completedSymbols ?? 0);
  const total = Number(progress.targetSymbols ?? progress.requestedSymbols ?? completed);
  if (total <= 0) return progress.status ?? "unknown";
  return `${completed}/${total}`;
}
