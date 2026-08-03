import { describe, expect, it } from "vitest";
import {
  currentRuntimeInfo,
  localCommandsEnabled,
  refreshLiveAvailability,
  runtimeTarget
} from "./runtime-target";

describe("runtime target helpers", () => {
  it("defaults to local runtime with local commands disabled", () => {
    const env = {};

    expect(runtimeTarget(env)).toBe("local");
    expect(localCommandsEnabled(env)).toBe(false);
    expect(currentRuntimeInfo(env).labels).toEqual([
      "LOCAL FILE",
      "LOCAL COMMANDS DISABLED",
      "CLOUDFLARE READY: NO"
    ]);
  });

  it("enables local commands only with an explicit local opt-in", () => {
    const env = {
      PREP_WATCHDECK_RUNTIME_TARGET: "local",
      PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS: "true"
    };

    expect(localCommandsEnabled(env)).toBe(true);
    expect(refreshLiveAvailability("127.0.0.1", env)).toMatchObject({ ok: true });
  });

  it("keeps refresh-live disabled for cloudflare target even with command opt-in", () => {
    const env = {
      PREP_WATCHDECK_RUNTIME_TARGET: "cloudflare",
      PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS: "true"
    };

    expect(localCommandsEnabled(env)).toBe(false);
    expect(refreshLiveAvailability("localhost", env)).toMatchObject({
      ok: false,
      status: 409,
      error: "LOCAL_COMMAND_DISABLED"
    });
  });

  it("requires localhost for refresh-live", () => {
    expect(
      refreshLiveAvailability("example.com", {
        PREP_WATCHDECK_RUNTIME_TARGET: "local",
        PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS: "true"
      })
    ).toMatchObject({
      ok: false,
      status: 403,
      error: "LOCALHOST_REQUIRED"
    });
  });
});
