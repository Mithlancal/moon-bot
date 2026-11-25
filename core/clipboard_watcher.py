"""
core/clipboard_watcher.py — Opt-in local highlight capture for PDFs/tabs/slides.

A student highlights text in a PDF or web page and presses Ctrl+C. This watcher
notices the new clipboard text and hands it to the UI together with the active
window context, so MoonBot can explain, translate, quiz or memo the selection
with the right PDF/site context attached. No keyboard input is read and nothing
is sent anywhere until the user asks MoonBot to analyse the text.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Callable, Optional

import config

logger = logging.getLogger("MoonBot.ClipboardWatcher")

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:  # pragma: no cover - environment dependent
    pyperclip = None
    HAS_PYPERCLIP = False


class ClipboardWatcher:
    """Poll the clipboard for newly copied study text on a stoppable daemon thread."""

    MIN_CHARS = 12
    MAX_CHARS = 12000

    def __init__(self, context_provider: Optional[Callable[[], dict]] = None):
        self.context_provider = context_provider
        self._enabled = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callback: Optional[Callable[[str, dict], None]] = None
        self._last_hash = ""
        self._lock = threading.RLock()

    def set_callback(self, cb: Callable[[str, dict], None]) -> None:
        self._callback = cb

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if self._enabled and self._running:
                try:
                    self._last_hash = self._hash_current()
                except Exception:
                    pass

    def is_enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        with self._lock:
            if self._running or not HAS_PYPERCLIP:
                return
            self._running = True
            self._stop_event.clear()
            try:
                self._last_hash = self._hash_current()
            except Exception:
                self._last_hash = ""
            self._thread = threading.Thread(
                target=self._watch_loop, daemon=True, name="MoonBot-Clipboard"
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def _hash_current(self) -> str:
        try:
            return self._hash((pyperclip.paste() or "").strip())
        except Exception:
            return ""

    def _watch_loop(self) -> None:
        interval = max(0.4, float(config.CLIPBOARD_POLL_INTERVAL))
        while not self._stop_event.wait(interval):
            with self._lock:
                if not self._enabled or not self._callback:
                    continue
            try:
                text = (pyperclip.paste() or "").strip()
            except Exception:
                continue

            digest = self._hash(text)
            if not text or digest == self._last_hash:
                continue
            self._last_hash = digest
            if not (self.MIN_CHARS <= len(text) <= self.MAX_CHARS):
                continue
            if "\n" not in text and len(text) < 24 and " " not in text:
                continue

            context = {}
            if self.context_provider:
                try:
                    context = dict(self.context_provider() or {})
                except Exception:
                    context = {}

            try:
                self._callback(text, context)
            except Exception as exc:
                logger.debug(f"Clipboard callback failed: {exc}")
