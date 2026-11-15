// =============================================================================
// netlify/functions/chat/index.mjs: POST /api/chat
// =============================================================================
// The main backend. Every chat message (from the web page or the test runner)
// comes here. It is a Netlify Function: Netlify runs this file on its servers
// whenever someone calls /api/chat, so the API key never reaches the browser.
//
// Request : { "session_id": "<uuid>" (omit for a new chat), "message": "..." }
// Response: { session_id, turn, behavior, reply, flags, provider, model,
//             prompt_version, storage, latency_ms, usage }
//
// FLOW 1 in docs/HOW_IT_WORKS.md. The step numbers below match the doc:
//   1  Accept only POST with a JSON body
//   2  Validate the message (empty / too long)
//   3  Rate-limit the caller
//   4  Load the chat session, or create a new one
//   5  Stop if the chat is too long
//   6  Mask personal data, and flag injection / distress
//   7a Health question? Retrieve evidence:
//        local knowledge base (clinical [E], scored community [C], Ayurveda [A])
//        + live APIs in parallel (PubMed [P], ClinicalTrials [T], OpenFDA [F], StackExchange [Q], Reddit [R])
//        + ranking: every fetched item scored, top 10 kept with source diversity (rank.mjs)
//   7  Build the conversation history the model will see (this is the "memory")
//   8  Call the model and check its answer format
//   9  Force a caring reply if distress was detected; urgent note on red flags
//   10 Remove personal data from the reply
//   11 Save both messages to the session
//   12 Return the reply, and log (without message text)
// =============================================================================

import { loadSession, saveSession, newSession, isValidId, storageKind } from "../../lib/store.mjs";
import {
  validateMessage, redactPII, looksLikeInjection, showsDistress, parseModelOutput, hasRedFlag, policyBlock,
  SUPPORT_LINE, URGENT_NOTE, MAX_TURNS_PER_SESSION, HISTORY_TURNS_SENT,
} from "../../lib/checks.mjs";
import { callLLM, mockLLM, provider, modelName, env, PROMPT_VERSION } from "../../lib/llm.mjs";
import { buildEvidence } from "../../lib/evidence.mjs";
import { toStructured } from "../../lib/structure.mjs";

// -----------------------------------------------------------------------------
// Rate limiter used in step 3.
// Remembers the timestamps of recent requests per IP address and refuses
// anything over RATE_LIMIT_PER_MIN in the last 60 seconds.
// Limitation: it lives in this function instance's memory, so it is
// best-effort (Netlify may run several instances). Good enough for a demo;
// use a shared store (e.g. Netlify Blobs or Redis) for real traffic.
// -----------------------------------------------------------------------------
const hits = new Map(); // ip -> [timestamp, timestamp, ...]

function rateLimited(ip) {
  const limit = Number(env("RATE_LIMIT_PER_MIN") || 30);
  const now = Date.now();
  // Keep only requests from the last 60 seconds, then add this one.
  const recent = (hits.get(ip) ?? []).filter((t) => now - t < 60_000);
  recent.push(now);
  hits.set(ip, recent);
  return recent.length > limit;
}

