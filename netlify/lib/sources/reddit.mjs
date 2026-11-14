// Reddit, live: optional. Reddit blocks most unauthenticated cloud traffic, so
// the reliable path is the Python batch fetcher (pipeline/reddit_fetcher.py),
// whose output is built into netlify/lib/knowledge/community.mjs.
// If REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are set (a free "script" app at
// https://www.reddit.com/prefs/apps), we also search live via OAuth.
import { qs, stripHtml, clip, USER_AGENT } from "./http.mjs";
import { trustScore } from "../trust.mjs";

let token = null; // { value, exp }

async function getToken(id, secret) {
  if (token && token.exp > Date.now()) return token.value;
  const res = await fetch("https://www.reddit.com/api/v1/access_token", {
    method: "POST",
    headers: { authorization: "Basic " + btoa(`${id}:${secret}`), "content-type": "application/x-www-form-urlencoded", "user-agent": USER_AGENT },
    body: "grant_type=client_credentials",
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) throw new Error(`reddit auth ${res.status}`);
  const d = await res.json();
  token = { value: d.access_token, exp: Date.now() + (d.expires_in - 60) * 1000 };
  return token.value;
}

export async function searchReddit(query, { id, secret, subs = ["Anemia", "nutrition", "Ayurveda", "AskDocs"], max = 3 } = {}) {
  if (!id || !secret) return [];
  const t = await getToken(id, secret);
  const res = await fetch(`https://oauth.reddit.com/r/${subs.join("+")}/search?${qs({ q: query, restrict_sr: 1, sort: "relevance", t: "year", limit: 8 })}`, {
    headers: { authorization: `Bearer ${t}`, "user-agent": USER_AGENT }, signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) throw new Error(`reddit ${res.status}`);
  const d = await res.json();
  return (d?.data?.children ?? []).map((c) => c.data).map((p) => {
    const text = clip(stripHtml(`${p.title}. ${p.selftext ?? ""}`), 600);
    const tr = trustScore({ text, author: `${p.author} ${p.author_flair_text ?? ""}`, upvotes: Math.max(p.score, 0), downvotes: 0, reactions: p.num_comments });
    return { kind: "community", source: `Reddit r/${p.subreddit}`, title: clip(p.title, 160), text, author: p.author, trust: tr.score, label: tr.label, signals: tr.signals, url: `https://www.reddit.com${p.permalink}`, upvotes: p.score };
  }).filter((x) => x.label !== "rejected").sort((a, b) => b.trust - a.trust).slice(0, max);
}
