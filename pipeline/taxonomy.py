"""
Health topic taxonomy shared by the pipeline and (via build_kb.py) the chat app.

Each topic has keywords used to:
  - tag community comments with topics (health relevance filter)
  - route a user's question to the right ayurvedic + clinical entries
  - search Reddit (reddit_fetcher.py)
"""

TOPICS = {
    "anemia_rbc": {
        "condition": "anemia",
        "label": "Blood health (RBC, hemoglobin, anemia)",
        "keywords": ["rbc", "red blood", "hemoglobin", "haemoglobin", "anemia", "anaemia", "anemic", "anaemic",
                     "iron", "ferritin", "hematocrit", "b12", "folate", "folic", "pale", "blood count", "hb",
                     "punarnava", "mandura", "weak blood", "low blood"],
    },
    "immunity": {
        "condition": "common cold OR immunity",
        "label": "Immunity",
        "keywords": ["immunity", "immune", "cold", "colds", "flu", "infection", "infections", "getting sick", "fall sick",
                     "sore throat", "tulsi", "kadha", "giloy", "guduchi", "chyawanprash"],
    },
    "digestion": {
        "condition": "dyspepsia OR constipation OR irritable bowel syndrome",
        "label": "Digestion and gut health",
        "keywords": ["digestion", "digestive", "bloating", "bloated", "constipation", "acidity", "acid reflux",
                     "heartburn", "indigestion", "gut", "ibs", "gas", "triphala", "stool", "bowel"],
    },
    "sleep_stress": {
        "condition": "insomnia OR stress",
        "label": "Sleep and stress",
        "keywords": ["sleep", "insomnia", "stress", "stressed", "cortisol", "restless", "tired", "fatigue",
                     "ashwagandha", "brahmi", "melatonin", "dinacharya"],
    },
    "blood_sugar": {
        "condition": "type 2 diabetes OR prediabetes",
        "label": "Blood sugar",
        "keywords": ["blood sugar", "glucose", "diabetes", "diabetic", "prediabetes", "prediabetic", "a1c",
                     "insulin", "methi", "fenugreek", "gymnema", "gudmar", "karela", "bitter melon"],
    },
    "heart_cholesterol": {
        "condition": "hypercholesterolemia OR hypertension",
        "label": "Heart health and cholesterol",
        "keywords": ["cholesterol", "ldl", "hdl", "triglycerides", "blood pressure", "hypertension", "heart",
                     "statin", "statins", "arjuna", "guggul", "guggulu", "bp meds"],
    },
    "joint_pain": {
        "condition": "osteoarthritis",
        "label": "Joints and inflammation",
        "keywords": ["joint", "joints", "arthritis", "osteoarthritis", "knee", "knees", "inflammation", "stiffness", "turmeric", "curcumin", "boswellia", "shallaki"],
    },
    "vitamin_d_bone": {
        "condition": "vitamin D deficiency OR osteoporosis",
        "label": "Vitamin D and bone health",
        "keywords": ["vitamin d", "bone", "bones", "osteoporosis", "calcium", "sunlight"],
    },
    "supplements_general": {
        "condition": "dietary supplements",
        "label": "Supplements in general",
        "keywords": ["supplement", "supplements", "multivitamin", "vitamins", "otc", "usp"],
    },
}


def tag_topics(text):
    """Return the topics whose keywords appear in `text` (word-boundary match)."""
    import re

    t = " " + text.lower() + " "
    found = []
    for topic, spec in TOPICS.items():
        for kw in spec["keywords"]:
            if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t):
                found.append(topic)
                break
    return found
