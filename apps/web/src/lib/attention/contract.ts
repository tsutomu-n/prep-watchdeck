import Ajv from "ajv";
import schema from "../../../../../schemas/attention-response.schema.json";
import type { AttentionResponse } from "$lib/generated/attention-response";
import { COMPONENTS } from "./attention";

const validate = new Ajv({ allErrors: false, strict: false }).compile<AttentionResponse>(schema);
export function parseAttention(payload: unknown, now = Date.now()): AttentionResponse {
  if (!validate(payload)) throw new Error("注目データの形式が不正です");
  const { inputs, rows, coverage } = payload;
  const times = [inputs.rankingCutoff, inputs.rankingGeneratedAt, inputs.universeGeneratedAt,
    inputs.serviceGeneratedAt, inputs.marketMetricsGeneratedAt, inputs.marketMetricsCandleCutoff];
  const invalid = payload.generationId !== inputs.generationId || payload.decisionAt !== inputs.decisionAt ||
    payload.decisionAt > now + 1000 || times.some(time => time !== null && time > payload.decisionAt) ||
    inputs.rankingCutoff % 60_000 !== 0 || inputs.rankingGeneratedAt < inputs.rankingCutoff ||
    (inputs.marketMetricsGenerationId === null) !== (inputs.marketMetricsGeneratedAt === null) ||
    new Set(rows.map(row => row.assetId)).size !== rows.length || rows.length !== coverage.rows ||
    coverage.eligible !== rows.filter(row => ["ready", "partial"].includes(row.identityStatus)).length ||
    coverage.confluenceReady !== rows.filter(row => row.components.confluence?.status === "ready").length ||
    COMPONENTS.some(name => coverage.componentReady[name] !== rows.filter(row => row.components[name]?.status === "ready").length) ||
    rows.some(row => {
      const ready = COMPONENTS.filter(name => row.components[name]?.status === "ready").length;
      return row.dataAsOf > payload.decisionAt || row.readyComponentCount !== ready || row.coverageRatio !== ready / 4 ||
        Object.keys(row.components).length !== 5 || [...COMPONENTS, "confluence"].some(name => !row.components[name]) ||
        (row.components.confluence.status === "ready" && ready !== 4) ||
        Object.values(row.components).some(component => component.status === "ready"
          ? component.score === null || component.rank === null || component.reason !== null
          : component.score !== null || component.rank !== null || !component.reason);
    }) || payload.shadowAllocations.some(allocation => allocation.generationId !== payload.generationId ||
      allocation.decisionAt !== payload.decisionAt || allocation.mapVersion !== inputs.rankingMapVersion);
  if (invalid) throw new Error("注目データの世代または品質が不正です");
  return now - inputs.rankingCutoff > 150_000 && payload.status !== "unavailable"
    ? { ...payload, status: "stale", reason: payload.reason ?? "attention_stale" } : payload;
}
