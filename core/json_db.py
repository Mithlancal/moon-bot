"""
core/json_db.py — Local-First Atomic JSON Database & Daily Log Engine
Provides thread-safe, corruption-proof JSON reads/writes, daily logging,
schedule management, memory vault, and analytics aggregation for MoonBot.
"""

import json
import os
import tempfile
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

import config

# Global thread lock for file operations
_db_lock = threading.RLock()


def _atomic_write_json(file_path: Path, data: Any) -> None:
    """
    Safely write JSON to disk using atomic replacement (tempfile + flush + replace).
    Guarantees no half-written or corrupted JSON files on sudden process interruption.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = file_path.parent

    # Create temporary file in the same directory to allow atomic os.replace across filesystem boundaries
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=2, ensure_ascii=False)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name

    # Atomic replace
    os.replace(temp_name, file_path)


def _safe_read_json(file_path: Path, default_factory: Any) -> Any:
    """Read a JSON file safely, returning default_factory() if missing, empty, or invalid."""
    file_path = Path(file_path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        default_val = default_factory() if callable(default_factory) else default_factory
        _atomic_write_json(file_path, default_val)
        return default_val

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        default_val = default_factory() if callable(default_factory) else default_factory
        _atomic_write_json(file_path, default_val)
        return default_val


# -------------------------------------------------------------------------
# Daily Log Engine
# -------------------------------------------------------------------------

def _default_daily_log(date_str: str) -> Dict[str, Any]:
    return {
        "date": date_str,
        "study_sessions": [],
        "activity_spans": [],
        "events": [],
        # Records when MoonBot itself was open/used on this day.
        "app_sessions": [],
        "summary": {
            "total_study_sec": 0,
            "total_active_sec": 0,
            "total_moonbot_sec": 0,
            "categories": {},
            "apps": {},
            "titles": {}
        }
    }


def _seconds(value: Any) -> int:
    """Tolerant conversion of a duration field to whole seconds."""
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def get_daily_log(date_str: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the daily log for the given YYYY-MM-DD or today."""
    with _db_lock:
        if not date_str:
            date_str = date.today().isoformat()
        path = config.get_daily_log_path(date_str)
        return _safe_read_json(path, lambda: _default_daily_log(date_str))


def save_daily_log(data: Dict[str, Any], date_str: Optional[str] = None) -> None:
    """Save daily log with auto-recalculated summary."""
    with _db_lock:
        if not date_str:
            date_str = data.get("date", date.today().isoformat())
        _recalculate_daily_summary(data)
        path = config.get_daily_log_path(date_str)
        _atomic_write_json(path, data)


def _recalculate_daily_summary(data: Dict[str, Any]) -> None:
    """Recalculate aggregations for the daily log in place (including legacy logs)."""
    categories: Dict[str, int] = {}
    apps: Dict[str, int] = {}
    titles: Dict[str, int] = {}
    total_active_sec = 0

    for span in data.get("activity_spans", []):
        dur = _seconds(span.get("duration_sec", 0))
        cat = span.get("category") or "Other / System"
        app = span.get("app") or "Unknown"
        title = span.get("window_or_tab") or "Untitled"

        total_active_sec += dur
        categories[cat] = categories.get(cat, 0) + dur
        apps[app] = apps.get(app, 0) + dur
        titles[title] = titles.get(title, 0) + dur

    total_study_sec = sum(
        _seconds(sess.get("duration_sec", 0))
        for sess in data.get("study_sessions", [])
    )
    total_moonbot_sec = sum(
        _seconds(sess.get("duration_sec", 0))
        for sess in data.get("app_sessions", [])
    )

    data["summary"] = {
        "total_study_sec": total_study_sec,
        "total_active_sec": total_active_sec,
        "total_moonbot_sec": total_moonbot_sec,
        "categories": categories,
        "apps": apps,
        "titles": titles
    }


def append_activity_span(span_data: Dict[str, Any], date_str: Optional[str] = None) -> None:
    """Append a completed foreground activity span to the daily log."""
    with _db_lock:
        if not date_str:
            date_str = date.today().isoformat()
        daily = get_daily_log(date_str)
        daily["activity_spans"].append(span_data)
        save_daily_log(daily, date_str)


def append_study_session(session_data: Dict[str, Any], date_str: Optional[str] = None) -> None:
    """Append a study timer session to the daily log."""
    with _db_lock:
        if not date_str:
            date_str = date.today().isoformat()
        daily = get_daily_log(date_str)
        daily["study_sessions"].append(session_data)
        save_daily_log(daily, date_str)


