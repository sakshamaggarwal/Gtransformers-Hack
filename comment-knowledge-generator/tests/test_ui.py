"""Group G: the published web page, checked in headless Chrome via public/test-runner.html.

Builds a fresh page from the fixtures with the current publish_cards.py, serves it on a
local port, opens the test runner in headless Chrome and reads back its results.
Skipped if Chrome/Chromium isn't installed (set CHROME_PATH to point at it).
"""
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

from conftest import ROOT, run

CANDIDATES = [os.environ.get("CHROME_PATH"), "google-chrome", "google-chrome-stable", "chromium",
              "chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"]
CHROME = next((c for c in CANDIDATES if c and (shutil.which(c) or os.path.exists(c))), None)
IDS = [f"G{i:02d}" for i in range(1, 11)]


@pytest.fixture(scope="module")
def browser_results(tmp_path_factory):
    if not CHROME:
        pytest.skip("Chrome/Chromium not found; set CHROME_PATH or open public/test-runner.html via make serve")
    site = tmp_path_factory.mktemp("site")
    fx = os.path.join(ROOT, "tests", "fixtures")
    run("verify_cards.py", os.path.join(fx, "cards.jsonl"), "--comments",
        f"nyt_units={fx}/nyt_comments.json", f"wapo_units={fx}/wapo_comments.json",
        "--no-llm", "-o", site / "verified.jsonl")
    run("publish_cards.py", site / "verified.jsonl", "--comments", f"nyt_units={fx}/nyt_comments.json",
        "--site", site / "index.html", "--db", site / "knowledge.db",
        "--article", "nyt_units=Supplements survey|https://www.nytimes.com/example",
        "--article", "wapo_units=Supplements and the brain|https://www.washingtonpost.com/example")
    shutil.copy(os.path.join(ROOT, "public", "test-runner.html"), site / "test-runner.html")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/test-runner.html"
        p = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                            "--virtual-time-budget=20000", "--dump-dom", url],
                           capture_output=True, text=True, timeout=120)
    finally:
        server.shutdown()
    m = re.search(r'<pre id="results-json" hidden="">(.*?)</pre>', p.stdout, re.S)
    assert m, "test runner produced no results:\n" + p.stdout[-2000:] + p.stderr[-2000:]
    import html
    return {r["id"]: r for r in json.loads(html.unescape(m.group(1)))}


@pytest.mark.parametrize("test_id", IDS)
def test_G_browser(browser_results, test_id):
    r = browser_results[test_id]
    if r["status"] == "SKIP":
        pytest.skip(r["detail"])
    assert r["status"] == "PASS", f"{test_id} {r['title']}: {r['detail']}"
