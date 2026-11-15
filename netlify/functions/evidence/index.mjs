// =============================================================================
// netlify/functions/evidence/index.mjs: GET /api/evidence?q=...
// =============================================================================
// Returns the raw evidence bundle for a health question, without calling the
// model: topics, clinical facts, trust-scored community items, Ayurveda
// entries, and live PubMed / ClinicalTrials / OpenFDA / StackExchange results.
// Handy for a custom front end, a dashboard, or for judges to inspect.
// CORS is open so any front end can call it.
// =============================================================================

import { buildEvidence } from "../../lib/evidence.mjs";
import { validateMessage, redactPII } from "../../lib/checks.mjs";
import { env } from "../../lib/llm.mjs";
import { KB_STATS } from "../../lib/health.mjs";


const CORS = { "access-control-allow-origin": "*", "access-control-allow-methods": "GET, OPTIONS" };

export default async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  const q = new URL(req.url).searchParams.get("q");
  // No question: a health check (the front end uses it to detect a same-origin backend).
  if (!q) return Response.json({ ok: true, usage: "add ?q=your health question", knowledge_base: KB_STATS }, { headers: CORS });
  const input = validateMessage(q);
  if (!input.ok) return Response.json({ error: input.error }, { status: 400, headers: CORS });

  const started = Date.now();
  const ev = await buildEvidence(redactPII(input.text).text, { env });
  if (!ev) return Response.json({ health_question: false, message: "Not recognised as a health question." }, { headers: CORS });
  const { contextText, ...rest } = ev;
  return Response.json({ health_question: true, ...rest, knowledge_base: KB_STATS, latency_ms: Date.now() - started }, { headers: CORS });
};

export const config = { path: "/api/evidence" };
