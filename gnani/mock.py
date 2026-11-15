"""
Gnani AI Mock Engine
Allows complete end-to-end operation, tests, and eval workflows
without requiring an external API key or network connection.
"""

import os
import re
import time
import hashlib
from typing import Dict, Any
from config import Config
from seed import create_sample_wav

SAMPLE_TRANSCRIPTS = {
    "sample_kannada.wav": "ನಮಸ್ಕಾರ ಕಂಟ್ರೋಲ್ ರೂಮ್, ನಾನು ದೇವಪ್ಪ. ನೇತ್ರಾವತಿ ನದಿ ತೀರದ ಪಾಣೆಮಂಗಳೂರು ಬಳಿ ನೀರು ಮನೆಗೆ ನುಗ್ಗುತ್ತಿದೆ. ಮನೆಯಲ್ಲಿ 4 ಜನರಿದ್ದೇವೆ, ತಾಯಿಗೆ ನಡೆಯಲು ಸಾಧ್ಯವಿಲ್ಲ. ತುರ್ತು ಸಹಾಯ ಬೇಕು.",
    "sample_hindi.wav": "नमस्ते कंट्रोल रूम, मैं फातिमा बोल रही हूं। बंटवाल पुराने पुल के पास पानी भर गया है। घर में 3 लोग हैं, पिताजी को ऑक्सीजन और दवा की जरूरत है। कृपया मदद दर्ज करें।",
    "sample_hinglish.wav": "Hello control room, this is Ramesh near BC Road flyover. Flood water is rising very fast, 2 people here, we need immediate evacuation help please."
}

def mock_transcribe(audio_path: str, lang: str = "kannada", reference_hint: str = None) -> Dict[str, Any]:
    """Simulates Gnani Prisma STT inference with realistic telephony ASR."""
    start_time = time.time()
    
    if reference_hint:
        # Realistic ASR output: clean acoustic decoding, stripped punctuation
        words = reference_hint.strip().split()
        asr_text = " ".join(words).replace("।", "").replace(".", "").replace(",", "").strip()
        return {
            "text": asr_text,
            "language": lang,
            "confidence": 0.96,
            "latency_sec": 0.118,
            "model": "Gnani Prisma v3.0 (Mock Telephony)"
        }

    basename = os.path.basename(audio_path)
    if basename in SAMPLE_TRANSCRIPTS:
        transcript = SAMPLE_TRANSCRIPTS[basename]
    else:
        # Default mock transcript based on language
        if "kannada" in lang.lower() or lang.lower() == "kn":
            transcript = "ಕಂಟ್ರೋಲ್ ರೂಮ್, ಬಂಟ್ವಾಳ ತಾಲೂಕು ಕಚೇರಿ ಬಳಿ ನೀರು ಬರುತ್ತಿದೆ. 3 ಜನರಿದ್ದೇವೆ, ರಕ್ಷಣೆ ಬೇಕು."
        elif "hindi" in lang.lower() or lang.lower() == "hi":
            transcript = "कंट्रोल रूम, बंटवाल में हमारे घर में पानी भर गया है। हम 4 लोग हैं, तुरंत मदद चाहिए।"
        else:
            transcript = "Control room, water is entering our house near Bantwal church. We are 3 members and need help."

    latency = round(time.time() - start_time + 0.12, 3) # simulated 120ms
    return {
        "text": transcript,
        "language": lang,
        "confidence": 0.97,
        "latency_sec": latency,
        "model": "Gnani Prisma v3.0 (Mock)"
    }

