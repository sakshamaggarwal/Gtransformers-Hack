#!/usr/bin/env python3
"""
Step 4 of the community knowledge generator: turn the top topics from step 3
(cluster_units.py) into "knowledge cards" in which every statement cites the
reader comments behind it.

For each selected topic the model gets an evidence pack: the topic's points
(best first), each with a few units from different people, every unit tagged
with a citation key like [c12]. It writes a card through a fixed schema:

    title, takeaway
    reported_experiences  what readers say happened to them (never as fact)
    claims                factual assertions readers made
    corrections           where readers say the article got it wrong / left it out
    disagreements         issues where readers split, with each side's position
    open_questions        what readers want answered
    advice                tips readers gave each other

The model never writes reader counts. The code resolves each item's citations
and computes "N readers" itself from the distinct authors cited. Items whose
citations don't resolve are dropped.

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python synthesize_cards.py clusters.json -o cards.jsonl --min-breadth 5 --top 30

    # see the exact prompt for the first topic without calling the API:
    python synthesize_cards.py clusters.json --dry-run --top 1

Writes:
    cards.jsonl   one card per line, citations resolved to comment ids (input to step 5)
    cards.md      readable cards with numbered footnotes quoting the comments
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_MODEL = "claude-sonnet-5-5"   # stronger model for synthesis; extraction used Haiku
HEALTH_NOTE = ("Reader experiences and claims collected from comments; not medical advice. "
               "Check with a doctor or pharmacist before changing what you take.")

SYSTEM_PROMPT = """You write "community knowledge cards" that summarise what newspaper readers collectively said about one topic in the comments under articles.

You get an evidence pack: the topic's POINTS (groups of similar statements, best first, with how many different people raised each) and, under each point, UNITS from individual readers, each with a citation key like [c12], its type and its stance toward the article.

