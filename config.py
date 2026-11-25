from pathlib import Path
import os
from dotenv import load_dotenv

# Base Project Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DAILY_LOGS_DIR = DATA_DIR / "daily_logs"
SCHEDULE_FILE = DATA_DIR / "schedule.json"
MEMORY_FILE = DATA_DIR / "memory.json"
ASSETS_DIR = BASE_DIR / "ui"
LOGO_PATH = ASSETS_DIR / "moon-bot-logo.png"
USER_SETTINGS_FILENAME = "settings.json"

# Clipboard highlight capture (opt-in, local only). When enabled MoonBot watches
# for newly copied text and offers to explain/translate it using the active window
# context (PDF/tab title). Nothing is uploaded except the text you explicitly ask
# MoonBot to analyze.
try:
    CLIPBOARD_POLL_INTERVAL = float(os.getenv("CLIPBOARD_POLL_INTERVAL", "1.2"))
except ValueError:
    CLIPBOARD_POLL_INTERVAL = 1.2

# Load environment variables from .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

# UI Configuration
UI_THEME = os.getenv("UI_THEME", "dark").strip().lower()
if UI_THEME not in ("dark", "light", "system"):
    UI_THEME = "dark"

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

# If the configured model is unavailable (bad name, unsupported, or out of
# quota), try these in order before using the local fallback answers.
GEMINI_FALLBACK_MODELS = tuple(
    model.strip()
    for model in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-3.5-flash,"
        "gemini-2.5-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-2.0-flash"
    ).split(",")
    if model.strip()
)
try:
    GEMINI_MAX_MODEL_ATTEMPTS = max(1, int(os.getenv("GEMINI_MAX_MODEL_ATTEMPTS", "3")))
except ValueError:
    GEMINI_MAX_MODEL_ATTEMPTS = 3

try:
    # Milliseconds. A hard cap keeps the offline fallback responsive when the
    # API is overloaded or the network stalls mid-request.
    # The Gemini SDK rejects deadlines below 10 seconds.
    GEMINI_TIMEOUT_MS = max(10000, int(os.getenv("GEMINI_TIMEOUT_MS", "10000")))
except ValueError:
    GEMINI_TIMEOUT_MS = 10000

try:
    # Total budget for one answer across all model attempts. A slow request or
    # a quota error stops immediately instead of walking a long fallback chain.
    GEMINI_TOTAL_TIMEOUT_MS = max(10000, int(os.getenv("GEMINI_TOTAL_TIMEOUT_MS", "13000")))
except ValueError:
    GEMINI_TOTAL_TIMEOUT_MS = 13000

# The UI shows a local answer before the network deadline so a question never
# sits on “processing” while the request is still pending.
QUERY_WATCHDOG_MS = max(4000, GEMINI_TIMEOUT_MS - 1500)

# Activity Tracking Configuration
try:
    ACTIVITY_POLL_INTERVAL = float(os.getenv("ACTIVITY_POLL_INTERVAL", "2.0"))
except ValueError:
    ACTIVITY_POLL_INTERVAL = 2.0

# Timer & Pomodoro Defaults (in minutes)
try:
    DEFAULT_WORK_MIN = int(os.getenv("POMODORO_WORK_MINUTES", "25"))
except ValueError:
    DEFAULT_WORK_MIN = 25

try:
    DEFAULT_BREAK_MIN = int(os.getenv("POMODORO_BREAK_MINUTES", "5"))
except ValueError:
    DEFAULT_BREAK_MIN = 5

# Bot Identity
BOT_NAME = "MoonBot"
PROJECT_TITLE = "MoonBot - Floating Desktop Study Companion"
ACADEMIC_LEVEL = "3rd Year CSE Capstone"

# Study dashboard design tokens
THEME_COLORS = {
    # Surfaces
    "surface": "#0F1115",
    "surface_sidebar": "#181C21",
    "surface_card": "#21262D",
    "surface_card_hover": "#293038",
    "surface_hud": "#1E222A",
    "surface_input": "#181C21",
    "border_subtle": "#2B313A",
    "border_highlight": "#38414D",
    
    # Primary & Secondary Accents
    "primary": "#5865F2",             # Primary Indigo
    "primary_hover": "#7289DA",
    "primary_light": "#BEC2FF",
    "secondary": "#7289DA",           # Periwinkle
    "accent_blue": "#8EA1FF",         # Electric Blue
    
    # Semantic Feedback
    "success": "#43B581",             # Emerald
    "warning": "#FAA61A",             # Amber
    "error": "#F04747",               # Rose / Emergency
    
    # Text / Foregrounds
    "text_primary": "#FFFFFF",
    "text_secondary": "#9BA3AF",
    "text_muted": "#5F6775",
    "text_on_primary": "#FFFFFF"
}

def ensure_data_directories() -> None:
    """Ensure data and logs directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_LOGS_DIR.mkdir(parents=True, exist_ok=True)

def get_daily_log_path(date_str: str) -> Path:
    """Return path to data/daily_logs/YYYY-MM-DD.json."""
    ensure_data_directories()
    return DAILY_LOGS_DIR / f"{date_str}.json"
