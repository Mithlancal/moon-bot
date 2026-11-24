# 🌙 MoonBot — Local-First Floating Desktop Study Companion

> **3rd-Year Computer Science & Engineering Capstone Project**  
> *A high-efficiency, always-on-top academic sanctuary built for continuous reading, deep work, and zero tab-switching on Windows.*

---

## 📖 Overview

When studying dense technical material—such as operating systems textbooks, machine learning lecture slides, research PDFs, or competitive programming problems—students lose focus and cognitive momentum when constantly switching browser tabs to look up definitions, derive formulas, or log study time.

**MoonBot** solves this by living directly on top of your desktop workspace as a sleek, draggable floating HUD. It monitors your academic reading context, grabs highlighted excerpts directly from your clipboard without switching windows, synthesizes concepts using Google's Gemini API, generates active recall pop quizzes, and atomically logs all study activity locally into human-readable JSON files.

---

## ⚡ Key Highlights & Architecture

- **Floating Always-On-Top Companion (`ui/floating_orb.py`)**:
  - Frameless, draggable HUD positioned over PDFs, slides, and code editors.
  - Quick action pills for **Start Study**, **Quick Snip (Clipboard Grab)**, **Pop Quiz**, and **Emergency Focus Reset**.
  - **Compact mode** (`—` button) shrinks the HUD to a clock + emergency button while you study.
  - Non-focus-stealing in-app notification toasts for alarms, due exams/quizzes, timer completion and distraction warnings.
  - Expands with one click into the full **Study Sanctuary Panel**.

- **No-Tab-Switch Reader Assistant (`core/reader_assistant.py` & `core/gemini_service.py`)**:
  - Highlights and extracts text via clipboard without losing your place in your PDF reader.
  - Queries Gemini (using the official `google-genai` SDK) to generate high-yield takeaways, formula explanations, and verified citation links (Wikipedia, Google Scholar, GeeksforGeeks, arXiv).
  - Robust offline mode with local heuristics when offline or without an API key.

- **Background Foreground Window Tracker (`core/activity_tracker.py`)**:
  - Uses Windows Win32 APIs (`pywin32`) and `psutil` to track foreground windows at configurable intervals (~2.0s).
  - Groups consecutive active seconds on the same PDF filename, slide deck, or browser tab into discrete study spans.
  - Classifies activities into *Study / Reading*, *Development & Coding*, *Browser / Research*, *Productivity*, or *Distraction / Entertainment*.

- **Pomodoro Timer, Alarms & Emergency Reset (`core/scheduler.py`)**:
  - Work/Break interval management (Classic 25/5, Deep Work 45/10, Ultradian 90/20), pause/reset, and logged sessions.
  - One-shot **alarms/reminders** set from the Timer tab, plus due-soon alerts for exams, tests, orientations and pop quizzes.
  - **Emergency Focus Reset Button**: instantly halts distraction drift, logs an emergency event, resets the timer, and starts a 3-minute cooldown breather.
  - Throttled distraction warnings (at most once every 5 minutes) are logged and shown as toasts.

- **Local-First JSON Database Engine (`core/json_db.py`)**:
  - **Zero Database Server Required**: All data is stored locally in clean JSON files.
  - **Corruption-Proof Atomic Writes**: Employs `tempfile.NamedTemporaryFile` + `flush` + `os.replace` to prevent corrupted JSON on system interrupts.
  - Stores:
    - `data/daily_logs/YYYY-MM-DD.json` (activity spans by app/category/window-tab title, focus sessions, MoonBot usage sessions, and triggered events).
    - `data/schedule.json` (exams, tests, orientations, pop quizzes, reminders, alarms).
    - `data/memory.json` (saved concepts, quick notes, reference links, quizzes and lookup history).
  - Aggregation helpers answer "time spent per app / category / window or tab title" directly from the daily log.

- **Embedded Nocturne Focus Analytics (`ui/charts.py`)**:
  - Dark-mode Matplotlib **donut chart** (time by category), **hourly time graph** (study minutes per hour), and **top applications** bar graph — all rendered from the local daily JSON log, with honest empty states.

---

## 📂 Repository Structure

