// OpenFDA: safety signals. Free, no key needed (240 req/min, 1,000/day per IP;
// set OPENFDA_API_KEY for 120,000/day). Docs: https://open.fda.gov/apis/
//   food/event        CAERS adverse event reports for foods and dietary supplements (herbs)
//   food/enforcement  recalls of foods and supplements
//   drug/event        FAERS adverse event reports for medicines
//   drug/label        official drug labels (warnings, interactions)
// Adverse event reports are NOT proof that a product caused the problem; we say so.
import { getJSON, qs, clip } from "./http.mjs";

const BASE = "https://api.fda.gov";
const term = (s) => `"${String(s).replace(/"/g, "")}"`;
const ymd = (s) => String(s ?? "").replace(/^(\d{4})(\d{2})(\d{2}).*/, "$1-$2-$3");

// Medicines named in the question, or the usual first-line medicine for a topic.
const DRUG_HINTS = [
  [/\b(levothyroxine|synthroid|thyroxine)\b/i, "levothyroxine"],
  [/\bmetformin\b/i, "metformin"],
  [/\b(warfarin|coumadin)\b/i, "warfarin"],
  [/\b(atorvastatin|statins?|lipitor)\b/i, "atorvastatin"],
  [/\b(amlodipine)\b/i, "amlodipine"],
  [/\b(lisinopril)\b/i, "lisinopril"],
  [/\b(aspirin)\b/i, "aspirin"],
  [/\b(ibuprofen|advil)\b/i, "ibuprofen"],
  [/\b(omeprazole|ppi)\b/i, "omeprazole"],
  [/\b(ferrous|iron (tablet|pill|supplement)s?)\b/i, "ferrous sulfate"],
];
const TOPIC_DRUG = { anemia_rbc: "ferrous sulfate", blood_sugar: "metformin", vitamin_d_bone: "cholecalciferol" };

export function pickDrug(question, topic) {
  return DRUG_HINTS.find(([re]) => re.test(question))?.[1] ?? TOPIC_DRUG[topic] ?? null;
}

export async function supplementSafety(herb, { apiKey } = {}) {
  const key = apiKey ? { api_key: apiKey } : {};
  const [events, recalls] = await Promise.allSettled([
    getJSON(`${BASE}/food/event.json?${qs({ search: `products.name_brand:${term(herb)}`, count: "reactions.exact", limit: 6, ...key })}`),
    getJSON(`${BASE}/food/enforcement.json?${qs({ search: `product_description:${term(herb)}`, sort: "report_date:desc", limit: 2, ...key })}`),
  ]);
  const out = [];
  const ev = events.status === "fulfilled" ? events.value?.results ?? [] : [];
  if (ev.length) {
    const total = ev.reduce((n, r) => n + r.count, 0);
    out.push({
      kind: "fda", subtype: "supplement_events",
      title: `FDA adverse event reports mentioning ${herb} (supplements)`,
      text: `Most reported reactions for ${herb} products: ${ev.map((r) => `${r.term.toLowerCase()} (${r.count})`).join(", ")}. Reports are voluntary and do not prove the product caused the reaction.`,
      reports: total, date: "",
      url: `https://open.fda.gov/apis/food/event/`,
      source: "OpenFDA CAERS",
    });
  }
  for (const r of recalls.status === "fulfilled" ? recalls.value?.results ?? [] : []) {
    out.push({
      kind: "fda", subtype: "recall",
      title: `FDA recall of ${herb} product (${r.classification ?? "unclassified"}, ${String(r.status ?? "").toLowerCase()})`,
      text: clip(`${r.product_description ?? ""}. Reason: ${r.reason_for_recall ?? "not stated"}`, 500),
      date: ymd(r.report_date), year: String(r.report_date ?? "").slice(0, 4),
      url: `https://api.fda.gov/food/enforcement.json?search=recall_number:${encodeURIComponent(term(r.recall_number ?? r.event_id ?? herb))}`,
      source: "OpenFDA enforcement",
    });
  }
  return out;
}

export async function drugSafety(drug, { apiKey } = {}) {
  const key = apiKey ? { api_key: apiKey } : {};
  const [events, labels] = await Promise.allSettled([
    getJSON(`${BASE}/drug/event.json?${qs({ search: `patient.drug.openfda.generic_name:${term(drug)}`, count: "patient.reaction.reactionmeddrapt.exact", limit: 6, ...key })}`),
    getJSON(`${BASE}/drug/label.json?${qs({ search: `openfda.generic_name:${term(drug)}`, limit: 1, ...key })}`),
  ]);
  const out = [];
  const ev = events.status === "fulfilled" ? events.value?.results ?? [] : [];
  if (ev.length) {
    out.push({
      kind: "fda", subtype: "drug_events",
      title: `FDA adverse event reports for ${drug}`,
      text: `Most reported reactions in FAERS for ${drug}: ${ev.map((r) => `${r.term.toLowerCase()} (${r.count})`).join(", ")}. Reports are voluntary and do not prove the medicine caused the reaction.`,
      reports: ev.reduce((n, r) => n + r.count, 0), date: "",
      url: `https://open.fda.gov/apis/drug/event/`,
      source: "OpenFDA FAERS",
    });
  }
  const label = labels.status === "fulfilled" ? labels.value?.results?.[0] : null;
  if (label) {
    const pick = (k) => (Array.isArray(label[k]) ? label[k].join(" ") : label[k] ?? "");
    const body = [pick("indications_and_usage") && `Uses: ${pick("indications_and_usage")}`,
      (pick("warnings") || pick("warnings_and_cautions")) && `Warnings: ${pick("warnings") || pick("warnings_and_cautions")}`,
      pick("drug_interactions") && `Interactions: ${pick("drug_interactions")}`].filter(Boolean).join(" ");
    out.push({
      kind: "fda", subtype: "label",
      title: `FDA drug label: ${label.openfda?.brand_name?.[0] ?? drug} (${drug})`,
      text: clip(body.replace(/\s+/g, " "), 900),
      date: ymd(label.effective_time), year: String(label.effective_time ?? "").slice(0, 4),
      url: label.set_id ? `https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=${label.set_id}` : "https://open.fda.gov/apis/drug/label/",
      source: "OpenFDA drug label",
    });
  }
  return out;
}
