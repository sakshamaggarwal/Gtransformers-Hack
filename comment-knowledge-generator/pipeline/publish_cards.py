#!/usr/bin/env python3
"""
Step 5b of the community knowledge generator: publish verified cards as
  site/index.html   a self-contained, searchable web page (no server, no build step)
  knowledge.db      a SQLite database with full-text search over every item

By default it publishes only cards whose verification status is ok or review,
leaves out items flagged as high health risk, and replaces commenter names with
"Reader 1, Reader 2..." (per card). Read verify_report.md before publishing.

Usage:
    python publish_cards.py cards_verified.jsonl \
        --comments nyt_units=comments.json \
        --article "nyt_units=Are supplements worth it?|https://www.nytimes.com/..." \
        --article "wapo_units=Supplements and the aging brain|https://www.washingtonpost.com/..." \
        --title "What readers know about supplements"

Options:
    --statuses ok           publish only cards that passed with no flags
    --include-high-risk     keep items flagged high health risk (marked with a warning)
    --show-names            show commenters' screen names instead of Reader 1, 2...

Search the database with search_knowledge.py (handles hyphens like omega-3), or in SQL:
    SELECT v.card_title, v.text FROM items_fts JOIN v_items v ON v.item_id = items_fts.rowid
    WHERE items_fts MATCH '"omega-3" AND heart' ORDER BY rank;
Quote any term containing a hyphen or other punctuation. Citations for an item:
    SELECT footnote, reader, quote, url FROM v_citations WHERE item_id = 42;
"""
import argparse
import html
import json
import os
import sqlite3
import sys

SECTIONS = [("reported_experiences", "What readers report"),
            ("claims", "What readers claim"),
            ("corrections", "Corrections and gaps readers raised"),
            ("disagreements", "Where readers disagree"),
            ("open_questions", "Open questions"),
            ("advice", "Advice readers shared")]
HEALTH_NOTE = ("These are reader experiences and claims collected from comments, not medical "
               "advice. Check with a doctor or pharmacist before changing what you take.")


def load_share_urls(specs):
    urls = {}

    def walk(cs):
        for c in cs:
            yield c
            yield from walk(c.get("replies", []))
    for spec in specs or []:
        name, _, path = spec.partition("=")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for c in walk(data if isinstance(data, list) else data.get("comments", [])):
            u = c.get("share_url") or c.get("permalink")
            if u:
                urls[(name, str(c["id"]))] = u
    return urls


def parse_articles(specs):
    out = {}
    for spec in specs or []:
        name, _, rest = spec.partition("=")
        title, _, url = rest.partition("|")
        out[name] = {"title": title.strip(), "url": url.strip()}
    return out


def prepare(cards, args, share_urls, articles):
    """Turn verified cards into the compact structure the page and database use."""
    out, skipped = [], []
    for card in cards:
        status = card.get("verification", {}).get("status", "unverified")
        if status not in args.statuses:
            skipped.append((card["topic"]["id"], card["title"], status))
            continue
        cit = card["citations"]
        names, refs = {}, {}

        def ref(key):
            """Citation key -> footnote number (assigned in order of first use)."""
            if key not in refs:
                u = cit[key]
                who = (u["source"], u["author"])
                if who not in names:
                    names[who] = u["author"] if args.show_names else f"Reader {len(names) + 1}"
                refs[key] = {"n": len(refs) + 1, "who": names[who], "quote": u["quote"],
                             "source": u["source"], "comment_id": str(u["comment_id"]),
                             "article": articles.get(u["source"], {}).get("title", u["source"]),
                             "url": share_urls.get((u["source"], str(u["comment_id"])))
                             or articles.get(u["source"], {}).get("url", "")}
            return refs[key]["n"]

        def item(it):
            v = it.get("verification", {})
            risk = v.get("health_risk", "none")
            if risk == "high" and not args.include_high_risk:
                return None
            return {"text": it.get("text") or it.get("position"),
                    "readers": it["readers"], "refs": [ref(c) for c in it["cites"]],
                    "risk": risk, "risk_note": v.get("risk_note", ""),
                    "verdict": v.get("verdict", "unverified"),
                    "revised": bool(v.get("revised", False))}

        c = {"id": card["topic"]["id"], "title": card["title"],
             "health": bool(card.get("health_related")),
             "breadth": card["topic"]["breadth"],
             "sources": sorted({articles.get(s, {}).get("title", s)
                                for s in card["topic"].get("sources", {})}),
             "source_keys": sorted(card["topic"].get("sources", {})),
             "takeaway": item(card["takeaway"]) if card.get("takeaway") else None,
             "status": status, "sections": []}
        for key, label in SECTIONS:
            if key == "disagreements":
                ds = []
                for d in card.get("disagreements", []):
                    sides = [x for x in (item(s) for s in d["sides"]) if x]
                    if len(sides) >= 2:
                        ds.append({"issue": d["issue"], "sides": sides})
                if ds:
                    c["sections"].append({"key": key, "label": label, "disagreements": ds})
            else:
                items = [x for x in (item(i) for i in card.get(key, [])) if x]
                if items:
                    c["sections"].append({"key": key, "label": label, "items": items})
        c["refs"] = sorted(refs.values(), key=lambda r: r["n"])
        out.append(c)
    return out, skipped


