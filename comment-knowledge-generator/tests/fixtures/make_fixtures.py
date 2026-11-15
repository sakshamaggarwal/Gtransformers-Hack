#!/usr/bin/env python3
"""
Build the synthetic test fixtures from the SPEC below.

Everything here is invented (people, comments, numbers), so the fixtures can be
committed to a public repo. The markup copies only the attributes the parsers
rely on from real NYT and Washington Post comment pages.

    python tests/fixtures/make_fixtures.py

Writes, next to this file:
    nyt_sample.html, wapo_sample.html     step 1 inputs
    nyt_comments.json, wapo_comments.json step 1 outputs (via the real parsers)
    nyt_units.jsonl, wapo_units.jsonl     step 2 outputs (hand-written units)
    cards.jsonl                           step 4 output (hand-written cards)

The content is chosen to exercise known edge cases:
  - a 4-level NYT reply chain, and a reader replying to themselves
  - a WaPo thread whose "Collapse 3 replies" button shows more replies than were loaded
  - three WaPo readers pasting the same sentence from the article ("echo" quotes)
  - "vitamin D" next to "vitamin deficiency" (phrase / word-boundary search)
  - "omega-3" (hyphenated search) and "Consumer Lab" found only in a quoted comment
  - "Readers say..." wording over a single reader (count-wording check)
  - a card titled "Fish oil..." whose items don't all mention fish (title-match check)
"""
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(HERE, "..", "..", "pipeline")

# ---------------------------------------------------------------- comments
# (id, author, location/date, text, recommendations or score, replies)
NYT = [
    ("900001", "Mara K.", "Portland", "Sept. 12",
     "My doctor tested my vitamin D level last spring and it was low, so I take 1,000 IU a day now. "
     "Get tested before you start anything.", 12, [
        ("900011", "Tom B.", "Ohio", "Sept. 12",
         "@Mara K. Same here. Testing first is the only sensible approach.", 3, [
            ("900111", "Mara K.", "Portland", "Sept. 13",
             "@Tom B. Agreed, and my levels are back in the normal range now.", 1, [
                ("901111", "Lena P.", "Austin", "Sept. 13",
                 "@Mara K. Did your doctor say how long you should keep taking it?", 0, []),
            ]),
        ]),
    ]),
    ("900002", "Raj S.", "Chicago", "Sept. 12",
     "Supplements aren't regulated, so you never know what's in the bottle. "
     "Choose ones verified by a third-party tester like USP.", 40, [
        ("900021", "Dee W.", "Denver", "Sept. 12",
         "@Raj S. Consumer Lab tests a lot of brands too, and posts the results.", 6, []),
    ]),
    ("900003", "Ann Q.", "Boston", "Sept. 13",
     "Real vitamin deficiency is uncommon in people who eat a varied diet.", 5, []),
    ("900004", "Bo L.", "Tampa", "Sept. 14",
     "Omega-3 pills never did anything for my triglycerides, and I took them for years.", 2, []),
    ("900005", "Cy N.", "Reno", "Sept. 14", "Ha.", 0, []),
]

# (id, author, iso time, text, score, reactions, replies, collapse_count_shown)
WAPO = [
    ("w-0001", "SunnyDays", "2026-09-10T14:02:00Z",
     "“The findings are preliminary and far from proof.” Oh really? This reads like a tabloid.",
     4, 1, [], None),
    ("w-0002", "OakTree", "2026-09-10T14:20:00Z",
     "“The findings are preliminary and far from proof.” Then why publish it at all?", 2, 0, [], None),
    ("w-0003", "RiverRun", "2026-09-10T15:05:00Z",
     "“The findings are preliminary and far from proof.” Exactly. Wait for better studies.", 1, 0, [], None),
    ("w-0004", "FishFan", "2026-09-10T16:00:00Z",
     "I take fish oil for dry eyes on my ophthalmologist's advice and it has helped a lot.", 7, 2, [
        ("w-0041", "KrillWatch", "2026-09-10T16:30:00Z",
         "Fish oil production depletes the krill that whales depend on.", 5, 0, [
            ("w-0411", "FishFan", "2026-09-10T17:00:00Z",
             "Algae-based omega-3 is an alternative that skips the krill problem.", 3, 0, [], None),
         ], 1),
        ("w-0042", "OakTree", "2026-09-10T16:45:00Z",
         "Fish oil quality varies a lot from brand to brand.", 1, 0, [], None),
     ], 3),   # button says 3 replies, but only 2 are in the page: one was never loaded
    ("w-0005", "Skeptic99", "2026-09-11T09:00:00Z",
     "I took 10,000 IU of vitamin D every day and ended up with hypercalcemia. More is not better.",
     9, 3, [], None),
]

