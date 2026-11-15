"""Group B: step 2, extracting knowledge units (extract_units.py), with a mock model."""
import json

from conftest import FakeClient, load, read_jsonl, run, tool_reply

ex = load("extract_units")


def items(work):
    return list(ex.flatten(ex.load_comments(str(work / "nyt_comments.json"))))


def test_B01_dry_run_makes_no_api_call(work):
    log = work / "calls.jsonl"
    p = run("extract_units.py", work / "nyt_comments.json", "--title", "Supplements",
            "--dry-run", "--limit", "3", env={"MOCK_LOG": str(log)})
    assert "=== SYSTEM ===" in p.stdout
    assert p.stdout.count("=== USER") == 3
    assert not log.exists()


def test_B02_replies_get_root_and_parent_context(work):
    lena, anc = next((c, a) for c, a in items(work) if c["author"] == "Lena P.")
    msg = ex.build_user_message(lena, anc)
    assert "Root comment by Mara K." in msg
    assert "Parent comment (1 replies omitted between) by Mara K." in msg
    assert msg.rstrip().endswith(lena["text"])
    top, anc0 = items(work)[0]
    assert "THREAD CONTEXT" not in ex.build_user_message(top, anc0)


def test_B03_malformed_units_dropped_and_stance_normalised():
    units = [{"type": "made_up", "statement": "x", "quote": "a"},
             {"type": "claim", "statement": "", "quote": "a"},
             {"type": "claim", "statement": "Fine.", "stance": "weird", "topic": "Vitamin D",
              "quote": "vitamin D"}]
    out = ex.validate_units(units, "Some text about vitamin D.")
    assert len(out) == 1
    assert out[0]["stance"] == "unrelated" and out[0]["topic"] == "vitamin d"


def test_B04_quote_check_tolerant_but_strict():
    text = "Supplements aren’t   regulated, so you never know."
    ok = ex.validate_units([{"type": "claim", "statement": "s", "stance": "extends", "topic": "t",
                             "quote": "Supplements aren't regulated"}], text)
    bad = ex.validate_units([{"type": "claim", "statement": "s", "stance": "extends", "topic": "t",
                              "quote": "Supplements are always safe"}], text)
    assert ok[0]["quote_verified"] is True
    assert bad[0]["quote_verified"] is False


def test_B05_short_comments_skipped(work):
    log = work / "calls.jsonl"
    run("extract_units.py", work / "nyt_comments.json", "--title", "T", "-o", work / "u.jsonl",
        env={"MOCK_LOG": str(log)})
    authors = [json.loads(l)["author"] for l in log.read_text().splitlines()]
    assert "Cy N." not in authors
    assert len(authors) == 8


def test_B06_failure_does_not_stop_run_and_rerun_retries_it(work):
    log, once = work / "calls.jsonl", work / "failed_once"
    env = {"MOCK_LOG": str(log), "MOCK_FAIL_AUTHOR": "Raj S.", "MOCK_FAIL_ONCE_FILE": str(once)}
    p = run("extract_units.py", work / "nyt_comments.json", "--title", "T", "-o", work / "u.jsonl", env=env)
    assert "Raj S." not in {r["author"] for r in read_jsonl(work / "u.jsonl")}
    assert len(read_jsonl(work / "u.jsonl")) == 7
    assert "re-run" in p.stderr
    log.unlink()
    run("extract_units.py", work / "nyt_comments.json", "--title", "T", "-o", work / "u.jsonl", env=env)
    assert [json.loads(l)["author"] for l in log.read_text().splitlines()] == ["Raj S."]
    assert len(read_jsonl(work / "u.jsonl")) == 8


def test_B07_rerun_resumes_without_duplicates(work):
    for _ in range(2):
        p = run("extract_units.py", work / "nyt_comments.json", "--title", "T", "-o", work / "u.jsonl")
    ids = [r["comment_id"] for r in read_jsonl(work / "u.jsonl")]
    assert len(ids) == len(set(ids)) == 8
    assert "8 already done" in p.stderr


def test_B08_extraction_requests_record_units_tool(work):
    c, anc = items(work)[0]
    client = FakeClient(tool_reply("record_units", {"units": []}))
    ex.extract_one(client, "claude-haiku-5-5", ex.system_blocks("T", ""), c, anc)
    kind, kw = client.calls[0]
    assert kw["tools"][0]["name"] == "record_units"
    assert kw["tool_choice"] == {"type": "tool", "name": "record_units"}
