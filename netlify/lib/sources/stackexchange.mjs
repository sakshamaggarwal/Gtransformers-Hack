// Health Stack Exchange (health.stackexchange.com): moderated Q&A where answers
// are expected to cite sources. Free; 300 requests/day per IP without a key,
// 10,000/day with STACKEXCHANGE_KEY (register at https://stackapps.com/apps/oauth/register).
// Docs: https://api.stackexchange.com/docs
import { getJSON, qs, stripHtml, clip } from "./http.mjs";
import { trustScore } from "../trust.mjs";

const BASE = "https://api.stackexchange.com/2.3";

export async function searchHealthSE(query, { max = 3, key } = {}) {
  const k = key ? { key } : {};
  const qs1 = await getJSON(`${BASE}/search/advanced?${qs({ site: "health", q: query, sort: "relevance", order: "desc", answers: 1, pagesize: 5, filter: "withbody", ...k })}`);
  const questions = (qs1?.items ?? []).slice(0, max);
  if (!questions.length) return [];
  const ans = await getJSON(`${BASE}/questions/${questions.map((q) => q.question_id).join(";")}/answers?${qs({ site: "health", sort: "votes", order: "desc", pagesize: 20, filter: "withbody", ...k })}`);
  const best = {};
  for (const a of ans?.items ?? []) {
    const cur = best[a.question_id];
    if (!cur || a.is_accepted || (!cur.is_accepted && a.score > cur.score)) best[a.question_id] = a;
  }
  return questions.filter((q) => best[q.question_id]).map((q) => {
    const a = best[q.question_id];
    const text = clip(stripHtml(a.body), 700);
    const t = trustScore({
      text, author: a.owner?.display_name ?? "", upvotes: Math.max(a.score, 0), downvotes: Math.max(-a.score, 0),
      accepted: a.is_accepted, reputation: a.owner?.reputation ?? 0, moderated: true,
    });
    return {
      kind: "community", source: "Health Stack Exchange", title: clip(stripHtml(q.title), 160), text,
      author: a.owner?.display_name ?? "anonymous", trust: t.score, label: t.label, signals: t.signals,
      url: q.link, upvotes: a.score,
    };
  }).filter((x) => x.label !== "rejected");
}