# ---------------------------------------------------------------- units (step 2)
# comment id -> list of (type, stance, topic, statement, quote)
UNITS = {
    "nyt_units": {
        "900001": [("experience", "extends", "vitamin d testing",
                    "The commenter's vitamin D level was low when tested, so they take 1,000 IU a day.",
                    "My doctor tested my vitamin D level last spring and it was low"),
                   ("advice", "extends", "vitamin d testing",
                    "Get tested before starting any supplement.", "Get tested before you start anything.")],
        "900011": [("advice", "extends", "vitamin d testing",
                    "Testing first is the sensible approach.", "Testing first is the only sensible approach.")],
        "900111": [("experience", "unrelated", "vitamin d testing",
                    "The commenter's levels are back in the normal range.",
                    "my levels are back in the normal range now")],
        "901111": [("question", "unrelated", "vitamin d duration",
                    "How long should someone keep taking vitamin D?",
                    "Did your doctor say how long you should keep taking it?")],
        "900002": [("claim", "extends", "supplement regulation",
                    "Supplements aren't regulated, so contents are uncertain.",
                    "Supplements aren't regulated, so you never know what's in the bottle."),
                   ("advice", "extends", "supplement quality testing",
                    "Choose supplements verified by a third-party tester such as USP.",
                    "Choose ones verified by a third-party tester like USP.")],
        "900021": [("claim", "extends", "supplement quality testing",
                    "Consumer Lab tests many brands and posts results.",
                    "Consumer Lab tests a lot of brands too")],
        "900003": [("claim", "disputes", "vitamin deficiency",
                    "Real vitamin deficiency is uncommon with a varied diet.",
                    "Real vitamin deficiency is uncommon in people who eat a varied diet.")],
        "900004": [("experience", "supports", "omega-3 triglycerides",
                    "Omega-3 pills did not lower the commenter's triglycerides.",
                    "Omega-3 pills never did anything for my triglycerides")],
    },
    "wapo_units": {
        "w-0001": [("opinion", "disputes", "article quality",
                    "The findings are preliminary and far from proof.",
                    "The findings are preliminary and far from proof.")],
        "w-0002": [("opinion", "disputes", "article quality",
                    "The findings are preliminary and far from proof.",
                    "The findings are preliminary and far from proof.")],
        "w-0003": [("opinion", "disputes", "article quality",
                    "The findings are preliminary and far from proof.",
                    "The findings are preliminary and far from proof.")],
        "w-0004": [("experience", "unrelated", "fish oil dry eye",
                    "Fish oil taken on an ophthalmologist's advice helped the commenter's dry eyes.",
                    "I take fish oil for dry eyes on my ophthalmologist's advice")],
        "w-0041": [("claim", "extends", "fish oil environment",
                    "Fish oil production depletes krill that whales depend on.",
                    "Fish oil production depletes the krill that whales depend on.")],
        "w-0411": [("advice", "extends", "fish oil environment",
                    "Algae-based omega-3 is an alternative to fish oil.",
                    "Algae-based omega-3 is an alternative")],
        "w-0042": [("claim", "extends", "fish oil quality",
                    "Fish oil quality varies by brand.", "Fish oil quality varies a lot from brand to brand.")],
        "w-0005": [("experience", "disputes", "vitamin d dosing",
                    "Taking 10,000 IU of vitamin D daily led to hypercalcemia for the commenter.",
                    "I took 10,000 IU of vitamin D every day and ended up with hypercalcemia.")],
    },
}

