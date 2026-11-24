"""
main.py — MoonBot Application Entry Point
3rd-Year CSE Capstone: Local-First Floating Desktop Study Companion

Wired Components:
- Background Activity Tracker (active document/PDF/tab logging to daily JSON)
- Background Academic Scheduler (exams, tests, pop quizzes, alarms, reminders)
- Pomodoro & Deep Work Timer with Emergency Reset & distraction warnings
- No-Tab-Switch Reader Assistant with Gemini API & offline fallback
- Floating Always-on-Top Draggable Orb Widget (ui/floating_orb.py)
- Full Study Sanctuary Dashboard (ui/study_panel.py)
- Nocturne Focus Analytics & Charts (ui/charts.py)

All background work runs in daemon threads; every Tkinter update is marshalled
back to the main thread with widget.after(...).
"""

import atexit
import logging

import customtkinter as ctk

import config
from core import json_db
from core.activity_tracker import ActivityTracker
from core.reader_assistant import ReaderAssistant
from core.scheduler import AcademicScheduler, StudyTimer
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

    # Ensure required data directories and files exist (atomic, per-day logs).
    config.ensure_data_directories()
    json_db.get_schedule()
    json_db.get_memory()
    json_db.get_daily_log()
    app_session_id = json_db.start_app_session()

    ctk.set_appearance_mode(config.UI_THEME)
    ctk.set_default_color_theme("blue")

    # 1. Core services (no UI dependencies).
    activity_tracker = ActivityTracker(poll_interval=config.ACTIVITY_POLL_INTERVAL)
    study_timer = StudyTimer(
        work_minutes=config.DEFAULT_WORK_MIN,
        break_minutes=config.DEFAULT_BREAK_MIN
    )
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

    # 3. Alert routing: all background callbacks are scheduled onto the Tk thread.
    def deliver_alert(item: dict) -> None:
        title = item.get("title", "MoonBot reminder")
        item_type = str(item.get("type", "reminder")).replace("_", " ")
        course = item.get("course", "")
        message = f"{title}" + (f" — {course}" if course else "")
        level = "warning" if item_type in ("alarm", "exam", "test") else "info"

        def on_ui():
            try:
                orb.active_context_lbl.configure(text=f"⏰ UPCOMING: {title} ({course})")
                orb.show_notification(f"MoonBot {item_type}", message, level=level)
                study_panel.refresh_live_data()
            except Exception as exc:
                logger.debug(f"Alert UI update failed: {exc}")

        orb.after(0, on_ui)

    def deliver_distraction(app_name: str, window_title: str) -> None:
        def on_ui():
            orb.show_notification(
                "Focus warning",
                f"Possible distraction active: {app_name} — {window_title[:60]}",
                level="warning"
            )
        orb.after(0, on_ui)

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
        orb.after(0, on_ui)

    academic_scheduler.set_alert_callback(deliver_alert)
    activity_tracker.set_distraction_callback(deliver_distraction)
    study_timer.add_completion_callback(deliver_timer_completion)

    # 4. Single, idempotent cleanup path for all background threads and JSON writes.
    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        logger.info("Cleaning up MoonBot background threads...")
        for stopper in (academic_scheduler.stop, activity_tracker.stop, study_timer.stop):
            try:
                stopper()
            except Exception as exc:
                logger.warning(f"Cleanup step failed: {exc}")
        try:
            json_db.end_app_session(app_session_id)
        except Exception as exc:
            logger.warning(f"Could not close MoonBot usage session: {exc}")

    orb.set_shutdown_callback(cleanup)
    atexit.register(cleanup)

    # 5. Start background workers only after the UI exists and callbacks are wired.
    activity_tracker.start()
    academic_scheduler.start()

    print("MoonBot HUD is live. Keep studying with your floating companion!")
    try:
        orb.mainloop()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
