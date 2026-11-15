"""Shared helpers for the test suite. Nothing here calls a real API."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
MOCKS = os.path.join(ROOT, "tests", "mocks")


def load(name):
    """Import a pipeline script (pipeline/<name>.py) as a module."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(PIPELINE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(script, *args, env=None, cwd=None, check=True):
    """Run a pipeline script with the mock `anthropic` package on the path."""
    e = dict(os.environ, PYTHONPATH=MOCKS, ANTHROPIC_API_KEY="test-key")
    e.update(env or {})
    p = subprocess.run([sys.executable, os.path.join(PIPELINE, script), *map(str, args)],
                       capture_output=True, text=True, env=e, cwd=cwd)
    if check and p.returncode != 0:
        raise AssertionError(f"{script} failed ({p.returncode}):\n{p.stdout}\n{p.stderr}")
    return p


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def fixture_path(name):
    return os.path.join(FIXTURES, name)


class FakeClient:
    """In-process fake for client.messages.create / .stream. `replies` is a list of
    callables(kwargs) -> response, used in order (the last one repeats)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def _next(self, kw):
        fn = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return fn(kw)

    def create(self, **kw):
        self.calls.append(("create", kw))
        return self._next(kw)

    def stream(self, **kw):
        self.calls.append(("stream", kw))
        resp = self._next(kw)

        class S:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def get_final_message(s):
                return resp
        return S()


def tool_reply(name, data):
    return lambda kw: types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", name=name, input=data)],
        usage=None, stop_reason="tool_use")


def text_reply(text="Here is my answer in prose."):
    return lambda kw: types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)], usage=None, stop_reason="end_turn")


@pytest.fixture
def work(tmp_path):
    """A temp folder pre-filled with copies of every fixture file."""
    for f in os.listdir(FIXTURES):
        if not f.endswith(".py"):
            shutil.copy(os.path.join(FIXTURES, f), tmp_path / f)
    return tmp_path


@pytest.fixture
def cards():
    return read_jsonl(fixture_path("cards.jsonl"))
