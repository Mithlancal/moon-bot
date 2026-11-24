"""
config.py — MoonBot Global Configuration & Design System Constants
Local-first floating desktop study companion for CSE Project.
"""

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

# Load environment variables from .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

# UI Configuration
UI_THEME = os.getenv("UI_THEME", "dark").strip().lower()
if UI_THEME not in ("dark", "light", "system"):
    UI_THEME = "dark"

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

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

# Nocturne Focus Design System Tokens
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
