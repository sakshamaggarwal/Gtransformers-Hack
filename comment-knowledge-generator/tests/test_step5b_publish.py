"""Group F: step 5b, publishing the page and database (publish_cards.py, search_knowledge.py)."""
import json
import re
import sqlite3

import pytest

from conftest import load, run

vf = load("verify_cards")

NYT_ARTICLE = "nyt_units=Supplements survey|https://www.nytimes.com/2026/09/11/example.html"
WAPO_ARTICLE = "wapo_units=Supplements and the brain|https://www.washingtonpost.com/example/"


def verified(cards, path):
    """Scripted verification: T1's hypercalcemia report is high-risk, T4 is put on hold."""
    with open(path, "w", encoding="utf-8") as f:
        for card in cards:
            items = []
            for item_id, it, _ in vf.iter_items(card):
                risky = "hypercalcemia" in (it.get("text") or "")
                items.append({"id": item_id, "verdict": "supported", "problems": [],
                              "unsupporting_cites": [], "revised_text": "",
                              "health_risk": "high" if risky else "none",
                              "risk_note": "dose" if risky else ""})
            out, _ = vf.apply_review(card, {"coherent": card["topic"]["id"] != "T4",
                                            "coherence_note": "", "title_fix": "", "items": items})
            f.write(json.dumps(out) + "\n")
    return path


def publish(work, cards, *extra):
    src = verified(cards, work / "verified.jsonl")
    p = run("publish_cards.py", src, "--comments", f"nyt_units={work / 'nyt_comments.json'}",
            f"wapo_units={work / 'wapo_comments.json'}", "--article", NYT_ARTICLE,
            "--article", WAPO_ARTICLE, "--site", work / "site" / "index.html",
            "--db", work / "knowledge.db", *extra)
    page = (work / "site" / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'id="data">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
    return p, page, data, sqlite3.connect(work / "knowledge.db")


def all_texts(data):
    out = []
    for c in data["cards"]:
        for s in c["sections"]:
            out += [i["text"] for i in s.get("items", [])]
            out += [x["text"] for d in s.get("disagreements", []) for x in d["sides"]]
    return out


def test_F01_held_cards_not_published(work, cards):
    p, _, data, db = publish(work, cards)
    assert "skipped T4 (hold)" in p.stderr
    assert [c["id"] for c in data["cards"]] == ["T1", "T2", "T3"]
    assert db.execute("SELECT count(*) FROM cards WHERE id='T4'").fetchone()[0] == 0


def test_F02_high_risk_items_excluded_by_default(work, cards):
    _, _, data, db = publish(work, cards)
    assert not any("hypercalcemia" in t for t in all_texts(data))
    assert db.execute("SELECT count(*) FROM items WHERE health_risk='high'").fetchone()[0] == 0
    _, _, data, db = publish(work, cards, "--include-high-risk")
    assert any("hypercalcemia" in t for t in all_texts(data))
    assert db.execute("SELECT count(*) FROM items WHERE health_risk='high'").fetchone()[0] == 1


def test_F03_names_hidden_unless_requested(work, cards):
    names = {u["author"] for c in cards for u in c["citations"].values()}
    _, page, _, db = publish(work, cards)
    db_text = json.dumps(db.execute("SELECT * FROM refs").fetchall())
    assert not any(n in page or n in db_text for n in names)
    _, page, _, _ = publish(work, cards, "--show-names")
    assert "Mara K." in page


def test_F04_database_integrity_and_no_orphan_quotes(work, cards):
    _, _, _, db = publish(work, cards)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("SELECT count(*) FROM refs WHERE id NOT IN (SELECT ref_id FROM item_refs)").fetchone()[0] == 0


def test_F05_takeaways_stored_with_citations(work, cards):
    _, _, _, db = publish(work, cards)
    rows = db.execute("SELECT i.card_id, count(ir.ref_id) FROM items i JOIN item_refs ir ON ir.item_id = i.id "
                      "WHERE i.section='takeaway' GROUP BY i.card_id").fetchall()
    assert len(rows) == 3 and all(n >= 1 for _, n in rows)


def fts(db, query):
    return db.execute("SELECT v.text, v.issue, items_fts.quotes FROM items_fts "
                      "JOIN v_items v ON v.item_id = items_fts.rowid WHERE items_fts MATCH ?",
                      (query,)).fetchall()


def test_F06_search_ignores_card_titles_and_section_names(work, cards):
    _, _, _, db = publish(work, cards)
    hits = fts(db, '"fish"')
    assert hits and all("fish" in " ".join(filter(None, h)).lower() for h in hits)
    assert not any("algae-based" in h[0] for h in hits)   # on the "Fish oil" card, no fish in it
    assert fts(db, '"claims"') == []


def test_F07_hyphenated_search_works(work, cards):
    publish(work, cards)
    p = run("search_knowledge.py", "omega-3", "--db", work / "knowledge.db")
    assert "omega-3" in p.stdout.lower() and "no such column" not in p.stderr


def test_F08_item_found_through_quoted_comment(work, cards):
    publish(work, cards)
    p = run("search_knowledge.py", "Consumer Lab", "--db", work / "knowledge.db")
    assert "independent tester" in p.stdout
    assert "(matched in a quoted comment)" in p.stdout and "Consumer Lab tests" in p.stdout


def test_F09_comment_text_cannot_inject_markup(work, cards):
    evil = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>'
    t2 = next(c for c in cards if c["topic"]["id"] == "T2")
    next(iter(t2["citations"].values()))["quote"] = evil
    _, page, data, _ = publish(work, cards)
    assert "</script><img" not in page
    assert page.count("<script") == 2          # only the data block and the page script
    quotes = [r["quote"] for c in data["cards"] for r in c["refs"]]
    assert evil in quotes                       # round-trips as plain text


def test_F10_links_per_comment_or_article(work, cards):
    _, _, data, _ = publish(work, cards)
    refs = [r for c in data["cards"] for r in c["refs"]]
    assert all("/shared/comment/fx" in r["url"] for r in refs if r["source"] == "nyt_units")
    assert all(r["url"] == "https://www.washingtonpost.com/example/" for r in refs if r["source"] == "wapo_units")
