// Health Stack Exchange (health.stackexchange.com): moderated Q&A where answers
// are expected to cite sources. Free; 300 requests/day per IP without a key,
// 10,000/day with STACKEXCHANGE_KEY (register at https://stackapps.com/apps/oauth/register).
// Docs: https://api.stackexchange.com/docs
import { getJSON, qs, stripHtml, clip } from "./http.mjs";

const BASE = "https://api.stackexchange.com/2.3";
const iso = (sec) => (sec ? new Date(sec * 1000).toISOString().slice(0, 10) : "");

export async function searchHealthSE(query, { max = 6, key } = {}) {
  const k = key ? { key } : {};
  const search = await getJSON(`${BASE}/search/advanced?${qs({ site: "health", q: query, sort: "relevance", order: "desc", answers: 1, pagesize: max, ...k })}`);
  const questions = (search?.items ?? []).slice(0, max);
  if (!questions.length) return [];
  const ans = await getJSON(`${BASE}/questions/${questions.map((q) => q.question_id).join(";")}/answers?${qs({ site: "health", sort: "votes", order: "desc", pagesize: 40, filter: "withbody", ...k })}`);
  const best = {};
  for (const a of ans?.items ?? []) {
    const cur = best[a.question_id];
    if (!cur || (a.is_accepted && !cur.is_accepted) || (a.is_accepted === cur.is_accepted && a.score > cur.score)) best[a.question_id] = a;
  }
  return questions.filter((q) => best[q.question_id]).map((q) => {
    const a = best[q.question_id];
    return {
      kind: "community", platform: "hse", source: "Health Stack Exchange",
      title: clip(stripHtml(q.title), 160),
      text: clip(stripHtml(a.body), 900),
      author: a.owner?.display_name ?? "anonymous",
      reputation: a.owner?.reputation ?? 0,
      upvotes: a.score, question_score: q.score ?? 0, views: q.view_count ?? 0, comments: q.answer_count ?? 0,
      accepted: Boolean(a.is_accepted),
      date: iso(a.last_edit_date ?? a.creation_date), year: iso(a.creation_date).slice(0, 4),
      url: a.answer_id ? `https://health.stackexchange.com/a/${a.answer_id}` : q.link,
    };
  });
}