# ---------------------------------------------------------------- cards (step 4)
# Citations are (source, comment_id, unit index). Items are (text, [citation refs]).
CARDS = [
    {"id": "T1", "label": "vitamin d testing", "title": "Vitamin D: test first, then dose carefully",
     "health": True,
     "takeaway": ("Readers favour testing vitamin D before supplementing, and one warns that high doses caused harm.",
                  ["n1a", "n2", "w5"]),
     "reported_experiences": [
         ("One reader's vitamin D was low when tested, and they now take 1,000 IU a day.", ["n1a"]),
         ("One reader says 10,000 IU of vitamin D a day led to hypercalcemia.", ["w5"])],
     "claims": [("Readers say real vitamin deficiency is uncommon with a varied diet.", ["n3"])],  # 1 reader: wording check
     "advice": [("Readers advise getting vitamin D tested before starting supplements.", ["n1b", "n2"])],
     "open_questions": [("How long should someone keep taking vitamin D?", ["n4"])],
     "corrections": [],
     "disagreements": []},
    {"id": "T2", "label": "supplement quality testing", "title": "Who checks what is in the bottle?",
     "health": True,
     "takeaway": ("Readers say supplements are unregulated and point to independent testers.", ["n5", "n6", "n7"]),
     "reported_experiences": [],
     "claims": [("One reader says supplements aren't regulated, so you can't know what's inside.", ["n5"])],
     "advice": [("Readers advise choosing supplements verified by an independent tester such as USP.", ["n6", "n7"])],
     "open_questions": [], "corrections": [], "disagreements": []},
    {"id": "T3", "label": "fish oil", "title": "Fish oil: eyes, krill and alternatives",
     "health": True,
     "takeaway": ("Readers report personal benefit from fish oil but raise environmental and quality concerns.",
                  ["w4", "w41", "w42"]),
     "reported_experiences": [("One reader says fish oil helped their dry eyes.", ["w4"])],
     "claims": [("One reader says production depletes krill that whales depend on.", ["w41"]),
                ("One reader says quality varies by brand.", ["w42"])],
     "advice": [("One reader suggests algae-based omega-3 as an alternative.", ["w411"])],
     "open_questions": [], "corrections": [],
     "disagreements": [{"issue": "Whether omega-3 supplements help",
                        "sides": [("They helped one reader's dry eyes.", ["w4"]),
                                  ("They did nothing for one reader's triglycerides.", ["n8"])]}]},
    {"id": "T4", "label": "article quality", "title": "Readers question the article's evidence",
     "health": False,
     "takeaway": ("Several readers say the findings are preliminary.", ["e1", "e2", "e3"]),
     "reported_experiences": [], "advice": [], "open_questions": [], "corrections": [],
     "claims": [("Readers point out that the findings are preliminary and far from proof.", ["e1", "e2", "e3"])],
     "disagreements": [{"issue": "Whether to publish early findings",
                        "sides": [("Don't publish preliminary work.", ["e2"]),
                                  ("Wait for better studies.", ["e2"])]}]},   # one reader on both sides
]
REFS = {  # short names used in CARDS -> (source, comment id, unit index)
    "n1a": ("nyt_units", "900001", 0), "n1b": ("nyt_units", "900001", 1), "n2": ("nyt_units", "900011", 0),
    "n3": ("nyt_units", "900003", 0), "n4": ("nyt_units", "901111", 0), "n5": ("nyt_units", "900002", 0),
    "n6": ("nyt_units", "900002", 1), "n7": ("nyt_units", "900021", 0), "n8": ("nyt_units", "900004", 0),
    "w4": ("wapo_units", "w-0004", 0), "w41": ("wapo_units", "w-0041", 0), "w42": ("wapo_units", "w-0042", 0),
    "w411": ("wapo_units", "w-0411", 0), "w5": ("wapo_units", "w-0005", 0),
    "e1": ("wapo_units", "w-0001", 0), "e2": ("wapo_units", "w-0002", 0), "e3": ("wapo_units", "w-0003", 0),
}


