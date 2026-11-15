#!/usr/bin/env python3
"""
Convert a saved Washington Post comments list (HTML) into hierarchical JSON.

Each comment is an <article data-comment-id="...">. Its replies are in a
<section aria-label="Replies to comment"> placed right after the article
(as a sibling of the article, or of one of the article's wrappers). So a
section's owner is the closest comment article that comes before it
at the same nesting level.

Usage:
    python wapo_comments_to_json.py wparticlefullcomments.txt -o comments.json

Requires: beautifulsoup4 (lxml is used for speed if installed).
"""
import argparse
import json
import re
import sys

from bs4 import BeautifulSoup, Tag


def is_comment(tag):
    return isinstance(tag, Tag) and tag.name == "article" and tag.has_attr("data-comment-id")


def is_reply_section(tag):
    return (isinstance(tag, Tag) and tag.name == "section"
            and tag.get("aria-label") == "Replies to comment")


def section_owner(section):
    """Find the comment article a replies section belongs to."""
    node = section
    while node is not None and node.name not in ("ol", "body", "[document]"):
        for sib in node.find_previous_siblings():
            if is_comment(sib):
                return sib
            nested = sib.find(is_comment) if isinstance(sib, Tag) else None
            if nested is not None and not sib.find(is_reply_section):
                return nested
        node = node.parent
    return None


def to_int(text):
    m = re.search(r"-?\d[\d,]*", text or "")
    return int(m.group().replace(",", "")) if m else 0


def parse_comment(art):
    label = art.get("aria-label", "")
    kind, _, author_label = label.partition(" by ")

    header = art.find("div", class_="wpds-c-fIaqhA") or art
    time_el = header.find("time")
    author_el = time_el.find_previous_sibling() if time_el else None
    author = author_el.get_text(strip=True) if author_el else author_label or None

    paragraphs = [p.get_text().strip() for p in art.find_all("p", class_="nodeToHtml")]
    text = "\n\n".join(p for p in paragraphs if p)

    upvote = art.find("button", attrs={"aria-label": "Upvote"})
    score_el = upvote.find_next_sibling("span") if upvote else None
    score = to_int(score_el.get_text()) if score_el else 0

    reactions_btn = art.find("button", attrs={"aria-label": re.compile(r"^Reactions, \d+ total")})
    reactions = to_int(reactions_btn["aria-label"]) if reactions_btn else 0

    collapse = art.find("button", attrs={"aria-label": re.compile(r"^Collapse \d+ repl")})
    reply_count = to_int(collapse["aria-label"]) if collapse else 0

    return {
        "id": art["data-comment-id"],
        "author": author,
        "posted_at": time_el.get("datetime") if time_el else None,
        "posted_relative": time_el.get_text(strip=True) if time_el else None,
        "text": text,
        "vote_score": score,
        "reactions": reactions,
        "reply_count_shown": reply_count,  # from the "Collapse N replies" button
        "is_reply": kind.strip().lower() == "reply",
        "replies": [],
    }


def build_tree(html):
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # lxml not installed
        soup = BeautifulSoup(html, "html.parser")

    roots, by_id = [], {}
    # Document order guarantees a parent is parsed before its replies.
    for art in soup.find_all(is_comment):
        comment = parse_comment(art)
        by_id[comment["id"]] = comment

        section = art.find_parent(is_reply_section)
        owner = section_owner(section) if section is not None else None
        parent = by_id.get(owner["data-comment-id"]) if owner is not None else None
        (parent["replies"] if parent else roots).append(comment)
    return roots


def walk(comments, depth=0):
    for c in comments:
        yield depth, c
        yield from walk(c["replies"], depth + 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="saved HTML of the Washington Post comments list")
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

    flat = list(walk(tree))
    missing = sum(max(0, c["reply_count_shown"] - len(c["replies"])) for _, c in flat)
    print(f"{len(tree)} top-level comments, {len(flat)} total, "
          f"max reply depth {max((d for d, _ in flat), default=0)}"
          + (f"; {missing} replies not loaded in the saved page" if missing else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()
