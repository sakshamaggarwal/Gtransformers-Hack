// ClinicalTrials.gov API v2: registered trials. Free, no key.
// Docs: https://clinicaltrials.gov/data-api/api
import { getJSON, qs, clip } from "./http.mjs";

const FIELDS = "NCTId,BriefTitle,BriefSummary,OverallStatus,Phase,Condition,InterventionName,EnrollmentCount,StartDate,LastUpdatePostDate,HasResults";

function toItem(s) {
  const p = s.protocolSection ?? {};
  const id = p.identificationModule?.nctId;
  const status = p.statusModule?.overallStatus ?? "";
  const phases = p.designModule?.phases ?? [];
  const enrollment = p.designModule?.enrollmentInfo?.count ?? 0;
  const conditions = p.conditionsModule?.conditions ?? [];
  const interventions = (p.armsInterventionsModule?.interventions ?? []).map((i) => i.name).filter(Boolean);
  const started = p.statusModule?.startDateStruct?.date ?? "";
  const updated = p.statusModule?.lastUpdatePostDateStruct?.date ?? started;
  const facts = [
    `Status: ${status.toLowerCase().replace(/_/g, " ") || "unknown"}`,
    phases.length ? `phase: ${phases.join("/").toLowerCase().replace(/_/g, " ")}` : "",
    enrollment ? `${enrollment} participants` : "",
    conditions.length ? `conditions: ${conditions.slice(0, 3).join(", ")}` : "",
    interventions.length ? `interventions: ${interventions.slice(0, 3).join(", ")}` : "",
    started ? `started ${started}` : "",
  ].filter(Boolean).join("; ");
  return {
    kind: "trial",
    title: clip(p.identificationModule?.briefTitle ?? id ?? "Clinical trial", 200),
    text: clip(`${facts}. ${p.descriptionModule?.briefSummary ?? ""}`.trim(), 900),
    status, phases, enrollment, has_results: Boolean(s.hasResults),
    date: updated, year: String(updated).slice(0, 4),
    url: id ? `https://clinicaltrials.gov/study/${id}` : "https://clinicaltrials.gov",
    source: "ClinicalTrials.gov",
  };
}

// term: free-text keywords from the question; condition / intervention narrow it when known.
export async function searchTrials({ term, condition, intervention, max = 6 }) {
  const run = (params) => getJSON(`https://clinicaltrials.gov/api/v2/studies?${qs({ ...params, pageSize: max, fields: FIELDS })}`);
  let data = await run({ "query.term": term, "query.cond": condition, "query.intr": intervention });
  // Too narrow (e.g. herb + condition has no registered trial)? Retry on the condition or keywords alone.
  if (!(data?.studies ?? []).length && (intervention || term)) data = await run(condition ? { "query.cond": condition } : { "query.term": term });
  return (data?.studies ?? []).map(toItem);
}