Write the card with the record_card tool. Rules:
1. Use ONLY the evidence pack. Add no outside facts, statistics, or judgments of your own, even if you believe a reader is wrong.
2. Every item must cite the keys of the units that support it (cite ALL supporting units you see, not just one). Never cite a unit for something it does not say.
3. Never write counts of readers or percentages; the software adds reader counts from your citations. Words like "several", "many", "one reader" are fine when the evidence clearly supports them.
4. Keep types apart. Experiences are reported as experiences ("Readers report that...", "One reader says..."), never as facts or advice. Claims are attributed ("Readers point out that..."), not asserted in your own voice.
5. Disagreements: where readers genuinely split on an issue, state the issue neutrally and each side's position with its citations. Do not pick a winner.
6. Merge units that say the same thing into one item. Skip units that are off-topic for this card, insults, or pure agreement.
7. Each item is one or two plain sentences. Leave a section empty if there is nothing for it.
8. title: a short, specific title (not just the topic label). takeaway: one neutral sentence (max 30 words) capturing the overall shape of the discussion, with citations.
9. health_related: true if the topic involves health, medicine, supplements, or diet."""

ITEM = {
    "type": "object",
    "properties": {"text": {"type": "string"},
                   "cites": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "cites"],
}
SECTIONS = ["reported_experiences", "claims", "corrections", "open_questions", "advice"]
TOOL = {
    "name": "record_card",
    "description": "Record the knowledge card for this topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "takeaway": ITEM,
            "health_related": {"type": "boolean"},
            **{s: {"type": "array", "items": ITEM} for s in SECTIONS},
            "disagreements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue": {"type": "string"},
                        "sides": {"type": "array", "items": {
                            "type": "object",
                            "properties": {"position": {"type": "string"},
                                           "cites": {"type": "array", "items": {"type": "string"}}},
                            "required": ["position", "cites"]}},
                    },
                    "required": ["issue", "sides"],
                },
            },
        },
        "required": ["title", "takeaway", "health_related", "disagreements", *SECTIONS],
    },
}
SECTION_TITLES = {
    "reported_experiences": "What readers report",
    "claims": "What readers claim",
    "corrections": "Corrections and gaps readers raised",
    "disagreements": "Where readers disagree",
    "open_questions": "Open questions",
    "advice": "Advice readers shared",
}


# ---------------- evidence pack ----------------

def build_pack(topic, max_points, units_per_point, include_unverified):
    """Return (prompt text, {key: unit}, coverage info)."""
    keys, lines = {}, []
    sc = topic["stance_counts"]
    lines.append(f"TOPIC: {topic['label']}")
    lines.append(f"Raised by {topic['breadth']} different readers; stance toward the article: "
                 f"supports {sc.get('supports', 0)}, disputes {sc.get('disputes', 0)}, "
                 f"extends {sc.get('extends', 0)}, unrelated {sc.get('unrelated', 0)}.")
    used_points = topic["points"][:max_points]
    n = 0
    for pi, p in enumerate(used_points, 1):
        lines.append(f"\nPOINT p{pi} (raised by {p['breadth']} "
                     f"{'reader' if p['breadth'] == 1 else 'different readers'}):")
        seen = set()
        for u in p["units"]:   # already ordered most-central first by step 3
            if not include_unverified and not u.get("quote_verified", True):
                continue
            who = (u["source"], u["author"])
            if who in seen:
                continue
            seen.add(who)
            n += 1
            key = f"c{n}"
            keys[key] = u
            extra = f"; claims expertise: {u['expertise_claimed']}" if u.get("expertise_claimed") else ""
            lines.append(f"[{key}] ({u['type']}, {u['stance']} article; {u['author']}{extra}) "
                         f"{u['statement']}")
            if len(seen) >= units_per_point:
                break
    coverage = {"points_total": len(topic["points"]), "points_used": len(used_points),
                "units_total": topic["n_units"], "units_used": n}
    if len(used_points) < len(topic["points"]):
        lines.append(f"\n(Only the top {len(used_points)} of {len(topic['points'])} points are shown.)")
    return "\n".join(lines), keys, coverage


# ---------------- resolving citations ----------------

def resolve(cites, keys):
    out, seen = [], set()
    for c in cites or []:
        c = str(c).strip("[] ")
        if c in keys and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def readers(cites, keys):
    return len({(keys[c]["source"], keys[c]["author"]) for c in cites})


def resolve_card(raw, keys):
    """Keep only items with valid citations; attach reader counts. Returns (card, dropped)."""
    dropped = 0

    def item(it):
        nonlocal dropped
        cites = resolve(it.get("cites"), keys)
        if not cites or not it.get("text"):
            dropped += 1
            return None
        return {"text": it["text"].strip(), "cites": cites, "readers": readers(cites, keys)}

    card = {"title": raw.get("title", "").strip(),
            "health_related": bool(raw.get("health_related")),
            "takeaway": item(raw.get("takeaway") or {})}
    for s in SECTIONS:
        card[s] = [x for x in (item(i) for i in raw.get(s) or []) if x]
    card["disagreements"] = []
    for d in raw.get("disagreements") or []:
        sides = []
        for side in d.get("sides") or []:
            cites = resolve(side.get("cites"), keys)
            if cites and side.get("position"):
                sides.append({"position": side["position"].strip(), "cites": cites,
                              "readers": readers(cites, keys)})
            else:
                dropped += 1
        if len(sides) >= 2:      # a disagreement needs at least two supported sides
            card["disagreements"].append({"issue": d.get("issue", "").strip(), "sides": sides})
        elif sides:
            dropped += 1
    used = {c for s in SECTIONS for i in card[s] for c in i["cites"]}
    used |= {c for d in card["disagreements"] for side in d["sides"] for c in side["cites"]}
    if card["takeaway"]:
        used |= set(card["takeaway"]["cites"])
    card["citations"] = {c: keys[c] for c in sorted(used, key=lambda k: int(k[1:]))}
    return card, dropped


# ---------------- API ----------------

def strict_schema(schema):
    """Copy of a JSON schema with additionalProperties: false on every object (for strict tools)."""
    if isinstance(schema, dict):
        out = {k: strict_schema(v) for k, v in schema.items()}
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [strict_schema(v) for v in schema]
    return schema


# Claude Sonnet 5.5 / Opus 5.5 reject forced tool use (tool_choice "tool" or "any").
# Anthropic's recommended replacement: tool_choice "auto" + a strict tool (inputs are
# guaranteed to match the schema) + telling the model to call it. If the model still
# answers without calling the tool, we ask once more.
STRICT_TOOL = {**TOOL, "strict": True, "input_schema": strict_schema(TOOL["input_schema"])}
CALL_INSTRUCTION = "\n\nRecord the card by calling the record_card tool. Do not reply in prose."


def synthesize(client, model, topic_text, attempts=2):
    messages = [{"role": "user", "content": topic_text + CALL_INSTRUCTION}]
    for _ in range(attempts):
        resp = client.messages.create(
            model=model,
            max_tokens=16000,   # these models think before answering; thinking uses this budget
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[STRICT_TOOL],
            tool_choice={"type": "auto"},
            messages=messages,
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_card":
                return block.input, resp.usage
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise RuntimeError("ran out of tokens before writing the card")
        # No tool call: show the model its own reply and ask again.
        messages = messages + [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": "Please call the record_card tool now with the card."},
        ]
    raise RuntimeError("model did not call record_card")


# ---------------- rendering ----------------

def render_markdown(cards, path):
    out = [f"# Community knowledge cards ({len(cards)})\n"]
    for card in cards:
        num = {c: i for i, c in enumerate(card["citations"], 1)}

        def refs(cites):
            return "".join(f"[{num[c]}]" for c in cites)

        def who(it):
            n = it["readers"]
            return f"({n} reader{'s' if n != 1 else ''})"

        t = card["topic"]
        out.append(f"## {card['title']}")
        out.append(f"_{t['id']} · {t['label']} · raised by {t['breadth']} readers · "
                   f"contested {t['contested']} · evidence used: {card['coverage']['units_used']} "
                   f"units from {card['coverage']['points_used']} of "
                   f"{card['coverage']['points_total']} points_\n")
        if card["takeaway"]:
            out.append(f"**{card['takeaway']['text']}** {refs(card['takeaway']['cites'])}\n")
        if card["health_related"]:
            out.append(f"> {HEALTH_NOTE}\n")
        for s in ["reported_experiences", "claims", "corrections", "disagreements",
                  "open_questions", "advice"]:
            items = card[s]
            if not items:
                continue
            out.append(f"### {SECTION_TITLES[s]}")
            if s == "disagreements":
                for d in items:
                    out.append(f"- **{d['issue']}**")
                    for side in d["sides"]:
                        out.append(f"  - {side['position']} {who(side)} {refs(side['cites'])}")
            else:
                for it in items:
                    out.append(f"- {it['text']} {who(it)} {refs(it['cites'])}")
            out.append("")
        out.append("<details><summary>Sources</summary>\n")
        for c, i in num.items():
            u = card["citations"][c]
            out.append(f"{i}. \"{u['quote']}\" — {u['author']} ({u['source']}, comment {u['comment_id']})")
        out.append("\n</details>\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clusters", help="clusters.json from step 3")
    ap.add_argument("-o", "--output", default="cards.jsonl")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--top", type=int, default=30, help="max topics to turn into cards")
    ap.add_argument("--min-breadth", type=int, default=5,
                    help="only topics raised by at least this many readers")
    ap.add_argument("--topics", help="comma-separated topic ids to (re)do, e.g. T1,T4")
    ap.add_argument("--max-points", type=int, default=25, help="points per card's evidence")
    ap.add_argument("--units-per-point", type=int, default=6,
                    help="units per point, each from a different reader")
    ap.add_argument("--include-unverified", action="store_true",
                    help="also use units whose quote wasn't found in the comment")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="redo topics already in the output")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.clusters, encoding="utf-8") as f:
        topics = json.load(f)["topics"]
    if args.topics:
        wanted = set(args.topics.split(","))
        selected = [t for t in topics if t["id"] in wanted]
    else:
        selected = [t for t in topics if t["breadth"] >= args.min_breadth][: args.top]

    if args.dry_run:
        print("=== SYSTEM ===\n" + SYSTEM_PROMPT)
        for t in selected:
            text, keys, cov = build_pack(t, args.max_points, args.units_per_point,
                                         args.include_unverified)
            print(f"\n=== USER ({t['id']}; {len(keys)} units; ~{len(text) // 4} tokens) ===\n{text}")
        return

    existing = {}
    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    existing[c["topic"]["id"]] = c
    todo = [t for t in selected if args.force or t["id"] not in existing]
    print(f"{len(selected)} topics selected, {len(selected) - len(todo)} already done, "
          f"{len(todo)} to write with {args.model}", file=sys.stderr)

    if todo:
        import anthropic
        client = anthropic.Anthropic(max_retries=5)
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = {}
            for t in todo:
                text, keys, cov = build_pack(t, args.max_points, args.units_per_point,
                                             args.include_unverified)
                if cov["points_used"] < cov["points_total"]:
                    print(f"  note: {t['id']} '{t['label']}' has {cov['points_total']} points; "
                          f"using the top {cov['points_used']}", file=sys.stderr)
                jobs[pool.submit(synthesize, client, args.model, text)] = (t, keys, cov)
            for fut in as_completed(jobs):
                t, keys, cov = jobs[fut]
                try:
                    raw, usage = fut.result()
                except Exception as e:
                    print(f"  ! {t['id']}: {type(e).__name__}: {e} (re-run to retry)",
                          file=sys.stderr)
                    continue
                card, dropped = resolve_card(raw, keys)
                card["topic"] = {k: t[k] for k in ("id", "label", "score", "breadth",
                                                   "stance_counts", "contested", "sources")}
                card["coverage"] = cov
                card["dropped_items"] = dropped
                card["model"] = args.model
                with lock:
                    existing[t["id"]] = card
                n_items = sum(len(card[s]) for s in SECTIONS) + len(card["disagreements"])
                print(f"  {t['id']}: {n_items} items, {len(card['citations'])} citations"
                      + (f", {dropped} dropped (bad citations)" if dropped else ""),
                      file=sys.stderr)

        # rewrite in topic order so --force replacements don't leave duplicates
        order = {t["id"]: i for i, t in enumerate(topics)}
        with open(args.output, "w", encoding="utf-8") as f:
            for c in sorted(existing.values(), key=lambda c: order.get(c["topic"]["id"], 1e9)):
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    order = {t["id"]: i for i, t in enumerate(topics)}
    cards = sorted(existing.values(), key=lambda c: order.get(c["topic"]["id"], 1e9))
    md = os.path.splitext(args.output)[0] + ".md"
    render_markdown(cards, md)
    print(f"Wrote {len(cards)} cards to {args.output} and {md}", file=sys.stderr)


if __name__ == "__main__":
    main()
