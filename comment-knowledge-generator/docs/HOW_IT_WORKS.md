# How it works

## 1. Parse (`nyt_comments_to_json.py`, `wapo_comments_to_json.py`)
Reads the comments panel saved from the browser. NYT replies are nested inside their
parent's markup; WaPo replies sit in a "Replies to comment" section next to the parent.
Output: a JSON tree (`replies` lists). The WaPo parser also compares each "Collapse N
replies" button with the replies actually in the page and reports any that weren't loaded.

## 2. Extract (`extract_units.py`, Claude Haiku)
Each comment is sent with the article's title and summary and the comments above it, and
the model records zero or more **units**: claim, experience, expertise, correction,
question, advice or opinion, each with a standalone statement, a topic, a stance toward
the article and a verbatim quote. Code checks each quote really appears in the comment.
Runs are resumable: one JSON line per comment.

## 3. Cluster (`cluster_units.py`)
Units are embedded (Voyage, OpenAI, a local model or offline TF-IDF) and grouped twice:
**topics** (same subject) and, inside each, **points** (same statement). Groups are scored
mainly by **breadth** (distinct readers), plus endorsement (log-scaled, normalised per
article) and claimed expertise. `--sweep` shows how thresholds change the grouping.

## 4. Write cards (`synthesize_cards.py`, Claude Sonnet)
For each top topic the model gets an evidence pack (top points, one unit per reader, each
with a key like `[c12]`) and writes a card: takeaway, experiences, claims, corrections,
disagreements, open questions, advice. It must cite keys and may not write reader counts;
code resolves citations, drops unknown ones and computes "N readers" itself.

## 5a. Verify (`verify_cards.py`, Claude Sonnet)
Free code checks first: citations resolve, quotes appear in the full comment, text pasted
by 3+ readers is flagged, wording matches the reader count, disagreements have two
different people. Then one review per card against the full cited comments (and what they
reply to): supported / partly / unsupported, the problem (misread, sarcasm, article text,
overstated), a corrected wording and a health-risk level. Code applies the verdicts and
gives each card a status: **ok**, **review** (high health risk or leftover flags) or
**hold** (incoherent, unsupported takeaway, or over 40% of items removed).

## 5b. Publish (`publish_cards.py`, `search_knowledge.py`)
Writes one self-contained page and a SQLite database. By default: only ok/review cards,
no high-risk items, commenter names replaced by "Reader 1, 2…", a not-medical-advice note
on health cards. The page searches item text and the quoted comments as a phrase on word
boundaries and shows only matching items. The database has `cards`, `items`,
`disagreements`, `refs` (quotes), `item_refs`, views `v_items` and `v_citations`, and
full-text indexes over item text, issues and quotes.
