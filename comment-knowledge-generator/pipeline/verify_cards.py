#!/usr/bin/env python3
"""
Step 5a of the community knowledge generator: verify the cards from step 4
against the FULL text of the comments they cite, fix or remove what isn't
supported, and flag health content for human review.

Two layers of checks:

  Code checks (always run, free):
    - every citation resolves to a real comment, and its quote is in that comment
    - "echo" quotes: the same sentence posted by 3+ readers (usually the article's
      own text pasted in to respond to it, not the readers' point)
    - count wording: "Readers say..." over 1 reader, "One reader..." over several,
      "Another reader..." when every citation is the same person
    - disagreements whose sides all come from the same single reader

  Model review (one call per card; skip with --no-llm):
    For every item, the model reads the full cited comments (plus the comment each
    one replies to) and decides: supported / partly supported / unsupported, which
    citations don't back it (sarcasm, article quotes, misreadings), a corrected
    wording if needed, and a health-risk level. It judges support only, never
    whether a reader is right; outside knowledge is used only to flag health risk.

Then code applies the verdicts: unsupported items are removed, unsupporting
citations dropped, wording corrected, reader counts recomputed, and each card
gets a status: ok / review / hold.

Usage:
    python verify_cards.py cards.jsonl \
        --comments nyt_units=comments.json wapo_units=wapo_comments.json \
        -o cards_verified.jsonl

    python verify_cards.py cards.jsonl --comments ... --no-llm   # code checks only

Source names (nyt_units, wapo_units) are the step-2 file names without extension,
as they appear in the cards' citations.

Writes cards_verified.jsonl (input to publish_cards.py) and verify_report.md.
"""
import argparse
import json
import os
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_MODEL = "claude-sonnet-5-5"
SECTIONS = ["reported_experiences", "claims", "corrections", "open_questions", "advice"]
PROBLEMS = ["count_wording", "misattributed", "quotes_article", "sarcasm_or_joke",
            "overstated", "merges_different_points", "off_topic", "other"]

SYSTEM_PROMPT = """You fact-check "community knowledge cards" that summarise newspaper reader comments. Each card item cites comments by key ([c12]). You see the FULL text of every cited comment, plus the start of the comment it replies to.

For EVERY item, decide whether the cited comments support it:
- supported: the cited comments say what the item says, at the strength it says it.
- partly_supported: some citations or parts don't hold up, but a corrected item would.
- unsupported: the cited comments don't support it.

Problems to look for (list all that apply):
- count_wording: plural wording ("Readers say", "Some readers") when the citations come from one person, or "One reader" when several people are cited, or "another reader" when it's the same person. The item's reader count is given; trust it.
- misattributed: a citation doesn't say this, or says the opposite (watch for double negatives and truncated quotes).
- quotes_article: the cited text is the article's own wording, pasted in (often in quotation marks) to respond to or mock it. That is not the reader making the point.
- sarcasm_or_joke: the citation is sarcastic or a joke taken literally.
- overstated: the item is stronger or more general than the comments (e.g. "proven" for "I think", "readers agree" for one person).
- merges_different_points: the item lumps together citations that make different points.
- off_topic: the item doesn't belong on a card about this topic.

unsupporting_cites: the keys of citations that do NOT support the item (including quotes_article and sarcasm cases). Leave empty if all support it.

revised_text: if the item is partly_supported or has count_wording/overstated problems, write a corrected version that is fully supported by the remaining citations. Keep the card's style (attributed, neutral, one or two sentences, no reader counts or percentages). Add no facts that are not in the comments. Otherwise "".

health_risk: judge the item as published text a reader might act on.
- high: specific doses, stopping or starting medication or treatment, "no one should take X", or a medical claim that conflicts with well-established medical guidance.
- caution: a health claim that rests on one or two readers and could be read as established fact.
- none: everything else (including clearly framed personal experiences without advice).
You may use general medical knowledge ONLY to set health_risk and risk_note, never to change revised_text.

Do not judge whether readers are right. Judge only whether the card faithfully represents what they wrote.

Also judge the card as a whole: coherent = true if its items are about one recognisable subject that the title describes. If the title is misleading, give a better one in title_fix (else "").

Record the review with the record_review tool, with one entry for every item id you were given."""

