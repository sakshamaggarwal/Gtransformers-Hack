# Community comment analysis

Static page ("What readers know") built from reader comments on health and supplement articles: 29 analyzed topics with verdicts, health risk flags, reader counts and citations.

- `index.html`: self-contained page (data inlined as JSON, no external requests). Open it directly or deploy as a static site.
- `knowledge.db`: SQLite source data (articles, cards, items, refs, disagreements, FTS indexes). Not read by the page; served as a download.
- `netlify.toml`: static deploy config. In Netlify set **Base directory** to `community-analysis`, leave the build command empty.