# ---------------------------------------------------------------- HTML builders
def nyt_comment(c, reply=False):
    cid, author, loc, date, text, recs, replies = c
    testid = "reply-comment-container" if reply else "comment-container"
    a, d = html.escape(author), html.escape(date)
    url = f"https://www.nytimes.com/shared/comment/fx{cid}?rsrc=cshare"
    inner = "".join(nyt_comment(r, True) for r in replies)
    return (f'<div class="css-5zk2v4" role="article" data-testid="{testid}" id="comment-container-{cid}">'
            f'<a class="css-1dv1kvn" href="" id="comment-description-{cid}" aria-label="{a} commented {d}">{a} commented {d}</a>'
            f'<div class="css-ts36e2" data-testid="user-header"><div class="css-dqm0it">'
            f'<div class="css-xrhnuy"><span>{a}</span></div><div class="css-1pmv44">'
            f'<span class="css-rdbb7z" data-testid="user-header-subtitle"><span><span>{html.escape(loc)}</span> · </span>'
            f'<a href="" data-testid="date-permalink"><span data-testid="todays-date" aria-label="{d}">{d}</span></a>'
            f'</span></div></div></div>'
            f'<div class="css-tvu5oc"><p id="comment-content-{cid}" class="css-qj4lbw">{html.escape(text)}</p>'
            f'<div><button class="mTNqGW_button" data-testid="recommend-button"><div><span>'
            f'<span class="mTNqGW_count">{recs}</span></span><span>Recommend</span></div></button>'
            f'<button data-testid="share-button"><span><button data-testid="copy-link" '
            f'id="share-link-{url}" type="button"></button></span></button></div>'
            f'{inner}</div></div>')


def wapo_article(c, reply=False):
    cid, author, iso, text, score, reactions, replies, shown = c
    a = html.escape(author)
    collapse = f'<button aria-label="Collapse {shown} {"reply" if shown == 1 else "replies"}"></button>' if shown else ""
    art = (f'<article aria-label="{"Reply" if reply else "Comment"} by {a}" data-comment-id="{cid}" '
           f'class="wpds-c-hhbezg{" isReply" if reply else ""}">'
           f'<div class="wpds-c-fIaqhA"><div><div><div><span><span type="button">{a}</span>'
           f'<time datetime="{iso}">2 months ago</time></span></div></div></div></div>'
           f'<div><div><div><p class="nodeToHtml">{html.escape(text)}</p></div></div></div>'
           f'<div class="wpds-c-jrkZHy"><div><div><button aria-label="Upvote"></button>'
           f'<span><span>{score}</span></span><button aria-label="Downvote"></button></div>'
           f'<span><button aria-label="Reactions, {reactions} total"></button></span></div>{collapse}</div>'
           f'</article>')
    if not replies:
        return art
    block = "".join(f"<div>{wapo_article(r, True)}</div>" for r in replies)
    return (art + '<div class="wpds-c-knxFEx"><div role="button" aria-label="Write your reply here"></div>'
            f'<div><div class="wpds-c-gOCDxw"><section aria-label="Replies to comment">{block}'
            '</section></div></div></div>')


def flatten(threads, depth=0, parent=None):
    for t in threads:
        yield t, depth, parent
        yield from flatten(t[-1] if len(t) == 6 else t[6], depth + 1, t[0])


