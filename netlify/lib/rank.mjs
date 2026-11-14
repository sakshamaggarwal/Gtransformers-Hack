// =============================================================================
// netlify/lib/rank.mjs: score every fetched item and keep the 10 best
// =============================================================================
// Every candidate from the 6 sources (PubMed, ClinicalTrials.gov, OpenFDA,
// Health Stack Exchange, Reddit, Ayurvedic KB) gets five explainable 0..1 scores:
//
//   relevance    how well title + text match the question (IDF-weighted terms,
//                topic synonyms, and the API's own relevance order)
//   trust        source authority tier x quality inside that source
//                (meta-analysis > RCT > review; completed trial > recruiting;
//                accepted answer; scam / promo / risky-dose language penalised)
//   recency      exponential decay, half-life per source (papers age slower than posts)
//   engagement   upvotes, comments, awards, answer score, views, trial enrollment
//   credibility  author signals: MD / PhD / RN / BAMS / "Physician" flair,
//                Stack Exchange reputation, accepted answer
//
//   total = 0.38 relevance + 0.25 trust + 0.15 credibility + 0.12 recency + 0.10 engagement
//
// Items below MIN_RELEVANCE, or rejected by the community trust filter (scams,
// promotions, "stop your meds"), are dropped. The top 10 are then picked with
// a SOURCE DIVERSITY rule: the best item of every source that has a relevant
// one goes in first, no source gets more than 3 slots (2 for FDA data and the
// local KB), and near-duplicate
// titles are skipped. Every score is returned so the UI can show WHY.
// =============================================================================

import { trustScore, authorIsClinician } from "./trust.mjs";

export const WEIGHTS = { relevance: 0.38, trust: 0.25, credibility: 0.15, recency: 0.12, engagement: 0.10 };
export const TIER = { pubmed: 1.0, trial: 0.85, fda: 0.8, ayurveda: 0.65, hse: 0.6, reddit: 0.4 };
const HALF_LIFE_YEARS = { pubmed: 6, trial: 5, fda: 4, hse: 4, reddit: 2 };
export const MIN_RELEVANCE = 0.2;
export const TOP_K = 10;
export const MAX_PER_SOURCE = 3;
// Safety data and the local KB support the answer but are not "posts": 2 slots each.
const SOURCE_CAP = { fda: 2, ayurveda: 2 };

const clamp = (x) => Math.max(0, Math.min(1, x));
const r2 = (x) => Math.round(x * 100) / 100;

// ---- text ---------------------------------------------------------------------
const STOP = new Set(("a an and are as at be but by can do does for from has have how i in is it its of on or so that the this to was what when where which who will with you your my me im should could would any there their them they about get some more most much very really just " +
  "increase improve improving reduce lower raise boost help helps natural naturally way ways best take taking good bad safe tips need want know").split(" "));
const stem = (w) => (w.length > 4 ? w.replace(/(ing|ies|ed|es|s)$/, "") : w);
export const tokenize = (s) => (String(s).toLowerCase().match(/[a-z0-9]+/g) ?? []).map(stem).filter((w) => w.length > 1 && !STOP.has(w));

// A few everyday synonyms the topic taxonomy may not cover.
const SYNONYMS = { rbc: ["red blood cell", "erythrocyte", "hemoglobin", "anemia"], hb: ["hemoglobin"], bp: ["blood pressure", "hypertension"],
  sugar: ["glucose", "diabetes"], gut: ["digestion", "bowel"], bloat: ["bloating", "flatulence"], sleep: ["insomnia"], stress: ["anxiety", "cortisol"],
  cholesterol: ["ldl", "lipid"], joint: ["arthritis"], amla: ["amalaki", "emblica"], turmeric: ["curcumin"], ashwagandha: ["withania"] };

export function bucketOf(it) {
  if (it.kind === "community") return it.platform ?? (/reddit/i.test(it.source ?? "") ? "reddit" : "hse");
  return it.kind; // pubmed | trial | fda | ayurveda
}

