#!/usr/bin/env python3
"""
Build a demo site in public/ from the synthetic test fixtures, using the real
pipeline scripts with no API calls (verification runs its free code checks only).

    python scripts/build_demo.py

Writes public/index.html and public/knowledge.db.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "tests", "fixtures")
P = os.path.join(ROOT, "pipeline")


def step(script, *args):
    subprocess.run([sys.executable, os.path.join(P, script), *args], check=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        verified = os.path.join(tmp, "cards_verified.jsonl")
        step("verify_cards.py", os.path.join(FX, "cards.jsonl"), "--comments",
             f"nyt_units={FX}/nyt_comments.json", f"wapo_units={FX}/wapo_comments.json",
             "--no-llm", "-o", verified)
        step("publish_cards.py", verified, "--comments", f"nyt_units={FX}/nyt_comments.json",
             "--article", "nyt_units=Demo: NYT-style article (synthetic)|https://www.nytimes.com/",
             "--article", "wapo_units=Demo: Washington Post-style article (synthetic)|https://www.washingtonpost.com/",
             "--title", "Demo: what readers know (synthetic test data)",
             "--site", os.path.join(ROOT, "public", "index.html"),
             "--db", os.path.join(ROOT, "public", "knowledge.db"))


if __name__ == "__main__":
    main()
