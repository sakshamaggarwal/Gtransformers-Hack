"""Group D: step 4, writing cited cards (synthesize_cards.py), with a mock model."""
import json

from conftest import FakeClient, load, read_jsonl, run, text_reply, tool_reply

sy = load("synthesize_cards")


def make_topic(n_points=3, repeat_reader=True):
    """A synthetic step-3 topic: each point has two units by reader R0 plus others."""
    points = []
    for p in range(n_points):
        units = []
        for k in range(4):
            author = "R0" if (repeat_reader and k < 2) else f"R{p}{k}"
            units.append({"uid": f"s:{p}{k}:0", "source": "s", "comment_id": f"{p}{k}",
                          "author": author, "type": "claim", "stance": "extends",
                          "statement": f"Statement {p}{k}", "quote": f"quote {p}{k}",
                          "endorsement": 1, "expertise_claimed": None, "quote_verified": True})
        points.append({"breadth": 3, "units": units})
    return {"id": "T9", "label": "test topic", "score": 9.0, "breadth": 9, "n_units": 4 * n_points,
            "stance_counts": {"extends": 4 * n_points}, "contested": 0.0, "sources": {"s": 4 * n_points},
            "points": points}


def test_D01_evidence_pack_one_unit_per_reader_per_point_capped():
    text, keys, cov = sy.build_pack(make_topic(3), max_points=2, units_per_point=6,
                                    include_unverified=False)
    assert cov == {"points_total": 3, "points_used": 2, "units_total": 12, "units_used": 6}
    per_point = {}
    for u in keys.values():
        per_point.setdefault(u["comment_id"][0], []).append(u["author"])
    assert all(len(a) == len(set(a)) for a in per_point.values())
    assert "Only the top 2 of 3 points" in text


def test_D02_unknown_keys_dropped_and_brackets_accepted():
    _, keys, _ = sy.build_pack(make_topic(1), 25, 6, False)
    raw = {"title": "T", "health_related": False, "takeaway": {"text": "t", "cites": ["[c1]"]},
           "reported_experiences": [], "corrections": [], "open_questions": [], "advice": [],
           "claims": [{"text": "kept", "cites": ["c2", "c9999"]}, {"text": "gone", "cites": ["c9999"]}],
           "disagreements": []}
    card, dropped = sy.resolve_card(raw, keys)
    assert card["takeaway"]["cites"] == ["c1"]
    assert [c["text"] for c in card["claims"]] == ["kept"] and card["claims"][0]["cites"] == ["c2"]
    assert dropped == 1


def test_D03_reader_counts_from_citations():
    keys = {"c1": {"source": "s", "author": "Same"}, "c2": {"source": "s", "author": "Same"},
            "c3": {"source": "s", "author": "Other"}}
    assert sy.readers(["c1", "c2"], keys) == 1
    assert sy.readers(["c1", "c2", "c3"], keys) == 2


def test_D04_one_sided_disagreement_dropped():
    _, keys, _ = sy.build_pack(make_topic(1), 25, 6, False)
    raw = {"title": "T", "health_related": False, "takeaway": {"text": "t", "cites": ["c1"]},
           **{s: [] for s in sy.SECTIONS},
           "disagreements": [{"issue": "x", "sides": [{"position": "a", "cites": ["c1"]},
                                                       {"position": "b", "cites": ["c999"]}]}]}
    card, dropped = sy.resolve_card(raw, keys)
    assert card["disagreements"] == [] and dropped == 2


def test_D05_request_uses_auto_choice_and_strict_tool():
    client = FakeClient(tool_reply("record_card", {}))
    sy.synthesize(client, "claude-sonnet-5-5", "evidence")
    _, kw = client.calls[0]
    assert kw["tool_choice"] == {"type": "auto"}
    tool = kw["tools"][0]
    assert tool["strict"] is True

    def objects(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                yield s
            for v in s.values():
                yield from objects(v)
        elif isinstance(s, list):
            for v in s:
                yield from objects(v)
    assert all(o.get("additionalProperties") is False for o in objects(tool["input_schema"]))


def test_D06_retries_once_after_prose_answer():
    client = FakeClient(text_reply(), tool_reply("record_card", {"title": "ok"}))
    raw, _ = sy.synthesize(client, "claude-sonnet-5-5", "evidence")
    assert raw == {"title": "ok"} and len(client.calls) == 2
    assert client.calls[1][1]["messages"][-1]["role"] == "user"


def test_D07_rerun_skips_done_and_force_replaces(work):
    clusters = {"topics": [dict(make_topic(2), id=f"T{i}", breadth=6) for i in (1, 2)]}
    (work / "clusters.json").write_text(json.dumps(clusters))
    out = work / "cards.out.jsonl"
    run("synthesize_cards.py", work / "clusters.json", "-o", out)
    p = run("synthesize_cards.py", work / "clusters.json", "-o", out)
    assert "2 already done" in p.stderr
    run("synthesize_cards.py", work / "clusters.json", "-o", out, "--topics", "T1", "--force")
    ids = [c["topic"]["id"] for c in read_jsonl(out)]
    assert ids == ["T1", "T2"]


def test_D08_health_note_in_markdown(tmp_path, cards):
    for c in cards:
        c["coverage"] = c.get("coverage", {"units_used": 1, "points_used": 1, "points_total": 1})
    sy.render_markdown(cards, tmp_path / "cards.md")
    md = (tmp_path / "cards.md").read_text()
    assert md.count(sy.HEALTH_NOTE) == sum(1 for c in cards if c["health_related"]) == 3
