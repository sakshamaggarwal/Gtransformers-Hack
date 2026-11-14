// Shared helper for the live connectors: timeout, small in-memory cache, and a
// polite User-Agent. Every connector must fail soft (return [] on any error),
// so a slow or down API never breaks the chat.

const cache = new Map(); // url -> { at, data }
const TTL_MS = 30 * 60 * 1000;
export const USER_AGENT = "web:vaidya-pulse:0.3 (health research hackathon prototype)";

export async function getJSON(url, { timeoutMs = 5000, headers = {} } = {}) {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.data;
  const res = await fetch(url, {
    headers: { "user-agent": USER_AGENT, accept: "application/json", ...headers },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (res.status === 404) return null; // OpenFDA answers 404 for "no matches"
  if (!res.ok) throw new Error(`${new URL(url).host} ${res.status}`);
  const data = await res.json();
  cache.set(url, { at: Date.now(), data });
  if (cache.size > 500) cache.delete(cache.keys().next().value);
  return data;
}

// Same as getJSON, for XML / text APIs (PubMed efetch).
export async function getText(url, { timeoutMs = 5000, headers = {} } = {}) {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.data;
  const res = await fetch(url, { headers: { "user-agent": USER_AGENT, ...headers }, signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`${new URL(url).host} ${res.status}`);
  const data = await res.text();
  cache.set(url, { at: Date.now(), data });
  if (cache.size > 500) cache.delete(cache.keys().next().value);
  return data;
}

export const clearCache = () => cache.clear();

export const qs = (params) =>
  Object.entries(params).filter(([, v]) => v != null && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");

export const stripHtml = (s) =>
  String(s ?? "").replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();

export const clip = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
