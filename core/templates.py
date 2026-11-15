"""
Fixed, honest templates in Kannada, Hindi, and English.
Rule: Before driver acceptance, the ONLY ride sentence permitted is:
"Your request is recorded. No driver has accepted yet."
"""

PRE_ACCEPTANCE_EN = "Your request is recorded. No driver has accepted yet."
PRE_ACCEPTANCE_KN = "ನಿಮ್ಮ ಕೋರಿಕೆಯನ್ನು ದಾಖಲಿಸಲಾಗಿದೆ. ಇನ್ನೂ ಯಾವುದೇ ಚಾಲಕರು ಸ್ವೀಕರಿಸಿಲ್ಲ."
PRE_ACCEPTANCE_HI = "आपका अनुरोध दर्ज कर लिया गया है। अभी किसी ड्राइवर ने स्वीकार नहीं किया है।"

RIDE_TEMPLATES = {
    "not_reached": {
        "en": "We could not connect with your household.",
        "kn": "ನಿಮ್ಮ ಮನೆಯನ್ನು ಸಂಪರ್ಕಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.",
        "hi": "हम आपके घर से संपर्क नहीं कर सके।"
    },
    "needs_help": {
        "en": PRE_ACCEPTANCE_EN,
        "kn": PRE_ACCEPTANCE_KN,
        "hi": PRE_ACCEPTANCE_HI
    },
    "can_help": {
        "en": "Thank you for confirming you are able to assist. We have noted your available resources.",
        "kn": "ಸಹಾಯ ಮಾಡಲು ಸಿದ್ಧರಿದ್ದೀರಿ ಎಂದು ದೃಢಪಡಿಸಿದ್ದಕ್ಕಾಗಿ ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಲಭ್ಯವಿರುವ ಸಂಪನ್ಮೂಲಗಳನ್ನು ದಾಖಲಿಸಲಾಗಿದೆ.",
        "hi": "सहायता की पेशकश के लिए धन्यवाद। हमने आपका विवरण और संसाधन दर्ज कर लिए हैं।"
    },
    "request_recorded": {
        "en": PRE_ACCEPTANCE_EN,
        "kn": PRE_ACCEPTANCE_KN,
        "hi": PRE_ACCEPTANCE_HI
    },
    "driver_accepted": {
        "en": "A driver has accepted your evacuation ride. Driver {driver_name} in vehicle {vehicle_designation} is assigned with an estimated time of {eta_minutes} minutes.",
        "kn": "ಚಾಲಕರು ನಿಮ್ಮ ಸ್ಥಳಾಂತರ ವಿನಂತಿಯನ್ನು ಸ್ವೀಕರಿಸಿದ್ದಾರೆ. ವಾಹನ {vehicle_designation} ನಲ್ಲಿ ಚಾಲಕ {driver_name} ನಿಯೋಜಿಸಲ್ಪಟ್ಟಿದ್ದು, ಸುಮಾರು {eta_minutes} ನಿಮಿಷಗಳಲ್ಲಿ ಬರಲಿದ್ದಾರೆ.",
        "hi": "एक ड्राइवर ने आपकी निकासी सवारी स्वीकार कर ली है। वाहन {vehicle_designation} में ड्राइवर {driver_name} को सौंपा गया है, जो लगभग {eta_minutes} मिनट में पहुंचेंगे।"
    },
    "on_run": {
        "en": "The rescue vehicle is currently en route to your location. Please stay in your designated spot.",
        "kn": "ರಕ್ಷಣಾ ವಾಹನವು ಈಗ ನಿಮ್ಮ ಸ್ಥಳಕ್ಕೆ ಬರುತ್ತಿದೆ. ದಯವಿಟ್ಟು ನಿಗದಿತ ಸ್ಥಳದಲ್ಲೇ ಇರಿ.",
        "hi": "बचाव वाहन वर्तमान में आपके स्थान की ओर आ रहा है। कृपया अपने स्थान पर ही बने रहें।"
    },
    "picked_up": {
        "en": "Household members have been picked up and are being transported to the relief center.",
        "kn": "ಕುಟುಂಬದ ಸದಸ್ಯರನ್ನು ಕರೆದೊಯ್ಯಲಾಗಿದ್ದು, ಪರಿಹಾರ ಕೇಂದ್ರಕ್ಕೆ ಸಾಗಿಸಲಾಗುತ್ತಿದೆ.",
        "hi": "परिवार के सदस्यों को ले जाया जा चुका है और उन्हें राहत केंद्र पहुंचाया जा रहा है।"
    },
    "evacuated": {
        "en": "Household is evacuated to the relief center.",
        "kn": "ಕುಟುಂಬವನ್ನು ಪರಿಹಾರ ಕೇಂದ್ರಕ್ಕೆ ಸ್ಥಳಾಂತರಿಸಲಾಗಿದೆ.",
        "hi": "परिवार को राहत केंद्र में पहुंचा दिया गया है।"
    }
}

def get_template(status: str, lang: str = "en", **kwargs) -> str:
    """
    Returns the strict predefined template for a given status and language.
    Guarantees no false promises before driver acceptance.
    """
    lang = lang.lower() if lang else "en"
    if lang not in ("en", "kn", "hi"):
        if "kannada" in lang:
            lang = "kn"
        elif "hindi" in lang:
            lang = "hi"
        else:
            lang = "en"

    # Pre-acceptance statuses must only return the exact pre-acceptance sentence
    if status in ("needs_help", "request_recorded"):
        return RIDE_TEMPLATES[status][lang]

    status_dict = RIDE_TEMPLATES.get(status, RIDE_TEMPLATES["request_recorded"])
    template_str = status_dict.get(lang, status_dict["en"])

    if "{driver_name}" in template_str:
        driver = kwargs.get("driver_name", "Assigned Driver")
        veh = kwargs.get("vehicle_designation", "Assigned Vehicle")
        eta = kwargs.get("eta_minutes", 15)
        return template_str.format(driver_name=driver, vehicle_designation=veh, eta_minutes=eta)

    return template_str
