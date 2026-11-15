"""
Gnani Prisma Speech-to-Text (STT) Client
"""

import time
import requests
from pathlib import Path
from typing import Dict, Any
from config import Config
from gnani.mock import mock_transcribe

def transcribe(audio_path: str, lang: str = "kannada", reference_hint: str = None) -> Dict[str, Any]:
    """
    Transcribes audio using Gnani Prisma ASR.
    Returns: { "text": str, "language": str, "confidence": float, "latency_sec": float, "model": str }
    """
    start_time = time.time()
    
    # If in mock mode or API key is absent, use high-fidelity mock
    if Config.USE_MOCK_GNANI or not Config.GNANI_API_KEY:
        res = mock_transcribe(audio_path, lang, reference_hint=reference_hint)
        res["latency_sec"] = round(time.time() - start_time, 3)
        return res

    # Real Gnani API Call
    stt_url = Config.GNANI_BASE_URLS.get("stt", "https://api.vachana.ai/api/v1/stt")
    headers = {
        "X-API-Key-ID": Config.GNANI_API_KEY
    }

    try:
        with open(audio_path, "rb") as f:
            files = {"audio": (Path(audio_path).name, f, "audio/wav")}
            data = {"language": lang, "model": "prisma-v3.0"}
            response = requests.post(stt_url, headers=headers, files=files, data=data, timeout=8.0)
            response.raise_for_status()
            payload = response.json()
            
            latency = round(time.time() - start_time, 3)
            return {
                "text": payload.get("transcript", payload.get("text", "")),
                "language": payload.get("language", lang),
                "confidence": payload.get("confidence", 0.95),
                "latency_sec": latency,
                "model": "Gnani Prisma v3.0"
            }
    except Exception as e:
        # Graceful fallback to mock with logged notice
        res = mock_transcribe(audio_path, lang)
        res["model"] = "Gnani Prisma v3.0 (Fallback)"
        res["latency_sec"] = round(time.time() - start_time, 3)
        res["error"] = str(e)
        return res
