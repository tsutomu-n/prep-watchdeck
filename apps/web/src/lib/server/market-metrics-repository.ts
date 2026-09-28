import { readFile } from "node:fs/promises";
import Ajv2020 from "ajv/dist/2020";
import schema from "../../../../../schemas/market-metrics.schema.json";
import type { MarketMetricsArtifact } from "$lib/generated/market-metrics";
import { resolveMarketStatePaths } from "./market-state-paths";

const ajv = new Ajv2020({ strict: false });
ajv.addFormat("date-time", {
  type: "string",
  validate: (value: string) => Number.isFinite(Date.parse(value))
});
const validate = ajv.compile(schema);

export async function readMarketMetrics(
  path = resolveMarketStatePaths().marketMetricsPath
): Promise<MarketMetricsArtifact> {
  const payload: unknown = JSON.parse(await readFile(path, "utf-8"));
  if (!validate(payload)) throw new Error("market metrics invalid");
  const metrics = payload as unknown as MarketMetricsArtifact;
  const keys = new Set<string>();
  for (const row of metrics.rows) {
    const key = `${row.venueInstrumentId}/${row.venueInstrumentVersionId}`;
    if (keys.has(key) || Object.keys(row.oiChange).sort().join(",") !== "15m,1h" ||
        Object.keys(row.tradeChange).sort().join(",") !== "15m,1h,24h") {
      throw new Error("market metrics invalid");
    }
    keys.add(key);
  }
  return metrics;
}
