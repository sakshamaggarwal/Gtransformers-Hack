#!/usr/bin/env python3
"""
Step 3 of the community knowledge generator: embed, cluster and score the
knowledge units from step 2 (extract_units.py).

Two levels of grouping:
  topic  - units about the same subject (e.g. "vitamin D dosing")
  point  - inside a topic, units making essentially the same point
           (e.g. "my doctor told me to take 2,000 IU a day")

Each topic and point is scored mainly by BREADTH (how many different people
said it), plus endorsement (recommendations/votes, log-scaled and normalised
per source, since NYT and WaPo counts differ) and claimed expertise. It also
reports stance mix (how contested a topic is) and replies that push back.

Usage:
    python cluster_units.py nyt_units.jsonl wapo_units.jsonl -o clusters.json \
        --embedder voyage            # or openai | local | tfidf (offline)

    # pick thresholds: print how clustering changes as they vary
    python cluster_units.py units.jsonl --embedder voyage --sweep

Embedders (embeddings are cached next to the output, so re-runs are free):
    voyage  pip install voyageai;  VOYAGE_API_KEY   model voyage-4-lite
    openai  pip install openai;    OPENAI_API_KEY   model text-embedding-3-small
    local   pip install sentence-transformers       model all-MiniLM-L6-v2
    tfidf   no install, no network; rougher (word overlap, not meaning)

Writes:
    clusters.json   full structure for step 4 (every unit, with its comment id)
    clusters.md     quick human-readable overview of the top topics
"""
import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np
from sklearn.cluster import AgglomerativeClustering

# Cosine-distance thresholds (lower = tighter). Dense embeddings and TF-IDF
# live on very different scales, so each embedder gets its own defaults.
# Run --sweep to tune for your data.
DEFAULTS = {
    "voyage": {"model": "voyage-4-lite", "topic": 0.45, "point": 0.25},
    "openai": {"model": "text-embedding-3-small", "topic": 0.50, "point": 0.30},
    "local":  {"model": "all-MiniLM-L6-v2", "topic": 0.55, "point": 0.35},
    "tfidf":  {"model": "tfidf-lsa", "topic": 0.70, "point": 0.30},
}


# ---------------- loading ----------------

def load_units(paths):
    """Flatten step-2 JSONL files into one list of units with their context."""
    units, replies = [], defaultdict(list)   # replies[(source, parent_id)] -> records
    for path in paths:
        source = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("parent_id"):
                    replies[(source, rec["parent_id"])].append(rec)
                for i, u in enumerate(rec.get("units", [])):
                    units.append({
                        "uid": f"{source}:{rec['comment_id']}:{i}",
                        "source": source,
                        "comment_id": rec["comment_id"],
                        "parent_id": rec.get("parent_id"),
                        "author": rec.get("author") or "?",
                        "depth": rec.get("depth", 0),
                        "endorsement": rec.get("endorsement", 0) or 0,
                        "type": u.get("type"),
                        "stance": u.get("stance"),
                        "topic": u.get("topic", ""),
                        "statement": u.get("statement", ""),
                        "quote": u.get("quote", ""),
                        "expertise_claimed": u.get("expertise_claimed"),
                        "quote_verified": u.get("quote_verified", True),
                    })
    return units, replies


def embed_text(u):
    # Topic label + statement; leave out type/stance so that an experience and a
    # claim about the same subject land in the same topic.
    return f"{u['topic']}: {u['statement']}"


# ---------------- embeddings ----------------

def embed(texts, embedder, model, cache_path):
    cache = {}
    if os.path.exists(cache_path):
        z = np.load(cache_path, allow_pickle=False)
        cache = dict(zip(z["keys"].tolist(), z["vecs"]))
    keys = [hashlib.sha1(f"{model}|{t}".encode()).hexdigest() for t in texts]
    missing = [i for i, k in enumerate(keys) if k not in cache]

    if embedder == "tfidf":   # corpus-dependent, so never cached; always recompute all
        vecs = tfidf_lsa(texts)
        return normalise(vecs)

    if missing:
        print(f"Embedding {len(missing)} new texts with {embedder}/{model} "
              f"({len(texts) - len(missing)} cached)", file=sys.stderr)
        new = call_embedder([texts[i] for i in missing], embedder, model)
        for i, v in zip(missing, new):
            cache[keys[i]] = np.asarray(v, dtype=np.float32)
        np.savez(cache_path, keys=np.array(list(cache.keys())),
                 vecs=np.stack(list(cache.values())))
    return normalise(np.stack([cache[k] for k in keys]))


def call_embedder(texts, embedder, model, batch=128):
    out = []
    if embedder == "voyage":
        import voyageai
        client = voyageai.Client()
        for i in range(0, len(texts), batch):
            out += client.embed(texts[i:i + batch], model=model, input_type="document").embeddings
    elif embedder == "openai":
        from openai import OpenAI
        client = OpenAI()
        for i in range(0, len(texts), batch):
            resp = client.embeddings.create(model=model, input=texts[i:i + batch])
            out += [d.embedding for d in resp.data]
    elif embedder == "local":
        from sentence_transformers import SentenceTransformer
        out = SentenceTransformer(model).encode(texts, batch_size=64, show_progress_bar=True)
    else:
        raise ValueError(embedder)
    return out


