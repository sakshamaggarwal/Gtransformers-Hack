#!/usr/bin/env python3
"""
Convert a saved NYT comments panel (HTML) into hierarchical JSON.

Every comment is an element whose data-testid is "comment-container"
(top-level) or "reply-comment-container" (reply). Replies sit inside their
parent's element in the DOM, so a comment's parent is the closest
enclosing comment element.

Usage:
    python nyt_comments_to_json.py nytarticlecommentslist.txt -o comments.json

Requires: beautifulsoup4 (lxml is used for speed if installed).
"""
import argparse
import json
import re
import sys

from bs4 import BeautifulSoup

COMMENT_TESTIDS = {"comment-container", "reply-comment-container"}


def is_comment(tag):
    return getattr(tag, "name", None) and tag.get("data-testid") in COMMENT_TESTIDS


def first_own(node, *args, **kwargs):
    """Like node.find(), but skips matches inside nested reply comments."""
    for match in node.find_all(*args, **kwargs):
        owner = match.find_parent(is_comment)
        if owner is node:
            return match
    return None


def to_int(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def parse_comment(node):
    raw_id = node.get("id", "")
    comment_id = raw_id.replace("comment-container-", "") or None

    header = first_own(node, attrs={"data-testid": "user-header"})
    author = location = date = None
    if header:
        name_el = header.select_one("div.css-xrhnuy span") or header.find("span")
        # Fallback that doesn't rely on CSS class names: the hidden
        # "<name> commented <date>" label.
        if name_el:
            author = name_el.get_text(strip=True)
        subtitle = header.find(attrs={"data-testid": "user-header-subtitle"})
        if subtitle:
            date_el = subtitle.find(attrs={"data-testid": "todays-date"})
            if date_el:
                date = date_el.get("aria-label") or date_el.get_text(strip=True)
            # Location is the text before the "·" separator, if present.
            permalink = subtitle.find(attrs={"data-testid": "date-permalink"})
            loc_parts = []
            for child in subtitle.children:
                if child is permalink:
                    break
                loc_parts.append(child.get_text(" ", strip=True)
                                 if hasattr(child, "get_text") else str(child))
            loc = " ".join(loc_parts).replace("·", "").strip()
            location = loc or None

    if not author:
        label = first_own(node, "a", id=re.compile(r"^comment-description-"))
        if label:
            author = re.sub(r"\s+commented\s+.*$", "", label.get_text(strip=True))

    body_el = node.find(id=f"comment-content-{comment_id}") if comment_id else None
    text = body_el.get_text("\n").strip() if body_el else ""

    rec_btn = first_own(node, attrs={"data-testid": "recommend-button"})
    recommendations = 0
    if rec_btn:
        count_el = rec_btn.find(class_=re.compile(r"_count$"))
        recommendations = to_int(count_el.get_text() if count_el else "")

    share = first_own(node, attrs={"data-testid": "copy-link"})
    permalink_url = None
    if share and share.get("id", "").startswith("share-link-"):
        permalink_url = share["id"][len("share-link-"):]

    return {
        "id": comment_id,
        "author": author,
        "location": location,
        "date": date,
        "text": text,
        "recommendations": recommendations,
        "share_url": permalink_url,
        "replies": [],
    }


def build_tree(html):
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # lxml not installed
        soup = BeautifulSoup(html, "html.parser")

    roots = []
    by_node = {}
    # find_all returns elements in document order, so a parent is always
    # processed before its replies.
    for node in soup.find_all(is_comment):
        comment = parse_comment(node)
        by_node[id(node)] = comment
        parent = node.find_parent(is_comment)
        if parent is not None and id(parent) in by_node:
            by_node[id(parent)]["replies"].append(comment)
        else:
            roots.append(comment)
    return roots


def count(comments):
    return sum(1 + count(c["replies"]) for c in comments)


def max_depth(comments, d=1):
    return max((max_depth(c["replies"], d + 1) for c in comments), default=d - 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="saved HTML of the NYT comments list")
    ap.add_argument("-o", "--output", help="output JSON file (default: stdout)")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        tree = build_tree(f.read())

    out = json.dumps(tree, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)

    print(f"{len(tree)} top-level comments, {count(tree)} total, "
          f"max depth {max_depth(tree)}", file=sys.stderr)


if __name__ == "__main__":
    main()
