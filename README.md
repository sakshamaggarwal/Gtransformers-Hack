# CollectiveMind: What Readers Know

**Community-generated intelligence for health.** CollectiveMind turns the reader comments under health news articles into checked, searchable knowledge: what readers report, claim, correct, disagree about and ask, with every statement linked back to the comments behind it.

*General information only, not medical advice.*

## What's live

`public/community/index.html` (served at `/community/`): a self-contained static page built from reader comments on two supplement articles:

| Source | Article |
|---|---|
| New York Times | *Americans Love Supplements, but Experts Doubt Their Benefits* |
| Washington Post | *Why scientists are starting to worry popular supplements could harm the aging brain* |

| What the data holds | Count |
|---|---|
| Reader comments and reviews (each linked to the original) | 547 |
| Claims extracted from those comments | 384 |
| Topic cards | 29 |
| Claims flagged as a health risk | 99 |
| Disagreements between readers | 31 |

Each topic card shows a takeaway, a verdict for every claim (287 supported, 97 partly supported), health-risk flags with a note, how many readers said it, the disagreements, and citations back to the reader comments. Only comments related to the requested keyword are kept.

## How it works

```
saved comment page ─▶ 1 parse ─▶ 2 extract ─▶ 3 cluster ─▶ 4 write cards ─▶ 5a verify ─▶ 5b publish
 (NYT / WaPo)         JSON tree    claims       topics       cited cards      checked     page + SQLite
                                   (LLM)      (embeddings)     (LLM)          (LLM)
```

1. **Collect and parse** NYT and WaPo comment threads (saved locally) into nested JSON.
2. **Filter and extract** comments about the requested keyword into individual claims, each linked to its reader.
3. **Embed and cluster** similar claims into topics with sentence embeddings.
4. **Write topic cards** with consensus, disagreements, open questions and citations.
5. **Verify** every card against the full comments, then **publish** a static page and `knowledge.db`.

## Repository layout

| Path | What it is |
|---|---|
| `public/community/` | The CollectiveMind page: `index.html` (data inlined, no external requests) and `knowledge.db` (SQLite: articles, cards, items, refs, disagreements, full-text indexes) |
| `comment-knowledge-generator/` | The pipeline that builds the page and database: `pipeline/` steps, `tests/`, `docs/HOW_IT_WORKS.md`, `docs/TESTING.md`, `Makefile`. See its README. |
| `DEPLOY.md` | Netlify setup, auto-deploy, branch switching and rollback |

## Deploy on Netlify

Set the site's production branch to `demo`, publish directory `public`, no build command. Every push to `demo` redeploys. Full steps in [`DEPLOY.md`](DEPLOY.md).

## Run the pipeline locally

```bash
cd comment-knowledge-generator
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # add API keys; never commit .env
make test                   # offline tests with mocked model calls
make serve                  # open http://localhost:8000
```

## Team

Team 16 (VAAS): Asit Chakrabarty, Anish Chakrabarty, Vikram Poojary, Saksham Aggarwal. Built for the Gtransformers Hack (AI for Good Buildathon), November 2026.