# ---------------- SQLite ----------------

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE articles (
    source  TEXT PRIMARY KEY,          -- e.g. nyt_units
    title   TEXT,
    url     TEXT
);

CREATE TABLE cards (
    id        TEXT PRIMARY KEY,        -- topic id from step 3, e.g. T4
    title     TEXT NOT NULL,
    takeaway  TEXT,                    -- convenience copy; the cited version is in items
    health    INTEGER NOT NULL,        -- 1 if health-related
    breadth   INTEGER,                 -- distinct readers in the whole topic
    status    TEXT                     -- verification status: ok / review / unverified
);

CREATE TABLE card_articles (
    card_id TEXT NOT NULL REFERENCES cards(id),
    source  TEXT NOT NULL REFERENCES articles(source),
    PRIMARY KEY (card_id, source)
);

CREATE TABLE disagreements (
    id       INTEGER PRIMARY KEY,
    card_id  TEXT NOT NULL REFERENCES cards(id),
    position INTEGER NOT NULL,         -- order on the card
    issue    TEXT NOT NULL
);

CREATE TABLE items (
    id              INTEGER PRIMARY KEY,
    card_id         TEXT NOT NULL REFERENCES cards(id),
    section         TEXT NOT NULL CHECK (section IN ('takeaway', 'reported_experiences',
                        'claims', 'corrections', 'disagreements', 'open_questions', 'advice')),
    position        INTEGER NOT NULL,  -- order within its section (or within its disagreement)
    disagreement_id INTEGER REFERENCES disagreements(id),  -- set only for disagreement sides
    text            TEXT NOT NULL,
    readers         INTEGER NOT NULL,  -- distinct readers cited
    health_risk     TEXT,              -- none / caution / high
    risk_note       TEXT,
    verdict         TEXT,              -- supported / partly_supported / unverified ...
    revised         INTEGER            -- 1 if the verifier reworded it
);

CREATE TABLE refs (                    -- one footnote: a quote from one comment
    id          INTEGER PRIMARY KEY,
    card_id     TEXT NOT NULL REFERENCES cards(id),
    footnote    INTEGER NOT NULL,      -- the [n] shown on the page
    source      TEXT REFERENCES articles(source),
    comment_id  TEXT,
    reader      TEXT,                  -- "Reader 3", or the screen name with --show-names
    quote       TEXT,
    url         TEXT,
    UNIQUE (card_id, footnote)
);

CREATE TABLE item_refs (
    item_id INTEGER NOT NULL REFERENCES items(id),
    ref_id  INTEGER NOT NULL REFERENCES refs(id),
    PRIMARY KEY (item_id, ref_id)
);

CREATE INDEX items_card ON items(card_id, section, position);
CREATE INDEX items_disagreement ON items(disagreement_id);
CREATE INDEX refs_comment ON refs(source, comment_id);
CREATE INDEX item_refs_ref ON item_refs(ref_id);

