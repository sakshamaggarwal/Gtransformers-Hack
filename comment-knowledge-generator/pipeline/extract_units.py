#!/usr/bin/env python3
"""
Step 2 of the community knowledge generator: extract "knowledge units" from
every comment in a hierarchical comments JSON (from nyt_comments_to_json.py
or wapo_comments_to_json.py).

For each comment, the model sees the article context, the thread above the
comment (root + parent), and the comment itself. It returns zero or more units:

    type            claim | experience | expertise | correction | question | advice | opinion
    statement       standalone one-sentence restatement
    topic           2-5 word topic label
    stance          supports | disputes | extends | unrelated   (relative to the article)
    quote           short verbatim span from the comment that backs the unit
    expertise_claimed  e.g. "pharmacist", or null

Output is JSON Lines, one line per comment, so runs can be resumed:
    {"comment_id": ..., "author": ..., "depth": ..., "endorsement": ..., "units": [...]}

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python extract_units.py comments.json -o units.jsonl \
        --title "Are supplements worth it?" --summary-file article_summary.txt

    # see exactly what gets sent for a few comments, without calling the API:
    python extract_units.py comments.json --title "..." --dry-run --limit 3
"""
import argparse
import json
import os
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_MODEL = "claude-haiku-5-5"   # cheap model for extraction; synthesis uses a stronger one
UNIT_TYPES = ["claim", "experience", "expertise", "correction", "question", "advice", "opinion"]
STANCES = ["supports", "disputes", "extends", "unrelated"]

SYSTEM_PROMPT = """You extract reusable community knowledge from reader comments on a news article.

For the TARGET comment only (thread context is there to resolve references like "@Erica" or "this"), record each distinct knowledge unit. Most comments contain 0-2 units; record none for jokes, insults, pure agreement ("so true"), or off-topic remarks.

Unit types:
- claim: a factual assertion about the world that could in principle be checked ("vitamin D is fat-soluble").
- experience: something the commenter reports happening to them or people they know ("magnesium stopped my leg cramps"). Never upgrade an experience to a claim.
- expertise: the commenter states relevant professional or lived expertise AND shares knowledge from it ("As a pharmacist, I see interactions with...").
- correction: says the article (or a parent comment) got a fact wrong or left out something important.
- question: a genuine open question readers want answered.
- advice: a recommendation to others ("ask your doctor to check levels before supplementing").
- opinion: a value judgment or policy view worth tracking across readers ("supplements should be regulated like drugs").

Rules:
- statement: one standalone sentence a reader could understand without the comment. Keep the commenter's hedges ("for me", "I think"). Do not add facts or fix errors; restate what was said, even if you believe it is wrong.
- quote: copy a short span (under 25 words) EXACTLY from the target comment, character for character, that backs the unit.
- topic: 2-5 lowercase words naming the subject (e.g. "vitamin d dosing"), consistent across comments.
- stance: relative to the article's main message: supports, disputes, extends (adds new info without contradicting), or unrelated.
- expertise_claimed: the role or credential the commenter claims, else null.
- Always call the record_units tool, with an empty list when there is nothing to record."""

TOOL = {
    "name": "record_units",
    "description": "Record the knowledge units found in the target comment (possibly none).",
    "input_schema": {
        "type": "object",
        "properties": {
            "units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": UNIT_TYPES},
                        "statement": {"type": "string"},
                        "topic": {"type": "string"},
                        "stance": {"type": "string", "enum": STANCES},
                        "quote": {"type": "string"},
                        "expertise_claimed": {"type": ["string", "null"]},
                    },
                    "required": ["type", "statement", "topic", "stance", "quote", "expertise_claimed"],
                },
            }
        },
        "required": ["units"],
    },
}


# ---------- loading & flattening ----------

def load_comments(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):  # e.g. the Reddit exporter's {"posts": [...]} shape isn't supported here
        data = data.get("comments", data.get("posts", []))
    return data


def endorsement(c):
    # NYT: recommendations; WaPo: vote_score (+ reactions); Reddit: score
    for key in ("recommendations", "vote_score", "score"):
        if key in c and isinstance(c[key], (int, float)):
            return c[key]
    return 0


def flatten(comments, ancestors=()):
    """Yield (comment, ancestors) in document order; ancestors run root -> parent."""
    for c in comments:
        yield c, list(ancestors)
        yield from flatten(c.get("replies", []), (*ancestors, c))