def tfidf_lsa(texts):
    """Offline fallback: TF-IDF reduced with LSA so related wording groups together."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    tf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1,
                         sublinear_tf=True).fit_transform(texts)
    k = max(2, min(150, tf.shape[1] - 1, tf.shape[0] - 1))
    return TruncatedSVD(n_components=k, random_state=0).fit_transform(tf)


def normalise(v):
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1
    return v / n


# ---------------- clustering ----------------

def agglomerate(vecs, threshold):
    if len(vecs) == 1:
        return np.zeros(1, dtype=int)
    return AgglomerativeClustering(n_clusters=None, distance_threshold=threshold,
                                   metric="cosine", linkage="average").fit_predict(vecs)


def group(labels):
    g = defaultdict(list)
    for i, lab in enumerate(labels):
        g[lab].append(i)
    return list(g.values())


def sweep(vecs, units, thresholds):
    print(f"{'threshold':>9} {'clusters':>8} {'multi-person':>12} {'largest':>8} "
          f"{'units in multi-person':>22}")
    for t in thresholds:
        groups = group(agglomerate(vecs, t))
        multi = [g for g in groups if len({units[i]['author'] for i in g}) > 1]
        print(f"{t:>9.2f} {len(groups):>8} {len(multi):>12} "
              f"{max(len(g) for g in groups):>8} {sum(len(g) for g in multi):>22}")
    print("\nGood topic thresholds: most units end up in multi-person clusters while the "
          "largest cluster stays a coherent subject (check a few in clusters.md). "
          "Point thresholds are tighter, roughly 50-60% of the topic one.")


# ---------------- scoring ----------------

def endorsement_scale(units):
    """Per-source mean of log1p(endorsement) over comments, used to normalise."""
    per = defaultdict(dict)
    for u in units:
        per[u["source"]][u["comment_id"]] = u["endorsement"]
    return {s: (np.mean([math.log1p(max(0, e)) for e in d.values()]) or 1.0)
            for s, d in per.items()}


def stats(idx, units, replies, scale, weights):
    us = [units[i] for i in idx]
    authors = {(u["source"], u["author"]) for u in us}
    comments = {(u["source"], u["comment_id"]): u for u in us}
    endorse = sum(math.log1p(max(0, u["endorsement"])) / scale[u["source"]]
                  for u in comments.values())
    experts = {(u["source"], u["author"]) for u in us if u["expertise_claimed"]}

    # Pushback: direct replies to these comments, by someone else, that contain
    # a correction or dispute something. (Approximate: stance is relative to the
    # article, so a "disputes" reply may be disputing the article, not the parent.)
    pushback = set()
    for (src, cid), u in comments.items():
        for r in replies.get((src, cid), []):
            if r.get("author") != u["author"] and any(
                    x.get("type") == "correction" or x.get("stance") == "disputes"
                    for x in r.get("units", [])):
                pushback.add((src, r["comment_id"]))

    stance = Counter(u["stance"] for u in us)
    sup, dis = stance.get("supports", 0), stance.get("disputes", 0)
    breadth = len(authors)
    score = (weights["breadth"] * breadth + weights["endorsement"] * endorse
             + weights["expertise"] * len(experts))
    return {
        "score": round(score, 2),
        "breadth": breadth,
        "n_units": len(us),
        "n_comments": len(comments),
        "endorsement": round(endorse, 2),
        "expertise_authors": len(experts),
        "pushback_replies": len(pushback),
        "stance_counts": dict(stance),
        "contested": round(min(sup, dis) / (sup + dis), 2) if sup + dis else 0.0,
        "type_counts": dict(Counter(u["type"] for u in us)),
        "sources": dict(Counter(u["source"] for u in us)),
    }


def representatives(idx, vecs, units, k=3):
    """Units nearest the group's centre, one per author, best first."""
    centre = normalise(vecs[idx].mean(axis=0, keepdims=True))[0]
    order = sorted(idx, key=lambda i: -float(vecs[i] @ centre))
    reps, seen = [], set()
    for i in order:
        a = (units[i]["source"], units[i]["author"])
        if a not in seen:
            reps.append(i)
            seen.add(a)
        if len(reps) == k:
            break
    return reps, order


def label_for(idx, order, units):
    counts = Counter(units[i]["topic"] for i in idx)
    top, n = counts.most_common(1)[0]
    return top if n >= 2 else units[order[0]]["topic"]


def public(u):
    return {k: u[k] for k in ("uid", "source", "comment_id", "author", "type", "stance",
                              "statement", "quote", "endorsement", "expertise_claimed",
                              "quote_verified")}


