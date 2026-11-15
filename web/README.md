# Vaidya Pulse web app

Single-page front end for the health intelligence app.

- `index.html` is the standalone page (open in a browser or deploy on Netlify).
- `app.html` is the same page without the HTML wrapper, used for the claude.ai artifact.

## Modes
- **Demo** (default): curated sample answers for 7 questions (blood count, follow-up on Punarnava with iron, blood pressure, digestion, sleep, blood sugar, ashwagandha with thyroid medicine), plus the same rule-based refusals and crisis screen the backend uses.
- **Live sources**: "Connect backend" → tick the live box. The browser calls PubMed E-utilities, OpenFDA (FAERS + CAERS), ClinicalTrials.gov v2, Stack Exchange (site=health) and Reddit search directly. All are free and need no key.
- **Live backend**: set the backend URL. The app POSTs `{ "message": "..." }` to `/api/chat` and expects the structured JSON shown in the Connect dialog (a plain `{ "reply": "..." }` also works). The backend runs Llama 3.1 8B on Groq (`llama-3.1-8b-instant`).

Crisis messages (self-harm, poisoning, emergencies) are screened in the browser first and never sent for a normal answer.

## Page layout
Hero (what it does) → **Ask** (question box, 7-step guided demo, source rail, layered answer with ranked source cards) → How it works → Data sources → Safety.

Loading shows three stages (search, rank, write). Errors offer **Try again**, **Show the sample answer** and backend settings. Declines, urgent red-flag notes and the model fallback each have their own card or banner.
