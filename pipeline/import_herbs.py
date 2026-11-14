"""
Import an open ayurvedic herb dataset (CSV) into knowledge/ayurveda.json.

Many open datasets (e.g. GitHub exports of IMPPAT, Indian medicinal plant lists,
Kaggle "Ayurvedic herbs" tables) share roughly these columns. Map yours with
--map if the names differ:

    python pipeline/import_herbs.py herbs.csv \
        --map name=Herb botanical=Scientific_Name uses=Indications cautions=Side_Effects

Imported rows are tagged evidence="traditional (unreviewed import)" so the bot
presents them as tradition only, and get a topic from their 'uses' text via
the taxonomy. Rows that match no health topic are skipped. Existing curated
entries (A1..A22) are never overwritten. Re-run build_kb.py afterwards.
"""

import argparse
import csv
import json
from pathlib import Path

from taxonomy import tag_topics

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "knowledge" / "ayurveda.json"
FIELDS = {"name": "name", "botanical": "botanical_name", "uses": "uses", "cautions": "cautions", "reference": "reference"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--map", nargs="*", default=[], help="field=ColumnName pairs")
    ap.add_argument("--source", default="", help="dataset URL, kept as a reference")
    args = ap.parse_args()
    cols = dict(FIELDS, **dict(m.split("=", 1) for m in args.map))

    kb = json.loads(KB.read_text(encoding="utf-8"))
    names = {e["name"].lower() for e in kb}
    next_id = max(int(e["id"][1:]) for e in kb) + 1
    added = skipped = 0
    with open(args.csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get(cols["name"]) or "").strip()
            uses = (row.get(cols["uses"]) or "").strip()
            topics = tag_topics(f"{name} {uses}")
            if not name or not topics or name.lower() in names:
                skipped += 1
                continue
            botanical = (row.get(cols["botanical"]) or "").strip()
            kb.append({
                "id": f"A{next_id}", "topic": topics[0],
                "name": f"{name} ({botanical})" if botanical else name,
                "tradition": f"Traditionally used for: {uses}",
                "how_used": "Ask a qualified Ayurvedic physician for form and dose.",
                "evidence": "traditional (unreviewed import)",
                "evidence_note": "Imported from an open herb dataset; not yet reviewed against clinical evidence.",
                "cautions": (row.get(cols["cautions"]) or "").strip() or "Safety data not provided; check with your doctor, especially if pregnant or on medication.",
                "references": [x for x in [(row.get(cols["reference"]) or "").strip(), args.source] if x],
                "search_terms": [name.lower()] + ([botanical.lower()] if botanical else []),
            })
            names.add(name.lower())
            next_id += 1
            added += 1
    KB.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"added {added}, skipped {skipped} (no health topic, duplicate or empty). Now run: python pipeline/build_kb.py")


if __name__ == "__main__":
    main()
