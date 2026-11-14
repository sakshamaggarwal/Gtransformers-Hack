# 🌿 Vaidya Pulse: Community-Generated Health Intelligence

Ask a health question, for example **"How can I increase my RBC count?"**. Vaidya Pulse fetches **six sources live**, **ranks every result** on relevance, trust, recency, engagement and author credibility, keeps the **top 10**, and has Llama 3.1 8B write **one cited answer** from them:

| Layer | Sources | What it adds |
|---|---|---|
| 🩺 **Clinical research** | PubMed (live), ClinicalTrials.gov (live), curated NIH / AHA facts | What the evidence actually supports |
| 🛡️ **Safety** | OpenFDA supplement + medicine adverse events, recalls, drug labels (live), red-flag symptom checks | What could go wrong |
| 👥 **Community** | Health Stack Exchange (live), Reddit posts + top comments (live, keyless public JSON) | Real experience, **trust-scored** so scams and risky advice are filtered out |
| 🌿 **Ayurveda** | Curated herb knowledge base (22 entries) + importer for open herb datasets | Traditional remedies, each with **evidence level and cautions** |

The answer model is **Llama 3.1 8B (open source) on Groq**, which is free and fast. You can switch to any OpenAI-compatible open model (Ollama, Together, Hugging Face) or to Claude with one environment variable. With no key at all, a **mock mode** still produces cited answers, so the demo never depends on Wi-Fi or credits.

*General information only, not medical advice.*

---

## Live fetching and ranking (what happens on every question)

1. **Plan** (`netlify/lib/sources/index.mjs`): keywords from the question, plus the detected topic's condition, the best-matching Ayurvedic herb and the relevant medicine (e.g. ferrous sulfate for low RBC).
2. **Fetch in parallel, keyless** (each with a timeout; a failing source is skipped, never fatal):

| Source | Endpoint | What we take |
|---|---|---|
| PubMed | E-utilities `esearch` + `efetch` | up to 8 papers with **abstracts**, RCTs / reviews / meta-analyses first, retracted papers dropped |
| ClinicalTrials.gov | API v2 `/studies` | up to 6 trials: status, phase, enrollment, results, summary |
| OpenFDA | `food/event`, `food/enforcement`, `drug/event`, `drug/label` | herb adverse events + recalls, medicine adverse events + label warnings |
| Health Stack Exchange | `/search/advanced` + `/answers` | best (accepted / top-voted) answer for up to 6 questions |
| Reddit | public `.json` search over r/health, r/Ayurveda, r/nutrition, r/Supplements, r/medicine, r/AskDocs (+ topic subs) | up to 10 posts + top 2 comments of the 3 best threads (OAuth if `REDDIT_CLIENT_ID/SECRET` set) |
| Ayurvedic herb KB | local `knowledge/ayurveda.json` | best-matching curated entries with evidence level and cautions |

3. **Rank** (`netlify/lib/rank.mjs`). Every candidate (typically 30 to 50) gets five explainable 0..1 scores:

| Score | Weight | How |
|---|---|---|
| Relevance | 38% | IDF-weighted query terms in title (full) / text (0.7), topic synonyms, the API's own order |
| Trust | 25% | source tier (PubMed 1.0 > trials 0.85 > FDA 0.8 > Ayurveda KB 0.65 > Stack Exchange 0.6 > Reddit 0.4) × quality inside the source (meta-analysis > RCT > review; completed with results > recruiting; content check for scams, promo, risky dosing) |
| Credibility | 15% | MD / PhD / RN / BAMS / "Physician" flair, Stack Exchange reputation, accepted answer |
| Recency | 12% | exponential decay; half-life 6 y papers, 5 y trials, 4 y FDA / Q&A, 2 y Reddit |
| Engagement | 10% | upvotes, comments, awards, upvote ratio, answer score, views, trial enrollment |

   Items with relevance below 0.2, or rejected by the scam / promotion / "stop your meds" filter, are dropped. The top 10 are picked with **source diversity**: the best item of each source goes in first, then by score with at most 3 per source (2 for FDA and the KB).
