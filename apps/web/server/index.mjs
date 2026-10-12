import { configureAdapter, createProductionServer, listenOptions } from "./http.mjs";

configureAdapter(process.env);
const options = listenOptions(process.env);
const { handler } = await import("../build/handler.js");
const server = createProductionServer(handler);

server.listen(options, () => {
  console.log(`Watchdeck production Web listening on ${options.host}:${options.port}`);
});

let stopping = false;
function shutdown() {
  if (stopping) return;
  stopping = true;
  const timeout = setTimeout(() => {
    server.closeAllConnections();
    process.exit(0);
  }, 25_000);
  timeout.unref();
  server.close(() => {
    clearTimeout(timeout);
    process.exit(0);
  });
  server.closeIdleConnections();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