def clip(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def build_user_message(comment, ancestors):
    parts = []
    if ancestors:
        parts.append("THREAD CONTEXT (for reference only):")
        chain = ancestors if len(ancestors) <= 2 else [ancestors[0], ancestors[-1]]
        labels = ["Root comment", "Parent comment"] if len(chain) == 2 else ["Parent comment"]
        if len(ancestors) > 2:
            labels = ["Root comment", f"Parent comment ({len(ancestors) - 2} replies omitted between)"]
        for label, a in zip(labels, chain):
            parts.append(f"{label} by {a.get('author')}: {clip(a.get('text'), 1200)}")
        parts.append("")
    parts.append(f"TARGET COMMENT by {comment.get('author')}:")
    parts.append(comment.get("text") or "")
    return "\n".join(parts)


def system_blocks(title, summary):
    article = f"ARTICLE TITLE: {title}\n"
    if summary:
        article += f"ARTICLE SUMMARY: {summary.strip()}\n"
    # Same text for every call, so it is marked for prompt caching.
    return [{"type": "text", "text": SYSTEM_PROMPT + "\n\n" + article,
             "cache_control": {"type": "ephemeral"}}]


# ---------- validation ----------

def norm(s):
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def validate_units(units, comment_text):
    """Drop malformed units; mark whether each quote really appears in the comment."""
    good = []
    body = norm(comment_text)
    for u in units or []:
        if not isinstance(u, dict) or u.get("type") not in UNIT_TYPES or not u.get("statement"):
            continue
        u["stance"] = u.get("stance") if u.get("stance") in STANCES else "unrelated"
        u["topic"] = norm(u.get("topic"))[:60]
        u["quote_verified"] = bool(u.get("quote")) and norm(u["quote"]) in body
        good.append(u)
    return good


# ---------- API ----------

def extract_one(client, model, system, comment, ancestors):
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_units"},
        messages=[{"role": "user", "content": build_user_message(comment, ancestors)}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_units":
            return block.input.get("units", []), resp.usage
    return [], resp.usage


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="hierarchical comments JSON")
    ap.add_argument("-o", "--output", default="units.jsonl")
    ap.add_argument("--title", required=True, help="article headline")
    ap.add_argument("--summary", default="", help="1-3 sentence article summary")
    ap.add_argument("--summary-file", help="read the summary from a file instead")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=4, help="parallel requests")
    ap.add_argument("--limit", type=int, help="process only the first N comments")
    ap.add_argument("--min-chars", type=int, default=40,
                    help="skip comments shorter than this (they rarely hold knowledge)")
    ap.add_argument("--dry-run", action="store_true", help="print prompts, call nothing")
    args = ap.parse_args()

    summary = args.summary
    if args.summary_file:
        with open(args.summary_file, encoding="utf-8") as f:
            summary = f.read()
    system = system_blocks(args.title, summary)

    items = [(c, anc) for c, anc in flatten(load_comments(args.input))]
    if args.limit:
        items = items[: args.limit]

    if args.dry_run:
        print("=== SYSTEM ===\n" + system[0]["text"])
        for c, anc in items:
            print(f"\n=== USER (comment {c.get('id')}, depth {len(anc)}) ===")
            print(build_user_message(c, anc))
        return

    # Resume: skip comments already in the output file.
    done = set()
    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["comment_id"])
                except (ValueError, KeyError):
                    pass

    todo, skipped_short = [], 0
    for c, anc in items:
        if c.get("id") in done:
            continue
        if len((c.get("text") or "").strip()) < args.min_chars:
            skipped_short += 1
            continue
        todo.append((c, anc))
    print(f"{len(items)} comments: {len(done)} already done, {skipped_short} too short, "
          f"{len(todo)} to process with {args.model}", file=sys.stderr)
    if not todo:
        return

    import anthropic  # imported here so --dry-run works without the SDK
    client = anthropic.Anthropic(max_retries=5)  # retries 429/5xx with backoff

    lock = threading.Lock()
    types, failures = Counter(), 0
    tokens = Counter()

    with open(args.output, "a", encoding="utf-8") as out, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(extract_one, client, args.model, system, c, anc): (c, anc)
                   for c, anc in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            c, anc = futures[fut]
            try:
                units, usage = fut.result()
            except Exception as e:  # keep going; failed comments are retried on the next run
                failures += 1
                print(f"  ! {c.get('id')}: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            units = validate_units(units, c.get("text"))
            record = {
                "comment_id": c.get("id"),
                "author": c.get("author"),
                "depth": len(anc),
                "parent_id": anc[-1].get("id") if anc else None,
                "endorsement": endorsement(c),
                "units": units,
            }
            with lock:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                types.update(u["type"] for u in units)
                for k in ("input_tokens", "output_tokens",
                          "cache_read_input_tokens", "cache_creation_input_tokens"):
                    tokens[k] += getattr(usage, k, 0) or 0
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done", file=sys.stderr)

    print(f"Units by type: {dict(types)}", file=sys.stderr)
    print(f"Tokens: {dict(tokens)}", file=sys.stderr)
    if failures:
        print(f"{failures} comments failed; re-run the same command to retry them.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
