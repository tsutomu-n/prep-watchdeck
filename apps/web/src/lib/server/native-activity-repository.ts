import { readFile } from "node:fs/promises";
import Ajv2020 from "ajv/dist/2020";
import schema from "../../../../../schemas/native-activity.schema.json";
import type { ActivityValue, NativeActivityArtifact } from "$lib/generated/native-activity";
import { resolveMarketStatePaths } from "./market-state-paths";

const ajv = new Ajv2020({ strict: false });
ajv.addFormat("date-time", { type: "string", validate: (value: string) => Number.isFinite(Date.parse(value)) });
const validate = ajv.compile(schema);
const validValue = (item: ActivityValue, nonnegative = false) => item.status === "ready"
  ? item.value !== null && Number.isFinite(item.value) && (!nonnegative || item.value >= 0)
  : item.value === null;
const sameValue = (a: ActivityValue, b: ActivityValue) => a.status === b.status && a.value === b.value;

export async function readNativeActivity(
  path = resolveMarketStatePaths().nativeActivityPath
): Promise<NativeActivityArtifact> {
  const payload: unknown = JSON.parse(await readFile(path, "utf-8"));
  const invalid = () => { throw new Error("native activity invalid"); };
  if (!validate(payload)) invalid();
  const artifact = payload as NativeActivityArtifact;
  const cutoff = Date.parse(artifact.candleCutoff);
  if (cutoff !== Math.floor(Date.parse(artifact.generatedAt) / 60_000) * 60_000 - 180_000) invalid();
  const identities = new Set<string>();
  for (const row of artifact.rows) {
    if (identities.has(row.venueInstrumentId) || row.venueInstrumentId !== `bitget:${row.sourceSymbol}`
      || Object.keys(row.windows).sort().join(",") !== "15m,1h") invalid();
    identities.add(row.venueInstrumentId);
    for (const [key, minutes] of [["15m", 15], ["1h", 60]] as const) {
      const window = row.windows[key];
      const duration = minutes * 60_000;
      if (window.minutes !== minutes || window.baselineDays !== window.baselineEndTimes.length
        || new Set(window.baselineEndTimes).size !== window.baselineDays) invalid();
      const ends = window.baselineEndTimes.map(Date.parse);
      if (ends.some((time, index) => (index > 0 && time <= ends[index - 1])
        || (cutoff - time) % 86_400_000 !== 0 || time >= cutoff || time < cutoff - 7 * 86_400_000)) invalid();
      for (const [index, sample] of window.history.entries()) {
        if (Date.parse(sample.endAt) !== cutoff - (3 - index) * duration
          || Date.parse(sample.startAt) !== cutoff - (4 - index) * duration
          || !validValue(sample.turnover, true) || !validValue(sample.priceChangePct)) invalid();
      }
      const latest = window.history[3];
      if (window.current.startAt !== latest.startAt || window.current.endAt !== latest.endAt
        || !sameValue(window.current.turnover, latest.turnover)
        || !sameValue(window.current.priceChangePct, latest.priceChangePct)
        || !validValue(window.baselineTurnover, true) || !validValue(window.relativeRatio, true)
        || !validValue(window.previousChangePct)) invalid();
      if (window.baselineTurnover.value !== null && window.baselineDays < 3) invalid();
      const floor = minutes === 15 ? 1000 : 4000;
      if (window.relativeRatio.value !== null && (window.current.turnover.value === null
        || window.baselineTurnover.value === null || window.baselineTurnover.value < floor)) invalid();
      const previous = window.history[2].turnover.value;
      if (window.previousChangePct.value !== null && (window.current.turnover.value === null
        || previous === null || previous < floor || window.previousChangePct.value < -100)) invalid();
    }
  }
  return artifact;
}
