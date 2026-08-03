export type RuntimeTarget = "local" | "cloudflare";

export type RuntimeInfo = {
  target: RuntimeTarget;
  localCommandsEnabled: boolean;
  localCommandsAvailable: boolean;
  cloudflareReady: false;
  labels: string[];
};

export type RefreshLiveAvailability =
  | { ok: true; runtime: RuntimeInfo }
  | {
      ok: false;
      status: number;
      error: "LOCAL_COMMAND_DISABLED" | "LOCALHOST_REQUIRED";
      message: string;
      runtime: RuntimeInfo;
    };

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

export function runtimeTarget(env: NodeJS.ProcessEnv = process.env): RuntimeTarget {
  return env.PREP_WATCHDECK_RUNTIME_TARGET === "cloudflare" ? "cloudflare" : "local";
}

export function localCommandsEnabled(env: NodeJS.ProcessEnv = process.env) {
  return runtimeTarget(env) === "local" && env.PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS === "true";
}

export function currentRuntimeInfo(env: NodeJS.ProcessEnv = process.env): RuntimeInfo {
  const target = runtimeTarget(env);
  const commandsEnabled = localCommandsEnabled(env);
  return {
    target,
    localCommandsEnabled: commandsEnabled,
    localCommandsAvailable: target === "local",
    cloudflareReady: false,
    labels: [
      target === "cloudflare" ? "CLOUDFLARE TARGET" : "LOCAL FILE",
      commandsEnabled ? "LOCAL COMMANDS ENABLED" : "LOCAL COMMANDS DISABLED",
      "CLOUDFLARE READY: NO"
    ]
  };
}

export function refreshLiveAvailability(
  hostname: string,
  env: NodeJS.ProcessEnv = process.env
): RefreshLiveAvailability {
  const runtime = currentRuntimeInfo(env);
  if (!LOCAL_HOSTS.has(hostname)) {
    return {
      ok: false,
      status: 403,
      error: "LOCALHOST_REQUIRED",
      message: "refresh-live is only available from localhost",
      runtime
    };
  }
  if (!runtime.localCommandsEnabled) {
    return {
      ok: false,
      status: 409,
      error: "LOCAL_COMMAND_DISABLED",
      message: "refresh-live is local-only and disabled in this runtime",
      runtime
    };
  }
  return { ok: true, runtime };
}
