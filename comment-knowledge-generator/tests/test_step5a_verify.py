"""Group E: step 5a, verifying cards against full comments (verify_cards.py)."""
import copy

from conftest import FakeClient, fixture_path, load, read_jsonl, run, tool_reply

vf = load("verify_cards")
COMMENTS = [f"nyt_units={fixture_path('nyt_comments.json')}",
            f"wapo_units={fixture_path('wapo_comments.json')}"]


def by_id(cards, tid):
    return next(c for c in cards if c["topic"]["id"] == tid)


def review(card, **overrides):
    """A review marking every item supported, with per-item overrides."""
    items = []
    for item_id, it, _ in vf.iter_items(card):
        r = {"id": item_id, "verdict": "supported", "problems": [], "unsupporting_cites": [],
             "revised_text": "", "health_risk": "none", "risk_note": ""}
        r.update(overrides.get(item_id, {}))
        items.append(r)
    return {"coherent": overrides.get("_coherent", True), "coherence_note": "", "title_fix": "",
            "items": items}


def test_E01_missing_comment_and_altered_quote_flagged(cards):
    cards = copy.deepcopy(cards)
    t1 = by_id(cards, "T1")
    t1["citations"]["c1"]["comment_id"] = "does-not-exist"
    t1["citations"]["c2"]["quote"] = "a sentence nobody wrote"
    vf.code_checks(cards, vf.load_comments(COMMENTS))
    assert t1["citations"]["c1"]["code_flags"] == ["comment_not_found"]
    assert t1["citations"]["c2"]["code_flags"] == ["quote_not_in_comment"]
    assert all(not u["code_flags"] for c in cards if c is not t1 for u in c["citations"].values()
               if u["author"] not in ("SunnyDays", "OakTree", "RiverRun"))


def test_E02_echo_quotes_flagged(cards):
    vf.code_checks(cards, vf.load_comments(COMMENTS))
    t4 = by_id(cards, "T4")
    assert {u["author"] for u in t4["citations"].values() if "echo_quote" in u["code_flags"]} == \
        {"SunnyDays", "OakTree", "RiverRun"}


def test_E03_plural_wording_over_one_reader_flagged(cards):
    vf.code_checks(cards, vf.load_comments(COMMENTS))
    claim = by_id(cards, "T1")["claims"][0]
    assert any(f.startswith("count_wording") for f in claim["code_flags"])


def test_E04_addressing_another_commenter_not_flagged():
    cit = {"c1": {"source": "s", "author": "A"}}
    assert vf.count_wording_issue("One reader suggests another commenter try flax seeds.", ["c1"], cit) is None
    assert vf.count_wording_issue("One reader asks whether another commenter has tried drops.", ["c1"], cit) is None
    assert vf.count_wording_issue("One reader says X. Another reader says Y.", ["c1"], cit) is not None


def test_E05_verdicts_applied_and_counts_recomputed(cards):
    t1 = by_id(cards, "T1")
    advice = t1["advice"][0]          # cites Mara K. + Tom B.
    tom_key = advice["cites"][1]
    rv = review(t1, **{
        "claims.0": {"verdict": "unsupported", "problems": ["overstated"]},
        "advice.0": {"verdict": "partly_supported", "unsupporting_cites": [tom_key],
                     "revised_text": "One reader advises getting tested before starting supplements.",
                     "problems": ["count_wording"]}})
    out, log = vf.apply_review(t1, rv)
    assert out["claims"] == []
    assert out["advice"][0]["text"].startswith("One reader advises")
    assert out["advice"][0]["cites"] == [advice["cites"][0]] and out["advice"][0]["readers"] == 1
    # still kept as a citation, because the takeaway cites Tom B. too
    assert tom_key in out["takeaway"]["cites"] and tom_key in out["citations"]
    assert out["verification"]["items_removed"] == 1 and out["verification"]["items_revised"] == 1


def test_E06_same_reader_on_every_side_removed(cards):
    vf.code_checks(cards, vf.load_comments(COMMENTS))
    t4 = by_id(cards, "T4")
    assert any("one reader on every side" in f for f in t4["code_flags"])
    out, _ = vf.apply_review(t4, review(t4))
    assert out["disagreements"] == []


def test_E07_card_status_rules(cards):
    t2 = by_id(cards, "T2")
    assert vf.apply_review(t2, review(t2))[0]["verification"]["status"] == "ok"
    assert vf.apply_review(t2, review(t2, _coherent=False))[0]["verification"]["status"] == "hold"
    assert vf.apply_review(t2, review(t2, takeaway={"verdict": "unsupported"}))[0]["verification"]["status"] == "hold"
    many = {i: {"verdict": "unsupported"} for i, _, _ in list(vf.iter_items(t2))[1:]}
    assert vf.apply_review(t2, review(t2, **many))[0]["verification"]["status"] == "hold"
    risky = vf.apply_review(t2, review(t2, **{"claims.0": {"health_risk": "high", "risk_note": "x"}}))[0]
    assert risky["verification"]["status"] == "review" and risky["verification"]["high_risk"] == 1


def test_E08_review_request_is_streamed(cards):
    t2 = by_id(cards, "T2")
    client = FakeClient(tool_reply("record_review", review(t2)))
    vf.review_card(client, "claude-sonnet-5-5", "prompt")
    kind, kw = client.calls[0]
    assert kind == "stream"
    assert kw["tool_choice"] == {"type": "auto"} and kw["tools"][0]["strict"] is True


def test_E09_no_llm_runs_offline_and_writes_report(work):
    log = work / "calls.jsonl"
    run("verify_cards.py", work / "cards.jsonl", "--comments",
        f"nyt_units={work / 'nyt_comments.json'}", f"wapo_units={work / 'wapo_comments.json'}",
        "--no-llm", "-o", work / "verified.jsonl", env={"MOCK_LOG": str(log)})
    assert not log.exists()
    assert len(read_jsonl(work / "verified.jsonl")) == 4
    report = (work / "verify_report.md").read_text()
    assert "echo_quote" in report and "count_wording" in report


def test_E10_full_model_review_with_mock(work):
    log = work / "calls.jsonl"
    run("verify_cards.py", work / "cards.jsonl", "--comments",
        f"nyt_units={work / 'nyt_comments.json'}", f"wapo_units={work / 'wapo_comments.json'}",
        "-o", work / "verified.jsonl", env={"MOCK_LOG": str(log)})
    calls = [l for l in log.read_text().splitlines() if l]
    assert len(calls) == 4 and all('"streamed": true' in l for l in calls)
    statuses = {c["topic"]["id"]: c["verification"]["status"] for c in read_jsonl(work / "verified.jsonl")}
    assert statuses["T2"] == "ok" and statuses["T4"] == "review"