-- Every item with its card and (for disagreement sides) the issue it belongs to.
CREATE VIEW v_items AS
SELECT i.id AS item_id, i.card_id, c.title AS card_title, i.section, d.issue, i.text,
       i.readers, i.health_risk, i.verdict
FROM items i JOIN cards c ON c.id = i.card_id
LEFT JOIN disagreements d ON d.id = i.disagreement_id;

-- Every citation: which item cites which quote, from which comment.
CREATE VIEW v_citations AS
SELECT ir.item_id, i.card_id, i.section, i.text AS item_text, r.footnote, r.reader,
       r.quote, a.title AS article, r.comment_id, r.url
FROM item_refs ir JOIN items i ON i.id = ir.item_id JOIN refs r ON r.id = ir.ref_id
LEFT JOIN articles a ON a.source = r.source;
"""

FTS_SCHEMA = """
-- Full-text search over what readers said: the item text, the issue (for disagreement
-- sides) and the quotes from the comments the item cites. Card titles and section names
-- are not indexed, so a search for "fish" doesn't return every item on a fish card.
CREATE VIRTUAL TABLE items_fts USING fts5(text, issue, quotes, tokenize='porter unicode61');
CREATE VIRTUAL TABLE cards_fts USING fts5(card_id UNINDEXED, title, takeaway,
                                          tokenize='porter unicode61');
