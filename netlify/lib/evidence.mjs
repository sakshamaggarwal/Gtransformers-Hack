// =============================================================================
// netlify/lib/evidence.mjs: one call that gathers ALL evidence for a question
// =============================================================================
// Used by both /api/chat (answers) and /api/evidence (raw evidence for any UI).
//   1 route: health question? (follow-ups reuse the previous question's topic)
//   2 local knowledge base: clinical facts, trust-scored community comments,
//     curated Ayurveda (health.mjs)
//   3 live APIs in parallel: PubMed, ClinicalTrials.gov, OpenFDA,
//     Health Stack Exchange, Reddit + the Ayurvedic KB, then RANKED to the
//     top 10 (sources/index.mjs + rank.mjs)
//   4 one text block for the model + one list of sources for the UI:
//     the ranked top 10 first, then the clinical reference facts they sit on
// =============================================================================

import { isHealthQuestion, retrieveHealth, formatHealthContext, sourcesForUI } from "./health.mjs";
import { gatherLiveEvidence, formatLiveEvidence } from "./sources/index.mjs";

const FOLLOW_UP = /^(and|what about|how about|ok|okay|also|any|anything|is it|are they|which|why|how long|how much|can i|should i|is that|tell me more|more)\b/i;

export async function buildEvidence(question, { previousContextType = null, previousQuestion = "", env = () => undefined } = {}) {
  if (!isHealthQuestion(question, previousContextType)) return null;

  // A short follow-up ("is it safe in pregnancy?") is searched together with the previous question.
  const isFollowUp = previousContextType === "health" && previousQuestion && (FOLLOW_UP.test(question.trim()) || question.length < 50);
  const searchText = isFollowUp ? `${previousQuestion} ${question}` : question;

  const local = retrieveHealth(searchText, { includeDemo: (env("INCLUDE_DEMO_COMMUNITY") ?? "").toLowerCase() === "on" });
  const live = await gatherLiveEvidence(searchText, local, env);

  // UI sources: ranked top 10, then unranked reference items (clinical facts, and
  // Ayurveda entries that did not make the top 10 but are cited on the herb cards).
  const rankedIds = new Set(live.items.map((x) => x.id));
  const refs = sourcesForUI(local).filter((x) => !rankedIds.has(x.id));

  return {
    question,
    search_text: searchText,
    topics: local.topics,
    topic_labels: local.topic_labels,
    clinical: local.clinical,
    community: local.community,
    ayurveda: local.ayurveda,
    live,
    ranking: live.ranking,
    sources: [...live.items, ...refs],
    contextText: formatHealthContext(local) + formatLiveEvidence(live),
  };
}
