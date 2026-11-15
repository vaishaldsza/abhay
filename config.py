import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Config:
    BASE_DIR = BASE_DIR
    SECRET_KEY = os.getenv("SECRET_KEY")
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