def append_daily_event(event_type: str, title: str, details: str = "", date_str: Optional[str] = None) -> None:
    """Log an alert, pop quiz, reminder, or emergency reset event."""
    with _db_lock:
        if not date_str:
            date_str = date.today().isoformat()
        daily = get_daily_log(date_str)
        daily["events"].append({
            "id": f"evt-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "title": title,
            "details": details
        })
        save_daily_log(daily, date_str)


def start_app_session(date_str: Optional[str] = None) -> str:
    """Mark the moment MoonBot was opened. Returns the session id used to close it."""
    with _db_lock:
        if not date_str:
            date_str = date.today().isoformat()
        daily = get_daily_log(date_str)
        session_id = f"app-{uuid.uuid4().hex[:8]}"
        daily.setdefault("app_sessions", []).append({
            "session_id": session_id,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "duration_sec": 0
        })
        save_daily_log(daily, date_str)
        return session_id


def end_app_session(session_id: str, date_str: Optional[str] = None) -> bool:
    """Close a MoonBot usage session and record its duration in seconds."""
    with _db_lock:
        now = datetime.now()
        # Also search yesterday's log for sessions that crossed midnight.
        candidates = [date_str] if date_str else [
            now.date().isoformat(),
            (now.date() - timedelta(days=1)).isoformat()
        ]
        for candidate in candidates:
            daily = get_daily_log(candidate)
            for sess in daily.get("app_sessions", []):
                if sess.get("session_id") == session_id:
                    start = datetime.fromisoformat(sess["start_time"])
                    sess["end_time"] = now.isoformat()
                    sess["duration_sec"] = max(0, int((now - start).total_seconds()))
                    save_daily_log(daily, candidate)
                    return True
        return False


# -------------------------------------------------------------------------
# Schedule Engine (Exams, Tests, Orientations, Pop Quizzes, Reminders, Alarms)
# -------------------------------------------------------------------------

def _default_schedule() -> Dict[str, Any]:
    # Provide starter academic events for a 3rd-year CSE student
    now = datetime.now()
    tomorrow_10am = now.replace(hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "items": [
            {
                "id": "sch-seed-1",
                "title": "Computer Networks Midterm",
                "course": "CSE 312",
                "type": "exam",
                "datetime": tomorrow_10am,
                "priority": "high",
                "notes": "TCP/IP, Congestion Control, Subnetting. Room 402.",
                "completed": False,
                "created_at": now.isoformat()
            },
            {
                "id": "sch-seed-2",
                "title": "OS Memory Management Pop Quiz",
                "course": "CSE 304",
                "type": "pop_quiz",
                "datetime": now.strftime("%Y-%m-%dT23:59:59"),
                "priority": "medium",
                "notes": "Virtual Memory, Paging, Page Fault Handling.",
                "completed": False,
                "created_at": now.isoformat()
            },
            {
                "id": "sch-seed-3",
                "title": "Capstone Project Orientation",
                "course": "CSE 399",
                "type": "orientation",
                "datetime": now.strftime("%Y-%m-%dT15:30:00"),
                "priority": "medium",
                "notes": "Lab 3, Review SRS & System Architecture with Advisor.",
                "completed": False,
                "created_at": now.isoformat()
            }
        ]
    }


def get_schedule() -> Dict[str, Any]:
    with _db_lock:
        config.ensure_data_directories()
        return _safe_read_json(config.SCHEDULE_FILE, _default_schedule)


def save_schedule(data: Dict[str, Any]) -> None:
    with _db_lock:
        _atomic_write_json(config.SCHEDULE_FILE, data)


def add_schedule_item(
    title: str,
    course: str = "",
    item_type: str = "exam",
    item_datetime: str = "",
    priority: str = "medium",
    notes: str = ""
) -> Dict[str, Any]:
    """Add a new schedule item (exam, test, orientation, pop quiz, reminder, alarm)."""
    with _db_lock:
        sched = get_schedule()
        new_item = {
            "id": f"sch-{uuid.uuid4().hex[:8]}",
            "title": title.strip(),
            "course": course.strip(),
            "type": item_type.lower(),
            "datetime": item_datetime or datetime.now().isoformat(),
            "priority": priority.lower(),
            "notes": notes.strip(),
            "completed": False,
            "created_at": datetime.now().isoformat()
        }
        sched.setdefault("items", []).append(new_item)
        save_schedule(sched)
        return new_item


