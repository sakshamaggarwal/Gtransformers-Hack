// =============================================================================
// netlify/lib/structure.mjs: structured answer for rich front ends
// =============================================================================
// /api/chat keeps the starter-kit fields (reply, behavior, flags, context) and
// ALSO returns this structured shape, used by the Vaidya Pulse front end:
//   { summary, clinical[{text,cites}], ayurvedic[{herb,sanskrit,use,evidence,evidence_label,caution,cites}],
//     community[{text,who,cites}], safety[{text,cites}], redFlags[], sources[...], crisis }
//   sources[]: { id, src, title, snippet, meta, url, trust, rank, score{total,relevance,trust,recency,engagement,credibility}, why }
//     ranked top 10 first (rank 1..10), then unranked reference facts (rank null)
// Sections come from the model's reply headings; ayurvedic cards and sources
// come straight from the evidence, so they never depend on the model's wording.
// =============================================================================

import { URGENT_NOTE } from "./checks.mjs";

const HEAD = {
  summary: /^summary:/i, clinical: /^what (the )?research says:/i, community: /^what (the )?community reports:/i,
  ayurvedic: /^ayurvedic perspective:/i, safety: /^safety:/i,
};
const SRC = { pubmed: "pubmed", trial: "ctgov", fda: "openfda", ayurveda: "ayur", clinical: "nih" };

// One evidence vocabulary shared with the front end's badges:
//   moderate | limited | traditional | caution   (the KB's longer wording stays in evidence_label)
export function evidenceLevel(raw) {
  const e = String(raw ?? "").toLowerCase();
  if (/safety|warning|not supported|caution|prescription/.test(e)) return "caution";
  if (/moderate/.test(e)) return "moderate";
  if (/limited/.test(e)) return "limited";
  return "traditional";
}
const cites = (s) => [...new Set([...s.matchAll(/\[([A-Z]\d+)\]/g)].map((m) => m[1]))];
const sentences = (s) => s.split(/(?<=[.!?]|\])\s+(?=[A-Z"(])/).map((x) => x.trim()).filter(Boolean);

function sections(reply) {
  const out = { summary: "", clinical: [], community: [], ayurvedic: [], safety: [] };
  let cur = "summary";
  for (const raw of reply.replace(URGENT_NOTE, "").split(/\n+/)) {
    let line = raw.trim();
    if (!line) continue;
    const hit = Object.entries(HEAD).find(([, re]) => re.test(line));
    if (hit) { cur = hit[0]; line = line.replace(hit[1], "").trim(); }
    if (!line) continue;
    if (cur === "summary") out.summary = (out.summary + " " + line).trim();
    else out[cur].push(...sentences(line.replace(/^[-•*]\s*/, "")));
  }
  return out;
}

function srcOf(x) {
  if (x.kind !== "community") return SRC[x.kind] ?? x.kind;
  if (x.synthetic || x.platform === "demo") return "community"; // bundled demo samples, never labelled as a real site
  if (x.platform === "reddit" || /reddit/i.test(x.source ?? "")) return "reddit";
  if (x.platform === "hse" || /stack ?exchange/i.test(x.source ?? "")) return "hse";
  return "community";
}

function sourceFor(x) {
  const src = srcOf(x);
  const engagement = x.kind === "community"
    ? [x.upvotes != null ? `${x.upvotes} ${x.platform === "hse" ? "score" : "upvotes"}` : "", x.comments ? `${x.comments} ${x.platform === "hse" ? "answers" : "comments"}` : "", x.accepted ? "accepted answer" : "", x.flair ? `flair: ${x.flair}` : ""]
    : [x.status ? String(x.status).toLowerCase().replace(/_/g, " ") : "", x.enrollment ? `N=${x.enrollment}` : "", (x.pubtypes ?? []).filter((p) => p !== "Journal Article").slice(0, 2).join(", ")];
  const meta = [x.source, x.journal, x.date || x.year, ...engagement, x.evidence ? `evidence: ${x.evidence}` : ""].filter(Boolean).join(" · ");
  return {
    id: x.id, src, title: x.title, snippet: (x.text ?? "").slice(0, 320), meta, url: x.url ?? "", trust: x.trust ?? null,
    rank: x.rank ?? null, score: x.score ?? null, why: x.why ?? "", author: x.author ?? "", date: x.date || x.year || "",
    ...(x.synthetic && { synthetic: true }),
  };
}

export function toStructured({ reply, behavior, evidence, flags }) {
  const s = sections(reply);
  const byId = Object.fromEntries((evidence?.sources ?? []).map((x) => [x.id, x]));
  const authorOf = (ids) => ids.map((id) => byId[id]).filter((x) => x?.kind === "community")
    .map((x) => [x.source, x.author, x.upvotes != null ? `${x.upvotes} ${x.platform === "hse" ? "score" : "upvotes"}` : "", x.accepted ? "accepted answer" : ""].filter(Boolean).join(" · ")).join("; ");

  // Ayurvedic cards: entries the model cited, else the top retrieved ones.
  const citedA = cites(reply).filter((id) => id.startsWith("A"));
  const ayur = (evidence?.ayurveda ?? []).filter((a) => !citedA.length || citedA.includes(a.id)).slice(0, 3);

  return {
    summary: s.summary || (behavior === "ANSWER" ? "" : reply),
    clinical: s.clinical.map((text) => ({ text, cites: cites(text) })),
    ayurvedic: ayur.map((a) => {
      const m = a.name.match(/^(.*?)\s*\((.*?)\)/);
      return { herb: m ? m[1] : a.name, sanskrit: m ? m[2] : "", use: `${a.tradition} ${a.how_used}`, evidence: evidenceLevel(a.evidence), evidence_label: a.evidence, caution: a.cautions, cites: [a.id] };
    }),
    community: s.community.map((text) => ({ text, who: authorOf(cites(text)), cites: cites(text) })),
    safety: s.safety.map((text) => ({ text, cites: cites(text) })),
    redFlags: flags?.red_flag ? [URGENT_NOTE] : [],
    sources: (evidence?.sources ?? []).map(sourceFor),
    crisis: behavior === "CARE",
  };
}
