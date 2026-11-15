"""
Gnani Evon LLM Extraction Client
Strict schema enforcement and safety guardrails.
"""

import json
import time
import requests
from typing import Dict, Any
from config import Config
from gnani.mock import mock_extract

EVON_SYSTEM_PROMPT = """You are Gnani Evon, an emergency information extractor for disaster coordination.
Analyze the user transcript and output STRICT JSON ONLY. Do not write markdown fences, do not write explanations.
The output MUST be a JSON object with EXACTLY these keys:
- "address_or_landmark": string or "unknown"
- "headcount": integer or "unknown"
- "cannot_walk": integer 0 or 1, or "unknown"
- "medical_needs": integer 0 or 1, or "unknown"
- "emergency": integer 0 or 1, or "unknown"
- "can_help_others": integer 0 or 1, or "unknown"
- "language": string ("kannada" | "hindi" | "english" | "unknown")

CRITICAL RULES:
1. Do NOT guess. If information is missing or unclear, output "unknown".
2. You have NO knowledge about vehicles, roads, bridges, or rescue operations.
3. Output raw JSON only."""

REQUIRED_KEYS = {
    "address_or_landmark",
    "headcount",
    "cannot_walk",
    "medical_needs",
    "emergency",
    "can_help_others",
    "language"
}

def validate_evon_payload(data: Any) -> bool:
    """Validates that extracted data contains all required keys with compliant types."""
    if not isinstance(data, dict):
        return False
    if not REQUIRED_KEYS.issubset(data.keys()):
        return False
    
    # Check headcount
    hc = data["headcount"]
    if hc != "unknown":
        try:
            val = int(hc)
            if val < 0:
                return False
        except (ValueError, TypeError):
            return False

    # Check binary flags
    for flag in ["cannot_walk", "medical_needs", "emergency", "can_help_others"]:
        val = data[flag]
        if val not in (0, 1, "0", "1", "unknown"):
            return False

    return True

def clean_extracted_dict(data: dict) -> dict:
    """Standardizes types to int/str."""
    cleaned = dict(data)
    if cleaned["headcount"] != "unknown":
        cleaned["headcount"] = int(cleaned["headcount"])
    for flag in ["cannot_walk", "medical_needs", "emergency", "can_help_others"]:
        if cleaned[flag] in (1, "1", True):
            cleaned[flag] = 1
        elif cleaned[flag] in (0, "0", False):
            cleaned[flag] = 0
        else:
            cleaned[flag] = "unknown"
    return cleaned

def extract(transcript: str, retry: bool = True) -> Dict[str, Any]:
    """
    Extracts structured disaster needs using Gnani Evon.
    Guarantees strict schema compliance and retries once if malformed.
    """
    start_time = time.time()

    if Config.USE_MOCK_GNANI or not Config.GNANI_API_KEY:
        res = mock_extract(transcript)
        res["latency_sec"] = round(time.time() - start_time, 3)
        return res

    llm_url = Config.GNANI_BASE_URLS.get("llm", "https://api.vachana.ai/api/v1/llm")
    headers = {
        "X-API-Key-ID": Config.GNANI_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "evon-v1",
        "system_prompt": EVON_SYSTEM_PROMPT,
        "prompt": f"Caller Transcript:\n\"{transcript}\"\n\nJSON Output:",
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }

    for attempt in range(2 if retry else 1):
        try:
            response = requests.post(llm_url, headers=headers, json=payload, timeout=9.0)
            response.raise_for_status()
            raw_text = response.text.strip()
            # Clean possible markdown formatting
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            
            parsed = json.loads(raw_text.strip())
            if validate_evon_payload(parsed):
                cleaned = clean_extracted_dict(parsed)
                cleaned["latency_sec"] = round(time.time() - start_time, 3)
                cleaned["model"] = "Gnani Evon"
                return cleaned
        except Exception:
            if attempt == 0 and retry:
                continue # Retry once

    # If API call failed or malformed after retry, fallback cleanly to mock
    res = mock_extract(transcript)
    res["model"] = "Gnani Evon (Fallback)"
    res["latency_sec"] = round(time.time() - start_time, 3)
    return res
