import { error, json } from "@sveltejs/kit";
import {
  ChartDataValidationError,
  ChartRunMismatchError,
  createChartDataRepository,
  isDashboardTimeframe,
  isSafeChartSymbol
} from "$lib/server/chart-data-repository";

const safeRunIdPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;

export async function GET({ params, url }) {
  const requestedTimeframe = url.searchParams.get("tf") ?? "15m";
  const snapshotRunId = url.searchParams.get("runId");
  if (!isSafeChartSymbol(params.symbol)) {
    error(400, "invalid symbol");
  }
  if (!isDashboardTimeframe(requestedTimeframe)) {
    error(400, "invalid timeframe");
  }
  if (!snapshotRunId || !safeRunIdPattern.test(snapshotRunId)) {
    error(400, "invalid runId");
  }

  try {
    const payload = await createChartDataRepository().symbol(
      params.symbol,
      requestedTimeframe,
      snapshotRunId
    );
    if (!payload) {
      return json({
        schemaVersion: 2,
        snapshotRunId,
        symbol: params.symbol.toUpperCase(),
        generatedAt: Date.now(),
        dataAsOf: 0,
        timeframes: {
          [requestedTimeframe]: []
        }
      });
    }
    return json(payload);
  } catch (cause) {
    if (cause instanceof ChartRunMismatchError) {
      error(409, cause.message);
    }
    if (cause instanceof ChartDataValidationError) {
      error(503, cause.message);
    }
    if (cause && typeof cause === "object" && "status" in cause) {
      throw cause;
    }
    error(503, cause instanceof Error ? cause.message : "chart data unavailable");
  }
}
