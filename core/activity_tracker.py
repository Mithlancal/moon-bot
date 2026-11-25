"""
core/activity_tracker.py — Background Foreground Window & Time Tracker
Tracks active applications, document titles, slide decks, and browser tabs on Windows.
Groups consecutive activity spans and logs them atomically to local JSON daily logs.

PRIVACY NOTE:
MoonBot inspects the public OS-level foreground window handle and process metadata
via standard Windows Win32 APIs (GetForegroundWindow, GetWindowText, GetWindowThreadProcessId).
It does not inject DLLs, read keystrokes, scrape private browser DOMs, or inspect incognito/private
browsing content. Process names and window titles (e.g. document filenames, active tab names)
provide transparent, local-first study analytics without breaching system privacy.

LIMIT: Browser URLs (and especially private/incognito tabs) are NOT readable through these OS
APIs across arbitrary browsers. MoonBot only sees the window title the browser chooses to expose;
obtaining full URLs would require a per-browser extension and is deliberately not done here.
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

import config
from core import json_db, web_context

logger = logging.getLogger("MoonBot.ActivityTracker")

# Try importing Win32 APIs safely
try:
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# Category Classification Rules
STUDY_KEYWORDS = [
    ".pdf", "acrobat", "sumatra", "foxit", "kindle", "calibre",
    "powerpnt", ".pptx", ".ppt", "slides", "keynote",
    "winword", ".docx", ".doc", "notion", "obsidian", "anki",
    "overleaf", "latex", "arxiv", "canvas", "blackboard", "moodle",
    "coursera", "edx", "nptel", "mit opencourseware",
    "scholar.google", "researchgate", "ieee", "springer", "sciencedirect",
    "geeksforgeeks", "leetcode", "hackerrank", "w3schools",
    "python documentation", "docs.python", "mdn web docs"
]

DEV_KEYWORDS = [
    "code.exe", "cursor.exe", "pycharm", "intellij", "clion",
    "sublime_text.exe", "visual studio", "neovim", "windowsterminal.exe",
    "powershell.exe", "cmd.exe", "bash.exe", "git-bash.exe"
]

DISTRACTION_KEYWORDS = [
    "youtube", "netflix", "twitch", "prime video", "disney+", "hulu",
    "reddit", "twitter", "x.com", "instagram", "tiktok", "facebook",
    "steam.exe", "epicgameslauncher.exe", "discord.exe", "riotclientservices.exe",
    "spotify.exe"
]

DISTRACTION_CATEGORY = "Distraction / Entertainment"
MOONBOT_TITLE_TOKENS = ("moonbot", "study dashboard", "ask & learn", "focus pomodoro")


def classify_activity(process_name: str, window_title: str) -> str:
    """Classify the active application/window into an academic or productivity category."""
    p_lower = (process_name or "").lower()
    t_lower = (window_title or "").lower()
    combined = f"{p_lower} {t_lower}"

    # Check for direct distraction signals first (a study tab in a distraction app is still a distraction)
    for kw in DISTRACTION_KEYWORDS:
        if kw in combined:
            return DISTRACTION_CATEGORY

    # Check for study materials, PDFs, slides, courseware
    for kw in STUDY_KEYWORDS:
        if kw in combined:
            return "Study / Reading"

    # Check for IDEs and developer tools
    for kw in DEV_KEYWORDS:
        if kw in p_lower:
            return "Development & Coding"

    # Browser tabs that are general research
    if any(b in p_lower for b in ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"]):
        return "Browser / Research"

    # Common communication / tools
    if any(c in p_lower for c in ["teams.exe", "slack.exe", "outlook.exe"]):
        return "Productivity / Tools"

    return "Other / System"


def get_foreground_window_info(ignore_pids: Optional[set[int]] = None) -> Tuple[str, str]:
    """
    Retrieve the current active foreground process name and window title.

    MoonBot windows are ignored: interacting with the HUD or dashboard should not
    replace the PDF/page the student was reading. Returns ("", "") for ignored
    windows so the tracker can pause instead of logging MoonBot as an activity.
    """
    if not HAS_WIN32:
        return ("System", "Windows Foreground Window (pywin32 unavailable)")

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return ("Idle / LockScreen", "Screen Locked or No Active Window")

        window_title = win32gui.GetWindowText(hwnd).strip()
        lowered_title = window_title.lower()
        if any(token in lowered_title for token in MOONBOT_TITLE_TOKENS):
            return ("", "")

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        ignored = {os.getpid()}
        if ignore_pids:
            ignored.update(ignore_pids)
        if pid in ignored:
            return ("", "")

        if not window_title:
            window_title = "Untitled Window"

        process_name = "Unknown"
        if HAS_PSUTIL and pid > 0:
            try:
                proc = psutil.Process(pid)
                process_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                process_name = f"Process_{pid}"
        else:
            process_name = f"HWND_{hwnd}"

        # A process from this app can still be foreground without a MoonBot title
        # (for example a short-lived dialog). Keep the context stable there too.
        if pid in ignored and any(token in process_name.lower() for token in ("python", "pythonw")):
            return ("", "")

        return (process_name, window_title)

    except Exception as exc:
        logger.debug(f"Error reading foreground window: {exc}")
        return ("Unknown", "Inaccessible Window")


class ActivityTracker:
    """
    Background worker thread polling the active foreground application.
    Aggregates consecutive seconds on the same window into discrete activity spans.

    Time is measured with a monotonic clock (not assumed from the poll interval), so
    spans stay accurate if the machine sleeps or the tracker thread is delayed.
    Spans are check-pointed periodically, so a long session is visible in the daily
    log even before the application is closed.
    """

    CHECKPOINT_SEC = 60.0
    DISTRACTION_COOLDOWN_SEC = 300.0

    def __init__(self, poll_interval: float = config.ACTIVITY_POLL_INTERVAL):
        self.poll_interval = max(0.5, float(poll_interval))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # RLock: the loop calls _flush_current_span() while holding the lock.
        self._lock = threading.RLock()

        # Current active span state
        self._current_app: Optional[str] = None
        self._current_title: Optional[str] = None
        self._current_category: Optional[str] = None
        self._current_context: Dict[str, str] = {}
        self._span_start_time: Optional[datetime] = None
        self._accumulated_sec: float = 0.0
        self._last_poll_mono: float = 0.0
        self._last_checkpoint_mono: float = 0.0
        self._last_distraction_mono: float = 0.0
        self._ignored_pids: set[int] = {os.getpid()}

        # Callbacks: cb(app, title, category) / cb(app, title) / cb(context)
        self._on_activity_changed: Optional[Callable[[str, str, str], None]] = None
        self._on_distraction: Optional[Callable[[str, str], None]] = None
        self._on_context_changed: Optional[Callable[[Dict[str, str]], None]] = None

    def set_activity_changed_callback(self, cb: Callable[[str, str, str], None]) -> None:
        self._on_activity_changed = cb

    def set_distraction_callback(self, cb: Callable[[str, str], None]) -> None:
        """Register a callback for throttled distraction warnings (fired at most every 5 min)."""
        self._on_distraction = cb

    def set_context_callback(self, cb: Callable[[Dict[str, str]], None]) -> None:
        """Register a callback receiving the parsed PDF/site/document context."""
        self._on_context_changed = cb

    def ignore_pid(self, pid: int) -> None:
        """Add a process whose windows must never become study context."""
        if pid > 0:
            self._ignored_pids.add(int(pid))

    def get_current_context(self) -> Dict[str, str]:
        """Return a snapshot of the active document/site context (no browser URLs are read)."""
        with self._lock:
            return dict(self._current_context)

    def start(self) -> None:
        """Start the background tracker."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._last_poll_mono = time.monotonic()
            self._last_checkpoint_mono = self._last_poll_mono
            self._thread = threading.Thread(target=self._tracker_loop, daemon=True, name="MoonBot-Tracker")
            self._thread.start()
            logger.info("ActivityTracker started.")

    def stop(self) -> None:
        """Stop tracking and flush the current activity span to disk."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("ActivityTracker thread did not stop within 5 seconds")
        self._thread = None

        self._flush_current_span()
        logger.info("ActivityTracker stopped.")

    def get_current_activity(self) -> Dict[str, str]:
        """Return snapshot of the active window being tracked right now."""
        with self._lock:
            return {
                "app": self._current_app or "Initializing...",
                "title": self._current_title or "Detecting active window...",
                "category": self._current_category or "Study / Reading",
                "duration_sec": str(int(self._accumulated_sec))
            }

    def _flush_current_span(self) -> None:
        """Write the finished continuous activity span to JSON database."""
        with self._lock:
            if not self._current_app:
                return

            duration = int(round(self._accumulated_sec))
            end_time = datetime.now()
            start_time = self._span_start_time or end_time
            if duration >= 1:
                context = self._current_context or {}
                span_data = {
                    "app": self._current_app,
                    "window_or_tab": self._current_title or "Untitled",
                    "category": self._current_category or "Other / System",
                    "site": context.get("site", ""),
                    "document": context.get("document", ""),
                    "context_kind": context.get("kind", ""),
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_sec": duration
                }
                try:
                    # Attribute the span to the day it started, even across midnight.
                    json_db.append_activity_span(span_data, start_time.date().isoformat())
                except Exception as e:
                    logger.error(f"Failed to record activity span: {e}")

            # Reset accumulated state
            self._current_app = None
            self._current_title = None
            self._current_category = None
            self._current_context = {}
            self._accumulated_sec = 0.0
            self._span_start_time = None

    def _begin_span(self, app: str, title: str, category: str, context: Optional[Dict[str, str]] = None) -> None:
        self._current_app = app
        self._current_title = title
        self._current_category = category
        self._current_context = dict(context or {})
        self._accumulated_sec = 0.0
        self._span_start_time = datetime.now()

    def _tracker_loop(self) -> None:
        """Main background loop."""
        while self._running and not self._stop_event.is_set():
            now_mono = time.monotonic()
            # Cap catch-up time so a suspended machine does not log hours of phantom activity.
            elapsed = min(max(0.0, now_mono - self._last_poll_mono), self.poll_interval * 5)
            self._last_poll_mono = now_mono

            try:
                app_name, title = get_foreground_window_info(self._ignored_pids)
                if not app_name or not title:
                    # MoonBot's own window is foreground. Pause tracking so the
                    # last PDF/page context stays visible in Ask & Learn.
                    continue
                category = classify_activity(app_name, title)
                context = web_context.parse_context(app_name, title)

                with self._lock:
                    if self._current_app:
                        self._accumulated_sec += elapsed

                    changed = (
                        app_name != self._current_app
                        or title != self._current_title
                    )
                    if changed:
                        self._flush_current_span()
                        self._begin_span(app_name, title, category, context)
                        if self._on_activity_changed:
                            try:
                                self._on_activity_changed(app_name, title, category)
                            except Exception as e:
                                logger.debug(f"Activity callback error: {e}")
                        if self._on_context_changed:
                            try:
                                self._on_context_changed(dict(context))
                            except Exception as e:
                                logger.debug(f"Context callback error: {e}")
                    elif not self._current_app:
                        self._begin_span(app_name, title, category, context)

                    # Throttled distraction warning, only while actively tracking a window.
                    if (
                        category == DISTRACTION_CATEGORY
                        and now_mono - self._last_distraction_mono >= self.DISTRACTION_COOLDOWN_SEC
                    ):
                        self._last_distraction_mono = now_mono
                        try:
                            json_db.append_daily_event(
                                event_type="distraction_warning",
                                title="Distraction Detected",
                                details=f"{app_name} — {title}"
                            )
                        except Exception as e:
                            logger.debug(f"Failed to log distraction warning: {e}")
                        if self._on_distraction:
                            try:
                                self._on_distraction(app_name, title)
                            except Exception as e:
                                logger.debug(f"Distraction callback error: {e}")

                    # Check-point long spans so the JSON log stays current.
                    if (
                        now_mono - self._last_checkpoint_mono >= self.CHECKPOINT_SEC
                        and self._current_app
                        and self._accumulated_sec >= 1
                    ):
                        same_app = self._current_app
                        same_title = self._current_title
                        same_category = self._current_category
                        same_context = dict(self._current_context)
                        self._flush_current_span()
                        self._begin_span(same_app, same_title, same_category, same_context)
                        self._last_checkpoint_mono = now_mono

            except Exception as e:
                logger.error(f"Exception in ActivityTracker loop: {e}")

            # Interruptible sleep: shutdown does not wait for a full poll interval.
            if self._stop_event.wait(self.poll_interval):
                break
