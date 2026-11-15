"""Group A: step 1, parsing saved comment pages (nyt_/wapo_comments_to_json.py)."""
import json

import pytest

from conftest import fixture_path, load, run

nyt = load("nyt_comments_to_json")
wapo = load("wapo_comments_to_json")


def walk(cs, depth=0, parent=None):
    for c in cs:
        yield c, depth, parent
        yield from walk(c["replies"], depth + 1, c)


@pytest.fixture(scope="module")
def nyt_tree():
    with open(fixture_path("nyt_sample.html"), encoding="utf-8") as f:
        return nyt.build_tree(f.read())


@pytest.fixture(scope="module")
def wapo_tree():
    with open(fixture_path("wapo_sample.html"), encoding="utf-8") as f:
        return wapo.build_tree(f.read())


def find(tree, cid):
    return next(c for c, _, _ in walk(tree) if c["id"] == cid)


def test_A01_nyt_every_comment_parsed(nyt_tree):
    assert len(nyt_tree) == 5
    assert len(list(walk(nyt_tree))) == 9


def test_A02_nyt_replies_nest_under_right_parent(nyt_tree):
    chain = ["900001", "900011", "900111", "901111"]
    node = find(nyt_tree, chain[0])
    for child in chain[1:]:
        assert [r["id"] for r in node["replies"]] == [child]
        node = node["replies"][0]
    assert node["replies"] == []
    assert max(d for _, d, _ in walk(nyt_tree)) == 3


def test_A03_nyt_fields_extracted(nyt_tree):
    c = find(nyt_tree, "900002")
    assert c["author"] == "Raj S."
    assert c["location"] == "Chicago"
    assert c["date"] == "Sept. 12"
    assert c["recommendations"] == 40
    assert c["text"].startswith("Supplements aren't regulated")
    assert c["share_url"] == "https://www.nytimes.com/shared/comment/fx900002?rsrc=cshare"
    # the parent's fields must not be taken from its reply (Dee W., 6 recommendations)
    assert c["replies"][0]["author"] == "Dee W." and c["replies"][0]["recommendations"] == 6


def test_A04_wapo_every_comment_parsed_and_nested(wapo_tree):
    assert len(wapo_tree) == 5
    assert len(list(walk(wapo_tree))) == 8
    fish = find(wapo_tree, "w-0004")
    assert [r["id"] for r in fish["replies"]] == ["w-0041", "w-0042"]
    assert [r["id"] for r in fish["replies"][0]["replies"]] == ["w-0411"]
    assert all(c["is_reply"] == (d > 0) for c, d, _ in walk(wapo_tree))


def test_A05_wapo_reply_counts_match_button_when_loaded(wapo_tree):
    krill = find(wapo_tree, "w-0041")
    assert krill["reply_count_shown"] == len(krill["replies"]) == 1


def test_A06_wapo_missing_replies_reported(tmp_path):
    p = run("wapo_comments_to_json.py", fixture_path("wapo_sample.html"), "-o", tmp_path / "w.json")
    assert "1 replies not loaded" in p.stderr
    tree = json.loads((tmp_path / "w.json").read_text())
    fish = find(tree, "w-0004")
    assert fish["reply_count_shown"] == 3 and len(fish["replies"]) == 2


def test_A07_wapo_fields_extracted(wapo_tree):
    c = find(wapo_tree, "w-0005")
    assert c["author"] == "Skeptic99"
    assert c["posted_at"] == "2026-09-11T09:00:00Z"
    assert c["vote_score"] == 9
    assert c["reactions"] == 3
    assert "hypercalcemia" in c["text"]


@pytest.mark.parametrize("tree_name", ["nyt_tree", "wapo_tree"])
def test_A08_output_valid_unique_nonempty(tree_name, request):
    tree = request.getfixturevalue(tree_name)
    json.loads(json.dumps(tree))
    ids = [c["id"] for c, _, _ in walk(tree)]
    assert len(ids) == len(set(ids))
    assert all(c["text"].strip() and c["author"] for c, _, _ in walk(tree))