def main():
    with open(os.path.join(HERE, "nyt_sample.html"), "w", encoding="utf-8") as f:
        f.write('<div role="feed" aria-label="List of Comments">' +
                "".join(nyt_comment(c) for c in NYT) + "</div>")
    with open(os.path.join(HERE, "wapo_sample.html"), "w", encoding="utf-8") as f:
        f.write('<ol class="wpds-c-ubeuz">' +
                "".join(f'<li class="wpds-c-iIdhEv">{wapo_article(c)}</li>' for c in WAPO) + "</ol>")

    for name, script, src in [("nyt_comments.json", "nyt_comments_to_json.py", "nyt_sample.html"),
                              ("wapo_comments.json", "wapo_comments_to_json.py", "wapo_sample.html")]:
        subprocess.run([sys.executable, os.path.join(PIPELINE, script), os.path.join(HERE, src),
                        "-o", os.path.join(HERE, name)], check=True, capture_output=True)

    # step 2 units, with the comment metadata step 2 records
    meta = {}
    for c, depth, parent in flatten(NYT):
        meta[("nyt_units", c[0])] = (c[1], depth, parent, c[5])
    for c, depth, parent in flatten(WAPO):
        meta[("wapo_units", c[0])] = (c[1], depth, parent, c[4])
    unit_rows = {}
    for source, by_comment in UNITS.items():
        rows = []
        for cid, units in by_comment.items():
            author, depth, parent, endorse = meta[(source, cid)]
            rows.append({"comment_id": cid, "author": author, "depth": depth, "parent_id": parent,
                         "endorsement": endorse,
                         "units": [{"type": t, "statement": st, "topic": tp, "stance": sn, "quote": q,
                                    "expertise_claimed": None, "quote_verified": True}
                                   for t, sn, tp, st, q in units]})
        # the short "Ha." comment produced no units
        if source == "nyt_units":
            rows.append({"comment_id": "900005", "author": "Cy N.", "depth": 0, "parent_id": None,
                         "endorsement": 0, "units": []})
        unit_rows[source] = rows
        with open(os.path.join(HERE, f"{source}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def unit(ref):
        source, cid, i = REFS[ref]
        row = next(r for r in unit_rows[source] if r["comment_id"] == cid)
        u = row["units"][i]
        return {"uid": f"{source}:{cid}:{i}", "source": source, "comment_id": cid,
                "author": row["author"], "type": u["type"], "stance": u["stance"],
                "statement": u["statement"], "quote": u["quote"], "endorsement": row["endorsement"],
                "expertise_claimed": None, "quote_verified": True}

    with open(os.path.join(HERE, "cards.jsonl"), "w", encoding="utf-8") as f:
        for spec in CARDS:
            keys = {}

            def cites(refs):
                for r in refs:
                    keys.setdefault(r, f"c{len(keys) + 1}")
                return [keys[r] for r in refs]

            def readers(refs):
                return len({(REFS[r][0], unit(r)["author"]) for r in refs})

            def item(t):
                text, refs = t
                return {"text": text, "cites": cites(refs), "readers": readers(refs)}

            card = {"title": spec["title"], "health_related": spec["health"],
                    "takeaway": item(spec["takeaway"])}
            for s in ["reported_experiences", "claims", "corrections", "open_questions", "advice"]:
                card[s] = [item(t) for t in spec[s]]
            card["disagreements"] = [
                {"issue": d["issue"],
                 "sides": [{"position": p, "cites": cites(r), "readers": readers(r)} for p, r in d["sides"]]}
                for d in spec["disagreements"]]
            card["citations"] = {k: unit(r) for r, k in keys.items()}
            srcs = {}
            for r in keys:
                srcs[REFS[r][0]] = srcs.get(REFS[r][0], 0) + 1
            authors = {(REFS[r][0], unit(r)["author"]) for r in keys}
            card["topic"] = {"id": spec["id"], "label": spec["label"], "score": float(len(authors)),
                             "breadth": len(authors), "stance_counts": {}, "contested": 0.0,
                             "sources": srcs}
            card["coverage"] = {"points_total": 1, "points_used": 1, "units_total": len(keys),
                                "units_used": len(keys)}
            card["dropped_items"] = 0
            card["model"] = "fixture"
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
    print("fixtures written to", HERE)


if __name__ == "__main__":
    main()
