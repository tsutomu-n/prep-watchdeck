import { describe, expect, it } from "vitest";
import { refreshLiveAvailability } from "$lib/server/runtime-target";

describe("refresh-live route policy", () => {
  it("is disabled for direct bun dev defaults", () => {
    expect(refreshLiveAvailability("localhost", {})).toMatchObject({
      ok: false,
      status: 409,
      error: "LOCAL_COMMAND_DISABLED",
      message: "refresh-live is local-only and disabled in this runtime"
    });
  });

  it("is enabled only for localhost local runtime with command opt-in", () => {
    expect(
      refreshLiveAvailability("localhost", {
        PREP_WATCHDECK_RUNTIME_TARGET: "local",
        PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS: "true"
      })
    ).toMatchObject({ ok: true });
  });

  it("stays disabled for cloudflare target", () => {
    expect(
      refreshLiveAvailability("localhost", {
        PREP_WATCHDECK_RUNTIME_TARGET: "cloudflare",
        PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS: "true"
      })
    ).toMatchObject({
      ok: false,
      status: 409,
      error: "LOCAL_COMMAND_DISABLED"
    });
  });
});