def build(units, vecs, replies, topic_t, point_t, weights):
    scale = endorsement_scale(units)
    topics = []
    for t_idx in group(agglomerate(vecs, topic_t)):
        reps, order = representatives(t_idx, vecs, units)
        topic = {"label": label_for(t_idx, order, units),
                 **stats(t_idx, units, replies, scale, weights), "points": []}
        sub = agglomerate(vecs[t_idx], point_t) if len(t_idx) > 1 else [0]
        for p_local in group(sub):
            p_idx = [t_idx[j] for j in p_local]
            p_reps, p_order = representatives(p_idx, vecs, units)
            topic["points"].append({
                **stats(p_idx, units, replies, scale, weights),
                "representative": [public(units[i]) for i in p_reps],
                "units": [public(units[i]) for i in p_order],
            })
        topic["points"].sort(key=lambda p: (-p["score"], -p["n_units"]))
        topics.append(topic)
    topics.sort(key=lambda t: (-t["score"], -t["n_units"]))
    for ti, t in enumerate(topics, 1):
        t["id"] = f"T{ti}"
        for pi, p in enumerate(t["points"], 1):
            p["id"] = f"T{ti}.P{pi}"
    # put ids first for readability
    return [{"id": t.pop("id"), **t} for t in topics]


# ---------------- report ----------------

def write_markdown(topics, path, top_n, min_breadth):
    shown = [t for t in topics if t["breadth"] >= min_breadth][:top_n]
    lines = [f"# Top {len(shown)} topics (of {len(topics)}; breadth = distinct people)\n"]
    for t in shown:
        sc = t["stance_counts"]
        lines.append(f"## {t['id']} · {t['label']}")
        lines.append(f"score {t['score']} · {t['breadth']} people · {t['n_units']} units · "
                     f"supports {sc.get('supports', 0)} / disputes {sc.get('disputes', 0)} / "
                     f"extends {sc.get('extends', 0)} / unrelated {sc.get('unrelated', 0)}"
                     f" · contested {t['contested']} · pushback replies {t['pushback_replies']}"
                     f" · experts {t['expertise_authors']}\n")
        for p in t["points"][:5]:
            rep = p["representative"][0]
            lines.append(f"- **{p['breadth']} {'person' if p['breadth'] == 1 else 'people'}** ({', '.join(f'{k} {v}' for k, v in p['type_counts'].items())}): "
                         f"{rep['statement']}  \n  _\"{rep['quote']}\"_ — {rep['author']}")
        if len(t["points"]) > 5:
            lines.append(f"- … {len(t['points']) - 5} more points")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="one or more units.jsonl files from step 2")
    ap.add_argument("-o", "--output", default="clusters.json")
    ap.add_argument("--embedder", choices=DEFAULTS, default="voyage")
    ap.add_argument("--model", help="override the embedder's default model")
    ap.add_argument("--topic-threshold", type=float)
    ap.add_argument("--point-threshold", type=float)
    ap.add_argument("--drop-unverified", action="store_true",
                    help="drop units whose quote wasn't found in the comment")
    ap.add_argument("--w-breadth", type=float, default=1.0)
    ap.add_argument("--w-endorsement", type=float, default=0.5)
    ap.add_argument("--w-expertise", type=float, default=1.0)
    ap.add_argument("--sweep", action="store_true", help="print a threshold table and exit")
    ap.add_argument("--md-top", type=int, default=25)
    ap.add_argument("--md-min-breadth", type=int, default=2)
    args = ap.parse_args()

    d = DEFAULTS[args.embedder]
    model = args.model or d["model"]
    topic_t = args.topic_threshold or d["topic"]
    point_t = args.point_threshold or d["point"]

    units, replies = load_units(args.inputs)
    if args.drop_unverified:
        units = [u for u in units if u["quote_verified"]]
    if not units:
        sys.exit("No units found.")
    print(f"{len(units)} units from {len({(u['source'], u['comment_id']) for u in units})} "
          f"comments in {len(args.inputs)} file(s)", file=sys.stderr)

    cache = os.path.splitext(args.output)[0] + f".{args.embedder}.emb.npz"
    vecs = embed([embed_text(u) for u in units], args.embedder, model, cache)

    if args.sweep:
        lo, hi = (0.4, 0.95) if args.embedder == "tfidf" else (0.2, 0.7)
        sweep(vecs, units, np.round(np.linspace(lo, hi, 12), 2))
        return

    weights = {"breadth": args.w_breadth, "endorsement": args.w_endorsement,
               "expertise": args.w_expertise}
    topics = build(units, vecs, replies, topic_t, point_t, weights)

    result = {
        "params": {"embedder": args.embedder, "model": model, "topic_threshold": topic_t,
                   "point_threshold": point_t, "weights": weights, "inputs": args.inputs},
        "n_units": len(units),
        "topics": topics,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    md = os.path.splitext(args.output)[0] + ".md"
    write_markdown(topics, md, args.md_top, args.md_min_breadth)

    multi = [t for t in topics if t["breadth"] > 1]
    print(f"{len(topics)} topics ({len(multi)} raised by 2+ people, covering "
          f"{sum(t['n_units'] for t in multi)} units); "
          f"{sum(len(t['points']) for t in topics)} points. Wrote {args.output} and {md}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
