export function isIsolatedTestDatabaseUrl(raw) {
  try {
    const value = new URL(raw);
    const port = Number(value.port);
    const username = decodeURIComponent(value.username);
    const database = decodeURIComponent(value.pathname.slice(1));
    return (
      ["postgres:", "postgresql:"].includes(value.protocol) &&
      ["127.0.0.1", "localhost", "[::1]"].includes(value.hostname) &&
      username === "prep_watchdeck_test" &&
      value.password !== "" &&
      database === "prep_watchdeck_test" &&
      value.pathname.split("/").length === 2 &&
      value.search === "" &&
      value.hash === "" &&
      value.port !== "" &&
      Number.isInteger(port) &&
      port >= 1 &&
      port <= 65535 &&
      port !== 5432 &&
      port !== 55432
    );
  } catch {
    return false;
  }
}

if (import.meta.main && !isIsolatedTestDatabaseUrl(process.env.TEST_DATABASE_URL ?? "")) {
  process.exitCode = 2;
}
