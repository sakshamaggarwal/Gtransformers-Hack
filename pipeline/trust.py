"""
Credibility (trust) scoring for community comments.

Rule-based on purpose: fast, free, and every point is explainable to a
judge or a user ("why is this comment trusted?"). Each item starts at 50.

| Signal                                             | Effect     |
|----------------------------------------------------|------------|
| Net votes (log-scaled) + reactions                 | up to +20  |
| Author signals clinical expertise (MD, RN, RD...)  | +10        |
| Mentions evidence-backed nutrient/test for topic   | +10        |
| Recommends seeing a doctor / getting tested        | +5         |
| Cites a reputable source (NIH, USP, study, trial)  | +5         |
| Scam language ("miracle", "cure in 7 days", DM me) | -30        |
| Links / promo codes / affiliate                    | -20        |
| Extreme dosing                                     | -20        |
| Downvoted more than upvoted                        | -10        |
| Too short (< 12 words)                             | rejected   |

Labels: >= 65 trusted, 40-64 review, < 40 rejected.
"""

import math
import re

CLINICIAN_TOKENS = {"md", "rn", "np", "rd", "pa", "pt", "phd", "do", "doc", "dr", "bams", "vaidya", "nurse", "doctor",
                    "physician", "internist", "dietitian", "pharmacist", "pharmd", "cardio", "endo", "heme", "psych"}
CLINICIAN = re.compile(
    r"(\bmd\b|md$|\bdr\.?\s|\bdoctor\b|\bphysician\b|\binternist\b|\bnurse\b|\brn\b|\bnp\b|\bpharmacist\b|"
    r"\bpharmd\b|\bdietitian\b|\brd\b|\bnutritionist\b|\bhematolog|\bcardiolog|\bendocrinolog|\bgastroenterolog|"
    r"\bbams\b|\bvaidya\b|\bmd\(ayu\)|\bayurvedic (doctor|physician|practitioner))",
    re.I,
)
CLINICIAN_IN_TEXT = re.compile(
    r"\b(doctor|physician|internist|nurse|pharmacist|dietitian|nutritionist|hematologist|cardiologist|"
    r"endocrinologist|gastroenterologist|physical therapist|psychologist|nurse practitioner|"
    r"ayurvedic (doctor|physician|practitioner)|bams)\b",
    re.I,
)
NEGATED = re.compile(r"(never|don'?t|do not|not|without)\s+(\w+\s+){0,2}$", re.I)


def author_is_clinician(author):
    """'HemeDocRN' -> {heme, doc, rn}; 'ID_Physician_MD' -> {id, physician, md}."""
    parts = re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+", author)
    return bool({p.lower() for p in parts} & CLINICIAN_TOKENS) or bool(CLINICIAN.search(author))


def risky(text):
    """Extreme dose / stop-your-meds advice, ignoring negated warnings like 'never stop metformin'."""
    for m in EXTREME_DOSE.finditer(text):
        if not NEGATED.search(text[max(0, m.start() - 25):m.start()]):
            return True
    return False
EVIDENCE_TERMS = {
    "anemia_rbc": r"\b(iron|ferritin|b12|folate|folic|vitamin c|heme|cbc|blood test|hemoglobin)\b",
    "immunity": r"\b(sleep|vaccin|vitamin d|zinc|exercise|hand ?washing)\b",
    "digestion": r"\b(fiber|fibre|water|hydrat|probiotic|fodmap|smaller meals)\b",
    "sleep_stress": r"\b(sleep hygiene|caffeine|screen|routine|cbt-?i|exercise|melatonin)\b",
    "blood_sugar": r"\b(a1c|fiber|fibre|walk|exercise|carb|metformin|weight)\b",
    "heart_cholesterol": r"\b(ldl|statin|fiber|fibre|oats|saturated fat|exercise|sodium|salt)\b",
    "joint_pain": r"\b(exercise|physical therapy|weight|strength|low impact|swimming)\b",
    "vitamin_d_bone": r"\b(vitamin d|calcium|25-?oh|blood test|weight[- ]bearing|sun)\b",
    "supplements_general": r"\b(usp|third[- ]party|3rd[- ]party|fda|nsf|study|studies|trial)\b",
}
SEE_DOCTOR = re.compile(r"\b(see|ask|talk to|check with|consult) (a |your )?(doctor|physician|gp|pcp|hematologist|dietitian)|"
                        r"\b(get|got) (tested|a blood test|blood work|bloodwork|labs)\b|\bblood ?work\b", re.I)
