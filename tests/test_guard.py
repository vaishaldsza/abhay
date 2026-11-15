import pytest
from core.guard import is_safe_acknowledgment, sanitize_llm_reply, BLOCKED_PHRASES
from core.templates import get_template

def test_guard_blocks_all_forbidden_phrases():
    # Verify that BLOCKED_PHRASES contains at least 30 distinct phrases
    assert len(BLOCKED_PHRASES) >= 30

    for phrase in BLOCKED_PHRASES:
        sample_sentence = f"Please remain calm, {phrase}."
        safe, reason = is_safe_acknowledgment(sample_sentence, request_status="request_recorded")
        assert safe is False, f"Expected '{phrase}' to be blocked! Reason returned: {reason}"

def test_subtle_and_varied_promise_phrases():
    subtle_test_cases = [
        "we're working on getting someone to you",
        "Don't worry, a vehicle is coming soon",
        "A van is coming to your house",
        "Rescue team has been dispatched to Bantwal",
        "Ambulance is arriving right now",
        "Our team is heading towards you",
        "You will be rescued soon",
        "चिंता मत करो बचाव दल आ रहा है",
        "गाड़ी रास्ते में है",
        "ಆಂಬ್ಯುಲೆನ್ಸ್ ಬರುತ್ತಿದೆ",
        "ಸಹಾಯ ಬರುತ್ತಿದೆ ಧೈರ್ಯವಾಗಿರಿ",
        "ದೋಣಿ ಬರುತ್ತಿದೆ"
    ]
    for text in subtle_test_cases:
        safe, _ = is_safe_acknowledgment(text, request_status="request_recorded")
        assert safe is False, f"Failed to block subtle phrase: '{text}'"

def test_pre_acceptance_timing_and_ride_words_blocked():
    # Before driver accepted, words like "dispatched", "arriving", "mins away" must be blocked
    pre_acceptance_violations = [
        "Your status is noted, a driver will be dispatched shortly",
        "A boat will be sent to your location",
        "The team is 10 minutes away",
        "Wait for the ambulance"
    ]
    for text in pre_acceptance_violations:
        safe, _ = is_safe_acknowledgment(text, request_status="needs_help")
        assert safe is False, f"Did not block pre-acceptance timing phrase: '{text}'"

def test_approved_templates_pass_safely():
    templates_to_test = [
        get_template("request_recorded", "en"),
        get_template("request_recorded", "kn"),
        get_template("request_recorded", "hi"),
        get_template("can_help", "en"),
        get_template("driver_accepted", "en", driver_name="Suresh", vehicle_designation="Boat NDRF-1", eta_minutes=15)
    ]
    for tmpl in templates_to_test:
        safe, _ = is_safe_acknowledgment(tmpl, request_status="driver_accepted")
        assert safe is True, f"Approved template incorrectly blocked: {tmpl}"

def test_sanitization_drops_unsafe_text():
    unsafe_text = "Help is on the way! Don't worry, a van is coming."
    fallback = get_template("request_recorded", "en")
    sanitized = sanitize_llm_reply(unsafe_text, "request_recorded", fallback)
    assert sanitized == fallback
    assert "help is on the way" not in sanitized.lower()
