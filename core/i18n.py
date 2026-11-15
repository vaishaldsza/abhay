"""
Abhay DDMA Fixed Dictionary Internationalization (i18n)
Supports: English (en), Hindi (hi), Kannada (kn).
Strict Rule: No LLM translations. Safety and ride templates come strictly from core/templates.py.
"""

STATUS_TRANSLATIONS = {
    "not_reached": {
        "en": "Not reached",
        "hi": "संपर्क नहीं हुआ",
        "kn": "ಸಂಪರ್ಕವಾಗಿಲ್ಲ"
    },
    "needs_help": {
        "en": "Needs help",
        "hi": "मदद चाहिए",
        "kn": "ಸಹಾಯ ಬೇಕು"
    },
    "can_help": {
        "en": "Can help",
        "hi": "मदद कर सकते हैं",
        "kn": "ಸಹಾಯ ಮಾಡಬಹುದು"
    },
    "request_recorded": {
        "en": "Request recorded, no driver accepted yet",
        "hi": "अनुरोध दर्ज, अभी तक कोई चालक नहीं मिला",
        "kn": "ವಿನಂತಿ ದಾಖಲಾಗಿದೆ, ಇನ್ನೂ ಯಾವುದೇ ಚಾಲಕರು ಸ್ವೀಕರಿಸಿಲ್ಲ"
    },
    "driver_accepted": {
        "en": "Driver accepted",
        "hi": "चालक ने स्वीकार किया",
        "kn": "ಚಾಲಕರು ಸ್ವೀಕರಿಸಿದ್ದಾರೆ"
    },
    "on_run": {
        "en": "On run",
        "hi": "रास्ते में",
        "kn": "ಚಾಲನೆಯಲ್ಲಿದೆ"
    },
    "picked_up": {
        "en": "Picked up",
        "hi": "सवार कर लिया",
        "kn": "ಹತ್ತಿಸಿಕೊಳ್ಳಲಾಗಿದೆ"
    },
    "evacuated": {
        "en": "Evacuated",
        "hi": "सुरक्षित निकाला गया",
        "kn": "ಸ್ಥಳಾಂತರಿಸಲಾಗಿದೆ"
    }
}

NAV_TRANSLATIONS = {
    "Operations Center": {
        "en": "Operations Center",
        "hi": "नियंत्रण केंद्र",
        "kn": "ಕಾರ್ಯಾಚರಣೆ ಕೇಂದ್ರ"
    },
    "Dashboard": {
        "en": "Dashboard",
        "hi": "डैशबोर्ड",
        "kn": "ಡ್ಯಾಶ್‌ಬೋರ್ಡ್"
    },
    "Evacuation Manifest": {
        "en": "Evacuation Manifest",
        "hi": "निकासी सूची",
        "kn": "ಸ್ಥಳಾಂತರ ಪಟ್ಟಿ"
    },
    "Call floor": {
        "en": "Call floor",
        "hi": "कॉल फ्लोर",
        "kn": "ಕಾಲ್ ಫ್ಲೋರ್"
    },
    "Fleet": {
        "en": "Fleet",
        "hi": "बचाव वाहन",
        "kn": "ರಕ್ಷಣಾ ಪಡೆ"
    },
    "Telephony Audit Logs": {
        "en": "Telephony Audit Logs",
        "hi": "ऑडिट लॉग",
        "kn": "ಆಡಿಟ್ ದಾಖಲೆ"
    },
    "System Data & Privacy": {
        "en": "System Data & Privacy",
        "hi": "डेटा और गोपनीयता",
        "kn": "ಡೇಟಾ ಮತ್ತು ಗೌಪ್ಯತೆ"
    },
    "Under the Hood": {
        "en": "Under the Hood",
        "hi": "सिस्टम आर्किटेक्चर",
        "kn": "ಸಿಸ್ಟಂ ವಿವರ"
    },
    "Evals": {
        "en": "Evals",
        "hi": "मॉडल मूल्यांकन",
        "kn": "ಮೌಲ್ಯಮಾಪನ"
    },
    "Incident select": {
        "en": "Incident select",
        "hi": "आपदा चयन",
        "kn": "ಘಟನೆ ಆಯ್ಕೆ"
    },
    "Simulate call": {
        "en": "Simulate call",
        "hi": "कॉल सिमुलेशन",
        "kn": "ಕಾಲ್ ಸಿಮ್ಯುಲೇಶನ್"
    },
    "Driver": {
        "en": "Driver",
        "hi": "चालक ऐप",
        "kn": "ಚಾಲಕರ ಆ್ಯಪ್"
    },
    "Field Visits": {
        "en": "Field Visits",
        "hi": "फील्ड विज़िट",
        "kn": "ಕ್ಷೇತ್ರ ಭೇಟಿ"
    },
    "Resident Phone": {
        "en": "Resident Phone",
        "hi": "नागरिक फोन",
        "kn": "ನಾಗರಿಕರ ಫೋನ್"
    },
    "Ready Sign-Up": {
        "en": "Ready Sign-Up",
        "hi": "नागरिक पंजीकरण",
        "kn": "ಸಿದ್ಧತಾ ನೋಂದಣಿ"
    },
    "Logout": {
        "en": "Logout",
        "hi": "लॉग आउट",
        "kn": "ಲಾಗ್ ಔಟ್"
    },
    "Map": {
        "en": "Map",
        "hi": "नक्शा",
        "kn": "ನಕ್ಷೆ"
    }
}

def translate_status(status_key: str, lang: str = "en") -> str:
    lang = lang if lang in ("en", "hi", "kn") else "en"
    if status_key in STATUS_TRANSLATIONS:
        return STATUS_TRANSLATIONS[status_key].get(lang, STATUS_TRANSLATIONS[status_key]["en"])
    return status_key

def translate_nav(nav_key: str, lang: str = "en") -> str:
    lang = lang if lang in ("en", "hi", "kn") else "en"
    if nav_key in NAV_TRANSLATIONS:
        return NAV_TRANSLATIONS[nav_key].get(lang, NAV_TRANSLATIONS[nav_key]["en"])
    return nav_key