def toggle_schedule_item_completed(item_id: str) -> bool:
    with _db_lock:
        sched = get_schedule()
        for item in sched.get("items", []):
            if item.get("id") == item_id:
                item["completed"] = not item.get("completed", False)
                save_schedule(sched)
                return item["completed"]
        return False


def delete_schedule_item(item_id: str) -> bool:
    with _db_lock:
        sched = get_schedule()
        items = sched.get("items", [])
        new_items = [it for it in items if it.get("id") != item_id]
        if len(new_items) != len(items):
            sched["items"] = new_items
            save_schedule(sched)
            return True
        return False


# -------------------------------------------------------------------------
# Memory Engine (Saved Concepts, Quick Notes, Flashcards & Search History)
# -------------------------------------------------------------------------

def _default_memory() -> Dict[str, Any]:
    now = datetime.now().isoformat()
    return {
        "saved_concepts": [
            {
                "id": "mem-seed-1",
                "title": "Chemiosmotic Coupling & Proton-Motive Force",
                "course_or_topic": "Bioenergetics / Biophysics",
                "query": "Explain Chemiosmotic Hypothesis and ATP Synthase Proton Gradient",
                "explanation": "The chemiosmotic hypothesis describes how electrochemical proton gradients across the inner mitochondrial membrane drive ATP synthesis via ATP synthase (F0-F1 rotor complex).",
                "formula": "Δp = Δψ - (2.303 RT / F) ΔpH",
                "reference_links": [
                  {"title": "Wikipedia - Chemiosmosis", "url": "https://en.wikipedia.org/wiki/Chemiosmosis"},
                  {"title": "NCBI Bookshelf - Bioenergetics", "url": "https://www.ncbi.nlm.nih.gov/books/NBK21154/"}
                ],
                "quiz": {
                  "question": "What happens to ATP synthesis if the inner membrane becomes permeable to protons?",
                  "options": [
                    "ATP synthesis accelerates exponentially",
                    "Proton gradient dissipates as heat; ATP synthesis halts",
                    "ATP synthase reverses direction and pumps protons back",
                    "Membrane potential increases"
                  ],
                  "correct_index": 1,
                  "explanation": "Uncouplers like DNP collapse the proton gradient, converting potential energy into heat."
                },
                "created_at": now
            }
        ],
        "quick_notes": [
            {
                "id": "note-seed-1",
                "title": "Amdahl's Law Formula",
                "content": "Speedup = 1 / ((1 - P) + (P / S)), where P is parallel fraction and S is speedup of parallel part.",
                "tags": ["CSE312", "Hardware", "Formulas"],
                "created_at": now
            }
        ],
        "history": []
    }


def get_memory() -> Dict[str, Any]:
    with _db_lock:
        config.ensure_data_directories()
        return _safe_read_json(config.MEMORY_FILE, _default_memory)


def save_memory(data: Dict[str, Any]) -> None:
    with _db_lock:
        _atomic_write_json(config.MEMORY_FILE, data)