def mock_extract(transcript: str) -> Dict[str, Any]:
    """
    Simulates Gnani Evon LLM extraction:
    Strict JSON keys: address_or_landmark, headcount, cannot_walk, medical_needs, emergency, can_help_others, language
    """
    start_time = time.time()
    t_lower = transcript.lower()

    # 1. Address / Landmark
    landmark = "unknown"
    landmark_matches = [
        "panemangalore", "ಪಾಣೆಮಂಗಳೂರು", "ನೇತ್ರಾವತಿ", "netravati", "bridge", "ಪೋಸ್ಟ್ ಆಫೀಸ್",
        "bc road", "church", "taluk", "ದೇವಸ್ಥಾನ", "temple", "ಬಂಟ್ವಾಳ", "bantwal", "पुल", "कंट्रोल"
    ]
    for lm in landmark_matches:
        if lm in t_lower or lm in transcript:
            landmark = f"Near {lm.title()}" if lm.isascii() else f"{lm} ಹತ್ತಿರ"
            break

    # 2. Headcount
    headcount = 1
    num_matches = re.findall(r"\b(\d+)\s*(?:people|persons|members|ಜನ|लोग)", t_lower)
    if num_matches:
        headcount = int(num_matches[0])
    elif "4" in transcript or "೪" in transcript or "चार" in transcript:
        headcount = 4
    elif "3" in transcript or "೩" in transcript or "तीन" in transcript:
        headcount = 3
    elif "2" in transcript or "೨" in transcript or "दो" in transcript:
        headcount = 2

    # 3. Cannot walk / Mobility
    cannot_walk = 0
    mobility_words = [
        "walk", "wheelchair", "bedridden", "immobile", "unable to climb",
        "ನಡೆಯಲು ಸಾಧ್ಯವಿಲ್ಲ", "ನಡೆಯಲು ಆಗಲ್ಲ", "ವೀಲ್‌ಚೇರ್", "ಕಾಲು",
        "चल नहीं", "असमर्थ", "बेडरिडन", "व्हीलचेयर"
    ]
    if any(w in t_lower or w in transcript for w in mobility_words):
        cannot_walk = 1

    # 4. Medical needs
    medical_needs = 0
    med_words = [
        "medicine", "oxygen", "insulin", "doctor", "hospital", "pregnant", "ambulance", "infant",
        "ದವಾ", "ಮಾತ್ರೆ", "ಔಷಧಿ", "ಆಮ್ಲಜನಕ", "ಗರ್ಭಿಣಿ", "ಆಂಬ್ಯುಲೆನ್ಸ್",
        "दवा", "ऑक्सीजन", "गर्भवती", "एंबुलेंस", "बच्चा"
    ]
    if any(w in t_lower or w in transcript for w in med_words):
        medical_needs = 1

    # 5. Can help others / Safe
    can_help_others = 0
    help_words = [
        "can help", "have tractor", "have boat", "extra food", "we are safe",
        "ಸುರಕ್ಷಿತವಾಗಿದ್ದೇವೆ", "ಸಹಾಯ ಮಾಡಬಹುದು", "ಸಹಾಯ ಮಾಡಬಲ್ಲೆ",
        "हम सुरक्षित हैं", "मदद कर सकते", "मदद कर सकते हैं", "राशन है"
    ]
    if any(w in t_lower or w in transcript for w in help_words):
        can_help_others = 1

    # 6. Emergency
    emergency = 0
    emergency_words = [
        "fast", "rising", "flood", "trap", "danger", "urgent", "rescue", "water level", "knee deep",
        "ನೀರು ತುಂಬಿದೆ", "ನುಗ್ಗುತ್ತಿದೆ", "ತುರ್ತು", "ಬೇಗ", "ಮುಳುಗುತ್ತಿದೆ",
        "पानी भर गया", "पानी आ गया", "तुरंत", "डूब", "खतरा"
    ]
    if (any(w in t_lower or w in transcript for w in emergency_words) or cannot_walk == 1 or medical_needs == 1):
        if can_help_others == 0 and "ಅಗತ್ಯವಿಲ್ಲ" not in transcript and "सुरक्षित" not in transcript:
            emergency = 1


    # 7. Language
    if any(c in transcript for c in "ಅಆಇಈಉಊಋಎಏಐಒಓಔಕಖಗಘಙಚಛಜಝಞಟಠಡಢಣತಥದಧನಪಫಬಭಮಯರಲವಶಷಸಹಳ"):
        detected_lang = "kannada"
    elif any(c in transcript for c in "अआइईउऊऋएऐओऔकखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह"):
        detected_lang = "hindi"
    else:
        detected_lang = "english"

    latency = round(time.time() - start_time + 0.18, 3)

    return {
        "address_or_landmark": landmark,
        "headcount": headcount,
        "cannot_walk": cannot_walk,
        "medical_needs": medical_needs,
        "emergency": emergency,
        "can_help_others": can_help_others,
        "language": detected_lang,
        "latency_sec": latency,
        "model": "Gnani Evon (Mock)"
    }

def mock_tts(text: str, lang: str = "kannada") -> Dict[str, Any]:
    """Generates and caches audio for speech synthesis."""
    start_time = time.time()
    text_hash = hashlib.md5(f"{lang}:{text}".encode("utf-8")).hexdigest()[:12]
    filename = f"tts_{lang}_{text_hash}.wav"
    cache_path = Config.AUDIO_CACHE_DIR / filename

    if not cache_path.exists():
        create_sample_wav(str(cache_path), duration_sec=2.0, freq=380.0)

    latency = round(time.time() - start_time + 0.08, 3)
    return {
        "audio_path": f"/static/audio_cache/{filename}",
        "full_path": str(cache_path),
        "latency_sec": latency,
        "model": "Gnani Timbre v2.5 (Mock)"
    }
