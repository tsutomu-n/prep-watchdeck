import Ajv2020 from "ajv/dist/2020";
import schema from "../../../../../schemas/candle-recovery-state.schema.json";
import type { CandleRecoveryState } from "$lib/generated/candle-recovery-state";
import { readBoundedStateJson } from "./bounded-state-json";
import { resolveMarketStatePaths } from "./market-state-paths";

const ajv = new Ajv2020({ strict: false });
ajv.addFormat("date-time", { type: "string", validate: utcTime });
const validate = ajv.compile(schema);

function utcTime(value: string): boolean {
  return /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
}

export async function readCandleRecoveryState(
  path = resolveMarketStatePaths().candleRecoveryStatePath
): Promise<CandleRecoveryState> {
  const payload = await readBoundedStateJson(path, 1024 * 1024);
  if (!validate(payload)) throw new Error("recovery state invalid");
  const state = payload as unknown as CandleRecoveryState;
  const start = Date.parse(state.window.start);
  const end = Date.parse(state.window.end);
  const started = Date.parse(state.startedAt);
  const generated = Date.parse(state.generatedAt);
  const finished = state.finishedAt === null ? null : Date.parse(state.finishedAt);
  const count = (end - start) / 60_000;
  if (!Number.isInteger(count) || count < 1 || count > 1440 ||
      end > started || generated < started ||
      (finished !== null && (finished < started || generated < finished)) ||
      (state.execution === "running") !== (finished === null) ||
      state.summary.scannedTargetCount > state.summary.targetCount ||
      state.summary.inserted > (state.summary.missingBefore ?? Infinity) ||
      (state.summary.newlyPresent !== null && state.summary.inserted > state.summary.newlyPresent) ||
      state.summary.failedTargets + state.summary.deferredTargets > state.summary.targetCount ||
      state.detailsTruncated !== (state.details.length === 128 && state.summary.targetCount > 128)) {
    throw new Error("recovery state inconsistent");
  }
  const seen = new Set<string>();
  for (const detail of state.details) {
    const key = `${detail.target.venueInstrumentId}/${detail.target.venueInstrumentVersionId}`;
    if (seen.has(key) || detail.inserted > (detail.missingBefore ?? Infinity) ||
        (detail.remaining !== null && detail.remaining > (detail.missingBefore ?? Infinity))) {
      throw new Error("recovery target detail inconsistent");
    }
    seen.add(key);
  }
  return state;
}
