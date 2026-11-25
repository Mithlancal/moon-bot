"""
core/scheduler.py — Study Timer, Alarms, Reminders & Exam/Quiz Scheduler
Manages Pomodoro/Deep Work sprints, break intervals, upcoming exam countdowns,
pop quizzes, alarms, and emergency focus-reset interventions.
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

import config
from core import json_db

logger = logging.getLogger("MoonBot.Scheduler")


class StudyTimer:
    """
    Thread-safe Pomodoro and Deep Work study timer.
    Supports Work and Break phases, pauses, resets, and emergency interventions.
    """

    STATE_STOPPED = "stopped"
    STATE_RUNNING = "running"
    STATE_PAUSED = "paused"

    MODE_WORK = "work"
    MODE_BREAK = "break"

    def __init__(
        self,
        work_minutes: int = config.DEFAULT_WORK_MIN,
        break_minutes: int = config.DEFAULT_BREAK_MIN
    ):
        self.work_minutes = work_minutes
        self.break_minutes = break_minutes

        self.state = self.STATE_STOPPED
        self.mode = self.MODE_WORK
        self.total_target_seconds = work_minutes * 60
        self.remaining_seconds = self.total_target_seconds

        self.current_objective: str = "Deep Focus Sprint"
        self._session_start_time: Optional[datetime] = None
        self._elapsed_in_session: int = 0

        self._lock = threading.RLock()
        self._running_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Listeners
        self._tick_callbacks: List[Callable[[int, int, str, str], None]] = []
        self._completion_callbacks: List[Callable[[str], None]] = []

    def add_tick_callback(self, cb: Callable[[int, int, str, str], None]) -> None:
        """cb(remaining_sec, total_sec, mode, state)"""
        with self._lock:
            self._tick_callbacks.append(cb)

    def add_completion_callback(self, cb: Callable[[str], None]) -> None:
        """cb(mode)"""
        with self._lock:
            self._completion_callbacks.append(cb)

    def set_duration(self, work_min: int, break_min: int) -> None:
        """Configure work/break durations."""
        with self._lock:
            self.work_minutes = max(1, work_min)
            self.break_minutes = max(1, break_min)
            if self.state == self.STATE_STOPPED:
                self.total_target_seconds = (self.work_minutes if self.mode == self.MODE_WORK else self.break_minutes) * 60
                self.remaining_seconds = self.total_target_seconds
                self._notify_ticks()

    def set_objective(self, objective: str) -> None:
        with self._lock:
            self.current_objective = objective.strip() or "General Study Sprint"

    def start(self) -> None:
        """Start or resume the timer."""
        with self._lock:
            if self.state == self.STATE_RUNNING:
                return

            if self.state == self.STATE_STOPPED:
                self._session_start_time = datetime.now()
                self._elapsed_in_session = 0
                self.total_target_seconds = (self.work_minutes if self.mode == self.MODE_WORK else self.break_minutes) * 60
                self.remaining_seconds = self.total_target_seconds

            self.state = self.STATE_RUNNING
            self._stop_event.clear()

            if self._running_thread is None or not self._running_thread.is_alive():
                self._running_thread = threading.Thread(target=self._run_loop, daemon=True, name="MoonBot-Timer")
                self._running_thread.start()

            self._notify_ticks()

    def pause(self) -> None:
        """Pause the current timer."""
        with self._lock:
            if self.state == self.STATE_RUNNING:
                self.state = self.STATE_PAUSED
                self._notify_ticks()

    def stop(self) -> None:
        """Stop the worker thread cleanly (used during application shutdown)."""
        with self._lock:
            self._stop_event.set()
            self.state = self.STATE_STOPPED
        thread = self._running_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("StudyTimer thread did not stop within 5 seconds")
        with self._lock:
            self._running_thread = None

    def reset(self) -> None:
        """Reset timer to beginning of current mode."""
        with self._lock:
            if self.state != self.STATE_STOPPED and self._elapsed_in_session >= 30 and self.mode == self.MODE_WORK:
                self._log_session(completed=False)

            self.state = self.STATE_STOPPED
            self.total_target_seconds = (self.work_minutes if self.mode == self.MODE_WORK else self.break_minutes) * 60
            self.remaining_seconds = self.total_target_seconds
            self._elapsed_in_session = 0
            self._session_start_time = None
            self._notify_ticks()

    def emergency_reset(self) -> str:
        """
        Emergency button action: halts active sprint, logs distraction/drift alert,
        resets timer, and returns an emergency calm response.
        """
        with self._lock:
            if self.state == self.STATE_RUNNING and self._elapsed_in_session >= 15:
                self._log_session(completed=False)

            self.state = self.STATE_STOPPED
            self.mode = self.MODE_BREAK
            self.total_target_seconds = 3 * 60  # 3 min emergency reset breath
            self.remaining_seconds = self.total_target_seconds
            self._elapsed_in_session = 0
            self._session_start_time = None

            # Log to daily events
            msg = "Emergency focus-reset triggered. Distraction paused. Take a 3-minute breather."
            json_db.append_daily_event(
                event_type="emergency_reset",
                title="Emergency Focus Reset",
                details=f"Sprint interrupted on '{self.current_objective}'. Cooldown break initiated."
            )

            self._notify_ticks()
            return msg

    def switch_mode(self, new_mode: str) -> None:
        with self._lock:
            self.mode = new_mode
            self.state = self.STATE_STOPPED
            self.total_target_seconds = (self.work_minutes if new_mode == self.MODE_WORK else self.break_minutes) * 60
            self.remaining_seconds = self.total_target_seconds
            self._elapsed_in_session = 0
            self._session_start_time = None
            self._notify_ticks()

    def _notify_ticks(self) -> None:
        for cb in self._tick_callbacks:
            try:
                cb(self.remaining_seconds, self.total_target_seconds, self.mode, self.state)
            except Exception as e:
                logger.debug(f"Tick callback error: {e}")

    def _log_session(self, completed: bool) -> None:
        if self._elapsed_in_session <= 0:
            return

        end_time = datetime.now()
        start_iso = self._session_start_time.isoformat() if self._session_start_time else end_time.isoformat()
        session_data = {
            "session_id": f"sess-{uuid.uuid4().hex[:8]}",
            "start_time": start_iso,
            "end_time": end_time.isoformat(),
            "duration_sec": self._elapsed_in_session,
            "objective": self.current_objective,
            "status": "completed" if completed else "interrupted"
        }
        json_db.append_study_session(session_data)

    def _run_loop(self) -> None:
        """Second-by-second countdown loop."""
        while not self._stop_event.is_set():
            if self._stop_event.wait(1.0):
                break
            with self._lock:
                if self.state == self.STATE_RUNNING:
                    if self.remaining_seconds > 0:
                        self.remaining_seconds -= 1
                        self._elapsed_in_session += 1
                        self._notify_ticks()
                    else:
                        # Timer finished!
                        finished_mode = self.mode
                        if finished_mode == self.MODE_WORK:
                            self._log_session(completed=True)
                            json_db.append_daily_event(
                                event_type="study_completed",
                                title="Study Sprint Completed",
                                details=f"Target: {self.current_objective} ({self.work_minutes} min)"
                            )
                            # Switch to break
                            self.mode = self.MODE_BREAK
                            self.total_target_seconds = self.break_minutes * 60
                            self.remaining_seconds = self.total_target_seconds
                            self.state = self.STATE_STOPPED
                        else:
                            # Break finished, switch to work
                            self.mode = self.MODE_WORK
                            self.total_target_seconds = self.work_minutes * 60
                            self.remaining_seconds = self.total_target_seconds
                            self.state = self.STATE_STOPPED

                        self._notify_ticks()

                        for cb in self._completion_callbacks:
                            try:
                                cb(finished_mode)
                            except Exception as e:
                                logger.debug(f"Completion callback error: {e}")


class AcademicScheduler:
    """
    Background checker for academic schedule deadlines, tests, alarms, and pop quizzes.
    """

    def __init__(self, check_interval_sec: float = 10.0):
        self.check_interval_sec = max(0.5, float(check_interval_sec))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._triggered_events: Set[str] = set()
        self._alarms: List[Dict[str, Any]] = []
        self._alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_alert_callback(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        self._alert_callback = cb

    def add_alarm(self, delay_seconds: float, title: str, details: str = "") -> Dict[str, Any]:
        """
        Schedule a one-shot alarm/reminder (e.g. a 20-minute break reminder).
        Due alarms are logged and delivered through the alert callback.
        """
        alarm = {
            "id": f"alarm-{uuid.uuid4().hex[:8]}",
            "title": title.strip() or "MoonBot Alarm",
            "details": details.strip(),
            "target_time": (datetime.now() + timedelta(seconds=max(1, float(delay_seconds)))).isoformat(),
            "created_at": datetime.now().isoformat(),
            "triggered": False
        }
        with self._lock:
            self._alarms.append(alarm)
        return dict(alarm)

    def snooze_alarm(self, alarm_id: str, delay_seconds: float = 300) -> bool:
        """Re-arm a triggered alarm for later."""
        with self._lock:
            for alarm in self._alarms:
                if alarm["id"] == alarm_id:
                    alarm["triggered"] = False
                    alarm["target_time"] = (
                        datetime.now() + timedelta(seconds=max(1, float(delay_seconds)))
                    ).isoformat()
                    return True
        return False

    def dismiss_alarm(self, alarm_id: str) -> bool:
        with self._lock:
            before = len(self._alarms)
            self._alarms = [a for a in self._alarms if a["id"] != alarm_id]
            return len(self._alarms) < before

    def list_alarms(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in self._alarms if not a["triggered"]]

    def _fire_alert(self, payload: Dict[str, Any], event_type: str, details: str) -> None:
        try:
            json_db.append_daily_event(
                event_type=event_type,
                title=payload.get("title", "MoonBot Alert"),
                details=details
            )
        except Exception as e:
            logger.error(f"Failed to log scheduler alert: {e}")
        if self._alert_callback:
            try:
                self._alert_callback(payload)
            except Exception as e:
                logger.debug(f"Alert callback error: {e}")

    def _check_alarms(self) -> None:
        now = datetime.now()
        with self._lock:
            due = [a for a in self._alarms if not a["triggered"]]
        for alarm in due:
            try:
                target = datetime.fromisoformat(alarm["target_time"])
            except (ValueError, KeyError, TypeError):
                continue
            if now < target:
                continue
            with self._lock:
                for stored in self._alarms:
                    if stored["id"] == alarm["id"]:
                        stored["triggered"] = True
            payload = {
                "id": alarm["id"],
                "title": alarm["title"],
                "course": "Alarm / Reminder",
                "type": "alarm",
                "datetime": alarm["target_time"],
                "notes": alarm.get("details", "")
            }
            self._fire_alert(payload, "alarm", alarm.get("details", "One-shot alarm triggered."))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._check_loop, daemon=True, name="MoonBot-Scheduler")
        self._thread.start()
        logger.info("AcademicScheduler started.")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("AcademicScheduler thread did not stop within 5 seconds")
        self._thread = None

    def _check_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                self._check_upcoming_items()
            except Exception as e:
                logger.error(f"Error checking schedule: {e}")
            if self._stop_event.wait(self.check_interval_sec):
                break

    def _check_upcoming_items(self) -> None:
        self._check_alarms()
        now = datetime.now()
        schedule_data = json_db.get_schedule()

        for item in schedule_data.get("items", []):
            if item.get("completed", False):
                continue

            item_id = item.get("id")
            if item_id in self._triggered_events:
                continue

            dt_str = item.get("datetime")
            if not dt_str:
                continue

            try:
                target_dt = datetime.fromisoformat(dt_str)
            except ValueError:
                continue

            diff = (target_dt - now).total_seconds()

            # Trigger when within 15 minutes or overdue by less than 1 hour
            if -3600 <= diff <= 900:
                self._triggered_events.add(item_id)
                item_type = item.get("type", "reminder")
                self._fire_alert(
                    item,
                    f"schedule_{item_type}",
                    f"Course: {item.get('course', 'N/A')}. Time: {target_dt.strftime('%H:%M')}."
                )