// ---- the five scores ------------------------------------------------------------
function relevance(it, core, expansion, idf) {
  const title = new Set(tokenize(it.title));
  const body = new Set(tokenize(`${it.text ?? ""} ${(it.pubtypes ?? []).join(" ")}`));
  let got = 0, max = 0;
  for (const t of core) { const w = idf(t); max += w; got += title.has(t) ? w : body.has(t) ? 0.7 * w : 0; }
  const coreScore = max ? got / max : 0;
  const expHits = expansion.filter((t) => title.has(t) || body.has(t)).length;
  const expScore = Math.min(1, expHits / 3);
  const apiPos = it._pos != null && it._n ? 1 - it._pos / it._n : 0.5; // the API's own relevance order
  let rel = core.length ? 0.65 * coreScore + 0.2 * expScore + 0.15 * apiPos : 0.8 * expScore + 0.2 * apiPos;
  if (it.kind === "fda" && it.planned) rel = Math.max(rel, 0.4);      // fetched for this question's herb / medicine
  if (it.kind === "ayurveda" && it.planned) rel = Math.max(rel, 0.35); // topic match in the curated KB
  return clamp(rel);
}

function quality(it, b) {
  const pt = (it.pubtypes ?? []).join(" ").toLowerCase();
  if (b === "pubmed") return /meta-analysis|systematic review/.test(pt) ? 1 : /randomized controlled/.test(pt) ? 0.95 : /clinical trial/.test(pt) ? 0.88 : /review/.test(pt) ? 0.82 : 0.7;
  if (b === "trial") {
    const s = String(it.status).toUpperCase();
    let q = it.has_results ? 1 : s === "COMPLETED" ? 0.9 : /RECRUITING|ACTIVE|ENROLLING/.test(s) ? 0.78 : /TERMINATED|WITHDRAWN|SUSPENDED/.test(s) ? 0.5 : 0.7;
    if ((it.phases ?? []).some((p) => /3|4/.test(p))) q = Math.min(1, q + 0.05);
    return q;
  }
  if (b === "fda") return it.subtype === "label" ? 1 : it.subtype === "recall" ? 0.9 : 0.85;
  if (b === "ayurveda") { const e = String(it.evidence).toLowerCase(); return /safety/.test(e) ? 0.9 : /moderate/.test(e) ? 0.85 : /limited/.test(e) ? 0.65 : /not supported/.test(e) ? 0.45 : 0.6; }
  return null; // community: computed from content
}

function recency(it, b, now) {
  if (b === "ayurveda") return 0.6; // curated, timeless reference
  const t = Date.parse(it.date || (it.year ? `${it.year}-07-01` : ""));
  if (!Number.isFinite(t)) return 0.5;
  const years = Math.max(0, (now - t) / (365.25 * 864e5));
  return 0.5 ** (years / HALF_LIFE_YEARS[b]);
}

function engagement(it, b) {
  const lg = (x, top) => Math.log10(1 + Math.max(0, x ?? 0)) / Math.log10(1 + top);
  if (b === "reddit") {
    let e = 0.7 * lg(it.upvotes, 2000) + 0.2 * lg(it.comments, 500) + (it.awards > 0 ? 0.1 : 0);
    if (it.upvote_ratio != null && it.upvote_ratio < 0.6) e *= 0.6; // controversial
    return clamp(e);
  }
  if (b === "hse") return clamp(0.6 * lg(it.upvotes, 100) + (it.accepted ? 0.25 : 0) + 0.15 * lg(it.views, 100000));
  if (b === "trial") return clamp(lg(it.enrollment, 5000));
  if (b === "fda") return it.reports ? clamp(lg(it.reports, 10000)) : 0.6;
  return 0.5; // PubMed (no citation counts in E-utilities) and the curated KB: neutral
}

function credibility(it, b) {
  if (b === "pubmed") return 0.9;
  if (b === "trial") return 0.85;
  if (b === "fda") return 0.95;
  if (b === "ayurveda") return 0.7;
  let c = 0.25;
  const who = `${it.author ?? ""} ${it.flair ?? ""}`;
  if (authorIsClinician(who) || /\b(physician|doctor|nurse|pharmacist|dietitian|nutritionist|phd|m\.?d\.?|bams)\b/i.test(it.flair ?? "")) c += 0.55;
  else if (it.flair) c += 0.05;
  if ((it.reputation ?? 0) >= 10000) c += 0.3; else if ((it.reputation ?? 0) >= 1000) c += 0.2;
  if (it.accepted) c += 0.1;
  return clamp(c);
}

