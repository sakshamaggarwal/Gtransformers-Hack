#!/usr/bin/env python3
"""
Run the test suite and write a report for every test case in public/data/test_cases.csv.

    python scripts/run_tests.py              # everything (browser checks need Chrome)
    python scripts/run_tests.py --group A    # one group (A..G)
    python scripts/run_tests.py --no-browser # skip group G

Writes to reports/:
    test_report_<timestamp>.md    summary by group, then every test case with its result
    test_report_<timestamp>.csv   one row per test case
    junit_<timestamp>.xml         raw pytest results (for CI tools)

Groups H (quality) are manual or need real API keys; they are listed as "not run"
with instructions in docs/TESTING.md.
"""
import argparse
import csv
import datetime as dt
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "public", "data", "test_cases.csv")
REPORTS = os.path.join(ROOT, "reports")
GROUPS = {"A": "Parse saved pages (step 1)", "B": "Extract units (step 2)",
          "C": "Cluster and score (step 3)", "D": "Write cards (step 4)",
          "E": "Verify cards (step 5a)", "F": "Publish page and database (step 5b)",
          "G": "Web page in a browser", "H": "Quality (manual / live API)"}


def junit_results(path):
    """test case id -> (status, detail) from pytest's junit xml."""
    out = {}
    for tc in ET.parse(path).getroot().iter("testcase"):
        name = tc.get("name", "")
        m = re.search(r"\[([A-H]\d{2})\]", name) or re.search(r"test_([A-H]\d{2})", name)
        if not m:
            continue
        tid = m.group(1)
        failure = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        if failure is not None:
            status, detail = "FAIL", (failure.get("message") or "").splitlines()[0][:300]
        elif tc.find("skipped") is not None:
            status, detail = "SKIP", (tc.find("skipped").get("message") or "")[:300]
        else:
            status, detail = "PASS", ""
        prev = out.get(tid)
        # a test case backed by several pytest cases: any failure fails it
        rank = {"FAIL": 3, "PASS": 2, "SKIP": 1}
        if not prev or rank[status] > rank[prev[0]] or (prev[0] == "PASS" and status == "FAIL"):
            out[tid] = (status, detail)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", help="run one group, e.g. A")
    ap.add_argument("--no-browser", action="store_true", help="skip group G (headless Chrome)")
    args = ap.parse_args()

    os.makedirs(REPORTS, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    junit = os.path.join(REPORTS, f"junit_{stamp}.xml")
    cmd = [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", os.path.join(ROOT, "tests")]
    if args.group:
        cmd += ["-k", f"test_{args.group.upper()}"]
    if args.no_browser:
        cmd += ["--deselect", "tests/test_ui.py"]
    print("Running:", " ".join(cmd[2:]), flush=True)
    code = subprocess.call(cmd, cwd=ROOT)

    results = junit_results(junit)
    with open(CATALOG, encoding="utf-8") as f:
        catalog = list(csv.DictReader(f))
    rows = []
    for c in catalog:
        if args.group and c["group"] != args.group.upper():
            continue
        if c["type"] in ("manual", "live"):
            status, detail = "NOT RUN", f"{c['type']}: see docs/TESTING.md"
        elif args.no_browser and c["group"] == "G":
            status, detail = "NOT RUN", "browser checks skipped (--no-browser)"
        else:
            status, detail = results.get(c["id"], ("MISSING", "no automated test found for this id"))
        rows.append({**c, "status": status, "detail": detail})

    md_path = os.path.join(REPORTS, f"test_report_{stamp}.md")
    csv_path = os.path.join(REPORTS, f"test_report_{stamp}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    count = lambda rs, s: sum(1 for r in rs if r["status"] == s)
    lines = [f"# Test report · {dt.datetime.now():%Y-%m-%d %H:%M}", "",
             f"**{count(rows, 'PASS')} passed, {count(rows, 'FAIL')} failed, {count(rows, 'SKIP')} skipped, "
             f"{count(rows, 'NOT RUN')} not run, {count(rows, 'MISSING')} missing** "
             f"of {len(rows)} test cases.", "",
             "| Group | Area | Passed | Failed | Skipped | Not run |", "|---|---|---|---|---|---|"]
    for g, name in GROUPS.items():
        rs = [r for r in rows if r["group"] == g]
        if rs:
            lines.append(f"| {g} | {name} | {count(rs, 'PASS')} | {count(rs, 'FAIL')} | "
                         f"{count(rs, 'SKIP')} | {count(rs, 'NOT RUN')} |")
    lines += ["", "| ID | Test | Type | Result | Details |", "|---|---|---|---|---|"]
    icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "SKIP": "⏭ SKIP", "NOT RUN": "· not run", "MISSING": "⚠ MISSING"}
    for r in rows:
        detail = r["detail"].replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['title']} | {r['type']} | {icon[r['status']]} | {detail} |")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n{count(rows, 'PASS')} passed, {count(rows, 'FAIL')} failed, {count(rows, 'SKIP')} skipped, "
          f"{count(rows, 'NOT RUN')} not run of {len(rows)} test cases")
    print(f"Report: {os.path.relpath(md_path, ROOT)}  ·  {os.path.relpath(csv_path, ROOT)}")
    missing = [r["id"] for r in rows if r["status"] == "MISSING"]
    if missing:
        print("No automated test for:", ", ".join(missing))
    sys.exit(1 if (code not in (0, 5) or count(rows, "FAIL") or missing) else 0)


if __name__ == "__main__":
    main()