CITES_SOURCE = re.compile(r"\b(nih|usp|nsf|who|cdc|mayo clinic|pubmed|study|studies|trial|meta-?analysis|cochrane)\b", re.I)
SCAM = re.compile(
    r"\b(miracle|guaranteed|100% (cure|natural cure)|cures? (it )?in \d+ days|doctors (hate|don'?t want)|"
    r"dm me|message me|whatsapp|telegram|limited offer|buy now|order now|big pharma (hides|doesn'?t want)|"
    r"detox your blood|secret (remedy|cure))\b",
    re.I,
)
PROMO = re.compile(r"(bit\.ly|promo code|discount code|use code|affiliate|\.com/\S*ref=)", re.I)
EXTREME_DOSE = re.compile(
    r"\b(\d{3,}\s*mg (of )?iron|iron[^.]{0,30}\b\d{3,}\s*mg|\d{2,3},?000\s*iu|\d{2,}\s*(g|grams) (of )?(turmeric|ashwagandha)|"
    r"(megadose|mega-dose)|drink (a )?(cup|glass) of (bleach|turpentine|kerosene)|stop (taking )?(your )?(insulin|metformin|statin|medication|meds))",
    re.I,
)
ACTION = re.compile(
    r"\b(eat|add|take|try|drink|cook|pair|avoid|skip|switch|walk|sleep|ask|get|check|soak|combine|have|cut|limit|use)\b",
    re.I,
)


def trust_score(item, topics):
    text, author = item["text"], item.get("author", "") + " " + item.get("author_flair", "")
    words = len(text.split())
    signals = []
    if words < 12:
        return 0, "rejected", ["too short"]

    score = 50
    net = item.get("upvotes", 0) - item.get("downvotes", 0)
    engagement = max(net, 0) + 0.5 * item.get("reactions", 0)
    if engagement > 0:
        pts = min(20, round(6 * math.log2(1 + engagement)))
        score += pts
        signals.append(f"+{pts} community votes ({net:+d} net)")
    if net < 0:
        score -= 10
        signals.append("-10 downvoted")

    if author_is_clinician(author) or CLINICIAN_IN_TEXT.search(text[:90]):
        score += 10
        signals.append("+10 clinical expertise signal")
    if any(re.search(EVIDENCE_TERMS[t], text, re.I) for t in topics if t in EVIDENCE_TERMS):
        score += 10
        signals.append("+10 evidence-aligned advice")
    if SEE_DOCTOR.search(text):
        score += 5
        signals.append("+5 recommends testing / doctor")
    if CITES_SOURCE.search(text):
        score += 5
        signals.append("+5 cites a source")
    if SCAM.search(text):
        score -= 30
        signals.append("-30 scam language")
    if PROMO.search(text):
        score -= 20
        signals.append("-20 links / promotion")
    if risky(text):
        score -= 20
        signals.append("-20 risky dosing / stopping meds")

    score = max(0, min(100, score))
    label = "trusted" if score >= 65 else "review" if score >= 40 else "rejected"
    return score, label, signals


def extract_tips(text, max_tips=3):
    """Pick the sentences that read like actionable advice."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    tips = [s.strip() for s in sentences if ACTION.search(s) and 5 <= len(s.split()) <= 45]
    return tips[:max_tips]
