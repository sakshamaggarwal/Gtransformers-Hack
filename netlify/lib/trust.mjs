// =============================================================================
// netlify/lib/trust.mjs: credibility score for LIVE community items
// =============================================================================
// JavaScript mirror of pipeline/trust.py (same rules, same labels), used for
// Health Stack Exchange answers and live Reddit posts fetched at question time.
// Starts at 50; >= 65 trusted, 40-64 review, < 40 rejected. Every point is
// explained in `signals`, so the UI can show WHY an item is trusted.
// =============================================================================

const CLINICIAN_TOKENS = new Set(["md", "rn", "np", "rd", "pa", "pt", "phd", "do", "doc", "dr", "bams", "vaidya", "nurse",
  "doctor", "physician", "internist", "dietitian", "pharmacist", "pharmd", "cardio", "endo", "heme", "psych"]);
const CLINICIAN_IN_TEXT = /\b(doctor|physician|internist|nurse|pharmacist|dietitian|nutritionist|hematologist|cardiologist|endocrinologist|gastroenterologist|physical therapist|psychologist|ayurvedic (doctor|physician|practitioner)|bams)\b/i;
const EVIDENCE = /\b(iron|ferritin|b12|folate|vitamin [cd]|cbc|blood test|hemoglobin|fiber|fibre|exercise|sleep|vaccin\w*|a1c|ldl|statin|calcium|usp|third[- ]party|randomi[sz]ed|placebo)\b/i;
const SEE_DOCTOR = /\b(see|ask|talk to|check with|consult) (a |your )?(doctor|physician|gp|pcp|hematologist|dietitian)\b|\b(get|got) (tested|a blood test|blood ?work|labs)\b/i;
const CITES = /\b(nih|usp|nsf|who|cdc|mayo clinic|pubmed|doi|study|studies|trial|meta-?analysis|cochrane)\b|ncbi\.nlm\.nih\.gov/i;
const SCAM = /\b(miracle|guaranteed|100% (cure|natural)|cures? (it )?in \d+ days|doctors (hate|don'?t want)|dm me|message me|whatsapp|telegram|limited offer|buy now|order now|big pharma (hides|doesn'?t want)|detox your blood|secret (remedy|cure))\b/i;
const PROMO = /(bit\.ly|promo code|discount code|use code|affiliate|ref=)/i;
const EXTREME = /\b(\d{3,}\s*mg (of )?iron|\d{2,3},?000\s*iu|megadose|stop (taking )?(your )?(insulin|metformin|statin|medication|meds))\b/gi;
const NEGATED = /(never|don'?t|do not|not|without)\s+(\w+\s+){0,2}$/i;

export const authorIsClinician = (author) =>
  (author.match(/[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+/g) ?? []).some((p) => CLINICIAN_TOKENS.has(p.toLowerCase()));

function risky(text) {
  for (const m of text.matchAll(EXTREME)) if (!NEGATED.test(text.slice(Math.max(0, m.index - 25), m.index))) return true;
  return false;
}

export function trustScore({ text = "", author = "", upvotes = 0, downvotes = 0, reactions = 0, accepted = false, reputation = 0, moderated = false }) {
  if (text.split(/\s+/).length < 12) return { score: 0, label: "rejected", signals: ["too short"] };
  let score = 50;
  const signals = [];
  const add = (pts, why) => { score += pts; signals.push(`${pts > 0 ? "+" : ""}${pts} ${why}`); };

  const net = upvotes - downvotes;
  const engagement = Math.max(net, 0) + 0.5 * reactions;
  if (engagement > 0) add(Math.min(20, Math.round(6 * Math.log2(1 + engagement))), `community votes (${net >= 0 ? "+" : ""}${net} net)`);
  if (net < 0) add(-10, "downvoted");
  if (accepted) add(10, "accepted answer");
  if (reputation >= 1000) add(5, `high-reputation author (${reputation})`);
  if (moderated) add(5, "moderated Q&A site");
  if (authorIsClinician(author) || CLINICIAN_IN_TEXT.test(text.slice(0, 90))) add(10, "clinical expertise signal");
  if (EVIDENCE.test(text)) add(10, "evidence-aligned advice");
  if (SEE_DOCTOR.test(text)) add(5, "recommends testing / doctor");
  if (CITES.test(text)) add(5, "cites a source");
  if (SCAM.test(text)) add(-30, "scam language");
  if (PROMO.test(text)) add(-20, "links / promotion");
  if (risky(text)) add(-20, "risky dosing / stopping meds");

  score = Math.max(0, Math.min(100, score));
  return { score, label: score >= 65 ? "trusted" : score >= 40 ? "review" : "rejected", signals };
}