// -----------------------------------------------------------------------------
// The handler. Netlify calls this with a standard web Request object and a
// `context` object (context.ip is the caller's IP address).
// -----------------------------------------------------------------------------
export default async (req, context) => {
  const started = Date.now(); // used for latency_ms in the response

  // ---- Step 1: accept only POST with a JSON body ---------------------------
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (req.method !== "POST") return Response.json({ error: "Use POST" }, { status: 405, headers: CORS });

  let body;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'Body must be JSON: {"message": "..."}' }, { status: 400, headers: CORS });
  }

  // ---- Step 2: validate the message ----------------------------------------
  // Rejects empty messages and messages over MAX_MESSAGE_CHARS (see checks.mjs).
  const input = validateMessage(body?.message);
  if (!input.ok) return Response.json({ error: input.error }, { status: 400, headers: CORS });

  // ---- Step 3: rate limit ----------------------------------------------------
  // 429 + retry-after tells well-behaved clients (like scripts/run-tests.mjs)
  // to wait and try again.
  if (rateLimited(context?.ip ?? "unknown")) {
    return Response.json(
      { error: "Too many messages, please slow down." },
      { status: 429, headers: { ...CORS, "retry-after": "10" } }
    );
  }

  // ---- Step 4: load the session, or create a new one -----------------------
  // The browser sends the session_id it got back from the first message.
  // We only accept proper UUIDs, so nobody can use odd keys in the store.
  let session = null;
  if (body.session_id != null) {
    if (!isValidId(body.session_id)) return Response.json({ error: "invalid session_id" }, { status: 400, headers: CORS });
    session = await loadSession(body.session_id);
  }
  // No id, or an id we've never seen (e.g. after a local restart): start a new chat.
  session ??= newSession(isValidId(body.session_id) ? body.session_id : crypto.randomUUID());

  // ---- Step 5: cap the conversation length (cost control) -------------------
  const userTurns = session.messages.filter((m) => m.role === "user").length;
  if (userTurns >= MAX_TURNS_PER_SESSION) {
    return Response.json({ error: "This conversation is full. Please start a new chat." }, { status: 400, headers: CORS });
  }

  // ---- Step 6: mask personal data, and raise flags ---------------------------
  // From here on we only use `redacted.text`: the model, the saved chat and
  // the logs never see the original email / phone / card / SSN.
  const redacted = redactPII(input.text);
  const flags = {
    pii_redacted: redacted.found,                     // e.g. ["email", "phone"]
    injection_suspected: looksLikeInjection(input.text), // flagged, NOT blocked
    distress: showsDistress(input.text),                // triggers step 9
    output_valid: true,                                  // updated in step 8
  };

  // ---- Step 6b: hard policy guards ------------------------------------------------
  // Jailbreaks, "stop my medicine", prescription / bhasma dosing: decline without
  // calling the model (small models are easier to argue out of their rules).
  const blocked = flags.distress ? null : policyBlock(input.text, flags.injection_suspected);

  // ---- Step 7a: add extra context (RAG or external API) --------------------------
  // Health question (or a short follow-up to one)? buildEvidence (evidence.mjs)
  // fetches all six sources live, ranks them and keeps the top 10.
  // Anything else gets no extra context and is declined by the model.
  // The extra context is put IN FRONT of the user's message for the model only.
  // It is not saved in the chat history; only which sources were used is saved.
  let extra = null;        // { type: "health", source, items: [...] }, returned to the browser
  let contextText = "";    // the text block the model sees
  let evidence = null;     // structured evidence (also used by the mock model)
  const lastBot = [...session.messages].reverse().find((m) => m.role === "assistant");
  const lastUser = [...session.messages].reverse().find((m) => m.role === "user");

  const ev = blocked ? null : await buildEvidence(redacted.text, { previousContextType: lastBot?.context_type, previousQuestion: lastUser?.content, env });
  if (ev) {
    evidence = ev;
    contextText = ev.contextText;
    extra = { type: "health", source: "Vaidya Pulse evidence", topics: ev.topic_labels, items: ev.sources, live_errors: ev.live?.errors ?? [], live_ms: ev.live?.took_ms ?? 0, ranking: ev.ranking ?? null };
  }

  // ---- Step 7: build the conversation history (the "memory") ----------------
  // The model itself remembers nothing between calls. We resend the last
  // HISTORY_TURNS_SENT exchanges every time, followed by the new message.
  // That is how "how about the orange?" is understood after the apple question.
  // Past bot replies are sent back in the same JSON shape we ask the model to
  // use, which helps it keep answering in that format.
  const past = session.messages.slice(-HISTORY_TURNS_SENT * 2).map((m) => ({
    role: m.role,
    content: m.role === "assistant" ? JSON.stringify({ behavior: m.behavior, reply: m.content }) : m.content,
  }));
  const userForModel = contextText ? `${contextText}\n\nUSER MESSAGE:\n${redacted.text}` : redacted.text;
  const history = [...past, { role: "user", content: userForModel }];

  // ---- Step 8: call the model and check its answer ---------------------------
  // callLLM (llm.mjs) picks Claude, OpenAI or the mock model.
  // parseModelOutput (checks.mjs) makes sure we got {"behavior", "reply"}.
  let behavior, reply, usage = { input_tokens: 0, output_tokens: 0 }, usedModel = modelName(), degraded = null;
  try {
    if (blocked) throw Object.assign(new Error("policy"), { blocked: true });
    const llm = await callLLM(history, evidence);
    usage = llm.usage;
    if (llm.model) usedModel = llm.model;
    const parsed = parseModelOutput(llm.raw);
    flags.output_valid = parsed.ok;
    ({ behavior, reply } = parsed);
  } catch (err) {
    if (err.blocked) { behavior = "DECLINE"; reply = blocked; flags.policy_block = true; } else {
      // Network error, bad key, rate limit, timeout... Log the reason for the developer
      // (Netlify → Logs → Functions). The user still gets a cited answer: the rule-based
      // writer builds it from the same ranked evidence, and the UI says so.
      console.error(JSON.stringify({ event: "llm_error", message: String(err.message).slice(0, 300) }));
      if (env("LLM_FALLBACK") === "off") return Response.json({ error: "The assistant is unavailable right now. Please try again." }, { status: 502, headers: CORS });
      const parsed = parseModelOutput(mockLLM(history, evidence));
      ({ behavior, reply } = parsed);
      reply = reply.replace(" (mock model, no AI key set)", "");
      usedModel = "rule-based fallback";
      degraded = /\b(401|403)\b/.test(err.message) ? "model_auth" : /\b429\b/.test(err.message) ? "model_rate_limited" : /timeout|abort/i.test(err.message) ? "model_timeout" : "model_unavailable";
      flags.llm_fallback = true;
    }
  }

  // ---- Step 9: distress always gets support resources ------------------------
  // A safety net that doesn't depend on the model getting it right.
  if (flags.distress) {
    behavior = "CARE";
    if (!reply.includes("988")) reply = `${reply} ${SUPPORT_LINE}`.trim();
  }
  // ---- Step 9b: red-flag symptoms always get an urgent-care note first ------------
  flags.red_flag = hasRedFlag(input.text);
  if (flags.red_flag && !flags.distress && !reply.startsWith("⚠️")) reply = `${URGENT_NOTE}\n\n${reply}`;

  // ---- Step 10: never echo personal data back --------------------------------
  reply = redactPII(reply).text;

  // ---- Step 11: save both messages to the session ----------------------------
  // The chat title is the first message (shown in the sidebar and downloads).
  session.messages.push({ role: "user", content: redacted.text, ts: new Date().toISOString() });
  session.messages.push({
    role: "assistant", content: reply, behavior, ts: new Date().toISOString(),
    // Remember which sources were used, so follow-ups can reuse RAG (step 7a)
    // and reopened chats can show the source tags.
    ...(extra && { context_type: extra.type, context_source: extra.source, context_ids: extra.items.map((x, i) => x.id ?? `H${i + 1}`) }),
  });
  if (!session.title) session.title = redacted.text.slice(0, 60);
  await saveSession(session);

  // ---- Step 12: respond, and log without message text ------------------------
  const response = {
    session_id: session.id,   // the browser keeps this and sends it with the next message
    turn: userTurns + 1,
    behavior,                 // ANSWER | DECLINE | CARE (used by the test runner)
    reply,                    // what the user sees
    flags,
    ...toStructured({ reply, behavior, evidence, flags }), // summary, clinical, ayurvedic, community, safety, redFlags, sources, crisis
    context: extra,           // every source given to the model, with trust scores (null if not a health question)
    ranking: extra?.ranking ?? null, // { candidates, eligible, kept, per_source: {pubmed: {fetched, eligible, kept}, ...}, weights }
    live_errors: extra?.live_errors ?? [],
    provider: degraded ? "fallback" : provider(), // groq | oss | anthropic | openai | mock | fallback
    model: usedModel,
    degraded,                 // null, or why the AI model was skipped (model_auth | model_rate_limited | model_timeout | model_unavailable)
    prompt_version: PROMPT_VERSION,
    storage: await storageKind(), // netlify-blobs | memory
    latency_ms: Date.now() - started,
    usage,                    // tokens, for cost estimates
  };

  // QUIET_LOGS is set by the test script to keep its output readable.
  if (!env("QUIET_LOGS")) {
    console.log(JSON.stringify({ event: "chat", turn: response.turn, behavior, flags, context_type: extra?.type ?? null, latency_ms: response.latency_ms }));
  }
  return Response.json(response, { headers: CORS });
};

// Open CORS so a separately hosted front end (e.g. the demo artifact) can call the API.
const CORS = { "access-control-allow-origin": "*", "access-control-allow-methods": "POST, OPTIONS", "access-control-allow-headers": "content-type" };

// Tells Netlify which URL this function answers on.
export const config = { path: "/api/chat" };
