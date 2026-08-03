import type {
  PrepWatchdeckScannerSnapshot,
  ScannerRowDTO,
  SparklineDTO
} from "$lib/generated/scanner-snapshot";

const dashboardSparklineBarLimit = 16;

type SparklinePayload = {
  points?: unknown[];
  bars?: unknown[];
  timeframes?: Record<string, unknown[]>;
  [key: string]: unknown;
};

type Sparkline = SparklineDTO | null;

export function slimSnapshotForDashboard(
  snapshot: PrepWatchdeckScannerSnapshot
): PrepWatchdeckScannerSnapshot {
  let slimmedRows: ScannerRowDTO[] | undefined;
  snapshot.rows.forEach((row, index) => {
    const slimmedRow = slimRowForDashboard(row);
    if (slimmedRows) {
      slimmedRows.push(slimmedRow);
    } else if (slimmedRow !== row) {
      slimmedRows = [...snapshot.rows.slice(0, index), slimmedRow];
    }
  });
  return slimmedRows ? { ...snapshot, rows: slimmedRows } : snapshot;
}

function slimRowForDashboard(row: ScannerRowDTO): ScannerRowDTO {
  const sparkline = slimSparklineForDashboard(row.sparkline);
  return sparkline === row.sparkline ? row : { ...row, sparkline };
}

function slimSparklineForDashboard(sparkline: Sparkline | undefined): Sparkline | undefined {
  if (!sparkline || typeof sparkline !== "object") return sparkline;
  const payload = sparkline as SparklinePayload;
  const points = Array.isArray(payload.points) ? payload.points : undefined;
  const bars = Array.isArray(payload.bars) ? payload.bars : undefined;
  const oversizedPoints = points !== undefined && points.length > dashboardSparklineBarLimit;
  const oversizedBars = bars !== undefined && bars.length > dashboardSparklineBarLimit;
  const oversizedTimeframes = Object.entries(payload.timeframes ?? {}).filter(
    ([, bars]) => Array.isArray(bars) && bars.length > dashboardSparklineBarLimit
  );
  if (!oversizedPoints && !oversizedBars && oversizedTimeframes.length === 0) return sparkline;

  const slimmed: SparklinePayload = { ...payload };
  if (oversizedPoints && points) {
    slimmed.points = points.slice(-dashboardSparklineBarLimit);
  }
  if (oversizedBars && bars) {
    slimmed.bars = bars.slice(-dashboardSparklineBarLimit);
  }
  if (oversizedTimeframes.length > 0 && payload.timeframes) {
    slimmed.timeframes = { ...payload.timeframes };
    for (const [timeframe, bars] of oversizedTimeframes) {
      slimmed.timeframes[timeframe] = bars.slice(-dashboardSparklineBarLimit);
    }
  }

  return slimmed as Sparkline;
}
