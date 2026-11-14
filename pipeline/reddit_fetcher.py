"""
Reddit fetcher: pull health posts + top comments from target subreddits.

Two modes:
  * OAuth via PRAW (recommended): create a free "script" app at
    https://www.reddit.com/prefs/apps, then
        pip install praw
        export REDDIT_CLIENT_ID=...  REDDIT_CLIENT_SECRET=...
    100 requests/minute, works from servers.
  * Public JSON (no key): light, read-only use; ~10 requests/minute and often
    blocked from cloud IPs, so the script sleeps between calls.

Run it on your own machine (cloud sandboxes often block reddit.com):

    python pipeline/reddit_fetcher.py --topic anemia_rbc --limit 10
    python pipeline/reddit_fetcher.py --query "low hemoglobin diet" --subs Anemia nutrition

Output: data/raw/reddit/<topic or query>.json in the same thread shape as the
WaPo parser, so build_kb.py treats both sources the same way.
"""

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from taxonomy import TOPICS

USER_AGENT = "community-health-intelligence/0.1 (hackathon research prototype)"
DEFAULT_SUBS = {
    "anemia_rbc": ["Anemia", "nutrition", "AskDocs", "Ayurveda"],
    "immunity": ["nutrition", "Ayurveda", "AskDocs"],
    "digestion": ["IBS", "nutrition", "Ayurveda", "GERD"],
    "sleep_stress": ["insomnia", "Ayurveda", "Supplements"],
    "blood_sugar": ["prediabetes", "diabetes", "nutrition"],
    "heart_cholesterol": ["Cholesterol", "nutrition", "AskDocs"],
    "joint_pain": ["Arthritis", "Ayurveda", "nutrition"],
    "vitamin_d_bone": ["Supplements", "nutrition", "Osteoporosis"],
}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "reddit"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def search(sub, query, limit):
    q = urllib.parse.urlencode({"q": query, "restrict_sr": 1, "sort": "top", "t": "year", "limit": limit})
    data = get_json(f"https://www.reddit.com/r/{sub}/search.json?{q}")
    return [c["data"] for c in data.get("data", {}).get("children", [])]


def top_comments(permalink, n=5):
    data = get_json(f"https://www.reddit.com{permalink}.json?sort=top&limit={n}")
    if len(data) < 2:
        return []
    out = []
    for c in data[1]["data"]["children"][:n]:
        d = c.get("data", {})
        if c.get("kind") != "t1" or not d.get("body") or d.get("body") in ("[deleted]", "[removed]"):
            continue
        out.append({
            "id": d["id"],
            "author": d.get("author", ""),
            "author_flair": d.get("author_flair_text") or "",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(d.get("created_utc", 0))),
            "text": d["body"],
            "upvotes": max(d.get("score", 0), 0),
            "downvotes": 0,
            "reactions": 0,
        })
    return out


def fetch_with_praw(query, subs, limit, n_comments):
    """OAuth path: same output shape as the public-JSON path."""
    import praw  # pip install praw

    reddit = praw.Reddit(client_id=os.environ["REDDIT_CLIENT_ID"], client_secret=os.environ["REDDIT_CLIENT_SECRET"],
                         user_agent=USER_AGENT)
    ts = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    threads = []
    for sub in subs:
        for p in reddit.subreddit(sub).search(query, sort="top", time_filter="year", limit=limit):
            p.comment_sort = "top"
            p.comments.replace_more(limit=0)
            replies = [{"id": c.id, "author": str(c.author or ""), "author_flair": c.author_flair_text or "",
                        "timestamp": ts(c.created_utc), "text": c.body, "upvotes": max(c.score, 0), "downvotes": 0,
                        "reactions": 0} for c in p.comments[:n_comments]]
            threads.append({"id": p.id, "author": str(p.author or ""), "author_flair": p.author_flair_text or "",
                            "timestamp": ts(p.created_utc), "text": f"{p.title}. {p.selftext}".strip(),
                            "upvotes": max(p.score, 0), "downvotes": 0, "reactions": p.num_comments,
                            "url": "https://www.reddit.com" + p.permalink, "subreddit": sub, "replies": replies})
        print(f"  r/{sub}: done ({len(threads)} posts so far)")
    return threads


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", choices=sorted(TOPICS), help="use the topic's keywords + default subreddits")
    ap.add_argument("--query", help="free-text search query")
    ap.add_argument("--subs", nargs="*", help="subreddits to search")
    ap.add_argument("--limit", type=int, default=8, help="posts per subreddit")
    ap.add_argument("--comments", type=int, default=5, help="top comments per post")
    ap.add_argument("--sleep", type=float, default=6.5, help="seconds between requests (stay under rate limit)")
    args = ap.parse_args()
    if not (args.topic or args.query):
        ap.error("give --topic or --query")

    query = args.query or " OR ".join(TOPICS[args.topic]["keywords"][:5])
    subs = args.subs or DEFAULT_SUBS.get(args.topic, ["nutrition", "Ayurveda"])
    if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"):
        print("Using PRAW (OAuth)")
        threads = fetch_with_praw(query, subs, args.limit, args.comments)
        subs = []  # skip the public-JSON loop
    else:
        print("Using public JSON (set REDDIT_CLIENT_ID/SECRET to use OAuth)")
        threads = []
    for sub in subs:
        try:
            posts = search(sub, query, args.limit)
        except Exception as e:  # network/rate-limit: keep going with other subs
            print(f"  r/{sub}: search failed ({e})")
            continue
        print(f"  r/{sub}: {len(posts)} posts")
        time.sleep(args.sleep)
        for p in posts:
            try:
                replies = top_comments(p["permalink"], args.comments)
            except Exception as e:
                print(f"    comments failed for {p['id']} ({e})")
                replies = []
            time.sleep(args.sleep)
            threads.append({
                "id": p["id"],
                "author": p.get("author", ""),
                "author_flair": p.get("author_flair_text") or "",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.get("created_utc", 0))),
                "text": (p.get("title", "") + ". " + (p.get("selftext") or "")).strip(),
                "upvotes": max(p.get("score", 0), 0),
                "downvotes": 0,
                "reactions": p.get("num_comments", 0),
                "url": "https://www.reddit.com" + p["permalink"],
                "subreddit": sub,
                "replies": replies,
            })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", (args.topic or args.query).lower()).strip("_")[:50]
    out = OUT_DIR / f"{slug}.json"
    payload = {"source": "reddit", "url": "", "title": f"Reddit search: {query}", "synthetic": False, "threads": threads}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(threads)} posts -> {out}")


if __name__ == "__main__":
    main()
