import { describe, expect, test } from "bun:test";
import { isIsolatedTestDatabaseUrl } from "../lib/validate-test-database-url.mjs";

describe("isolated verification database target", () => {
  test("accepts only a dedicated loopback test database on a non-reserved explicit port", () => {
    expect(
      isIsolatedTestDatabaseUrl(
        "postgresql://prep_watchdeck_test:test-only@127.0.0.1:55439/prep_watchdeck_test"
      )
    ).toBe(true);

    for (const target of [
      "postgresql://prep_watchdeck_test:test-only@127.0.0.1:5432/prep_watchdeck_test",
      "postgresql://prep_watchdeck_test:test-only@127.0.0.1:55432/prep_watchdeck_test",
      "postgresql://prep_watchdeck_test:test-only@example.com:55439/prep_watchdeck_test",
      "postgresql://prep_watchdeck_market:test-only@127.0.0.1:55439/prep_watchdeck_test",
      "postgresql://prep_watchdeck_test:test-only@127.0.0.1:55439/prep_watchdeck_market",
      "postgresql://prep_watchdeck_test:test-only@127.0.0.1/prep_watchdeck_test"
    ]) {
      expect(isIsolatedTestDatabaseUrl(target)).toBe(false);
    }
  });
});
