#!/usr/bin/env python3
"""
Download posts from a subreddit, with each post's full comment tree, as
hierarchical JSON (each comment has a "replies" list).

Needs Reddit Data API credentials (an approved "script" app). Put them in
environment variables:
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
e.g. REDDIT_USER_AGENT="comment-export/1.0 by u/your_username"

Usage:
    pip install praw
    python reddit_sub_to_json.py Supplements -o supplements.json --limit 200 --sort new

Notes:
  * Reddit listings (new/hot/top) return at most ~1000 posts, so you can't
    page back through a sub's entire history this way.
  * replace_more(limit=None) expands every "load more comments" link. That
    costs one API request per link, so big threads are slow. PRAW waits out
    rate limits for you automatically.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import praw


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def comment_to_dict(c):
    return {
        "id": c.id,
        "author": str(c.author) if c.author else "[deleted]",
        "created_utc": iso(c.created_utc),
        "score": c.score,
        "text": c.body,
        "permalink": "https://www.reddit.com" + c.permalink,
        "replies": [comment_to_dict(r) for r in c.replies],
    }


def post_to_dict(s, more_limit):
    # Expand all "load more comments" stubs so the tree is complete.
    s.comments.replace_more(limit=more_limit)
    return {
        "id": s.id,
        "title": s.title,
        "author": str(s.author) if s.author else "[deleted]",
        "created_utc": iso(s.created_utc),
        "score": s.score,
        "upvote_ratio": s.upvote_ratio,
        "num_comments": s.num_comments,
        "flair": s.link_flair_text,
        "url": s.url,
        "permalink": "https://www.reddit.com" + s.permalink,
        "text": s.selftext,
        "comments": [comment_to_dict(c) for c in s.comments],  # top-level only; replies nest
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subreddit", help="name without r/, e.g. Supplements")
    ap.add_argument("-o", "--output", default=None, help="output JSON (default: <sub>.json)")
    ap.add_argument("--sort", choices=["new", "hot", "top"], default="new")
    ap.add_argument("--time", default="all",
                    help="time filter for --sort top: hour/day/week/month/year/all")
    ap.add_argument("--limit", type=int, default=None,
                    help="max posts (default: as many as Reddit returns, ~1000)")
    ap.add_argument("--more-limit", type=int, default=None,
                    help="cap on 'load more' expansions per post (default: expand all)")
    args = ap.parse_args()

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
    )  # read-only mode: no username/password needed

    sub = reddit.subreddit(args.subreddit)
    if args.sort == "top":
        listing = sub.top(time_filter=args.time, limit=args.limit)
    else:
        listing = getattr(sub, args.sort)(limit=args.limit)

    posts = []
    out_path = args.output or f"{args.subreddit}.json"
    for i, s in enumerate(listing, 1):
        posts.append(post_to_dict(s, args.more_limit))
        print(f"[{i}] {s.num_comments:>5} comments  {s.title[:70]}", file=sys.stderr)
        if i % 25 == 0:  # save progress periodically in case of interruption
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({"subreddit": args.subreddit, "posts": posts}, f,
                          ensure_ascii=False, indent=2)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"subreddit": args.subreddit, "posts": posts}, f,
                  ensure_ascii=False, indent=2)
    print(f"Saved {len(posts)} posts to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
