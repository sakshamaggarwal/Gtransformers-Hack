#!/usr/bin/env python3
"""
Serve public/ locally and open the browser test runner.

    python scripts/serve.py            # http://localhost:8000/test-runner.html
    python scripts/serve.py --port 9000 --no-open

If public/index.html doesn't exist yet, a demo page is built from the test fixtures
first. To test your real site, publish it into public/ (publish_cards.py --site
public/index.html) or type its file name into the runner's "Page to test" box.
"""
import argparse
import functools
import http.server
import os
import subprocess
import sys
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(PUBLIC, "index.html")):
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_demo.py")], check=True)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=PUBLIC)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    base = f"http://localhost:{args.port}"
    print(f"\n  Site:         {base}/index.html")
    print(f"  Test runner:  {base}/test-runner.html")
    print(f"  Test cases:   {base}/data/test_cases.csv\n  Press Ctrl+C to stop.\n")
    if not args.no_open:
        webbrowser.open(f"{base}/test-runner.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
