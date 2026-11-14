// =============================================================================
// scripts/serve.mjs: run the whole app locally with plain Node (no Netlify CLI)
// =============================================================================
//   cp .env.example .env      # add GROQ_API_KEY (everything else is keyless)
//   npm start                 # http://localhost:8888
//
// Serves public/ (the Vaidya Pulse page) and routes /api/chat, /api/evidence and
// /api/session to the same Netlify Function files that run in production.
// Live API calls (PubMed, ClinicalTrials.gov, OpenFDA, Stack Exchange, Reddit,
// Groq) go out from YOUR machine, so they work wherever you have internet.
// =============================================================================
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

// 1 Load .env into process.env (does not override variables already set).
const envFile = join(ROOT, ".env");
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*(#.*)?$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}

// 2 Import the functions after .env is loaded.
const routes = {
  "/api/chat": (await import("../netlify/functions/chat/index.mjs")).default,
  "/api/evidence": (await import("../netlify/functions/evidence/index.mjs")).default,
  "/api/session": (await import("../netlify/functions/session/index.mjs")).default,
};
const { provider, modelName } = await import("../netlify/lib/llm.mjs");

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".csv": "text/csv", ".svg": "image/svg+xml", ".png": "image/png" };
const PUBLIC = join(ROOT, "public");

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  try {
    const fn = routes[url.pathname] ?? (url.pathname.startsWith("/api/session") ? routes["/api/session"] : null);
    if (fn) {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      const body = ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks);
      const request = new Request(url, { method: req.method, headers: req.headers, body });
      const response = await fn(request, { ip: req.socket.remoteAddress ?? "local" });
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(Buffer.from(await response.arrayBuffer()));
      return;
    }
    // static files from public/
    let path = normalize(join(PUBLIC, decodeURIComponent(url.pathname)));
    if (!path.startsWith(PUBLIC)) { res.writeHead(403).end(); return; }
    if (url.pathname.endsWith("/")) path = join(path, "index.html");
    const data = await readFile(path).catch(() => null);
    if (!data) { res.writeHead(404, { "content-type": "text/plain" }).end("Not found"); return; }
    res.writeHead(200, { "content-type": TYPES[extname(path)] ?? "application/octet-stream" });
    res.end(data);
  } catch (err) {
    console.error(err);
    res.writeHead(500, { "content-type": "application/json" }).end(JSON.stringify({ error: "server error" }));
  }
});

const port = Number(process.env.PORT) || 8888;
server.listen(port, () => {
  console.log(`\nVaidya Pulse running at http://localhost:${port}`);
  console.log(`  answer model : ${provider()} (${modelName()})${provider() === "mock" ? "  <- add GROQ_API_KEY to .env for real Llama 3.1 8B answers" : ""}`);
  console.log(`  live sources : ${(process.env.LIVE_SOURCES ?? "on").toLowerCase() === "off" ? "OFF" : "PubMed, ClinicalTrials.gov, OpenFDA, Health Stack Exchange, Reddit" + (process.env.REDDIT_CLIENT_ID ? " (OAuth)" : " (public JSON)") + " + Ayurvedic KB"}`);
  console.log(`  try          : curl "http://localhost:${port}/api/evidence?q=how+can+I+increase+my+RBC+count"\n`);
});
