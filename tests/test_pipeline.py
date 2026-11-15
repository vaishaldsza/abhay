import pytest
import os
from gnani.stt import transcribe
from gnani.llm import extract, validate_evon_payload, clean_extracted_dict
from gnani.tts import speak
from core.guard import sanitize_llm_reply
from core.templates import get_template
from core.status import update_household_status
from db import init_db, get_standalone_db
from config import Config

def setup_module():
    init_db()

def test_stt_transcription():
    sample_wav = str(Config.BASE_DIR / "static" / "audio" / "sample_kannada.wav")
    result = transcribe(sample_wav, lang="kannada")
    assert "text" in result
    assert len(result["text"]) > 0
    assert result["confidence"] > 0.8
    assert "latency_sec" in result
    assert "model" in result

def test_evon_extraction_keys():
    transcript = "ನಮಸ್ಕಾರ ಕಂಟ್ರೋಲ್ ರೂಮ್, ನಾನು ದೇವಪ್ಪ. ಪಾಣೆಮಂಗಳೂರು ಬಳಿ ನೀರು ಮನೆಗೆ ನುಗ್ಗುತ್ತಿದೆ. ಮನೆಯಲ್ಲಿ 4 ಜನರಿದ್ದೇವೆ, ತಾಯಿಗೆ ನಡೆಯಲು ಸಾಧ್ಯವಿಲ್ಲ. ತುರ್ತು ಸಹಾಯ ಬೇಕು."
    extracted = extract(transcript)
    required_keys = [
        "address_or_landmark",
        "headcount",
        "cannot_walk",
        "medical_needs",
        "emergency",
        "can_help_others",
        "language"
    ]
    for key in required_keys:
        assert key in extracted, f"Missing key '{key}' in extracted data"

    assert extracted["headcount"] == 4
    assert extracted["cannot_walk"] == 1
    assert extracted["emergency"] == 1
    assert extracted["can_help_others"] == 0
    assert extracted["language"] == "kannada"

def test_evon_validation_rejects_missing_keys():
    incomplete = {
        "address_or_landmark": "Bantwal",
        "headcount": 2
        # Missing cannot_walk, medical_needs, emergency, etc.
    }
    assert validate_evon_payload(incomplete) is False

def test_tts_generation_and_caching():
    text = "ನಿಮ್ಮ ಕೋರಿಕೆಯನ್ನು ದಾಖಲಿಸಲಾಗಿದೆ. ಇನ್ನೂ ಯಾವುದೇ ಚಾಲಕರು ಸ್ವೀಕರಿಸಿಲ್ಲ."
    res1 = speak(text, lang="kn")
    assert "audio_url" in res1
    assert os.path.exists(res1["full_path"])
    
    # Second call should hit the local audio cache
    res2 = speak(text, lang="kn")
    assert res2["cached"] is True
    assert res2["latency_sec"] < res1["latency_sec"] + 0.05

def test_full_pipeline_mock_flow():
    """
    Simulates the complete pipeline:
    1. Audio -> Prisma STT
    2. STT -> Evon Extraction
    3. Status Engine -> update to needs_help
    4. Guard -> ensures honest template response
    5. Timbre TTS -> spoken audio reply
    """
    sample_wav = str(Config.BASE_DIR / "static" / "audio" / "sample_hindi.wav")
    
    # 1. STT
    stt_res = transcribe(sample_wav, lang="hindi")
    assert len(stt_res["text"]) > 0

    # 2. LLM Extraction
    evon_res = extract(stt_res["text"])
    assert evon_res["headcount"] > 0

    # 3. Guard & Template
    # Caller might ask "is help coming?"
    untrusted_llm_reply = "Help is on the way! Don't worry, 10 minutes away."
    template_reply = get_template("needs_help", evon_res["language"])
    safe_reply = sanitize_llm_reply(untrusted_llm_reply, "needs_help", template_reply)

    assert safe_reply == template_reply
    assert "help is on the way" not in safe_reply.lower()

    # 4. TTS
    tts_res = speak(safe_reply, lang=evon_res["language"])
    assert tts_res["audio_url"].endswith(".wav")
