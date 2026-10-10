import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Database } from "bun:sqlite";
import { ChartHistoryService } from "../../src/lib/server/chart-history.ts";
import { SharedMexcBudget, openMexcBudgetStore } from "../../src/lib/server/mexc-budget.ts";

const scratch = await mkdtemp(join(tmpdir(), "watchdeck-mexc-transport-"));
const results = [];
try {
  for (const warm of [false, true]) {
    const path = join(scratch, `${warm}.sqlite3`);
    const budget = new SharedMexcBudget({ loadStore: () => openMexcBudgetStore(path) });
    const sockets = new Set();
    let targetRequests = 0;
    let connections = 0;
    let targetConnection = null;
    const server = createServer(socket => {
      const connection = ++connections;
      sockets.add(socket);
      socket.on("close", () => sockets.delete(socket));
      let buffered = "";
      socket.on("data", chunk => {
        buffered += chunk.toString("utf8");
        const end = buffered.indexOf("\r\n\r\n");
        if (end < 0) return;
        const request = buffered.slice(0, end).split("\r\n")[0];
        buffered = buffered.slice(end + 4);
        if (request.includes(" /prime ")) {
          socket.write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\n{}");
        } else if (++targetRequests === 1) {
          targetConnection = connection;
          // A pooled Bun socket would retry this already-sent GET without a new admission.
          socket.destroy();
        } else {
          const body = JSON.stringify({ success: true, code: 0, data: {
            time: [], open: [], high: [], low: [], close: [], vol: [], amount: []
          } });
          socket.end(`HTTP/1.1 200 OK\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n${body}`);
        }
      });
    });
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    try {
      if (warm) {
        await budget.acquire("foreground", AbortSignal.timeout(1_000));
        const primer = await fetch(`${origin}/prime`);
        assert.equal(primer.status, 200);
        await primer.text();
      }
      const service = new ChartHistoryService({
        mexcBudget: budget,
        artifacts: { latest: async () => { throw new Error("unexpected artifact read"); } },
        fetch: (url, init) => {
          assert.equal(url.hostname, "api.mexc.com");
          return fetch(new URL(url.pathname + url.search, origin), init);
        }
      });
      const now = Date.parse("2026-10-10T00:00:00Z");
      await assert.rejects(service.minuteCandles({
        venue: "mexc", sourceSymbol: "BTC_USDT", venueInstrumentId: "mexc:BTC_USDT",
        venueInstrumentVersionId: 1, active: true, marketType: "linear_perpetual",
        quoteAsset: "USDT", settleAsset: "USDT"
      }, { before: now + 1, now, limit: 1, latest: true }),
      { code: "chart_source_unavailable" });
      const db = new Database(path, { readonly: true });
      let admissions;
      try { admissions = db.query("SELECT count(*) AS count FROM mexc_budget_attempts").get().count; }
      finally { db.close(); }
      assert.equal(targetRequests, 1, "one budget admission must not send two GETs");
      assert.equal(admissions, warm ? 2 : 1);
      if (warm) assert.notEqual(targetConnection, 1, "MEXC must not reuse the primed connection");
      results.push({ warm, targetRequests, targetBudgetAdmissions: admissions - Number(warm),
        targetConnection });
    } finally {
      for (const socket of sockets) socket.destroy();
      await new Promise(resolve => server.close(resolve));
    }
  }
  console.log(JSON.stringify({ bunVersion: Bun.version, results }));
} finally {
  await rm(scratch, { recursive: true, force: true });
}
