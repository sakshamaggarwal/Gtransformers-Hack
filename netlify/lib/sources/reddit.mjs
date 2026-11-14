// Reddit: live posts + their top comments.
//   No setup needed: uses Reddit's public JSON API (any reddit URL + ".json").
//   Optional: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (a free "script" app at
//   https://www.reddit.com/prefs/apps) switches to OAuth, which has higher rate
//   limits and is not blocked from cloud hosts (Reddit sometimes answers 403 to
//   unauthenticated requests from data-centre IPs such as Netlify).
// Posts and comments are returned raw; the ranker (rank.mjs) scores trust.
import { qs, stripHtml, clip, USER_AGENT } from "./http.mjs";

export const DEFAULT_SUBS = ["health", "Ayurveda", "nutrition", "Supplements", "medicine", "AskDocs"];
const TOPIC_SUBS = {
  anemia_rbc: ["Anemia"], blood_sugar: ["diabetes"], heart_cholesterol: ["Cholesterol", "hypertension"],
  digestion: ["ibs", "Gastritis"], sleep_stress: ["insomnia", "Anxiety"], joint_pain: ["Arthritis"],
  vitamin_d_bone: ["Osteoporosis"], immunity: [], supplements_general: [],
};

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

async function redditGet(path, params, auth) {
  const base = auth ? "https://oauth.reddit.com" : "https://www.reddit.com";
  const url = `${base}${path}${auth ? "" : ".json"}?${qs({ ...params, raw_json: 1 })}`;
  const res = await fetch(url, {
    headers: { "user-agent": USER_AGENT, accept: "application/json", ...(auth && { authorization: `Bearer ${auth}` }) },
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) throw new Error(`reddit ${res.status}`);
  return res.json();
}

const iso = (sec) => (sec ? new Date(sec * 1000).toISOString().slice(0, 10) : "");
const usable = (p) => p && !p.over_18 && !p.stickied && !["[removed]", "[deleted]"].includes(p.selftext ?? "") && p.author !== "[deleted]";

export function postToItem(p) {
  return {
    kind: "community", platform: "reddit", source: `Reddit r/${p.subreddit}`,
    title: clip(stripHtml(p.title ?? ""), 180),
    text: clip(stripHtml(`${p.title ?? ""}. ${p.selftext ?? ""}`), 900),
    author: p.author ?? "", flair: p.author_flair_text ?? "",
    upvotes: p.score ?? 0, comments: p.num_comments ?? 0, awards: p.total_awards_received ?? 0,
    upvote_ratio: p.upvote_ratio ?? null,
    date: iso(p.created_utc), year: iso(p.created_utc).slice(0, 4),
    url: `https://www.reddit.com${p.permalink}`,
  };
}

export function commentToItem(c, post) {
  return {
    kind: "community", platform: "reddit", source: `Reddit r/${post.subreddit} (comment)`,
    title: clip(`Reply on: ${stripHtml(post.title ?? "")}`, 180),
    text: clip(stripHtml(c.body ?? ""), 900),
    author: c.author ?? "", flair: c.author_flair_text ?? "",
    upvotes: c.score ?? 0, comments: 0, awards: c.total_awards_received ?? 0,
    date: iso(c.created_utc), year: iso(c.created_utc).slice(0, 4),
    url: `https://www.reddit.com${c.permalink ?? post.permalink}`,
  };
}

// query: keywords. Returns up to `max` posts plus the top comments of the best `withComments` posts.
export async function searchReddit(query, { id, secret, topic, max = 10, withComments = 3 } = {}) {
  const auth = id && secret ? await getToken(id, secret) : null;
  const subs = [...new Set([...DEFAULT_SUBS, ...(TOPIC_SUBS[topic] ?? [])])];
  const d = await redditGet(`/r/${subs.join("+")}/search`, { q: query, restrict_sr: 1, sort: "relevance", t: "all", limit: 25, type: "link" }, auth);
  const posts = (d?.data?.children ?? []).map((c) => c.data).filter(usable).slice(0, max);

  // Top comments: often where the useful (and physician-flaired) answers are.
  const top = [...posts].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, withComments);
  const threads = await Promise.allSettled(top.map((p) => redditGet(`/comments/${p.id}`, { sort: "top", limit: 6, depth: 1 }, auth)));
  const comments = [];
  threads.forEach((t, i) => {
    if (t.status !== "fulfilled") return;
    const list = (t.value?.[1]?.data?.children ?? []).filter((c) => c.kind === "t1").map((c) => c.data);
    list.filter((c) => usable(c) && (c.body ?? "").length > 80 && c.author !== "AutoModerator").slice(0, 2)
      .forEach((c) => comments.push(commentToItem(c, top[i])));
  });
  return [...posts.map(postToItem), ...comments];
}
