"""Group C: step 3, clustering and scoring (cluster_units.py), offline with --embedder tfidf."""
import json
import math

import numpy as np

from conftest import load, run

cl = load("cluster_units")
WEIGHTS = {"breadth": 1.0, "endorsement": 0.5, "expertise": 1.0}


def all_units(topics):
    return [u for t in topics for p in t["points"] for u in p["units"]]


def cluster(work, *extra):
    run("cluster_units.py", work / "nyt_units.jsonl", work / "wapo_units.jsonl",
        "--embedder", "tfidf", "-o", work / "clusters.json", *extra)
    return json.loads((work / "clusters.json").read_text())


def test_C01_every_unit_in_exactly_one_topic_and_point(work):
    data = cluster(work)
    uids = [u["uid"] for u in all_units(data["topics"])]
    assert data["n_units"] == 18
    assert len(uids) == len(set(uids)) == 18
    assert sum(t["n_units"] for t in data["topics"]) == 18


def test_C02_breadth_counts_distinct_readers(work):
    units, replies = cl.load_units([str(work / "nyt_units.jsonl")])
    mara = [i for i, u in enumerate(units) if u["author"] == "Mara K."]
    assert len(mara) == 3
    s = cl.stats(mara, units, replies, cl.endorsement_scale(units), WEIGHTS)
    assert s["n_units"] == 3 and s["breadth"] == 1


def test_C03_endorsement_log_scaled_and_normalised_per_source(work):
    units, replies = cl.load_units([str(work / "nyt_units.jsonl"), str(work / "wapo_units.jsonl")])
    scale = cl.endorsement_scale(units)
    assert set(scale) == {"nyt_units", "wapo_units"} and all(v > 0 for v in scale.values())
    raj = [i for i, u in enumerate(units) if u["author"] == "Raj S."]   # 40 recommendations
    s = cl.stats(raj, units, replies, scale, WEIGHTS)
    assert math.isclose(s["endorsement"], round(math.log1p(40) / scale["nyt_units"], 2), abs_tol=0.01)
    assert s["endorsement"] < 40 / 4   # nowhere near the raw count


def test_C04_same_comment_id_in_two_sources_not_merged(tmp_path):
    row = {"comment_id": "1", "author": "A", "depth": 0, "parent_id": None, "endorsement": 0,
           "units": [{"type": "claim", "statement": "x", "topic": "t", "stance": "extends",
                      "quote": "x", "quote_verified": True}]}
    for name in ("first.jsonl", "second.jsonl"):
        (tmp_path / name).write_text(json.dumps(row) + "\n")
    units, _ = cl.load_units([str(tmp_path / "first.jsonl"), str(tmp_path / "second.jsonl")])
    assert {u["uid"] for u in units} == {"first:1:0", "second:1:0"}


def test_C05_pushback_counts_other_readers_corrections(tmp_path):
    rows = [
        {"comment_id": "p", "author": "A", "parent_id": None, "endorsement": 0,
         "units": [{"type": "claim", "statement": "s", "topic": "t", "stance": "extends", "quote": "q"}]},
        {"comment_id": "r1", "author": "B", "parent_id": "p", "endorsement": 0,
         "units": [{"type": "correction", "statement": "no", "topic": "t", "stance": "extends", "quote": "q"}]},
        {"comment_id": "r2", "author": "A", "parent_id": "p", "endorsement": 0,     # self-reply
         "units": [{"type": "correction", "statement": "no", "topic": "t", "stance": "disputes", "quote": "q"}]},
    ]
    path = tmp_path / "u.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    units, replies = cl.load_units([str(path)])
    s = cl.stats([0], units, replies, cl.endorsement_scale(units), WEIGHTS)
    assert s["pushback_replies"] == 1


def test_C06_topics_sorted_and_markdown_written(work):
    data = cluster(work)
    scores = [t["score"] for t in data["topics"]]
    assert scores == sorted(scores, reverse=True)
    assert [t["id"] for t in data["topics"]] == [f"T{i}" for i in range(1, len(scores) + 1)]
    assert (work / "clusters.md").read_text().startswith("# Top")


def test_C07_sweep_prints_table_and_writes_nothing(work):
    p = run("cluster_units.py", work / "nyt_units.jsonl", work / "wapo_units.jsonl",
            "--embedder", "tfidf", "-o", work / "clusters.json", "--sweep")
    table = [l for l in p.stdout.splitlines() if l.strip() and l.strip()[0].isdigit()]
    assert len(table) == 12
    assert not (work / "clusters.json").exists()


def test_C08_drop_unverified(work):
    rows = [json.loads(l) for l in (work / "nyt_units.jsonl").read_text().splitlines()]
    rows[0]["units"][0]["quote_verified"] = False
    (work / "nyt_units.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert cluster(work)["n_units"] == 18
    assert cluster(work, "--drop-unverified")["n_units"] == 17
