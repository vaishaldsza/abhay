"""
Core Safety Answers for Critical Disaster Situations.
Replaces invented guidance with official district placeholders:
- Known safety topics: "Approved answer pending from district authority"
- Fallback / Unknown topics: "I don't know that yet. A person will follow up."
- Always flags for human follow-up.
"""

from typing import Tuple, Optional

APPROVED_PENDING_ANSWER = {
    "en": "Approved answer pending from district authority.",
    "kn": "ಜಿಲ್ಲಾಡಳಿತದಿಂದ ಅಧಿಕೃತ ಉತ್ತರ ಬಾಕಿ ಇದೆ.",
    "hi": "जिला प्राधिकरण से स्वीकृत उत्तर प्रतीक्षित है।"
}

FALLBACK_UNKNOWN_ANSWER = {
    "en": "I don't know that yet. A person will follow up.",
    "kn": "ನನಗೆ ಈ ಮಾಹಿತಿ ತಿಳಿದಿಲ್ಲ. ಅಧಿಕಾರಿಯೊಬ್ಬರು ನಂತರ ಸಂಪರ್ಕಿಸಲಿದ್ದಾರೆ.",
    "hi": "मुझे अभी इसकी जानकारी नहीं है। कोई व्यक्ति आपसे संपर्क करेगा।"
}

SAFETY_QA_DATABASE = [
    {
        "category": "pets_cattle",
        "keywords": ["pet", "dog", "cat", "cow", "cattle", "livestock", "buffalo", "ಹಸು", "ದನ", "ನಾಯಿ", "ಬೆಕ್ಕು", "गाय", "भैंस", "पालतू", "जानवर"],
        "answer_en": "Approved answer pending from district authority."
    },
    {
        "category": "road_bridge_routes",
        "keywords": ["road open", "which road", "bridge safe", "can i drive", "highway open", "nh 66", "ರಸ್ತೆ", "ಸೇತುವೆ", "ಯಾವ ರಸ್ತೆ", "ಸಂಚಾರ", "रास्ता खुला", "सड़क खुली", "पुल", "गाड़ी चलाऊं"],
        "answer_en": "Approved answer pending from district authority."
    },
    {
        "category": "medicine_oxygen",
        "keywords": ["oxygen", "cylinder", "flow rate", "insulin", "dosage", "medicine dose", "ಆಮ್ಲಜನಕ", "ಸಿಲಿಂಡರ್", "ಔಷಧಿ", "ಮಾತ್ರೆ", "ऑक्सीजन", "दवा", "सिलेंडर"],
        "answer_en": "Approved answer pending from district authority."
    }
]

def get_safety_answer(query: str, lang: str = "en") -> Tuple[Optional[str], bool]:
    """
    Checks if a query contains safety/danger topics.
    Returns: (answer_string, is_flagged_for_human).
    - Known safety topics return "Approved answer pending from district authority" and flag for a human.
    - Other safety inquiries return fallback "I don't know that yet. A person will follow up." and flag for a human.
    """
    if not query:
        return None, False

    lang = lang.lower() if lang in ("en", "kn", "hi") else "en"
    q_lower = query.lower()

    # Check known categories
    for item in SAFETY_QA_DATABASE:
        for kw in item["keywords"]:
            if kw.lower() in q_lower:
                return APPROVED_PENDING_ANSWER.get(lang, APPROVED_PENDING_ANSWER["en"]), True

    # Check danger signals
    danger_signals = ["safe to go", "can i swim", "drink water", "electric wire", "current", "wire fallen", "ಕರೆಂಟ್", "ವಿದ್ಯುತ್", "बिजली का तार", "करंट", "help", "danger", "water rising"]
    for sig in danger_signals:
        if sig in q_lower:
            return FALLBACK_UNKNOWN_ANSWER.get(lang, FALLBACK_UNKNOWN_ANSWER["en"]), True

    return None, False
