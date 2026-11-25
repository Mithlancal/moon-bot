"""
main.py — MoonBot Application Entry Point
3rd-Year CSE Capstone: Local-First Floating Desktop Study Companion

Wired Components:
- Background Activity Tracker (active document/PDF/tab logging to daily JSON)
- Background Academic Scheduler (exams, tests, pop quizzes, alarms, reminders)
- Pomodoro & Deep Work Timer with Emergency Reset & distraction warnings
- Ask & Learn assistant with Gemini API and local fallback
- Floating always-on-top orb and compact HUD (ui/floating_orb.py)
- Full Study Dashboard (ui/study_panel.py)
- Study analytics and charts (ui/charts.py)

All background work runs in daemon threads; every Tkinter update is marshalled
back to the main thread through ui.ui_dispatch, which also owns ordered shutdown.
"""

import atexit
import logging
import os

import customtkinter as ctk

import config
from core import json_db
from core.activity_tracker import ActivityTracker
from core.clipboard_watcher import ClipboardWatcher
from core.reader_assistant import ReaderAssistant
from core.scheduler import AcademicScheduler, StudyTimer
from ui import ui_dispatch
from ui.floating_orb import FloatingOrb
from ui.study_panel import StudyPanel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("MoonBot.Main")


def main() -> None:
    print(f"Starting {config.PROJECT_TITLE}...")
    print(f"Local data directory: {config.DATA_DIR}")
    if config.GEMINI_API_KEY:
        logger.info("Gemini is configured. Model: %s (fallbacks enabled)", config.GEMINI_MODEL)
    else:
        logger.info("No Gemini API key found; local study answers are enabled.")

    # Ensure required data directories and files exist (atomic, per-day logs).
    config.ensure_data_directories()
    json_db.get_schedule()
    json_db.get_memory()
    json_db.get_daily_log()
    app_session_id = json_db.start_app_session()
    settings = json_db.get_user_settings()

    ctk.set_appearance_mode(config.UI_THEME)
    ctk.set_default_color_theme("blue")

    # 1. Core services (no UI dependencies). The first sprint length comes from
    # the user's saved choice, never a hard-coded preset.
    def _minutes(key: str, default: int) -> int:
        try:
            return max(1, min(600, int(settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    activity_tracker = ActivityTracker(poll_interval=config.ACTIVITY_POLL_INTERVAL)
    activity_tracker.ignore_pid(os.getpid())
    study_timer = StudyTimer(
        work_minutes=_minutes("focus_minutes", config.DEFAULT_WORK_MIN),
        break_minutes=_minutes("break_minutes", config.DEFAULT_BREAK_MIN)
    )
    study_timer.set_objective(settings.get("last_objective", "Deep Focus Sprint"))
    academic_scheduler = AcademicScheduler(check_interval_sec=10.0)
    reader_assistant = ReaderAssistant()

    # 2. UI: the orb is the master Tk window; the panel is a hidden Toplevel.
    orb = FloatingOrb(
        study_timer=study_timer,
        reader_assistant=reader_assistant,
        activity_tracker=activity_tracker
    )
    study_panel = StudyPanel(
        study_timer=study_timer,
        reader_assistant=reader_assistant,
        master=orb,
        academic_scheduler=academic_scheduler
    )
    study_panel.withdraw()
    orb.set_study_panel(study_panel)

    # Keep both timer surfaces in sync when the user changes the sprint length.
    study_panel.set_duration_change_callback(
        lambda work, rest: ui_dispatch.submit(orb.sync_duration_inputs, work, rest)
    )
    orb.set_duration_change_callback(
        lambda work, rest: ui_dispatch.submit(study_panel.sync_duration_inputs, work, rest)
    )

    # 2b. Install the single main-thread dispatcher and register UI teardown hooks.
    dispatcher = ui_dispatch.install(orb)
    dispatcher.add_cleanup(study_panel.dispose)

    # 3. Alert routing: all background callbacks are scheduled onto the Tk thread.
    def deliver_alert(item: dict) -> None:
        title = item.get("title", "MoonBot reminder")
        item_type = str(item.get("type", "reminder")).replace("_", " ")
        course = item.get("course", "")
        message = f"{title}" + (f" — {course}" if course else "")
        level = "warning" if item_type in ("alarm", "exam", "test") else "info"

        def on_ui():
            try:
                # Keep the current-page label intact; the toast carries the alert.
                orb.show_notification(f"MoonBot {item_type}", message, level=level)
                study_panel.refresh_live_data()
            except Exception as exc:
                logger.debug(f"Alert UI update failed: {exc}")

        ui_dispatch.submit(on_ui)

    def deliver_distraction(app_name: str, window_title: str) -> None:
        def on_ui():
            orb.show_notification(
                "Focus warning",
                f"Possible distraction active: {app_name} — {window_title[:60]}",
                level="warning"
            )
        ui_dispatch.submit(on_ui)

    def deliver_timer_completion(mode: str) -> None:
        def on_ui():
            if mode == StudyTimer.MODE_WORK:
                orb.show_notification(
                    "Sprint complete", "Great work. Take your break, then start another sprint.",
                    level="success"
                )
            else:
                orb.show_notification(
                    "Break over", "Ready when you are — press Start Study to focus again.",
                    level="info"
                )
        ui_dispatch.submit(on_ui)

    academic_scheduler.set_alert_callback(deliver_alert)
    activity_tracker.set_distraction_callback(deliver_distraction)
    study_timer.add_completion_callback(deliver_timer_completion)

    # 3b. Site/PDF context. Only OS-visible window titles and text the user copies
    # are used; browser URLs, DOMs and private tabs are never read.
    def apply_context(context: dict) -> None:
        orb.set_live_context(context)
        study_panel.set_live_context(context)

    activity_tracker.set_context_callback(
        lambda context: ui_dispatch.submit(apply_context, context)
    )

    clipboard_watcher = ClipboardWatcher(context_provider=activity_tracker.get_current_context)
    clipboard_watcher.set_enabled(bool(settings.get("auto_clipboard_capture", True)))
    clipboard_watcher.set_callback(
        lambda text, context: ui_dispatch.submit(orb.handle_highlight, text, context)
    )
    orb.clipboard_watcher = clipboard_watcher

    # 4. Single, idempotent cleanup path for all background threads and JSON writes.
    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        logger.info("Cleaning up MoonBot background threads...")
        for stopper in (
            clipboard_watcher.stop,
            academic_scheduler.stop,
            activity_tracker.stop,
            study_timer.stop
        ):
            try:
                stopper()
            except Exception as exc:
                logger.warning(f"Cleanup step failed: {exc}")
        try:
            json_db.end_app_session(app_session_id)
        except Exception as exc:
            logger.warning(f"Could not close MoonBot usage session: {exc}")
        # Cancel timers, join UI workers, release Tk objects, then destroy windows.
        ui_dispatch.shutdown([orb, study_panel])

    orb.set_shutdown_callback(cleanup)
    atexit.register(cleanup)

    # 5. Start background workers only after the UI exists and callbacks are wired.
    activity_tracker.start()
    academic_scheduler.start()
    clipboard_watcher.start()

    print("MoonBot orb is live. Click the logo for your mini dashboard!")
    try:
        orb.mainloop()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
