// OpenFDA: supplement safety signals. Free, no key needed (240 req/min,
// 1,000/day per IP; set OPENFDA_API_KEY for 120,000/day). Docs: https://open.fda.gov/apis/
//   food/event        CAERS adverse event reports for foods and dietary supplements
//   food/enforcement  recalls of foods and supplements
// Adverse event reports are NOT proof that a product caused the problem; we say so.
import { getJSON, qs, clip } from "./http.mjs";

const BASE = "https://api.fda.gov";
const term = (s) => `"${String(s).replace(/"/g, "")}"`;

export async function supplementSafety(herb, { apiKey } = {}) {
  const key = apiKey ? { api_key: apiKey } : {};
  const [events, recalls] = await Promise.allSettled([
    getJSON(`${BASE}/food/event.json?${qs({ search: `products.name_brand:${term(herb)}`, count: "reactions.exact", limit: 5, ...key })}`),
    getJSON(`${BASE}/food/enforcement.json?${qs({ search: `product_description:${term(herb)}`, sort: "report_date:desc", limit: 2, ...key })}`),
  ]);
  const out = [];
  const ev = events.status === "fulfilled" ? events.value?.results ?? [] : [];
  if (ev.length) {
    const total = ev.reduce((n, r) => n + r.count, 0);
    out.push({
      kind: "fda",
      title: `FDA adverse event reports mentioning ${herb}`,
      text: `Most reported reactions: ${ev.map((r) => `${r.term.toLowerCase()} (${r.count})`).join(", ")}. Reports are voluntary and do not prove the product caused the reaction.`,
      count: total,
      url: `https://open.fda.gov/apis/food/event/`,
      source: "OpenFDA CAERS",
    });
  }
  for (const r of recalls.status === "fulfilled" ? recalls.value?.results ?? [] : []) {
    out.push({
      kind: "fda",
      title: `FDA recall (${r.classification ?? "unclassified"}, ${r.status ?? ""}) ${String(r.report_date ?? "").replace(/(\d{4})(\d{2})(\d{2})/, "$1-$2-$3")}`,
      text: clip(`${r.product_description ?? ""}. Reason: ${r.reason_for_recall ?? "not stated"}`, 400),
      url: "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
      source: "OpenFDA enforcement",
    });
  }
  return out;
}
