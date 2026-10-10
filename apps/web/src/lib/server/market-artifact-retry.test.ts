import { describe, expect, test, vi } from "vitest";
import { retryArtifactPublication } from "./market-artifact-repository";

describe("market artifact publication retry", () => {
  test("waits for the service manifest after artifacts are published", async () => {
    const value = { generation: "next" };
    let published = false;
    const publish = setTimeout(() => { published = true; }, 75);
    const read = vi.fn(async () => {
      if (!published) throw new Error("market artifacts changed while being read");
      return value;
    });

    try {
      await expect(retryArtifactPublication(read)).resolves.toBe(value);
      expect(read).toHaveBeenCalledTimes(3);
    } finally {
      clearTimeout(publish);
    }
  });

  test("does not retry invalid or persistently stale artifacts", async () => {
    const invalid = vi.fn(async () => { throw new Error("selected-market is stale"); });
    await expect(retryArtifactPublication(invalid)).rejects.toThrow("selected-market is stale");
    expect(invalid).toHaveBeenCalledTimes(1);

    const mismatch = vi.fn(async () => { throw new Error("market artifacts changed while being read"); });
    await expect(retryArtifactPublication(mismatch))
      .rejects.toThrow("market artifacts changed while being read");
    expect(mismatch).toHaveBeenCalledTimes(4);
  });
});