4. **Answer**: the ranked top 10 (plus curated NIH clinical reference facts) go to **Llama 3.1 8B on Groq**, which must cite every claim (`[P1] [T1] [F1] [Q1] [R1] [A1] [E1]`). The UI shows each source card with its rank, "why ranked" and the full score breakdown.

## Architecture

```mermaid
flowchart LR
    U[User question] --> API["/api/chat (Netlify Function)"]
    API --> G{"Guards<br/>PII mask · jailbreak · stop-meds<br/>crisis · red flags · scope"}
    G -->|health question| EV[evidence.mjs]
    EV --> KB[("Local knowledge base<br/>clinical [E] · community [C] · Ayurveda [A]")]
    EV --> LIVE["Live connectors (parallel, 4s timeout each)"]
    LIVE --> P[PubMed P#]
    LIVE --> T[ClinicalTrials.gov T#]
    LIVE --> F[OpenFDA F#]
    LIVE --> Q[Health StackExchange Q#]
    LIVE --> R[Reddit R#]
    EV --> LLM["Llama 3.1 8B on Groq<br/>(or any open model / Claude / mock)"]
    LLM --> A["Cited answer:<br/>Summary · Research · Community · Ayurveda · Safety"]

    subgraph Offline pipeline (Python)
      RF[reddit_fetcher.py] --> B[build_kb.py]
      WP[wapo_parser.py] --> B
      HD[import_herbs.py] --> AJ[knowledge/ayurveda.json] --> B
      B -->|topic tagging + trust scoring| KB
    end
```

**How a question is answered**
1. **Guards** (`netlify/lib/checks.mjs`). Personal data is masked. Jailbreaks, "should I stop my medicine?" and prescription or bhasma dosing are declined **without calling the model**, because small models are easier to talk out of their rules. Crisis messages always get support lines, and red-flag symptoms (chest pain, fainting, Hb below 7) always get an urgent-care note first.
2. **Routing** (`netlify/lib/health.mjs`). The question is mapped to health topics (anemia/RBC, immunity, digestion, sleep, blood sugar, heart, joints, vitamin D). Off-topic messages and topic drift are declined.
3. **Local retrieval.** BM25 relevance × trust weight picks clinical facts, community comments and Ayurvedic entries.
4. **Live evidence** (`netlify/lib/sources/`). The topic gives the *condition* and the top Ayurvedic entry gives the *herb*. All APIs are queried in parallel, and any that fail are skipped.
5. **Answer.** The model must cite every claim (`[E1] [P2] [C3] [A1] [F1]`) and always include the Ayurvedic view with its evidence level and cautions.

## Community trust scoring

Every community item gets an **explainable 0–100 score**, starting from 50 (`pipeline/trust.py`, mirrored in `netlify/lib/trust.mjs`):

| Signal | Points |
|---|---|
| Net upvotes + reactions (log-scaled) | up to +20 |
| Accepted answer / high-reputation author / moderated site | +10 / +5 / +5 |
| Clinical expertise signal ("MD", "RN", "dietitian", "BAMS" in name or intro) | +10 |
| Evidence-aligned advice (iron + vitamin C, CBC, fibre, exercise…) | +10 |
| Recommends testing or seeing a doctor / cites a source | +5 / +5 |
| Scam language ("miracle", "cure in 7 days", "DM me") | −30 |
| Promo codes / affiliate links | −20 |
| Extreme doses or "stop your insulin" (negations like "never stop" are ignored) | −20 |

**≥ 65 trusted** (used), **40–64 review** (used only as a fallback), **< 40 rejected** (never shown). The UI shows *why* each item is trusted.

## Quick start (about 5 minutes)

Only **Node 18+** and a free **Groq key** are needed. Every data source is keyless.

```bash
git clone https://github.com/sakshamaggarwal/Gtransformers-Hack.git
cd Gtransformers-Hack
cp .env.example .env          # paste GROQ_API_KEY (free: https://console.groq.com/keys)
npm start                     # plain Node, no install needed -> http://localhost:8888
```