REVIEW_TOOL = {
    "name": "record_review",
    "description": "Record the verification review of one card.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "coherent": {"type": "boolean"},
            "coherence_note": {"type": "string"},
            "title_fix": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "verdict": {"type": "string",
                                    "enum": ["supported", "partly_supported", "unsupported"]},
                        "problems": {"type": "array", "items": {"type": "string", "enum": PROBLEMS}},
                        "unsupporting_cites": {"type": "array", "items": {"type": "string"}},
                        "revised_text": {"type": "string"},
                        "health_risk": {"type": "string", "enum": ["none", "caution", "high"]},
                        "risk_note": {"type": "string"},
                    },
                    "required": ["id", "verdict", "problems", "unsupporting_cites",
                                 "revised_text", "health_risk", "risk_note"],
                },
            },
        },
        "required": ["coherent", "coherence_note", "title_fix", "items"],
    },
}


# ---------------- loading ----------------

def load_comments(specs):
    """--comments name=path ... -> {(source, comment_id): (comment, parent)}"""
    index = {}

    def walk(cs, parent=None):
        for c in cs:
            yield c, parent
            yield from walk(c.get("replies", []), c)

    for spec in specs or []:
        name, _, path = spec.partition("=")
        if not path:
            sys.exit(f"--comments expects name=path, got {spec!r}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("comments", [])
        for c, parent in walk(data):
            index[(name, str(c.get("id")))] = (c, parent)
    return index


def norm(s):
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------- card items ----------------

def iter_items(card):
    """Yield (item_id, item_dict, kind) for every checkable item, in card order."""
    if card.get("takeaway"):
        yield "takeaway", card["takeaway"], "takeaway"
    for s in SECTIONS:
        for i, it in enumerate(card.get(s, [])):
            yield f"{s}.{i}", it, s
    for d, dis in enumerate(card.get("disagreements", [])):
        for k, side in enumerate(dis["sides"]):
            yield f"disagreements.{d}.sides.{k}", side, "disagreement_side"


def item_text(it):
    return it.get("text") or it.get("position") or ""


def readers_of(cites, citations):
    return len({(citations[c]["source"], citations[c]["author"]) for c in cites if c in citations})


PLURAL = re.compile(r"^(readers|some readers|several readers|many readers|most readers|"
                    r"commenters|other readers|a few readers)\b", re.I)
SINGULAR = re.compile(r"^(one reader|a reader|one commenter|a commenter)\b", re.I)


def count_wording_issue(text, cites, citations):
    n = readers_of(cites, citations)
    t = text.strip()
    if n == 1 and PLURAL.match(t):
        return f"says '{PLURAL.match(t).group(0)}' but only 1 reader is cited"
    if n == 1 and re.search(r"\banother (reader|commenter) (says|said|adds|notes|reports|"
                            r"points|argues|thinks|cites|calls|asks|writes)\b", t, re.I):
        return "mentions 'another reader' but every citation is the same person"
    if n > 1 and SINGULAR.match(t) and not re.search(r"\b(another|others?|second)\b", t, re.I):
        return f"says '{SINGULAR.match(t).group(0)}' but {n} readers are cited"
    return None


# ---------------- code checks ----------------

def code_checks(cards, comments):
    """Annotate items in place with code-check flags. Returns echo info."""
    # echo quotes: same normalised quote from 3+ distinct authors across all cards
    by_quote = defaultdict(set)
    for card in cards:
        for u in card["citations"].values():
            by_quote[norm(u["quote"])[:100]].add((u["source"], u["author"]))
    echoes = {q for q, authors in by_quote.items() if len(authors) >= 3 and len(q) > 30}

    for card in cards:
        cit = card["citations"]
        card_flags = []
        for c, u in cit.items():
            key = (u["source"], str(u["comment_id"]))
            flags = []
            if comments:
                if key not in comments:
                    flags.append("comment_not_found")
                elif norm(u["quote"]) not in norm(comments[key][0].get("text")):
                    flags.append("quote_not_in_comment")
            if norm(u["quote"])[:100] in echoes:
                flags.append("echo_quote")
            u["code_flags"] = flags
        for item_id, it, kind in iter_items(card):
            flags = []
            issue = count_wording_issue(item_text(it), it["cites"], cit)
            if issue:
                flags.append(f"count_wording: {issue}")
            bad = [c for c in it["cites"] if cit.get(c, {}).get("code_flags")]
            if bad:
                flags.append("cites flagged by code checks: " + ", ".join(
                    f"{c} ({'/'.join(cit[c]['code_flags'])})" for c in bad))
            it["code_flags"] = flags
        for d in card.get("disagreements", []):
            authors = {(cit[c]["source"], cit[c]["author"]) for s in d["sides"] for c in s["cites"]}
            if len(authors) == 1:
                card_flags.append(f"disagreement '{d['issue']}' has one reader on every side")
        card["code_flags"] = card_flags
    return echoes


# ---------------- model review ----------------

def build_review_prompt(card, comments, max_chars):
    cit = card["citations"]
    lines = [f"CARD TITLE: {card['title']}",
             f"TOPIC LABEL: {card['topic']['label']}", "", "ITEMS:"]
    for item_id, it, kind in iter_items(card):
        extra = ""
        if kind == "disagreement_side":
            d = int(item_id.split(".")[1])
            extra = f" (one side of the disagreement: {card['disagreements'][d]['issue']})"
        n = readers_of(it["cites"], cit)
        lines.append(f"[{item_id}]{extra} ({n} reader{'s' if n != 1 else ''}) "
                     f"{item_text(it)}  — cites {', '.join(it['cites'])}")
    lines += ["", "CITED COMMENTS:"]
    for c, u in cit.items():
        key = (u["source"], str(u["comment_id"]))
        if key in comments:
            comment, parent = comments[key]
            text = comment.get("text") or ""
            if len(text) > max_chars:
                text = text[:max_chars] + " …[truncated]"
            reply = ""
            if parent is not None:
                ptxt = re.sub(r"\s+", " ", parent.get("text") or "")[:300]
                reply = f" (replying to {parent.get('author')}: \"{ptxt}\")"
            lines.append(f"[{c}] {u['author']}{reply}:\n{text}\n")
        else:  # fall back to what step 4 kept
            lines.append(f"[{c}] {u['author']} (full comment unavailable; extracted quote): "
                         f"\"{u['quote']}\"\n")
    return "\n".join(lines)


def review_card(client, model, prompt, attempts=2):
    messages = [{"role": "user", "content": prompt +
                 "\n\nRecord your review by calling the record_review tool."}]
    for _ in range(attempts):
        # Streamed: the SDK refuses non-streaming requests whose max_tokens could take
        # over 10 minutes. get_final_message() returns the same object as create().
        with client.messages.stream(
                model=model, max_tokens=24000,
                system=[{"type": "text", "text": SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                tools=[REVIEW_TOOL], tool_choice={"type": "auto"},
                messages=messages) as stream:
            resp = stream.get_final_message()
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_review":
                return block.input
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise RuntimeError("ran out of tokens before finishing the review")
        messages = messages + [{"role": "assistant", "content": resp.content},
                               {"role": "user", "content": "Please call record_review now."}]
    raise RuntimeError("model did not call record_review")


# ---------------- applying verdicts ----------------

def apply_review(card, review):
    cit = card["citations"]
    verdicts = {r["id"]: r for r in review.get("items", [])}
    log = {"removed": [], "revised": [], "cites_dropped": 0, "high_risk": [], "caution": [],
           "not_reviewed": []}

    def fix(item_id, it):
        """Return the corrected item, or None to remove it."""
        r = verdicts.get(item_id)
        if r is None:
            log["not_reviewed"].append(item_id)
            it["verification"] = {"verdict": "not_reviewed"}
            return it
        bad = {c.strip("[] ") for c in r.get("unsupporting_cites", [])}
        keep = [c for c in it["cites"] if c not in bad]
        log["cites_dropped"] += len(it["cites"]) - len(keep)
        old = item_text(it)
        if r["verdict"] == "unsupported" or not keep:
            log["removed"].append((item_id, old, r))
            return None
        text = r["revised_text"].strip() if r["revised_text"].strip() else old
        if text != old:
            log["revised"].append((item_id, old, text))
        it = dict(it)
        it["text" if "text" in it else "position"] = text
        it["cites"] = keep
        it["readers"] = readers_of(keep, cit)
        it["verification"] = {"verdict": r["verdict"], "problems": r["problems"],
                              "health_risk": r["health_risk"], "risk_note": r["risk_note"],
                              "revised": text != old}
        issue = count_wording_issue(text, keep, cit)
        if issue:
            it["verification"]["count_wording_left"] = issue
        if r["health_risk"] == "high":
            log["high_risk"].append((item_id, text, r["risk_note"]))
        elif r["health_risk"] == "caution":
            log["caution"].append((item_id, text, r["risk_note"]))
        return it

    out = dict(card)
    n_before = sum(1 for _ in iter_items(card))
    take_review = verdicts.get("takeaway")
    out["takeaway"] = fix("takeaway", card["takeaway"]) if card.get("takeaway") else None
    for s in SECTIONS:
        out[s] = [x for x in (fix(f"{s}.{i}", it) for i, it in enumerate(card.get(s, []))) if x]
    dis_out = []
    for d, dis in enumerate(card.get("disagreements", [])):
        sides = [x for x in (fix(f"disagreements.{d}.sides.{k}", side)
                             for k, side in enumerate(dis["sides"])) if x]
        authors = {(cit[c]["source"], cit[c]["author"]) for s in sides for c in s["cites"]}
        if len(sides) >= 2 and len(authors) >= 2:
            dis_out.append({"issue": dis["issue"], "sides": sides})
        else:
            log["removed"].append((f"disagreements.{d}", dis["issue"],
                                   {"verdict": "fewer than two supported sides"}))
    out["disagreements"] = dis_out

    if review.get("title_fix", "").strip():
        out["original_title"] = card["title"]
        out["title"] = review["title_fix"].strip()

    # keep only citations still used
    used = {c for _, it, _ in iter_items(out) for c in it["cites"]}
    out["citations"] = {c: u for c, u in cit.items() if c in used}

    removed_share = len(log["removed"]) / max(1, n_before)
    reasons = []
    if not review.get("coherent", True):
        reasons.append("not coherent: " + review.get("coherence_note", ""))
    if out["takeaway"] is None or (take_review and take_review["verdict"] == "unsupported"):
        reasons.append("takeaway unsupported")
    if removed_share > 0.4:
        reasons.append(f"{removed_share:.0%} of items removed")
    status = "hold" if reasons else ("review" if (log["high_risk"] or card.get("code_flags")
                                                  or any("count_wording_left" in it.get("verification", {})
                                                         for _, it, _ in iter_items(out)))
                                     else "ok")
    out["verification"] = {
        "status": status, "hold_reasons": reasons,
        "coherent": review.get("coherent", True), "coherence_note": review.get("coherence_note", ""),
        "items_before": n_before, "items_removed": len(log["removed"]),
        "items_revised": len(log["revised"]), "cites_dropped": log["cites_dropped"],
        "high_risk": len(log["high_risk"]), "caution": len(log["caution"]),
        "code_flags": card.get("code_flags", []),
    }
    return out, log


# ---------------- report ----------------

def write_report(results, path, llm):
    counts = defaultdict(int)
    for card, _ in results:
        counts[card["verification"]["status"]] += 1
    lines = ["# Verification report", "",
             f"{len(results)} cards: {counts['ok']} ok, {counts['review']} need review, "
             f"{counts['hold']} on hold." + ("" if llm else " (code checks only; no model review)"), ""]
    for card, log in results:
        v = card["verification"]
        lines.append(f"## {card['topic']['id']} · {card['title']} — **{v['status'].upper()}**")
        if card.get("original_title"):
            lines.append(f"- Title changed from: {card['original_title']}")
        for r in v["hold_reasons"]:
            lines.append(f"- Hold: {r}")
        for f in v["code_flags"]:
            lines.append(f"- Code check: {f}")
        if llm:
            lines.append(f"- {v['items_removed']} of {v['items_before']} items removed, "
                         f"{v['items_revised']} reworded, {v['cites_dropped']} citations dropped, "
                         f"{v['high_risk']} high-risk, {v['caution']} caution")
            for item_id, old, r in log["removed"]:
                why = r.get("verdict", "")
                if r.get("problems"):
                    why += " — " + ", ".join(r["problems"])
                lines.append(f"  - Removed `{item_id}` ({why}): {old}")
            for item_id, old, new in log["revised"]:
                lines.append(f"  - Reworded `{item_id}`: ~~{old}~~ → {new}")
            for item_id, text, note in log["high_risk"]:
                lines.append(f"  - ⚠ HIGH health risk `{item_id}`: {text} _({note})_")
            for item_id, text, note in log["caution"]:
                lines.append(f"  - Caution `{item_id}`: {text} _({note})_")
        for item_id, it, _ in iter_items(card):
            for f in it.get("code_flags", []):
                lines.append(f"  - Code check `{item_id}`: {f} — “{item_text(it)[:120]}”")
            left = it.get("verification", {}).get("count_wording_left")
            if left:
                lines.append(f"  - Wording still off `{item_id}`: {left}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cards", help="cards.jsonl from step 4")
    ap.add_argument("--comments", nargs="+", metavar="SOURCE=PATH",
                    help="full comment files from step 1, e.g. nyt_units=comments.json")
    ap.add_argument("-o", "--output", default="cards_verified.jsonl")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-comment-chars", type=int, default=2500)
    ap.add_argument("--no-llm", action="store_true", help="run only the free code checks")
    ap.add_argument("--dry-run", action="store_true", help="print the first card's review prompt")
    args = ap.parse_args()

    with open(args.cards, encoding="utf-8") as f:
        cards = [json.loads(l) for l in f if l.strip()]
    comments = load_comments(args.comments)
    if not comments:
        print("Warning: no --comments given; the model will only see extracted quotes.",
              file=sys.stderr)
    echoes = code_checks(cards, comments)
    print(f"{len(cards)} cards; code checks found {len(echoes)} echoed quote(s)", file=sys.stderr)

    if args.dry_run:
        print("=== SYSTEM ===\n" + SYSTEM_PROMPT)
        print("\n=== USER ===\n" + build_review_prompt(cards[0], comments, args.max_comment_chars))
        return

    results = []
    if args.no_llm:
        for card in cards:
            card = dict(card)
            flagged = card.get("code_flags") or any(it.get("code_flags") for _, it, _ in iter_items(card))
            card["verification"] = {"status": "review" if flagged else "ok", "hold_reasons": [],
                                    "code_flags": card.get("code_flags", []), "llm": False}
            results.append((card, {}))
    else:
        import anthropic
        client = anthropic.Anthropic(max_retries=5)
        lock = threading.Lock()
        done = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(review_card, client, args.model,
                                build_review_prompt(c, comments, args.max_comment_chars)): c
                    for c in cards}
            for fut in as_completed(futs):
                card = futs[fut]
                try:
                    review = fut.result()
                except Exception as e:
                    print(f"  ! {card['topic']['id']}: {type(e).__name__}: {e}", file=sys.stderr)
                    continue
                new, log = apply_review(card, review)
                with lock:
                    done[card["topic"]["id"]] = (new, log)
                v = new["verification"]
                print(f"  {card['topic']['id']}: {v['status']} — removed {v['items_removed']}, "
                      f"reworded {v['items_revised']}, high-risk {v['high_risk']}", file=sys.stderr)
        results = [done[c["topic"]["id"]] for c in cards if c["topic"]["id"] in done]
        missing = len(cards) - len(results)
        if missing:
            print(f"{missing} card(s) failed; re-run to retry them.", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8") as f:
        for card, _ in results:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
    report = os.path.join(os.path.dirname(os.path.abspath(args.output)), "verify_report.md")
    write_report(results, report, llm=not args.no_llm)
    print(f"Wrote {args.output} and {report}", file=sys.stderr)


if __name__ == "__main__":
    main()
