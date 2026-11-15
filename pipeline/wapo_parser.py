"""
Washington Post comment parser.

WaPo loads comments with JavaScript, so save the comments section of an
article as HTML first (browser: open comments, right click > Save Page As,
or copy the comments <ul> outerHTML), then run:

    python pipeline/wapo_parser.py data/raw/wapo/my_article.html \
        --url "https://www.washingtonpost.com/..." \
        --out data/raw/wapo/my_article.json

Output: a JSON object {"source": "wapo", "url": ..., "threads": [...]}
where each thread is a top-level comment with its replies.
"""

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


def extract_comment(article):
    """Extract one comment or reply <article> into a dict."""
    aria_label = article.get("aria-label", "")
    author = re.sub(r"^(Comment|Reply) by\s+", "", aria_label)

    time_element = article.select_one("time[datetime]")
    text_element = article.select_one("p.nodeToHtml")

    upvotes = downvotes = 0
    for button in article.select("button[aria-label]"):
        label = button.get("aria-label", "")
        if label in ("Upvote", "Downvote"):
            count_element = button.find_next_sibling("span")
            try:
                count = int(count_element.get_text(strip=True)) if count_element else 0
            except ValueError:
                count = 0
            if label == "Upvote":
                upvotes = count
            else:
                downvotes = count

    reactions = 0
    for button in article.select('button[aria-label^="Reactions"]'):
        match = re.search(r"(\d+)\s+total", button.get("aria-label", ""))
        if match:
            reactions += int(match.group(1))

    return {
        "id": article.get("data-comment-id"),
        "author": author,
        "timestamp": time_element.get("datetime") if time_element else None,
        "text": text_element.get_text(" ", strip=True) if text_element else "",
        "upvotes": upvotes,
        "downvotes": downvotes,
        "reactions": reactions,
    }


def extract_threads(html):
    """Return top-level comments, each with a `replies` list."""
    soup = BeautifulSoup(html, "html.parser")
    threads = []
    for li in soup.select("li.wpds-c-iIdhEv"):
        parent_article = li.select_one(":scope > article[data-comment-id]")
        if not parent_article:
            continue
        parent = extract_comment(parent_article)
        replies = []
        reply_section = li.select_one('section[aria-label="Replies to comment"]')
        if reply_section:
            replies = [extract_comment(a) for a in reply_section.select(":scope article[data-comment-id]")]
        parent["replies"] = replies
        threads.append(parent)
    return threads


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html", help="saved WaPo comments HTML file")
    ap.add_argument("--url", default="", help="article URL, kept for source attribution")
    ap.add_argument("--title", default="", help="article title")
    ap.add_argument("--out", help="output JSON path (default: same name, .json)")
    args = ap.parse_args()

    src = Path(args.html)
    threads = extract_threads(src.read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else src.with_suffix(".json")
    payload = {"source": "wapo", "url": args.url, "title": args.title, "synthetic": False, "threads": threads}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    n_replies = sum(len(t["replies"]) for t in threads)
    print(f"Parsed {len(threads)} comments + {n_replies} replies -> {out}")


if __name__ == "__main__":
    main()
