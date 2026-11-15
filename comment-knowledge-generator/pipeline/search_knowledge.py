#!/usr/bin/env python3
"""
Search knowledge.db (from publish_cards.py) from the command line.

    python search_knowledge.py omega-3 heart          # items mentioning both
    python search_knowledge.py "vitamin D" --any testing sunlight
    python search_knowledge.py fish oil --section advice --quotes
    python search_knowledge.py --cards dementia       # search card titles/takeaways

Each argument is one search term, matched as typed (hyphens and punctuation are
safe) with English stemming, so "test" also finds "testing" and "tested". An item
matches if its own text, its disagreement issue, or a comment it cites contains
the term. Quote words to search them as a phrase:
    python search_knowledge.py "vitamin D" --section advice    # the phrase "vitamin D"
    python search_knowledge.py vitamin D --section advice      # "vitamin" and "D" anywhere
"""
import argparse
import re
import sqlite3
import sys
import textwrap

SECTIONS = ["takeaway", "reported_experiences", "claims", "corrections", "disagreements",
            "open_questions", "advice"]


def fts_query(terms, any_mode):
    """Quote every term so FTS5 treats hyphens etc. as text, not query syntax."""
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms if t.strip()]
    return (" OR " if any_mode else " AND ").join(quoted)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("terms", nargs="+")
    ap.add_argument("--db", default="knowledge.db")
    ap.add_argument("--any", action="store_true", help="match any term instead of all")
    ap.add_argument("--section", choices=SECTIONS)
    ap.add_argument("--card", help="limit to one card id, e.g. T4")
    ap.add_argument("--cards", action="store_true", help="search card titles and takeaways")
    ap.add_argument("--quotes", action="store_true", help="show the quoted comments")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    q = fts_query(args.terms, args.any)
    wrap = lambda s, ind="    ": textwrap.fill(s, 100, initial_indent=ind, subsequent_indent=ind)

    if args.cards:
        rows = db.execute("SELECT card_id, title, takeaway FROM cards_fts WHERE cards_fts MATCH ? "
                          "ORDER BY rank LIMIT ?", (q, args.limit)).fetchall()
        for cid, title, take in rows:
            print(f"{cid}  {title}")
            if take:
                print(wrap(take))
        print(f"\n{len(rows)} card(s)", file=sys.stderr)
        return

    sql = ("SELECT v.item_id, v.card_id, v.card_title, v.section, v.issue, v.text, v.readers, "
           "v.health_risk FROM items_fts JOIN v_items v ON v.item_id = items_fts.rowid "
           "WHERE items_fts MATCH ?")
    params = [q]
    if args.section:
        sql += " AND v.section = ?"
        params.append(args.section)
    if args.card:
        sql += " AND v.card_id = ?"
        params.append(args.card)
    sql += " ORDER BY rank LIMIT ?"
    params.append(args.limit)
    rows = db.execute(sql, params).fetchall()
    terms = [t for t in args.terms if t.strip()]

    def in_text(text):
        """Does the item's own text contain every term (or any, with --any)?"""
        found = [re.search(r"\b" + r"\s+".join(map(re.escape, t.split())), text, re.I)
                 for t in terms]
        return any(found) if args.any else all(found)

    for item_id, cid, title, section, issue, text, readers, risk in rows:
        flag = {"high": "  [check with a doctor]", "caution": "  [unconfirmed]"}.get(risk, "")
        print(f"{cid} · {title} · {section.replace('_', ' ')} · "
              f"{readers} reader{'s' if readers != 1 else ''}{flag}")
        print(wrap((issue + " — " if issue else "") + text))
        if not in_text((issue or "") + " " + text):
            print("    (matched in a quoted comment)")
        if args.quotes or not in_text((issue or "") + " " + text):
            for fn, reader, quote, url in db.execute(
                    "SELECT footnote, reader, quote, url FROM v_citations WHERE item_id = ? "
                    "ORDER BY footnote", (item_id,)):
                print(wrap(f"[{fn}] “{quote}” — {reader}" + (f"  {url}" if url else ""), "      "))
        print()
    print(f"{len(rows)} item(s) for {q}", file=sys.stderr)


if __name__ == "__main__":
    main()