"""


def write_db(cards, path, articles):
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    try:
        db.executescript(FTS_SCHEMA)
        fts = True
    except sqlite3.OperationalError:
        fts = False
        print("Note: this SQLite has no FTS5; skipping the full-text index.", file=sys.stderr)

    sources = {s for c in cards for s in c["source_keys"]} | {r["source"] for c in cards for r in c["refs"]}
    db.executemany("INSERT INTO articles VALUES (?,?,?)",
                   [(s, articles.get(s, {}).get("title", s), articles.get(s, {}).get("url", ""))
                    for s in sorted(sources)])

    def add_item(card_id, section, position, it, disagreement_id=None, issue=None):
        cur = db.execute(
            "INSERT INTO items (card_id, section, position, disagreement_id, text, readers, "
            "health_risk, risk_note, verdict, revised) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (card_id, section, position, disagreement_id, it["text"], it["readers"],
             it.get("risk", "none"), it.get("risk_note", ""), it.get("verdict", "unverified"),
             int(it.get("revised", False))))
        item_id = cur.lastrowid
        db.executemany("INSERT OR IGNORE INTO item_refs VALUES (?,?)",
                       [(item_id, ref_ids[n]) for n in it["refs"]])
        if fts:
            db.execute("INSERT INTO items_fts (rowid, text, issue, quotes) VALUES (?,?,?,?)",
                       (item_id, it["text"], issue or "",
                        "\n".join(quote_by_n[n] for n in it["refs"])))

    for c in cards:
        db.execute("INSERT INTO cards VALUES (?,?,?,?,?,?)",
                   (c["id"], c["title"], c["takeaway"]["text"] if c["takeaway"] else None,
                    int(c["health"]), c["breadth"], c["status"]))
        db.executemany("INSERT INTO card_articles VALUES (?,?)",
                       [(c["id"], s) for s in c["source_keys"]])
        ref_ids = {}
        quote_by_n = {r["n"]: r["quote"] for r in c["refs"]}
        for r in c["refs"]:
            cur = db.execute("INSERT INTO refs (card_id, footnote, source, comment_id, reader, "
                             "quote, url) VALUES (?,?,?,?,?,?,?)",
                             (c["id"], r["n"], r["source"], r.get("comment_id"), r["who"],
                              r["quote"], r["url"]))
            ref_ids[r["n"]] = cur.lastrowid
        if c["takeaway"]:
            add_item(c["id"], "takeaway", 0, c["takeaway"])
        for s in c["sections"]:
            for pos, it in enumerate(s.get("items", [])):
                add_item(c["id"], s["key"], pos, it)
            for dpos, d in enumerate(s.get("disagreements", [])):
                did = db.execute("INSERT INTO disagreements (card_id, position, issue) VALUES (?,?,?)",
                                 (c["id"], dpos, d["issue"])).lastrowid
                for pos, side in enumerate(d["sides"]):
                    add_item(c["id"], s["key"], pos, side, did, d["issue"])
        if fts:
            db.execute("INSERT INTO cards_fts VALUES (?,?,?)",
                       (c["id"], c["title"], c["takeaway"]["text"] if c["takeaway"] else ""))

    problems = db.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"foreign key problems: {problems[:5]}")
    db.commit()
    db.execute("VACUUM")
    db.close()


# ---------------- HTML ----------------

PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#faf9f6;--card:#fff;--ink:#1f1e1c;--muted:#6b6863;--line:#e4e1da;--accent:#3c5a99;--warn:#9a5b00;--warnbg:#fdf3e1}
@media (prefers-color-scheme:dark){:root{--bg:#191917;--card:#22221f;--ink:#ecebe6;--muted:#a3a19a;--line:#3a3935;--accent:#9db5ea;--warn:#f0b65c;--warnbg:#3a2f1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
header{max-width:860px;margin:0 auto;padding:40px 20px 8px}h1{font-size:30px;margin:0 0 6px;font-weight:600}
.sub{color:var(--muted);margin:0 0 18px}
.tools{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:6px}
input[type=search]{flex:1 1 100%;min-width:220px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font-size:15px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer}
.chip[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--bg)}
main{max-width:860px;margin:0 auto;padding:8px 20px 60px}.count{color:var(--muted);font-size:14px;margin:8px 0 14px}
article{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin:0 0 18px}
article h2{font-size:21px;margin:0 0 4px;font-weight:600}.meta{color:var(--muted);font-size:13px;margin-bottom:12px}
.take{font-size:17px;margin:0 0 12px}.note{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:8px 12px;font-size:13px;margin:0 0 12px}
h3{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:18px 0 6px;font-weight:600}
ul{margin:0;padding-left:20px}li{margin:4px 0}.n{color:var(--muted);font-size:13px;white-space:nowrap}
sup a{color:var(--accent);text-decoration:none;font-size:11px;margin-left:1px}.issue{font-weight:600}
.flag{color:var(--warn);font-size:12px;font-weight:600;margin-left:4px}
.via{color:var(--muted);font-size:12px;font-style:italic;margin-left:6px}
details{margin-top:14px;font-size:14px}summary{cursor:pointer;color:var(--accent)}
ol.refs{padding-left:24px;color:var(--muted)}ol.refs li:target{background:var(--warnbg)}ol.refs a{color:var(--accent)}
mark{background:#ffe58a;color:inherit;border-radius:2px}
footer{max-width:860px;margin:0 auto;padding:0 20px 40px;color:var(--muted);font-size:13px}
</style></head><body>
<header><h1 id="title"></h1><p class="sub" id="sub"></p>
<div class="tools"><input type="search" id="q" placeholder="Search what readers said, e.g. vitamin D, fish oil, omega-3" aria-label="Search">
<span id="chips"></span></div></header>
<main><div class="count" id="count"></div><div id="cards"></div></main>
<footer id="foot"></footer>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (t, cls, txt) => { const e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
document.getElementById('title').textContent = D.title;
document.title = D.title;
document.getElementById('sub').textContent = D.subtitle;
document.getElementById('foot').textContent = D.footer;
const filters = [['all','All'],['reported_experiences','Experiences'],['claims','Claims'],['corrections','Corrections'],['disagreements','Disagreements'],['open_questions','Questions'],['advice','Advice']];
let active = 'all';
const chips = document.getElementById('chips');
filters.forEach(([k, label]) => { const b = $('button', 'chip', label); b.type = 'button'; b.setAttribute('aria-pressed', k === active);
  b.onclick = () => { active = k; chips.querySelectorAll('.chip').forEach(c => c.setAttribute('aria-pressed', c === b)); render(); }; chips.appendChild(b); });
// Search: the whole query is matched as a phrase, case-insensitively, on word
// boundaries ("vitamin d" matches "Vitamin D" but not "vitamin deficiency").
function makeRe(q, flags) {
  if (!q) return null;
  let src = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
  if (/^\w/.test(q)) src = '\\b' + src;
  if (/\w$/.test(q)) src = src + '\\b';
  return new RegExp(src, flags || 'i');
}
let RE = null, REG = null;
const hit = t => !!(RE && t && RE.test(t));
function textWithMarks(el, text) {
  if (!REG) { el.appendChild(document.createTextNode(text)); return; }
  let i = 0, m; REG.lastIndex = 0;
  while ((m = REG.exec(text)) !== null) {
    if (!m[0].length) { REG.lastIndex++; continue; }
    el.appendChild(document.createTextNode(text.slice(i, m.index)));
    el.appendChild($('mark', null, m[0])); i = m.index + m[0].length;
  }
  el.appendChild(document.createTextNode(text.slice(i)));
}
function refsOf(card) { if (!card._byN) { card._byN = {}; card.refs.forEach(r => card._byN[r.n] = r); } return card._byN; }
// An item matches if its own text matches, or if a comment it cites does.
function itemHit(it, card) { return hit(it.text) || it.refs.some(n => hit(refsOf(card)[n].quote)); }
function line(el, it, card) {
  textWithMarks(el, it.text);
  el.appendChild(document.createTextNode(' '));
  el.appendChild($('span', 'n', '(' + it.readers + (it.readers === 1 ? ' reader)' : ' readers)')));
  it.refs.forEach(n => { const s = $('sup'); const a = $('a', null, '[' + n + ']'); a.href = '#' + card.id + '-r' + n;
    a.onclick = () => { card._det && (card._det.open = true); }; s.appendChild(a); el.appendChild(s); });
  if (it.risk === 'high') el.appendChild($('span', 'flag', 'check with a doctor'));
  else if (it.risk === 'caution') el.appendChild($('span', 'flag', 'unconfirmed'));
  if (RE && !hit(it.text)) {
    const via = it.refs.filter(n => hit(refsOf(card)[n].quote));
    if (via.length) el.appendChild($('span', 'via', 'match in source ' + via.map(n => '[' + n + ']').join('')));
  }
}
function render() {
  const q = document.getElementById('q').value.trim();
  RE = makeRe(q); REG = makeRe(q, 'gi');
  const root = document.getElementById('cards'); root.replaceChildren();
  let shownCards = 0, shownItems = 0;
  D.cards.forEach(card => {
    // Keep only the sections, items and disagreements that match the filter and the search.
    const secs = [];
    card.sections.forEach(s => {
      if (active !== 'all' && s.key !== active) return;
      const items = (s.items || []).filter(it => !RE || itemHit(it, card));
      const dis = (s.disagreements || []).filter(d => !RE || hit(d.issue) || d.sides.some(x => itemHit(x, card)));
      if (items.length || dis.length) secs.push({ label: s.label, items, dis });
    });
    const headHit = RE && active === 'all' && (hit(card.title) || (card.takeaway && itemHit(card.takeaway, card)));
    if (!secs.length && !headHit) return;
    shownCards++;
    const a = $('article'); a.id = card.id;
    const h = $('h2'); textWithMarks(h, card.title); a.appendChild(h);
    a.appendChild($('div', 'meta', card.breadth + ' readers took part · from comments on ' + card.sources.join(' and ')));
    const used = new Set();
    const use = it => it.refs.forEach(n => used.add(n));
    if (card.takeaway) { const p = $('p', 'take'); line(p, card.takeaway, card); a.appendChild(p); use(card.takeaway); }
    if (card.health) a.appendChild($('div', 'note', D.health_note));
    secs.forEach(s => {
      a.appendChild($('h3', null, s.label));
      const ul = $('ul');
      s.items.forEach(it => { const li = $('li'); line(li, it, card); ul.appendChild(li); use(it); shownItems++; });
      s.dis.forEach(d => { const li = $('li'); const b = $('span', 'issue'); textWithMarks(b, d.issue); li.appendChild(b);
        const sub = $('ul'); d.sides.forEach(x => { const sl = $('li'); line(sl, x, card); sub.appendChild(sl); use(x); shownItems++; });
        li.appendChild(sub); ul.appendChild(li); });
      a.appendChild(ul);
    });
    // Sources: only the comments cited by what is shown; opened automatically when one matches.
    const refs = card.refs.filter(r => !RE || used.has(r.n));
    const det = $('details'); card._det = det;
    det.appendChild($('summary', null, 'Sources (' + refs.length + ' comment' + (refs.length === 1 ? '' : 's') + ')'));
    const ol = $('ol', 'refs');
    refs.forEach(r => { const li = $('li'); li.id = card.id + '-r' + r.n; li.value = r.n;
      li.appendChild(document.createTextNode('“')); textWithMarks(li, r.quote);
      li.appendChild(document.createTextNode('” — ' + r.who + ', on '));
      if (r.url) { const l = $('a', null, r.article); l.href = r.url; l.target = '_blank'; l.rel = 'noopener'; li.appendChild(l); }
      else li.appendChild(document.createTextNode(r.article));
      ol.appendChild(li); });
    if (RE && refs.some(r => hit(r.quote))) det.open = true;
    det.appendChild(ol); a.appendChild(det);
    root.appendChild(a);
  });
  document.getElementById('count').textContent = RE
    ? shownItems + ' matching item' + (shownItems === 1 ? '' : 's') + ' in ' + shownCards + ' of ' + D.cards.length + ' topics'
    : shownCards + ' of ' + D.cards.length + ' topics';
}
// A search can be linked to: index.html?q=vitamin%20D&section=advice
const params = new URLSearchParams(location.search);
if (params.get('q')) document.getElementById('q').value = params.get('q');
if (filters.some(([k]) => k === params.get('section'))) {
  active = params.get('section');
  chips.querySelectorAll('.chip').forEach((c, i) => c.setAttribute('aria-pressed', filters[i][0] === active));
}
document.getElementById('q').addEventListener('input', render);
render();
</script></body></html>"""