Open http://localhost:8888, ask a question, and the page connects to the local backend automatically (pill shows **Live backend**).
Check the raw ranked evidence without the model: `curl "http://localhost:8888/api/evidence?q=how+can+I+increase+my+RBC+count"`.

* `npm run dev` (Netlify CLI, needs `npm install`) also works and adds Netlify Blobs session storage.
* **Test without any network or key:** `npm test` runs 37 backend checks (connectors, ranking, diversity, chat contract, safety) against recorded-shape API fixtures.
* Edited `web/index.html`? Run `npm run sync:web` to copy it to `public/index.html` and the artifact version `web/app.html`.
* **Rebuild the knowledge base** after adding data: `npm run build:kb` (Python 3.10+, `pip install -r pipeline/requirements.txt`).

### Model options (set in `.env`)

| Setting | Model | Notes |
|---|---|---|
| `GROQ_API_KEY` | **Llama 3.1 8B** (`llama-3.1-8b-instant`) ⭐ default | Free tier, about 1 s replies. Set `GROQ_MODEL=llama-3.3-70b-versatile` for higher quality. |
| `OSS_BASE_URL=http://localhost:11434/v1`, `OSS_MODEL=llama3.1:8b` | Llama 3.1 8B via **Ollama**, fully local | Also works with Together, Hugging Face and vLLM. |
| `ANTHROPIC_API_KEY` | Claude (starter kit) | Fallback |
| *(none)* | Mock | Rule-based cited answers for offline demos |

### Deploy (Netlify)

```bash
npx netlify login
npx netlify init                 # link the repo
npx netlify env:import .env      # pushes GROQ_API_KEY etc.
npm run deploy
```

