"""
Gnani Timbre Text-to-Speech (TTS) Client
Features local audio caching for fixed disaster templates.
"""

import time
import hashlib
import requests
from pathlib import Path
from typing import Dict, Any
from config import Config
from gnani.mock import mock_tts

def speak(text: str, lang: str = "kannada") -> Dict[str, Any]:
    """
    Synthesizes speech using Gnani Timbre.
    Caches audio for repeated templates (like status messages).
    Returns: { "audio_url": str, "full_path": str, "latency_sec": float, "cached": bool, "model": str }
    """
    start_time = time.time()
    lang_clean = lang.lower() if lang else "kannada"
    text_hash = hashlib.md5(f"{lang_clean}:{text.strip()}".encode("utf-8")).hexdigest()[:14]
    filename = f"timbre_{lang_clean}_{text_hash}.wav"
    cache_path = Config.AUDIO_CACHE_DIR / filename

    # Check cache first
    if cache_path.exists():
        return {
            "audio_url": f"/audio-cache/{filename}",
            "full_path": str(cache_path),
            "latency_sec": round(time.time() - start_time, 3),
            "cached": True,
            "model": "Gnani Timbre (Cached)"
        }

    # If mock mode or no API key, synthesize via mock
    if Config.USE_MOCK_GNANI or not Config.GNANI_API_KEY:
        res = mock_tts(text, lang_clean)
        # Ensure file copied/created at cache_path
        if not cache_path.exists():
            import shutil
            shutil.copyfile(res["full_path"], str(cache_path))
        return {
            "audio_url": f"/audio-cache/{filename}",
            "full_path": str(cache_path),
            "latency_sec": round(time.time() - start_time, 3),
            "cached": False,
            "model": "Gnani Timbre v2.5 (Mock)"
        }

    # Real Gnani Timbre API
    tts_url = Config.GNANI_BASE_URLS.get("tts", "https://api.vachana.ai/api/v1/tts/inference")
    headers = {
        "X-API-Key-ID": Config.GNANI_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "language": lang_clean,
        "model": "timbre-v2.5",
        "audio_config": {"audio_encoding": "LINEAR16", "sample_rate_hertz": 16000}
    }

    try:
        response = requests.post(tts_url, headers=headers, json=payload, timeout=8.0)
        response.raise_for_status()
        with open(cache_path, "wb") as f:
            f.write(response.content)

        return {
            "audio_url": f"/audio-cache/{filename}",
            "full_path": str(cache_path),
            "latency_sec": round(time.time() - start_time, 3),
            "cached": False,
            "model": "Gnani Timbre v2.5"
        }
    except Exception as e:
        # Fallback to mock
        res = mock_tts(text, lang_clean)
        return {
            "audio_url": f"/audio-cache/{filename}",
            "full_path": str(cache_path),
            "latency_sec": round(time.time() - start_time, 3),
            "cached": False,
            "model": "Gnani Timbre v2.5 (Fallback)"
        }
