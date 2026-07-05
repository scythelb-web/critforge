import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_SECRET = os.getenv("SECRET_KEY", "change-me-in-production")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Database
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
DB_PATH = BASE_DIR / "app.db"

# LiveKit
LK_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LK_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
LK_URL = os.getenv("LIVEKIT_URL", "")
