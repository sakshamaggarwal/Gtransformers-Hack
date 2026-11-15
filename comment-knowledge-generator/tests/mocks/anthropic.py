"""
Stand-in for the `anthropic` package, used when tests run pipeline scripts as
subprocesses (PYTHONPATH=tests/mocks). It never touches the network.

Behaviour is chosen from the request's tool:
  record_units  -> one claim unit quoting the first words of the target comment
  record_card   -> a card citing the first few evidence keys
  record_review -> every item "supported"

Environment variables:
  MOCK_LOG           append one JSON line per request (model, tool_choice, streamed, author)
  MOCK_FAIL_AUTHOR   raise an error for extraction prompts about this author
  MOCK_FAIL_ONCE_FILE  if set, the failure happens only while this file does not exist
"""
import json
import os
import re
import types

__version__ = "mock"


class APIError(Exception):
    pass


def _log(kw, streamed):
    path = os.environ.get("MOCK_LOG")
    if not path:
        return
    text = kw["messages"][0]["content"]
    m = re.search(r"TARGET COMMENT by (.+?):", text)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"model": kw.get("model"), "tool_choice": kw.get("tool_choice"),
                            "tool": kw["tools"][0]["name"], "strict": kw["tools"][0].get("strict"),
                            "streamed": streamed, "author": m.group(1) if m else None}) + "\n")


def _respond(kw):
    tool = kw["tools"][0]["name"]
    text = kw["messages"][0]["content"]
    if tool == "record_units":
        author = re.search(r"TARGET COMMENT by (.+?):", text).group(1)
        fail = os.environ.get("MOCK_FAIL_AUTHOR")
        once = os.environ.get("MOCK_FAIL_ONCE_FILE")
        if fail and author == fail and not (once and os.path.exists(once)):
            if once:
                open(once, "w").close()
            raise APIError("simulated failure for " + author)
        body = text.split("TARGET COMMENT by", 1)[1].split(":", 1)[1].strip()
        quote = " ".join(body.split()[:6])
        data = {"units": [{"type": "claim", "statement": "Mock statement about " + quote,
                           "topic": "mock topic", "stance": "extends", "quote": quote,
                           "expertise_claimed": None}]}
    elif tool == "record_card":
        keys = re.findall(r"\[(c\d+)\]", text)
        item = lambda ks: {"text": "Mock item.", "cites": ks}
        data = {"title": "Mock card", "takeaway": item(keys[:2]), "health_related": True,
                "reported_experiences": [item(keys[:1])], "claims": [item(keys[1:3])],
                "corrections": [], "open_questions": [], "advice": [], "disagreements": []}
    elif tool == "record_review":
        ids = re.findall(r"^\[([a-z_]+(?:\.\d+)+|takeaway)\]", text, re.M)
        data = {"coherent": True, "coherence_note": "", "title_fix": "",
                "items": [{"id": i, "verdict": "supported", "problems": [], "unsupporting_cites": [],
                           "revised_text": "", "health_risk": "none", "risk_note": ""} for i in ids]}
    else:
        raise APIError("unexpected tool " + tool)
    block = types.SimpleNamespace(type="tool_use", name=tool, input=data)
    usage = types.SimpleNamespace(input_tokens=10, output_tokens=5,
                                  cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return types.SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use")


class _Stream:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._resp


class _Messages:
    def create(self, **kw):
        _log(kw, False)
        return _respond(kw)

    def stream(self, **kw):
        _log(kw, True)
        return _Stream(_respond(kw))


class Anthropic:
    def __init__(self, **kw):
        self.messages = _Messages()