def add_saved_concept(
    title: str,
    explanation: str,
    query: str = "",
    course_or_topic: str = "General",
    formula: str = "",
    reference_links: Optional[List[Dict[str, str]]] = None,
    quiz: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Store an AI concept explanation into Memory Vault."""
    with _db_lock:
        mem = get_memory()
        item = {
            "id": f"mem-{uuid.uuid4().hex[:8]}",
            "title": title.strip() or "Untitled Concept",
            "course_or_topic": course_or_topic.strip(),
            "query": query.strip(),
            "explanation": explanation.strip(),
            "formula": formula.strip(),
            "reference_links": reference_links or [],
            "quiz": quiz or {},
            "created_at": datetime.now().isoformat()
        }
        mem.setdefault("saved_concepts", []).insert(0, item)
        save_memory(mem)
        return item


def add_quick_note(title: str, content: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """Store a quick note into Memory Vault."""
    with _db_lock:
        mem = get_memory()
        note = {
            "id": f"note-{uuid.uuid4().hex[:8]}",
            "title": title.strip() or "Quick Note",
            "content": content.strip(),
            "tags": tags or [],
            "created_at": datetime.now().isoformat()
        }
        mem.setdefault("quick_notes", []).insert(0, note)
        save_memory(mem)
        return note


def add_history_entry(query: str, mode: str, source: str = "local", result: str = "") -> Dict[str, Any]:
    """Record every lookup/quiz in the memory vault history (most recent first)."""
    with _db_lock:
        mem = get_memory()
        entry = {
            "id": f"hist-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "query": query.strip()[:2000],
            "mode": mode,
            "source": source,
            "result": result.strip()[:4000]
        }
        mem.setdefault("history", []).insert(0, entry)
        mem["history"] = mem["history"][:200]  # bounded local history
        save_memory(mem)
        return entry


def delete_memory_item(section: str, item_id: str) -> bool:
    """Delete an item from saved_concepts or quick_notes."""
    with _db_lock:
        mem = get_memory()
        items = mem.get(section, [])
        new_items = [it for it in items if it.get("id") != item_id]
        if len(new_items) != len(items):
            mem[section] = new_items
            save_memory(mem)
            return True
        return False


# -------------------------------------------------------------------------
# Aggregation & Analytics Helpers
# -------------------------------------------------------------------------

def get_daily_aggregates(date_str: Optional[str] = None) -> Dict[str, Any]:
    """Return recalculated summaries grouped by app, category and window/tab title."""
    daily = get_daily_log(date_str)
    _recalculate_daily_summary(daily)
    return daily["summary"]


def aggregate_by_app(date_str: Optional[str] = None) -> Dict[str, int]:
    """Seconds spent in each foreground application."""
    return dict(get_daily_aggregates(date_str).get("apps", {}))


def aggregate_by_category(date_str: Optional[str] = None) -> Dict[str, int]:
    """Seconds spent in each classified activity category."""
    return dict(get_daily_aggregates(date_str).get("categories", {}))


def aggregate_by_title(date_str: Optional[str] = None) -> Dict[str, int]:
    """Seconds spent per active window / PDF / slides / browser tab title."""
    return dict(get_daily_aggregates(date_str).get("titles", {}))


def get_today_analytics() -> Dict[str, Any]:
    """Compile aggregated stats for the dashboard and charts."""
    daily = get_daily_log()
    summary = get_daily_aggregates(daily.get("date"))
    categories = summary.get("categories", {})
    apps = summary.get("apps", {})
    titles = summary.get("titles", {})
    study_sessions = daily.get("study_sessions", [])

    top_app = "None"
    top_app_sec = 0
    for app_name, sec in sorted(apps.items(), key=lambda kv: kv[1], reverse=True):
        top_app, top_app_sec = app_name, sec
        break

    top_title = "None"
    top_title_sec = 0
    for title, sec in sorted(titles.items(), key=lambda kv: kv[1], reverse=True):
        top_title, top_title_sec = title, sec
        break

    return {
        "date": daily.get("date", date.today().isoformat()),
        "total_study_sec": summary.get("total_study_sec", 0),
        "total_active_sec": summary.get("total_active_sec", 0),
        "total_moonbot_sec": summary.get("total_moonbot_sec", 0),
        "session_count": len(study_sessions),
        "top_app": top_app,
        "top_app_sec": top_app_sec,
        "top_title": top_title,
        "top_title_sec": top_title_sec,
        "categories": categories,
        "apps": apps,
        "titles": titles,
        "recent_sessions": study_sessions[-5:],
        "events": daily.get("events", [])[-10:]
    }


def _fill_hourly_from_records(hourly: Dict[int, int], records: List[Dict[str, Any]]) -> Dict[int, int]:
    for record in records:
        try:
            start = datetime.fromisoformat(record.get("start_time", ""))
        except (ValueError, TypeError):
            continue
        hourly[start.hour] = hourly.get(start.hour, 0) + _seconds(record.get("duration_sec", 0))
    return hourly


def get_hourly_study_distribution(date_str: Optional[str] = None) -> Dict[int, int]:
    """Study seconds per hour (0-23) from focus sessions and study activity spans."""
    daily = get_daily_log(date_str)
    hourly = {h: 0 for h in range(24)}
    study_spans = [
        span for span in daily.get("activity_spans", [])
        if "study" in str(span.get("category", "")).lower()
        or "research" in str(span.get("category", "")).lower()
    ]
    _fill_hourly_from_records(hourly, study_spans)
    _fill_hourly_from_records(hourly, daily.get("study_sessions", []))
    return hourly


def get_hourly_activity_distribution(date_str: Optional[str] = None) -> Dict[int, int]:
    """Total tracked foreground activity seconds per hour (0-23)."""
    hourly = {h: 0 for h in range(24)}
    return _fill_hourly_from_records(hourly, get_daily_log(date_str).get("activity_spans", []))
