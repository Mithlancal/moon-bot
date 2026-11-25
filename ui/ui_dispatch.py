"""
ui/ui_dispatch.py — Thread-safe UI dispatching and ordered Tk shutdown for MoonBot.

Why this module exists
----------------------
Tkinter is not thread-safe. Background services (activity tracker, scheduler,
timer, Gemini workers) must never call widget.after()/widget.configure()
themselves. They submit plain callables to this dispatcher, which executes them
on the main thread from a single tracked `after` loop.

This module also tracks *every* `after()` id created in the process (including
CustomTkinter's internal DPI/appearance polling loops). At shutdown all pending
callbacks are cancelled, background threads are joined, Tk variables/images are
neutralised on the main thread, CTk's global loops are stopped, and only then is
the root window destroyed. This prevents:
  - "RuntimeError: main thread is not in main loop"
  - "Tcl_AsyncDelete: async handler deleted by the wrong thread"
  - "Exception ignored in ... Variable.__del__ / ImageTk.PhotoImage.__del__"
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from typing import Any, Callable, Iterable, Optional

import customtkinter as ctk

logger = logging.getLogger("MoonBot.UIDispatch")

# ---------------------------------------------------------------------------
# Global after() tracking (patched once, before any widgets are created)
# ---------------------------------------------------------------------------

_original_after = tk.Misc.after
_original_after_cancel = tk.Misc.after_cancel
# Tcl after ids are interpreter-wide; keep the scheduling widget too so a widget
# can be torn down without leaving its pending callbacks behind.
_after_records: dict[str, tk.Misc] = {}
_after_ids_lock = threading.RLock()
_patched = False


def _patch_tkinter_after() -> None:
    """Wrap tk.Misc.after so every scheduled callback id can be cancelled on exit."""
    global _patched
    if _patched:
        return

    def tracked_after(self, ms, func=None, *args):
        if func is None:
            return _original_after(self, ms, None)

        holder: dict[str, Any] = {}

        def callit(*call_args):
            with _after_ids_lock:
                _after_records.pop(holder.get("id"), None)
            return func(*call_args)

        try:
            callit.__name__ = getattr(func, "__name__", type(func).__name__)
        except Exception:
            pass

        ident = _original_after(self, ms, callit, *args)
        holder["id"] = ident
        with _after_ids_lock:
            _after_records[ident] = self
        return ident

    def tracked_after_cancel(self, ident):
        if ident:
            with _after_ids_lock:
                owner = _after_records.pop(ident, None)
            if owner is not None:
                # Tkinter's after_cancel deletes the Tcl command from the widget
                # passed in. It must be the widget that originally registered it,
                # otherwise its _tclCommands list keeps a stale name and destroy()
                # later fails with "can't delete Tcl command".
                return _original_after_cancel(owner, ident)
        return _original_after_cancel(self, ident)

    tk.Misc.after = tracked_after
    tk.Misc.after_cancel = tracked_after_cancel
    _patched = True


def _cancel_after_id(ident: Optional[str]) -> None:
    """Cancel a tracked after id using the widget that created it."""
    if not ident:
        return
    with _after_ids_lock:
        owner = _after_records.pop(ident, None)
    if owner is not None:
        try:
            _original_after_cancel(owner, ident)
        except Exception:
            pass


_patch_tkinter_after()


# ---------------------------------------------------------------------------
# Main-thread dispatcher
# ---------------------------------------------------------------------------

class UiDispatcher:
    """Single owner of Tk interaction for non-main threads."""

    POLL_MS = 16

    def __init__(self, root: tk.Tk):
        self.root = root
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._shutdown = False
        self._drain_id: Optional[str] = None
        self._workers: set[threading.Thread] = set()
        self._worker_lock = threading.RLock()
        self._cleanups: list[Callable[[], None]] = []

    # -- public API ---------------------------------------------------------
    def start(self) -> None:
        if self._drain_id is None and not self._shutdown:
            self._drain_id = self.root.after(self.POLL_MS, self._drain)

    def add_cleanup(self, func: Callable[[], None]) -> None:
        """Register a main-thread teardown callback (e.g. closing a Matplotlib figure)."""
        if not self._shutdown:
            self._cleanups.append(func)

    def submit(self, func: Callable[..., Any], *args: Any) -> None:
        """Queue a callable to run on the main Tk thread (safe from any thread)."""
        if self._shutdown:
            return
        self._queue.put((func, args))

    def after(self, ms: int, func: Callable[..., Any], *args: Any) -> Optional[str]:
        """Schedule a tracked timer on the main thread."""
        if self._shutdown:
            return None
        return self.root.after(ms, func, *args)

    def cancel_after(self, ident: Optional[str]) -> None:
        _cancel_after_id(ident)

    def run_worker(self, target: Callable[..., Any], *args: Any) -> Optional[threading.Thread]:
        """Run a short-lived background job and register it for clean joining."""
        if self._shutdown:
            return None

        def wrapper():
            try:
                if self._shutdown:
                    return
                target(*args)
            except Exception:
                logger.exception("Background worker failed")
            finally:
                with self._worker_lock:
                    self._workers.discard(thread)

        thread = threading.Thread(target=wrapper, daemon=True, name="MoonBot-Worker")
        with self._worker_lock:
            self._workers.add(thread)
        thread.start()
        return thread

    def shutdown(self, extra_widgets: Iterable[tk.Misc] = ()) -> None:
        """Cancel timers, join workers, neutralise Tk objects, then destroy windows."""
        if self._shutdown:
            return
        self._shutdown = True
        logger.info("Shutting down UI dispatcher...")

        # 1. Cancel every pending after() callback, including CTk's own loops.
        with _after_ids_lock:
            pending = list(_after_records)
        for ident in pending:
            _cancel_after_id(ident)
        self._drain_id = None

        # 2. Drop queued callbacks without executing them.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        # 3. Join worker threads. submit() is now a no-op, so late results cannot touch Tk.
        with self._worker_lock:
            workers = list(self._workers)
        for thread in workers:
            if thread is not threading.current_thread():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.debug("UI worker still running at shutdown; its results are ignored")

        # 4. Run UI-owned teardown (charts, images) on the main thread.
        for cleanup in self._cleanups:
            try:
                cleanup()
            except Exception as exc:
                logger.debug(f"UI cleanup callback failed: {exc}")
        self._cleanups.clear()

        # 5. Release Tk-owned objects while the interpreter is still alive.
        widgets = list(extra_widgets)
        if self.root not in widgets:
            widgets.append(self.root)
        for widget in widgets:
            try:
                _neutralise_widget(widget)
            except Exception as exc:
                logger.debug(f"Could not neutralise widget: {exc}")

        # 6. Stop CustomTkinter's class-level polling loops for good.
        _stop_ctk_loops()

        # 7. Destroy windows last. The root is destroyed after its children.
        for widget in widgets:
            if widget is self.root:
                continue
            cancel_widget_after(widget)
            try:
                if widget.winfo_exists():
                    widget.destroy()
            except Exception:
                pass
        cancel_widget_after(self.root)

        # CTk can queue a final callback while its widgets are being destroyed.
        # Sweep again *before* destroying the root, while after_cancel still works.
        with _after_ids_lock:
            late = list(_after_records)
        for ident in late:
            _cancel_after_id(ident)

        # Quit the event loop first so no queued Tcl callback can fire while the
        # interpreter is being torn down, then destroy the windows.
        try:
            self.root.quit()
        except Exception:
            logger.debug("Tk mainloop was already stopped")
        try:
            self.root.destroy()
        except Exception:
            logger.exception("Failed to destroy Tk root")

    # -- internal -----------------------------------------------------------
    def _drain(self) -> None:
        if self._shutdown:
            return
        try:
            while True:
                func, args = self._queue.get_nowait()
                if self._shutdown:
                    return
                try:
                    func(*args)
                except tk.TclError:
                    if not self._shutdown:
                        logger.exception("UI callback failed")
                except Exception:
                    if not self._shutdown:
                        logger.exception("UI callback failed")
        except queue.Empty:
            pass
        finally:
            if not self._shutdown:
                self._drain_id = self.root.after(self.POLL_MS, self._drain)


# ---------------------------------------------------------------------------
# Module-level helpers used by ui/ and main.py
# ---------------------------------------------------------------------------

_dispatcher: Optional[UiDispatcher] = None
_pending_cleanups: list[Callable[[], None]] = []


def install(root: tk.Tk) -> UiDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = UiDispatcher(root)
        _dispatcher.start()
    return _dispatcher


def get() -> Optional[UiDispatcher]:
    return _dispatcher


def is_shutdown() -> bool:
    return bool(_dispatcher and _dispatcher._shutdown)


def on_shutdown(func: Callable[[], None]) -> None:
    """Register a main-thread teardown callback (works with or without a dispatcher)."""
    if _dispatcher is not None:
        _dispatcher.add_cleanup(func)
    else:
        _pending_cleanups.append(func)


def submit(func: Callable[..., Any], *args: Any) -> None:
    if _dispatcher is not None:
        _dispatcher.submit(func, *args)
    else:
        logger.debug("UI callback dropped: dispatcher not installed yet")


def after(ms: int, func: Callable[..., Any], *args: Any) -> Optional[str]:
    return _dispatcher.after(ms, func, *args) if _dispatcher else None


def cancel_after(ident: Optional[str]) -> None:
    if _dispatcher:
        _dispatcher.cancel_after(ident)


def cancel_widget_after(widget: tk.Misc) -> None:
    """Cancel all tracked after() timers owned by a widget and its children."""
    targets: set[tk.Misc] = set()

    def collect(current: tk.Misc) -> None:
        targets.add(current)
        try:
            children = list(current.winfo_children())
        except Exception:
            return
        for child in children:
            collect(child)

    try:
        collect(widget)
    except Exception:
        return

    with _after_ids_lock:
        ids = [ident for ident, owner in _after_records.items() if owner in targets]
    for ident in ids:
        _cancel_after_id(ident)


def run_worker(target: Callable[..., Any], *args: Any) -> Optional[threading.Thread]:
    return _dispatcher.run_worker(target, *args) if _dispatcher else None


def shutdown(extra_widgets: Iterable[tk.Misc] = ()) -> None:
    if _dispatcher:
        _dispatcher.shutdown(extra_widgets)
        return

    # No dispatcher installed (e.g. an isolated widget smoke test). Still cancel
    # every tracked after() timer before the Tcl interpreter goes away, otherwise
    # CTk's polling callbacks fire against deleted commands.
    with _after_ids_lock:
        pending = list(_after_records)
    for ident in pending:
        _cancel_after_id(ident)

    for cleanup in _pending_cleanups:
        try:
            cleanup()
        except Exception as exc:
            logger.debug(f"UI cleanup callback failed: {exc}")
    _pending_cleanups.clear()
    for widget in extra_widgets:
        cancel_widget_after(widget)
    _stop_ctk_loops()


# ---------------------------------------------------------------------------
# Tk resource neutralisation (always executed on the main thread)
# ---------------------------------------------------------------------------

def _clear_ctk_image(image: Any) -> None:
    for attr in ("_scaled_light_photo_images", "_scaled_dark_photo_images"):
        photos = getattr(image, attr, None)
        if isinstance(photos, dict):
            photos.clear()


def _neutralise_value(value: Any, depth: int = 0) -> None:
    """Disable Variable.__del__ Tcl calls and drop PhotoImage references."""
    if depth > 4 or value is None or isinstance(value, (str, int, float, bool, bytes)):
        return
    if isinstance(value, tk.Variable):
        value._tk = None  # makes __del__ a no-op after interpreter teardown
        return
    if hasattr(value, "_PhotoImage__photo"):
        # PIL/ImageTk PhotoImage.__del__ calls into Tcl. Clear its name while the
        # main thread still owns the interpreter so late GC cannot touch Tcl.
        try:
            value._PhotoImage__photo.name = None
        except Exception:
            pass
        return
    if isinstance(value, tk.Misc):
        return  # widget trees are walked explicitly
    if hasattr(value, "_scaled_light_photo_images"):
        _clear_ctk_image(value)
        return
    if isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, (list, tuple, set, frozenset)):
        children = list(value)
    else:
        return
    for child in children:
        _neutralise_value(child, depth + 1)


def _neutralise_widget(widget: tk.Misc) -> None:
    try:
        for value in list(vars(widget).values()):
            _neutralise_value(value)
    except Exception:
        pass
    try:
        children = list(widget.winfo_children())
    except Exception:
        children = []
    for child in children:
        _neutralise_widget(child)


def _stop_ctk_loops() -> None:
    """Clear CustomTkinter's global polling registries so no after() loop restarts."""
    try:
        ctk.AppearanceModeTracker.app_list.clear()
        ctk.AppearanceModeTracker.callback_list.clear()
        ctk.AppearanceModeTracker.update_loop_running = False
    except Exception:
        pass
    try:
        ctk.ScalingTracker.window_widgets_dict.clear()
        ctk.ScalingTracker.window_dpi_scaling_dict.clear()
        ctk.ScalingTracker.update_loop_running = False
    except Exception:
        pass
