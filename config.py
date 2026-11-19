import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Config:
    BASE_DIR = BASE_DIR
    _secret_key = os.getenv("SECRET_KEY")
    if not _secret_key:
        raise ValueError("SECRET_KEY must be provided in .env with no default value.")
    SECRET_KEY = _secret_key

    _phone_hash_key = os.getenv("PHONE_HASH_KEY")
    if not _phone_hash_key:
        raise ValueError("PHONE_HASH_KEY must be provided in .env with no default value.")
    PHONE_HASH_KEY = _phone_hash_key

    _phone_encryption_key = os.getenv("PHONE_ENCRYPTION_KEY")
    if not _phone_encryption_key:
        raise ValueError("PHONE_ENCRYPTION_KEY must be provided in .env with no default value.")
    try:
        from cryptography.fernet import Fernet
        Fernet(_phone_encryption_key.encode("utf-8"))
    except Exception as e:
        raise ValueError(
            "PHONE_ENCRYPTION_KEY must be a valid 32-byte url-safe base64 Fernet key. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from e
    PHONE_ENCRYPTION_KEY = _phone_encryption_key

    DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "abhay.db"))
    
    # Gnani AI Configuration
    GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")
    USE_MOCK_GNANI = os.getenv("USE_MOCK_GNANI", "true").lower() in ("true", "1", "yes")
    
    raw_urls = os.getenv("GNANI_BASE_URLS", "{}")
    try:
        GNANI_BASE_URLS = json.loads(raw_urls)
    except Exception:
        GNANI_BASE_URLS = {
            "stt": "https://api.gnani.ai/stt",
            "llm": "https://api.gnani.ai/llm",
            "tts": "https://api.gnani.ai/tts"
        }
        
    AUDIO_CACHE_DIR = BASE_DIR / "audio_cache"
    AUDIO_CACHE_DIR.mkdir(exist_ok=True)
    
    # Coordinates of Bantwal district center (Dakshina Kannada)
    DEFAULT_LAT = 12.8904
    DEFAULT_LNG = 75.0378

    # Priority Scoring Weights (core/priority.py)
    PRIORITY_WEIGHTS = {
        "emergency": 50.0,
        "bedridden": 40.0,
        "oxygen": 35.0,
        "cannot_walk": 30.0,
        "elderly": 20.0,
        "unanswered_per_minute": 0.5,
        "max_unanswered_points": 30.0
    }

    # Optional Risk Model Configuration (core/optimizer.py & sim/run_sim.py)
    RISK_MODEL = os.getenv("RISK_MODEL", "false").lower() in ("true", "1", "yes")
    NOMINAL_SPEED_KMH = float(os.getenv("NOMINAL_SPEED_KMH", "25.0")) # Nominal straight-line km/h
    BOARDING_TIME_BASE_MIN = float(os.getenv("BOARDING_TIME_BASE_MIN", "3.0")) # Base minutes
    BOARDING_TIME_SPECIAL_MIN = float(os.getenv("BOARDING_TIME_SPECIAL_MIN", "4.0")) # Extra minutes for bedridden/mobility
    SAFETY_BUFFER_MIN = float(os.getenv("SAFETY_BUFFER_MIN", "5.0")) # Safety buffer in minutes
    RAMP_MARGIN_R_MIN = float(os.getenv("RAMP_MARGIN_R_MIN", "20.0")) # Ramp denominator in lateness formula