def write_site(cards, path, title, articles):
    sources = sorted({s for c in cards for s in c["sources"]})
    data = {
        "title": title,
        "subtitle": (f"{len(cards)} topics from reader comments on " + " and ".join(sources) +
                     ". Every statement links to the comments behind it; reader counts are "
                     "the number of different people cited."),
        "footer": ("Summaries were generated by AI from reader comments, checked against the full "
                   "comments, and reflect what readers wrote, not established fact."),
        "health_note": HEALTH_NOTE,
        "cards": cards,
    }
    # Escape every "<" so no comment text can open or close a tag inside the data block.
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    page = PAGE.replace("__TITLE__", html.escape(title)).replace("__DATA__", blob)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cards", help="cards_verified.jsonl from verify_cards.py")
    ap.add_argument("--comments", nargs="+", metavar="SOURCE=PATH",
                    help="comment files, used for per-comment links (NYT share links)")
    ap.add_argument("--article", action="append", metavar='SOURCE="Title|URL"',
                    help='article each source came from, e.g. nyt_units="Headline|https://..."')
    ap.add_argument("--title", default="What readers know: community knowledge from comments")
    ap.add_argument("--statuses", default="ok,review",
                    help="verification statuses to publish (ok, review, hold, unverified)")
    ap.add_argument("--include-high-risk", action="store_true")
    ap.add_argument("--show-names", action="store_true")
    ap.add_argument("--site", default="site/index.html")
    ap.add_argument("--db", default="knowledge.db")
    args = ap.parse_args()
    args.statuses = set(s.strip() for s in args.statuses.split(","))

    with open(args.cards, encoding="utf-8") as f:
        cards = [json.loads(l) for l in f if l.strip()]
    articles = parse_articles(args.article)
    cards_out, skipped = prepare(cards, args, load_share_urls(args.comments), articles)
    if not cards_out:
        sys.exit("No cards to publish with --statuses " + ",".join(sorted(args.statuses)))
    write_site(cards_out, args.site, args.title, articles)
    write_db(cards_out, args.db, articles)
    for cid, title, status in skipped:
        print(f"  skipped {cid} ({status}): {title}", file=sys.stderr)
    n_items = sum(len(s.get("items", [])) + sum(len(d["sides"]) for d in s.get("disagreements", []))
                  for c in cards_out for s in c["sections"])
    print(f"Published {len(cards_out)} cards ({n_items} items) to {args.site} and {args.db}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
