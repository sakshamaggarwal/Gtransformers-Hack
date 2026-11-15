# Community knowledge generator

Turns the reader comments under news articles (New York Times, Washington Post) into
**knowledge cards**: what readers report, claim, correct, disagree about and ask, with
every statement linked to the comments behind it, checked against the full comments,
and published as a searchable web page and SQLite database.

[![tests](https://github.com/OWNER/REPO/actions/workflows/tests.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/tests.yml)
&nbsp;**[▶ Run the tests on GitHub](https://github.com/OWNER/REPO/actions/workflows/tests.yml)** (Run workflow)
&nbsp;·&nbsp;**[▶ Run the page checks in your browser](http://localhost:8000/test-runner.html)** (after `make serve`)

> Replace `OWNER/REPO` in the two links above with your GitHub account and repo name.

```
saved comment page ─▶ 1 parse ─▶ 2 extract ─▶ 3 cluster ─▶ 4 write cards ─▶ 5a verify ─▶ 5b publish
   (.html/.txt)       JSON tree    units        topics       cited cards      checked     site + DB
                                  (Claude)     (embeddings)   (Claude)        (Claude)
```

## Files

```
├── README.md
├── Makefile                    make test / make serve / make demo ...
├── requirements.txt            pipeline dependencies
├── requirements-dev.txt        + pytest
├── .env.example                API keys (copy to .env)
├── netlify.toml                optional: deploy public/ as a static site
├── .github/workflows/tests.yml runs every test case on push, PR or "Run workflow"
├── docs/
│   ├── HOW_IT_WORKS.md         what each step does and why
│   └── TESTING.md              test groups, manual quality checks, writing new tests
├── pipeline/
│   ├── nyt_comments_to_json.py     step 1: NYT comments HTML  -> nested JSON
│   ├── wapo_comments_to_json.py    step 1: WaPo comments HTML -> nested JSON
│   ├── extract_units.py            step 2: comments -> knowledge units (Claude Haiku)
│   ├── cluster_units.py            step 3: units -> scored topics and points
│   ├── synthesize_cards.py         step 4: topics -> cited cards (Claude Sonnet)
│   ├── verify_cards.py             step 5a: check cards against full comments
│   ├── publish_cards.py            step 5b: web page + SQLite database
│   ├── search_knowledge.py         search the database from the command line
│   └── reddit_sub_to_json.py       Reddit export (needs pre-approved API access)
├── public/
│   ├── index.html                  published site (a synthetic demo until you publish yours)
│   ├── knowledge.db                its database
│   ├── test-runner.html            browser test runner for the web page (group G)
│   └── data/test_cases.csv         every test case: id, group, input, pass/fail criteria
├── scripts/
│   ├── run_tests.py                runs the suite, writes reports/test_report_*.md/.csv
│   ├── serve.py                    serves public/ and opens the test runner
│   └── build_demo.py               builds the demo site from the fixtures
├── tests/
│   ├── test_step1_parse.py ... test_step5b_publish.py, test_ui.py
│   ├── conftest.py                 helpers (fake model client, script runner)
│   ├── mocks/anthropic.py          offline stand-in for the Anthropic SDK
│   └── fixtures/                   synthetic pages, units and cards (no real comments)
└── reports/                        test reports land here
```

## 1. Set up

```bash
git clone https://github.com/OWNER/REPO.git && cd REPO
python3 -m venv .venv && source .venv/bin/activate
make install                    # or: pip install -r requirements-dev.txt
cp .env.example .env            # add your keys, then: set -a; source .env; set +a
```

Keep your real data (saved pages, units, clusters, cards) in a `data/` folder: it's in
`.gitignore`, because it contains readers' words.

## 2. Run the pipeline

```bash
# 1  Parse saved comment pages (save the comments panel's HTML from your browser)
python3 pipeline/nyt_comments_to_json.py  data/nyt_page.txt  -o data/nyt_comments.json
python3 pipeline/wapo_comments_to_json.py data/wapo_page.txt -o data/wapo_comments.json

# 2  Extract knowledge units (try --dry-run --limit 5 first)
python3 pipeline/extract_units.py data/nyt_comments.json  -o data/nyt_units.jsonl  --title "NYT headline"
python3 pipeline/extract_units.py data/wapo_comments.json -o data/wapo_units.jsonl --title "WaPo headline"

# 3  Cluster and score (pick thresholds with --sweep, then check clusters.md)
python3 pipeline/cluster_units.py data/nyt_units.jsonl data/wapo_units.jsonl --embedder voyage --sweep
python3 pipeline/cluster_units.py data/nyt_units.jsonl data/wapo_units.jsonl --embedder voyage -o data/clusters.json

# 4  Write cited cards
python3 pipeline/synthesize_cards.py data/clusters.json -o data/cards.jsonl --min-breadth 5 --top 30

# 5a Verify against the full comments, then read data/verify_report.md
python3 pipeline/verify_cards.py data/cards.jsonl \
  --comments nyt_units=data/nyt_comments.json wapo_units=data/wapo_comments.json -o data/cards_verified.jsonl

# 5b Publish the page and database into public/
python3 pipeline/publish_cards.py data/cards_verified.jsonl \
  --comments nyt_units=data/nyt_comments.json wapo_units=data/wapo_comments.json \
  --article "nyt_units=NYT headline|https://www.nytimes.com/..." \
  --article "wapo_units=WaPo headline|https://www.washingtonpost.com/..." \
  --site public/index.html --db public/knowledge.db

python3 pipeline/search_knowledge.py "vitamin D" --section advice --db public/knowledge.db
```

The names before `=` (`nyt_units`, `wapo_units`) are the step-2 file names without their
extension; they must match across steps 3–5.

## 3. Test

| How | Command / link | Runs |
|---|---|---|
| Everything, with a report | `make test` | groups A–G (G needs Chrome) → `reports/test_report_<time>.md` and `.csv` |
| Without a browser | `make test-fast` | groups A–F |
| One group | `make test-group G=E` | e.g. only verification tests |
| In your browser | `make serve`, then **http://localhost:8000/test-runner.html** | group G against `public/index.html` (or any page you name) |
| On GitHub | **Actions → tests → Run workflow** | everything; report on the run's summary page |

No test calls a real API: model calls go to `tests/mocks/anthropic.py`, and clustering
uses the offline `tfidf` embedder. All 68 test cases are listed, with their inputs and
pass/fail criteria, in [`public/data/test_cases.csv`](public/data/test_cases.csv):

| Group | Area | Cases | Type |
|---|---|---|---|
| A | Parse saved pages (step 1) | 8 | unit / integration |
| B | Extract units (step 2) | 8 | unit / integration |
| C | Cluster and score (step 3) | 8 | unit / integration |
| D | Write cards (step 4) | 8 | unit / integration |
| E | Verify cards (step 5a) | 10 | unit / integration |
| F | Publish page and database (step 5b) | 10 | integration |
| G | Web page in a browser | 10 | browser |
| H | Quality on real data | 6 | manual / live API |

Group H can't be automated with synthetic data: see [docs/TESTING.md](docs/TESTING.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| `tool_choice: type "tool" and "any" are not supported for this model` | Sonnet/Opus 5.5 reject forced tool use; the scripts use `auto` + a strict tool (test D05). |
| `Streaming is required for operations that may take longer than 10 minutes` | `verify_cards.py` streams its requests (test E08); update your copy. |
| `unrecognized arguments: wapo_units=...` | Put every `name=path` right after `--comments`, before the next option. |
| `No such file or directory` | Check the extension: `.jsonl` (letter l) vs `.json1` (digit 1). |
| Browser test runner says it can't read the page | Open it through `make serve`, not as a file. |
| Group G skipped | Install Chrome or Chromium, or set `CHROME_PATH`. |
| Reddit API access | Reddit closed new public API access on Oct 31, 2026; `reddit_sub_to_json.py` only works with existing approved credentials. |