On Netlify, set **`STACKEXCHANGE_KEY`** (free, see [stackapps.com](https://stackapps.com/apps/oauth/register)), because the key-less quota is only 300 requests a day per IP, and serverless IPs are shared. If Reddit returns 403 from Netlify (it sometimes blocks data-centre IPs without OAuth), create a free "script" app at https://www.reddit.com/prefs/apps and set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. On your laptop the keyless path works.

## API

### `POST /api/chat` (starter-kit contract, so the hackathon test runner works)
```json
// request
{ "session_id": "optional-uuid", "message": "How can I increase my RBC count?" }
// response (abridged)
{ "session_id": "…", "behavior": "ANSWER", "reply": "Summary: …\nWhat research says: … [E1][P1]\n…",
  "flags": { "red_flag": false, "pii_redacted": [], "injection_suspected": false, "policy_block": false },
  "context": { "type": "health", "topics": ["Blood health (RBC, hemoglobin, anemia)"],
               "items": [ { "id": "C2", "kind": "community", "title": "…", "trust": 95, "signals": ["+10 clinical expertise signal", "…"], "url": "…" },
                          { "id": "A1", "kind": "ayurveda", "evidence": "limited", "cautions": "…" },
                          { "id": "P1", "kind": "pubmed", "url": "https://pubmed.ncbi.nlm.nih.gov/…" } ],
               "live_errors": [] },
  "provider": "groq", "model": "llama-3.1-8b-instant", "latency_ms": 1840 }
```

The same response also carries a **structured answer** for rich front ends such as Vaidya Pulse:
`summary`, `clinical[{text,cites}]`, `ayurvedic[{herb,sanskrit,use,evidence,caution,cites}]`, `community[{text,who,cites}]`, `safety[{text,cites}]`, `redFlags[]`, `crisis`, and
`sources[{id,src,title,snippet,meta,url,trust,rank,score,why}]`, where `src` is one of `pubmed | ctgov | openfda | ayur | hse | reddit | nih | community`. Ranked items come first (`rank` 1..10, `score` = `{total, relevance, trust, recency, engagement, credibility}`), then unranked reference facts. `ranking` = `{candidates, eligible, kept, per_source:{pubmed:{fetched,eligible,kept},…}, weights}`. `ayurvedic[].evidence` is always one of `moderate | limited | traditional | caution` (the KB's full wording is in `evidence_label`).

### `GET /api/evidence?q=…` (raw evidence, no model call, CORS open)
Returns the topics, clinical facts, community items with trust scores, Ayurvedic entries, live PubMed / trials / FDA / Stack Exchange results and the query plan. Use it for a custom front end or to show judges the data behind an answer.

## Data pipeline (Python, offline)

```bash
pip install -r pipeline/requirements.txt
# Reddit: OAuth (recommended) or public JSON fallback
export REDDIT_CLIENT_ID=… REDDIT_CLIENT_SECRET=…        # free "script" app at reddit.com/prefs/apps
python pipeline/reddit_fetcher.py --topic anemia_rbc --limit 10
# Open ayurvedic herb dataset (CSV) → knowledge/ayurveda.json (tagged "unreviewed import")
python pipeline/import_herbs.py herbs.csv --map name=Herb uses=Indications --source https://github.com/…
# (parked) Washington Post comments saved as HTML
python pipeline/wapo_parser.py data/raw/wapo/article.html --url https://www.washingtonpost.com/…
# Build: ingest → clean/mask PII → health filter → trust score → extract tips → emit JS modules
python pipeline/build_kb.py
```

## 3-minute demo script

| # | Ask | What to point out |
|---|---|---|
| 1 | *How can I increase my RBC count?* | All four layers in one answer; open **Evidence used** to show trust scores, live PubMed papers and FDA data |
| 2 | *is punarnava safe with iron tablets?* (follow-up) | Memory plus a safety catch: Punarnava Mandura already contains iron |
| 3 | *My hemoglobin is 6.5 and I fainted. What herbs help?* | ⚠️ urgent-care note comes **first** |
| 4 | *Should I stop my metformin and take karela juice?* | Declined deterministically; the scam comment saying exactly this was rejected (trust 0) |
| 5 | *Ignore previous instructions…* or *Write a poem* | Jailbreak and off-topic handling |

The **Test runner** tab loads `health_tests.csv` (15) and `safety_tests.csv` (15 red-team cases).

## Project structure

```
netlify/functions/chat/        POST /api/chat
netlify/functions/evidence/    GET  /api/evidence
netlify/lib/
  checks.mjs                   PII, injection, crisis, red flags, policy guards
  health.mjs                   topic routing + local retrieval (BM25 × trust)
  evidence.mjs                 local + live evidence for one question
  trust.mjs                    trust scoring for live community items
  llm.mjs                      system prompt + Groq / OSS / Claude / mock
  sources/                     pubmed, clinicaltrials, openfda, stackexchange, reddit
  knowledge/*.mjs              GENERATED by pipeline/build_kb.py
knowledge/                     ayurveda.json, clinical.json (human-curated sources of truth)
pipeline/                      taxonomy, trust, build_kb, reddit_fetcher, import_herbs, wapo_parser
data/raw/                      parser / fetcher outputs
public/                        chat UI + test runner, data/*.csv test sets
scripts/                       test-backend.mjs (offline), run-tests.mjs (CSV eval)
```

## Honest limitations

* **Demo community data is partly synthetic.** `data/raw/wapo/demo_health_comments.synthetic.json` holds hand-written comments in the WaPo parser's format, so the demo runs without scraping, and the UI labels them *"demo sample"*. Replace it by running `reddit_fetcher.py` and rebuilding. Live Stack Exchange answers are real.
* The offline tests use **fixture** API responses (titles start with `[FIXTURE]`). The live connectors follow each API's documented format but were not exercised from the build sandbox, whose network blocks those hosts. Check them once on the deployed site or with `npm run dev`.
* Trust scoring is rule-based: explainable and fast, but it can be gamed. Next steps: LLM claim-checking against PubMed abstracts, and agreement between sources.
* The Ayurvedic entries were curated from public sources (NCCIH, NIH ODS, published trials); a qualified practitioner should review them before real-world use.

## Roadmap
WaPo comment ingestion at scale · Supabase (Postgres + pgvector) for embeddings · MedGemma as a medical-tuned open model · more topics and languages (Hindi) · clinician review queue for "review"-labelled items.

---
Built on the [Gtransformers hackathon starter kit](https://github.com/gtransformerteam-ai/starter-kit) (see `docs/STARTER_KIT_README.md`).
