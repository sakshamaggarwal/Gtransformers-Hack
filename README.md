# 🌿 Sangam Health: Community-Generated Health Intelligence

> *Sangam* (संगम) means "confluence": the place where rivers meet.

Ask a health question, for example **"How can I increase my RBC count?"**, and get **one cited answer** that brings together four streams of evidence:

| Layer | Sources | What it adds |
|---|---|---|
| 🩺 **Clinical research** | PubMed (live), ClinicalTrials.gov (live), curated NIH / AHA facts | What the evidence actually supports |
| 🛡️ **Safety** | OpenFDA adverse-event reports + recalls (live), red-flag symptom checks | What could go wrong |
| 👥 **Community** | Health Stack Exchange (live), Reddit (batch + optional live), WaPo comments (parked) | Real experience, **trust-scored** so scams and risky advice are filtered out |
| 🌿 **Ayurveda** | Curated herb knowledge base (22 entries) + importer for open herb datasets | Traditional remedies, each with **evidence level and cautions** |

The answer model is **Llama 3.1 8B (open source) on Groq**, which is free and fast. You can switch to any OpenAI-compatible open model (Ollama, Together, Hugging Face) or to Claude with one environment variable. With no key at all, a **mock mode** still produces cited answers, so the demo never depends on Wi-Fi or credits.

*General information only, not medical advice.*

---

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

```bash
git clone https://github.com/sakshamaggarwal/Gtransformers-Hack.git
cd Gtransformers-Hack
npm install
cp .env.example .env          # add GROQ_API_KEY (free: https://console.groq.com/keys), or leave empty for mock mode
npm run dev                   # http://localhost:8888
```

* **Test without any network or key:** `npm test` runs 26 backend checks against recorded-shape API fixtures.
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

On Netlify, set **`STACKEXCHANGE_KEY`** (free, see [stackapps.com](https://stackapps.com/apps/oauth/register)), because the key-less quota is only 300 requests a day per IP, and serverless IPs are shared.

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
`sources[{id,src,title,snippet,meta,url,trust}]`, where `src` is one of `pubmed | ctgov | openfda | ayur | hse | reddit | nih | wapo`.

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