// ---- score one candidate --------------------------------------------------------
export function scoreItem(it, ctx) {
  const b = bucketOf(it);
  let q = quality(it, b), signals = [];
  if (q == null) {
    // Community content check (scam / promo / risky dosing / evidence-aligned / cites a source).
    // Engagement and author are scored separately below, so they are left out here.
    const t = trustScore({ text: it.text, accepted: it.accepted, moderated: b === "hse" });
    if (t.label === "rejected") return null;
    q = t.score / 100;
    signals = t.signals;
  }
  const s = {
    relevance: relevance(it, ctx.core, ctx.expansion, ctx.idf),
    trust: TIER[b] * q,
    recency: recency(it, b, ctx.now),
    engagement: engagement(it, b),
    credibility: credibility(it, b),
  };
  if (s.relevance < MIN_RELEVANCE) return null;
  const total = Object.entries(WEIGHTS).reduce((n, [k, w]) => n + w * s[k], 0);
  return {
    ...it, bucket: b, signals: it.signals ?? signals,
    trust: Math.round(100 * (0.7 * s.trust + 0.3 * s.credibility)), // 0-100 shown on the source card
    score: { total: r2(total), ...Object.fromEntries(Object.entries(s).map(([k, v]) => [k, r2(v)])) },
    why: explain(s, it, b),
  };
}

function explain(s, it, b) {
  const out = [];
  if (s.relevance >= 0.6) out.push("strong match to your question");
  if (b === "pubmed") out.push(...(it.pubtypes ?? []).filter((p) => /meta|systematic|randomized|review|trial/i.test(p)).slice(0, 1).map((p) => p.toLowerCase()));
  if (b === "trial") out.push(`trial ${String(it.status).toLowerCase().replace(/_/g, " ")}${it.has_results ? " with results" : ""}`);
  if (b === "fda") out.push("official FDA data");
  if (b === "ayurveda") out.push(`curated Ayurveda entry (evidence: ${it.evidence})`);
  if (s.credibility >= 0.7 && (b === "reddit" || b === "hse")) out.push("clinician / expert author");
  if (it.accepted) out.push("accepted answer");
  if (b === "reddit" && it.upvotes >= 50) out.push(`${it.upvotes} upvotes`);
  if (s.recency >= 0.8 && b !== "ayurveda") out.push("recent");
  return out.join(" · ");
}

// ---- rank + diversify ---------------------------------------------------------------
const jaccard = (a, b) => { const A = new Set(tokenize(a)), B = new Set(tokenize(b)); const i = [...A].filter((x) => B.has(x)).length; return i / Math.max(1, A.size + B.size - i); };

// candidates: items from all sources (each may carry _pos/_n = its position in its API's result list)
// query: { question, expansion: [strings] }
export function rankEvidence(candidates, { question, expansion = [] }, { k = TOP_K, maxPerSource = MAX_PER_SOURCE, now = Date.now() } = {}) {
  const core = [...new Set(tokenize(question))];
  const syn = core.flatMap((t) => SYNONYMS[t] ?? []);
  const exp = [...new Set(tokenize([...expansion, ...syn].join(" ")))].filter((t) => !core.includes(t));
  const docs = candidates.map((c) => new Set(tokenize(`${c.title} ${c.text ?? ""}`)));
  const idf = (t) => Math.log(1 + (docs.length + 1) / (1 + docs.filter((d) => d.has(t)).length));

  const scored = candidates.map((c) => scoreItem(c, { core, expansion: exp, idf, now })).filter(Boolean)
    .sort((a, b) => b.score.total - a.score.total);

  const picked = [], count = {};
  const tryAdd = (it, cap, strict = true) => {
    const limit = strict ? Math.min(cap, SOURCE_CAP[it.bucket] ?? cap) : cap;
    if (picked.length >= k || picked.includes(it) || (count[it.bucket] ?? 0) >= limit) return;
    if (picked.some((p) => jaccard(p.title, it.title) >= 0.6)) return; // near-duplicate
    picked.push(it); count[it.bucket] = (count[it.bucket] ?? 0) + 1;
  };
  // 1) diversity: the best item from every source that has a relevant one
  for (const b of [...new Set(scored.map((x) => x.bucket))]) tryAdd(scored.find((x) => x.bucket === b), maxPerSource);
  // 2) fill by score, max `maxPerSource` per source; 3) relax the cap if sources are thin
  for (const it of scored) tryAdd(it, maxPerSource);
  for (const it of scored) tryAdd(it, k, false);

  const top = picked.sort((a, b) => b.score.total - a.score.total).map((it, i) => ({ ...it, rank: i + 1 }));
  const per_source = {};
  for (const c of candidates) { const b = bucketOf(c); per_source[b] ??= { fetched: 0, eligible: 0, kept: 0 }; per_source[b].fetched++; }
  for (const s of scored) per_source[s.bucket].eligible++;
  for (const t of top) per_source[t.bucket].kept++;
  return { top, per_source, candidates: candidates.length, eligible: scored.length, weights: WEIGHTS };
}
