import pytest
import sqlite3
import uuid
import re
from core.templates import get_template, PRE_ACCEPTANCE_EN, PRE_ACCEPTANCE_KN, PRE_ACCEPTANCE_HI, RIDE_TEMPLATES
from core.safety_answers import get_safety_answer, APPROVED_PENDING_ANSWER, FALLBACK_UNKNOWN_ANSWER
from db import init_db, get_standalone_db

def setup_module():
    init_db()

def test_pre_acceptance_templates_strictly_honest():
    for status in ("needs_help", "request_recorded"):
        for lang in ("en", "kn", "hi"):
            template = get_template(status, lang)
            if lang == "en":
                assert template == "Your request is recorded. No driver has accepted yet."
            elif lang == "kn":
                assert template == PRE_ACCEPTANCE_KN
            elif lang == "hi":
                assert template == PRE_ACCEPTANCE_HI

def test_pre_acceptance_templates_forbidden_words_and_advice():
    """
    Fails if a pre-acceptance template contains advice, timing,
    or the words safe, coming, on the way, dispatched, in English, Hindi, or Kannada.
    """
    forbidden_terms_by_lang = {
        "en": ["safe", "coming", "on the way", "dispatched", "ground", "minutes", "mins", "hours", "soon", "wait"],
        "kn": ["ಸುರಕ್ಷಿತ", "ಬರುತ್ತಿದೆ", "ದಾರಿಯಲ್ಲಿದೆ", "ಕಳುಹಿಸಲಾಗಿದೆ", "ಸ್ಥಳ", "ನಿಮಿಷ", "ಗಂಟೆ", "ಶೀಘ್ರದಲ್ಲೇ", "ಕಾಯಿರಿ"],
        "hi": ["सुरक्षित", "आ रही", "रास्ते में", "भेजी गई", "स्थान", "मिनट", "घंटे", "जल्द", "प्रतीक्षा", "रुको"]
    }
    advice_terms_by_lang = {
        "en": ["move to", "stay in", "keep your phone", "take your", "run to", "go to"],
        "kn": ["ಸ್ಥಳಾಂತರಿಸಿ", "ಹೋಗಿ", "ತೆರಳಿ", "ಇರಿ", "ತೆಗೆದುಕೊಳ್ಳಿ"],
        "hi": ["जाएं", "रहें", "चलें", "रखें", "लें"]
    }
    
    for status in ("needs_help", "request_recorded"):
        for lang in ("en", "kn", "hi"):
            template = get_template(status, lang)
            t_lower = template.lower()
            for word in forbidden_terms_by_lang[lang]:
                assert word not in t_lower, f"Forbidden term '{word}' found in pre-acceptance template for {status} ({lang}): {template}"
            for advice in advice_terms_by_lang[lang]:
                assert advice not in t_lower, f"Advice term '{advice}' found in pre-acceptance template for {status} ({lang}): {template}"
            # Ensure no timing regex pattern
            assert not re.search(r'\b\d+\s*(m|min|minutes|hrs|hours|ನಿಮಿಷ|ಗಂಟೆ|मिनट|घंटे)\b', t_lower), f"Timing pattern found in template: {template}"

def test_driver_accepted_template_format():
    tmpl_en = get_template(
        "driver_accepted",
        "en",
        driver_name="Suresh",
        vehicle_designation="Boat NDRF-1",
        eta_minutes=20
    )
    assert "Suresh" in tmpl_en
    assert "Boat NDRF-1" in tmpl_en
    assert "20" in tmpl_en

def test_dangerous_questions_answered_safely():
    # Pets & livestock -> Approved answer pending from district authority & flagged
    ans_pet, flagged = get_safety_answer("Should I go back into the house for my dog and cattle?", "en")
    assert ans_pet is not None
    assert "Approved answer pending from district authority" in ans_pet
    assert flagged is True

    # Road & bridge conditions -> Approved answer pending from district authority & flagged
    ans_road, flagged = get_safety_answer("Which road is open? Can I cross the Netravati bridge?", "en")
    assert ans_road is not None
    assert "Approved answer pending from district authority" in ans_road
    assert flagged is True

    # Medicine / Oxygen -> Approved answer pending from district authority & flagged
    ans_med, flagged = get_safety_answer("What should I set my father's oxygen cylinder flow rate to?", "en")
    assert ans_med is not None
    assert "Approved answer pending from district authority" in ans_med
    assert flagged is True

    # Fallback unknown safety risk -> I don't know that yet. A person will follow up & flagged
    ans_unknown, flagged = get_safety_answer("Can I swim across with an electric wire fallen nearby?", "en")
    assert flagged is True
    assert "I don't know that yet. A person will follow up." in ans_unknown

def test_callback_created_only_after_acceptance_and_idempotent():
    conn = get_standalone_db()
    cur = conn.cursor()

    req_id = f"req-{uuid.uuid4().hex[:6]}"
    hh_id = f"hh-{uuid.uuid4().hex[:6]}"

    cur.execute(
        """INSERT INTO household (id, incident_id, first_name, phone_masked, phone_enc, status)
           VALUES (?, 'inc-bantwal-01', 'Ramesh', '+91 XXXXX XXXXX', 'hash123', 'request_recorded')""",
        (hh_id,)
    )
    cur.execute(
        """INSERT INTO request (id, household_id, status)
           VALUES (?, ?, 'request_recorded')""",
        (req_id, hh_id)
    )
    conn.commit()

    def try_create_callback(request_id):
        c = conn.cursor()
        c.execute("SELECT household_id, status, vehicle_id FROM request WHERE id = ?", (request_id,))
        r = c.fetchone()
        if r["status"] != "driver_accepted":
            raise ValueError("Cannot create callback before driver acceptance.")
        
        c.execute(
            """INSERT OR IGNORE INTO callback (id, household_id, request_id, driver_first_name, vehicle_designation, eta_minutes, status)
               VALUES (?, ?, ?, 'Suresh', 'Boat NDRF-1', 15, 'scheduled')""",
            (f"cb-{request_id}", r["household_id"], request_id)
        )
        conn.commit()

    with pytest.raises(ValueError, match="Cannot create callback before driver acceptance"):
        try_create_callback(req_id)

    cur.execute(
        """UPDATE request SET status = 'driver_accepted', vehicle_id = 'veh-01' WHERE id = ?""",
        (req_id,)
    )
    conn.commit()

    try_create_callback(req_id)

    cur.execute("SELECT COUNT(*) as cnt FROM callback WHERE request_id = ?", (req_id,))
    count1 = cur.fetchone()["cnt"]
    assert count1 == 1

    try_create_callback(req_id)

    cur.execute("SELECT COUNT(*) as cnt FROM callback WHERE request_id = ?", (req_id,))
    count2 = cur.fetchone()["cnt"]
    assert count2 == 1

    conn.close()
