import { readFile } from "node:fs/promises";
import type { ServiceStateSnapshot, ServiceStateView } from "$lib/service-state";
import { summarizeServiceState, unreadableServiceStateView } from "$lib/service-state";
import { resolveStatePaths } from "./state-paths";

export type ServiceStateResult = {
  raw: ServiceStateSnapshot;
  view: ServiceStateView;
};

export interface ServiceStateRepository {
  latest(): Promise<ServiceStateResult | undefined>;
}

export class LocalFileServiceStateRepository implements ServiceStateRepository {
  constructor(private readonly serviceStatePath = defaultServiceStatePath()) {}

  async latest(): Promise<ServiceStateResult | undefined> {
    const raw = await readFile(this.serviceStatePath, "utf-8").catch((cause) => {
      if (cause && typeof cause === "object" && "code" in cause && cause.code === "ENOENT") {
        return null;
      }
      throw cause;
    });
    if (raw === null) return undefined;

    let state: ServiceStateSnapshot;
    try {
      state = JSON.parse(raw) as ServiceStateSnapshot;
    } catch {
      return {
        raw: {},
        view: unreadableServiceStateView()
      };
    }
    return {
      raw: state,
      view: summarizeServiceState(state)
    };
  }
}

export function createServiceStateRepository(): ServiceStateRepository {
  return new LocalFileServiceStateRepository();
}

function defaultServiceStatePath() {
  return resolveStatePaths().serviceStatePath;
}