```
moon-bot/
├── config.py                 # Central configurations, paths & Nocturne design tokens
├── requirements.txt          # Python package dependencies (incl. pyperclip)
├── .env.example              # Template for Gemini API key & settings
├── .gitignore                # Ignores .venv, cache, and runtime logs
├── main.py                   # Main entry point wiring UI and background services
│
├── core/                     # Backend Logic
│   ├── __init__.py
│   ├── json_db.py            # Local JSON database & atomic write engine
│   ├── activity_tracker.py   # Background foreground window and app tracker
│   ├── scheduler.py          # Study timer, emergency reset, academic scheduler
│   ├── gemini_service.py     # Google Gemini SDK integration & offline fallback
│   └── reader_assistant.py   # Clipboard snip, concept digestion & memory link
│
├── data/                     # Local-First Persistent JSON Storage
│   ├── schedule.json         # Academic milestones, exams, tests, alarms
│   ├── memory.json           # Synthesized concepts, formulas, and crib notes
│   └── daily_logs/           # Auto-created per-day logs (YYYY-MM-DD.json)
│       └── 2026-11-23.json
│
├── ui/                       # Nocturne Focus Design Interface
│   ├── __init__.py
│   ├── floating_orb.py       # Frameless, draggable, always-on-top HUD
│   ├── study_panel.py        # Tabbed study sanctuary dashboard
│   ├── charts.py             # Embedded Matplotlib donut, hourly time graph & bar charts
│   ├── moon-bot-logo.png     # Official MoonBot 3D icon
│   └── DESIGN.md             # Nocturne Focus design system specification
│
└── archive/                  # Archived legacy files
    └── legacy_flask_starter/ # Cleanly archived older starter files
```

---

## 🔒 Privacy & OS Permissions

MoonBot operates under strict transparency:
- It uses public Windows Win32 APIs (`GetForegroundWindow`, `GetWindowText`, `GetWindowThreadProcessId`) to read window titles and process names (e.g., `Bioenergetics_Ch12.pdf - Adobe Acrobat`).
- **No Keystroke Logging**: It does not install keyloggers or hook keyboard inputs.
- **No DOM Scraping**: It does not inject into browser processes or inspect private incognito tabs.
- **Local-First**: All activity logs and notes remain stored locally in `data/` on your computer.
- **Browser Limits**: OS APIs expose window/process titles (PDF names, slide decks, active tab titles) reliably. Full browser URLs or private/incognito content are *not* accessible without a browser extension; MoonBot deliberately does not attempt to read them.

---

## ⚙️ Installation & Setup

### 1. Prerequisites
- **OS**: Windows 10 or 11
- **Python**: 3.10+ (tested on Python 3.11)

### 2. Install Dependencies
Open PowerShell in the project directory:
```powershell
pip install -r requirements.txt
```

