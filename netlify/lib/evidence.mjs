// =============================================================================
// netlify/lib/evidence.mjs: one call that gathers ALL evidence for a question
// =============================================================================
// Used by both /api/chat (answers) and /api/evidence (raw evidence for any UI).
//   1 route: health question? (follow-ups reuse the previous question's topic)
//   2 local knowledge base: clinical facts, trust-scored community comments,
//     curated Ayurveda (health.mjs)
//   3 live APIs in parallel: PubMed, ClinicalTrials.gov, OpenFDA,
//     Health Stack Exchange, Reddit (sources/index.mjs)
//   4 one text block for the model + one list of sources for the UI
// =============================================================================

import { isHealthQuestion, retrieveHealth, formatHealthContext, sourcesForUI } from "./health.mjs";
import { gatherLiveEvidence, formatLiveEvidence } from "./sources/index.mjs";

const FOLLOW_UP = /^(and|what about|how about|ok|okay|also|any|anything|is it|are they|which|why|how long|how much|can i|should i|is that|tell me more|more)\b/i;

export async function buildEvidence(question, { previousContextType = null, previousQuestion = "", env = () => undefined } = {}) {
  if (!isHealthQuestion(question, previousContextType)) return null;

  // A short follow-up ("is it safe in pregnancy?") is searched together with the previous question.
  const isFollowUp = previousContextType === "health" && previousQuestion && (FOLLOW_UP.test(question.trim()) || question.length < 50);
  const searchText = isFollowUp ? `${previousQuestion} ${question}` : question;

  const local = retrieveHealth(searchText);
  const live = await gatherLiveEvidence(searchText, local, env);

  return {
    question,
    search_text: searchText,
    topics: local.topics,
    topic_labels: local.topic_labels,
    clinical: local.clinical,
    community: local.community,
    ayurveda: local.ayurveda,
    live,
    sources: [...sourcesForUI(local), ...live.items],
    contextText: formatHealthContext(local) + formatLiveEvidence(live),
  };
}
