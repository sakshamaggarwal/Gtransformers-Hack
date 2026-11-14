// ClinicalTrials.gov API v2: active and completed trials. Free, no key.
// Docs: https://clinicaltrials.gov/data-api/api
import { getJSON, qs, clip } from "./http.mjs";

export async function searchTrials({ condition, intervention, max = 3 }) {
  const data = await getJSON(`https://clinicaltrials.gov/api/v2/studies?${qs({
    "query.cond": condition, "query.intr": intervention, pageSize: max, sort: "LastUpdatePostDate:desc",
    fields: "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName,EnrollmentCount,StartDate",
  })}`);
  return (data?.studies ?? []).map((s) => {
    const p = s.protocolSection ?? {};
    const id = p.identificationModule?.nctId;
    return {
      kind: "trial",
      title: clip(p.identificationModule?.briefTitle ?? id ?? "Clinical trial", 200),
      text: [
        `Status: ${(p.statusModule?.overallStatus ?? "unknown").toLowerCase().replace(/_/g, " ")}`,
        p.designModule?.phases?.length ? `phase: ${p.designModule.phases.join("/").toLowerCase().replace(/_/g, " ")}` : "",
        p.designModule?.enrollmentInfo?.count ? `${p.designModule.enrollmentInfo.count} participants` : "",
        p.conditionsModule?.conditions?.length ? `conditions: ${p.conditionsModule.conditions.slice(0, 3).join(", ")}` : "",
        p.statusModule?.startDateStruct?.date ? `started ${p.statusModule.startDateStruct.date}` : "",
      ].filter(Boolean).join("; ") + ".",
      status: p.statusModule?.overallStatus ?? "",
      url: id ? `https://clinicaltrials.gov/study/${id}` : "https://clinicaltrials.gov",
      source: "ClinicalTrials.gov",
    };
  });
}