### 3. Configure `.env`
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
Open `.env` in any text editor and paste your free Gemini API key:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
ACTIVITY_POLL_INTERVAL=2.0
POMODORO_WORK_MINUTES=25
POMODORO_BREAK_MINUTES=5
```
*(Get your free API key at [Google AI Studio](https://aistudio.google.com/)). If you omit the key, MoonBot seamlessly operates in offline academic digest mode.*

---

## 🚀 Running MoonBot

Start the floating companion from terminal:
```powershell
python main.py
```

1. **Floating HUD**: MoonBot appears in the top-right corner of your desktop, staying on top of your reading material.
2. **Move it Anywhere**: Click and drag the HUD header to position it anywhere on your primary or secondary display.
3. **Start Study**: Click `▶ Start Study` to begin your deep focus session. Click `—` any time to shrink the HUD to a clock + emergency button.
4. **Zero-Tab-Switch Read**: Highlight any sentence or formula in your PDF reader or browser, press `Ctrl+C`, and click `📋 Quick Snip` on the HUD. MoonBot immediately digests the text without switching tabs.
5. **Open Dashboard**: Click `⤢ Dashboard` to view live dashboard metrics, countdown milestones, the Timer/Alarms tab, Academic Schedule, Memory Vault, and screen-time charts.
6. **Set an Alarm**: In `⏳ Focus Pomodoro`, enter minutes and a message, then click `+ Set Alarm`. A toast appears when it is due and the event is logged.
7. **Emergency Pause**: If you find yourself getting distracted or drifting, hit `🚨 Emergency` for an immediate focus intervention and calm cooldown.

All background threads are daemon threads and are stopped cleanly when you close the orb; closing the dashboard only hides it.

---

## 📊 JSON Storage Schema

### 1. `data/daily_logs/YYYY-MM-DD.json`
```json
{
  "date": "2026-11-23",
  "study_sessions": [
    {
      "session_id": "sess-a1b2c3d4",
      "start_time": "2026-11-23T10:00:00",
      "end_time": "2026-11-23T10:45:00",
      "duration_sec": 2700,
      "objective": "Computer Networks Midterm Prep",
      "status": "completed"
    }
  ],
  "activity_spans": [
    {
      "app": "Acrobat.exe",
      "window_or_tab": "Bioenergetics_Ch12.pdf - Adobe Acrobat",
      "category": "Study / Reading",
      "start_time": "2026-11-23T10:05:00",
      "end_time": "2026-11-23T10:35:00",
      "duration_sec": 1800
    }
  ],
  "events": [
    {
      "id": "evt-7f8e9a0b",
      "timestamp": "2026-11-23T10:35:10",
      "event_type": "emergency_reset",
      "title": "Emergency Focus Reset",
      "details": "Sprint interrupted on 'Deep Focus'. Cooldown break initiated."
    }
  ],
  "app_sessions": [
    {
      "session_id": "app-a1b2c3d4",
      "start_time": "2026-11-23T10:00:00",
      "end_time": "2026-11-23T11:00:00",
      "duration_sec": 3600
    }
  ],
  "summary": {
    "total_study_sec": 2700,
    "total_active_sec": 3600,
    "total_moonbot_sec": 3600,
    "categories": {
      "Study / Reading": 2700,
      "Browser / Research": 900
    },
    "apps": {
      "Acrobat.exe": 2700,
      "chrome.exe": 900
    },
    "titles": {
      "Bioenergetics_Ch12.pdf - Adobe Acrobat": 2700,
      "Lecture 7 - Slides - Chrome": 900
    }
  }
}
```

### 2. `data/schedule.json`
```json
{
  "items": [
    {
      "id": "sch-seed-1",
      "title": "Computer Networks Midterm",
      "course": "CSE 312",
      "type": "exam",
      "datetime": "2026-11-24T10:00:00",
      "priority": "high",
      "notes": "TCP/IP, Congestion Control, Subnetting. Room 402.",
      "completed": false
    }
  ]
}
```

### 3. `data/memory.json`
```json
{
  "saved_concepts": [
    {
      "id": "mem-1",
      "title": "Chemiosmotic Coupling & Proton-Motive Force",
      "course_or_topic": "Bioenergetics",
      "query": "Explain Chemiosmotic Hypothesis",
      "explanation": "Electrochemical proton gradients across the inner mitochondrial membrane drive ATP synthesis via ATP synthase...",
      "formula": "Δp = Δψ - (2.303 RT / F) ΔpH",
      "reference_links": [
        {"title": "Wikipedia: Chemiosmosis", "url": "https://en.wikipedia.org/wiki/Chemiosmosis"}
      ]
    }
  ],
  "quick_notes": [
    {
      "id": "note-1",
      "title": "Amdahl's Law Formula",
      "content": "Speedup = 1 / ((1 - P) + (P / S))",
      "tags": ["CSE312", "Hardware"]
    }
  ],
  "history": [
    {
      "id": "hist-1",
      "timestamp": "2026-11-23T10:40:00",
      "query": "Explain Amdahl's Law",
      "mode": "explain",
      "source": "gemini",
      "result": "Speedup is bounded by the serial fraction..."
    }
  ]
}
```

---

## 🎯 Capstone Presentation & Demo Script

When demonstrating MoonBot to professors or evaluators:
1. **Show the HUD Overlay**: Run `python main.py`. Point out how MoonBot floats non-intrusively in the corner over an open PDF or slide deck. Drag it with the mouse, then press `—` to demonstrate compact study mode and `⤢` to restore it.
2. **Demonstrate Zero-Tab-Switch Snip**: Open any PDF or webpage, highlight a technical term, press `Ctrl+C`, and click `📋 Quick Snip` on the orb. Show the instant explanation card, formula extraction, and verified citations without having switched tabs.
3. **Show Active Recall Pop Quiz**: In the Ask & Learn tab, click `🎯 Pop Quiz` to show how MoonBot turns textbook sentences into interactive multiple choice probes for retention.
4. **Demonstrate Focus Timer & Distraction Warnings**: Start a sprint. Open YouTube or another distraction in a browser to show the throttled distraction toast + logged event, then click `🚨 Emergency` on the orb for immediate intervention and the 3-minute breather cooldown.
5. **Demonstrate Alarms & Schedule**: Set a 1-minute alarm in the Timer tab and add a pop quiz in the Academic Schedule tab. Show the toast notification and the corresponding events in the daily JSON log.
6. **Demonstrate Local-First Analytics**: Open the `Analytics & Trends` tab to showcase the category donut, hourly study time graph and top-app bar chart rendered directly from the daily JSON log. Open `data/daily_logs/` in a text editor to prove all data is stored locally in clean, corruption-proof JSON.

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
