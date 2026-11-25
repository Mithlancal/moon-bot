"""
ui/study_panel.py — Full Study Dashboard for MoonBot.
Tabs:
1. Study Dashboard
2. Ask & Learn (questions, quizzes, memos and translations)
3. Focus Pomodoro
4. Academic Schedule
5. Memory Vault
6. Analytics
"""

import os
import tkinter as tk
from datetime import datetime
from typing import Any, Callable, Dict, Optional
import webbrowser

import customtkinter as ctk
from PIL import Image

import config
from core import gemini_service, json_db, web_context
from core.reader_assistant import ReaderAssistant
from core.scheduler import StudyTimer
from ui import ui_dispatch
from ui.charts import DailyChartsFrame

COLORS = config.THEME_COLORS


class StudyPanel(ctk.CTkToplevel):
    """
    Main study window with daily overview, Ask & Learn, and focus tools.
    """

    def __init__(
        self,
        study_timer: StudyTimer,
        reader_assistant: ReaderAssistant,
        master: Optional[Any] = None,
        academic_scheduler: Optional[Any] = None
    ):
        super().__init__(master)
        self.timer = study_timer
        self.reader = reader_assistant
        self.scheduler = academic_scheduler

        self.title("MoonBot — Study Dashboard")
        self.geometry("1180x760")
        # Keep enough room for the full header at every Windows scale factor.
        self.minsize(1100, 700)
        self.configure(fg_color=COLORS["surface"])

        # State tracking
        self._quiz_state: Optional[Dict[str, Any]] = None
        self._soundscape_active = False
        self._disposed = False
        self._context: Dict[str, str] = {}
        self._live_context_text = ""
        self._duration_applied = False
        self._duration_change_callback: Optional[Callable[[int, int], None]] = None
        self._query_request_id = 0
        self._query_watchdog_id: Optional[str] = None
        self._pending_query: Optional[tuple] = None

        # Build UI layout
        self._setup_header()
        self._setup_tabs()

        # Connect timer tick callback to update the pomodoro tab if open
        self.timer.add_tick_callback(self._on_timer_tick)

        # Handle window close gracefully (hide instead of terminate)
        self.protocol("WM_DELETE_WINDOW", self.hide_panel)
        ui_dispatch.on_shutdown(self.dispose)

    def dispose(self) -> None:
        """Release chart/Matplotlib resources on the main thread before Tk teardown."""
        if self._disposed:
            return
        self._disposed = True
        self._query_request_id += 1
        self._pending_query = None
        ident, self._query_watchdog_id = self._query_watchdog_id, None
        if ident:
            ui_dispatch.cancel_after(ident)
        charts = getattr(self, "charts_frame", None)
        if charts is not None:
            try:
                charts.dispose()
            except Exception:
                pass
        self._quiz_state = None

    def set_academic_scheduler(self, scheduler: Any) -> None:
        self.scheduler = scheduler

    def set_duration_change_callback(self, callback: Callable[[int, int], None]) -> None:
        """Notify the floating orb when the user changes the sprint length here."""
        self._duration_change_callback = callback

    def sync_duration_inputs(self, work_minutes: int, break_minutes: int) -> None:
        """Mirror a duration chosen in the orb without firing callbacks."""
        try:
            work = max(1, int(work_minutes))
            rest = max(1, int(break_minutes))
            self.focus_minutes_entry.delete(0, "end")
            self.focus_minutes_entry.insert(0, str(work))
            self.break_minutes_entry.delete(0, "end")
            self.break_minutes_entry.insert(0, str(rest))
            self.custom_duration_lbl.configure(
                text=f"Your sprint · {work}m focus / {rest}m break"
            )
        except Exception:
            pass

    def set_live_context(self, context: dict) -> None:
        """Attach the active PDF/site context to queries and both dashboard badges."""
        self._context = dict(context or {})
        self._live_context_text = web_context.site_summary(self._context)
        for label in (self.context_chip_lbl, self.dash_active_context_lbl):
            try:
                label.configure(text=f"Currently viewing: {self._live_context_text}")
            except Exception:
                pass

    def current_context_text(self) -> str:
        return web_context.context_for_prompt(self._context)

    def show_panel(self) -> None:
        try:
            self.refresh_live_data()
        except Exception:
            pass
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide_panel(self) -> None:
        self.withdraw()

    def refresh_live_data(self) -> None:
        """Reload all JSON-backed views when the panel is reopened."""
        self.sync_duration_inputs(self.timer.work_minutes, self.timer.break_minutes)
        self._refresh_dashboard_metrics()
        self._refresh_schedule_list()
        self._refresh_memory_tab()
        self._refresh_alarm_status()
        if hasattr(self, "charts_frame"):
            self.charts_frame.refresh_data()

    # -------------------------------------------------------------------------
    # Header Section
    # -------------------------------------------------------------------------
    def _setup_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLORS["surface_sidebar"], height=56, corner_radius=0)
        header.pack(fill="x", side="top")

        # Grid keeps the right-hand controls fixed while the title area flexes.
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        brand_frame = ctk.CTkFrame(header, fg_color="transparent")
        brand_frame.grid(row=0, column=0, sticky="w", padx=(16, 8), pady=8)

        if config.LOGO_PATH.exists():
            try:
                pil_img = Image.open(config.LOGO_PATH).resize((28, 28), Image.Resampling.LANCZOS)
                self.logo_ctk = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(28, 28))
                logo_lbl = ctk.CTkLabel(brand_frame, image=self.logo_ctk, text="")
                logo_lbl.pack(side="left", padx=(0, 8))
            except Exception:
                pass

        title_lbl = ctk.CTkLabel(
            brand_frame,
            text="MoonBot",
            font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        title_lbl.pack(side="left")

        sub_lbl = ctk.CTkLabel(
            brand_frame,
            text="3rd Year CSE Study Companion",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color=COLORS["text_muted"]
        )
        sub_lbl.pack(side="left", padx=(8, 0))

        right_frame = ctk.CTkFrame(header, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="e", padx=(8, 16), pady=8)

        self.soundscape_btn = ctk.CTkButton(
            right_frame,
            text="🎧 Binaural 40Hz: Off",
            width=172,
            height=30,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self._toggle_soundscape
        )
        self.soundscape_btn.pack(side="left", padx=6)

        pin_btn = ctk.CTkButton(
            right_frame,
            text="📌 Pinned",
            width=92,
            height=30,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self._toggle_topmost
        )
        pin_btn.pack(side="left", padx=6)

    def _toggle_topmost(self) -> None:
        current = self.attributes("-topmost")
        self.attributes("-topmost", not current)

    def _toggle_soundscape(self) -> None:
        self._soundscape_active = not self._soundscape_active
        if self._soundscape_active:
            self.soundscape_btn.configure(
                text="🎧 Binaural 40Hz: On",
                fg_color=COLORS["primary"]
            )
        else:
            self.soundscape_btn.configure(
                text="🎧 Binaural 40Hz: Off",
                fg_color=COLORS["surface_card"]
            )

    # -------------------------------------------------------------------------
    # Tab View Architecture
    # -------------------------------------------------------------------------
    def _setup_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=COLORS["surface"],
            segmented_button_fg_color=COLORS["surface_sidebar"],
            segmented_button_selected_color=COLORS["primary"],
            segmented_button_selected_hover_color=COLORS["primary_hover"],
            segmented_button_unselected_color=COLORS["surface_sidebar"],
            segmented_button_unselected_hover_color=COLORS["surface_card_hover"],
            corner_radius=12
        )
        self.tabview.pack(fill="both", expand=True, padx=16, pady=12)

        # Create Tabs
        self.tab_dashboard = self.tabview.add("📊 Study Dashboard")
        self.tab_reader = self.tabview.add("✨ Ask & Learn")
        self.tab_timer = self.tabview.add("⏳ Focus Pomodoro")
        self.tab_schedule = self.tabview.add("📅 Academic Schedule")
        self.tab_memory = self.tabview.add("🧠 Memory Vault")
        self.tab_analytics = self.tabview.add("📈 Analytics & Trends")

        # Initialize tab contents
        self._build_dashboard_tab()
        self._build_reader_tab()
        self._build_timer_tab()
        self._build_schedule_tab()
        self._build_memory_tab()
        self._build_analytics_tab()

    # -------------------------------------------------------------------------
    # TAB 1: Study Dashboard
    # -------------------------------------------------------------------------
    def _build_dashboard_tab(self) -> None:
        container = ctk.CTkScrollableFrame(self.tab_dashboard, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Metric Tiles Row
        stats_row = ctk.CTkFrame(container, fg_color="transparent")
        stats_row.pack(fill="x", pady=(0, 16))

        # Tile 1: Focus Today
        t1 = ctk.CTkFrame(stats_row, fg_color=COLORS["surface_card"], corner_radius=12)
        t1.pack(side="left", fill="both", expand=True, padx=(0, 8), ipady=8)
        ctk.CTkLabel(t1, text="⏱ FOCUS TODAY", font=ctk.CTkFont(family="Inter", size=11, weight="bold"), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16, pady=(12, 2))
        self.dash_focus_lbl = ctk.CTkLabel(t1, text="2h 45m", font=ctk.CTkFont(family="Inter", size=24, weight="bold"), text_color=COLORS["text_primary"])
        self.dash_focus_lbl.pack(anchor="w", padx=16)
        ctk.CTkLabel(t1, text="+18% vs weekly avg", font=ctk.CTkFont(family="Inter", size=11), text_color=COLORS["success"]).pack(anchor="w", padx=16, pady=(2, 10))

        # Tile 2: Study Sessions Today
        t2 = ctk.CTkFrame(stats_row, fg_color=COLORS["surface_card"], corner_radius=12)
        t2.pack(side="left", fill="both", expand=True, padx=4, ipady=8)
        ctk.CTkLabel(t2, text="🔥 FOCUS SPRINTS", font=ctk.CTkFont(family="Inter", size=11, weight="bold"), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16, pady=(12, 2))
        self.dash_sessions_lbl = ctk.CTkLabel(t2, text="0", font=ctk.CTkFont(family="Inter", size=24, weight="bold"), text_color=COLORS["warning"])
        self.dash_sessions_lbl.pack(anchor="w", padx=16)
        self.dash_sessions_sub_lbl = ctk.CTkLabel(t2, text="from local daily log", font=ctk.CTkFont(family="Inter", size=11), text_color=COLORS["text_muted"])
        self.dash_sessions_sub_lbl.pack(anchor="w", padx=16, pady=(2, 10))

        # Tile 3: Focus Ratio (study + coding vs total tracked time)
        t3 = ctk.CTkFrame(stats_row, fg_color=COLORS["surface_card"], corner_radius=12)
        t3.pack(side="left", fill="both", expand=True, padx=4, ipady=8)
        ctk.CTkLabel(t3, text="💡 FOCUS RATIO", font=ctk.CTkFont(family="Inter", size=11, weight="bold"), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16, pady=(12, 2))
        self.dash_ratio_lbl = ctk.CTkLabel(t3, text="—", font=ctk.CTkFont(family="Inter", size=24, weight="bold"), text_color=COLORS["accent_blue"])
        self.dash_ratio_lbl.pack(anchor="w", padx=16)
        self.dash_ratio_sub_lbl = ctk.CTkLabel(t3, text="productive / tracked time", font=ctk.CTkFont(family="Inter", size=11), text_color=COLORS["text_muted"])
        self.dash_ratio_sub_lbl.pack(anchor="w", padx=16, pady=(2, 10))

        # Tile 4: Top active context
        t4 = ctk.CTkFrame(stats_row, fg_color=COLORS["surface_card"], corner_radius=12)
        t4.pack(side="left", fill="both", expand=True, padx=(8, 0), ipady=8)
        ctk.CTkLabel(t4, text="🌙 TOP CONTEXT", font=ctk.CTkFont(family="Inter", size=11, weight="bold"), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=16, pady=(12, 2))
        self.dash_context_app_lbl = ctk.CTkLabel(t4, text="No data yet", font=ctk.CTkFont(family="Inter", size=16, weight="bold"), text_color=COLORS["secondary"])
        self.dash_context_app_lbl.pack(anchor="w", padx=16)
        self.dash_context_title_lbl = ctk.CTkLabel(t4, text="Start studying to see your top window/tab", font=ctk.CTkFont(family="Inter", size=11), text_color=COLORS["text_muted"])
        self.dash_context_title_lbl.pack(anchor="w", padx=16, pady=(2, 10))

        # Spotlight Banner
        banner = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        banner.pack(fill="x", pady=(0, 16), padx=2)
        self.dash_active_context_lbl = ctk.CTkLabel(
            banner,
            text="Currently viewing: detecting the active window...",
            font=ctk.CTkFont(family="Inter", size=15, weight="bold"),
            text_color=COLORS["primary_light"]
        )
        self.dash_active_context_lbl.pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            banner,
            text="Tip: copy a definition or equation from your PDF, slide, or page, then ask MoonBot in Ask & Learn.",
            font=ctk.CTkFont(family="Inter", size=12),
            text_color=COLORS["text_secondary"],
            wraplength=800
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # Urgent Milestones Preview
        self.milestones_box = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        self.milestones_box.pack(fill="x", pady=(0, 16), padx=2)
        ctk.CTkLabel(
            self.milestones_box,
            text="🚨 Upcoming Academic Milestones",
            font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(anchor="w", padx=16, pady=(14, 8))
        self.milestones_rows = ctk.CTkFrame(self.milestones_box, fg_color="transparent")
        self.milestones_rows.pack(fill="x", padx=8, pady=(0, 8))
        self._render_milestones()
        self._refresh_dashboard_metrics()

    def _render_milestones(self) -> None:
        for widget in self.milestones_rows.winfo_children():
            widget.destroy()

        def item_sort_key(item):
            try:
                return datetime.fromisoformat(item.get("datetime", ""))
            except (ValueError, TypeError):
                return datetime.max

        items = sorted(
            [it for it in json_db.get_schedule().get("items", []) if not it.get("completed", False)],
            key=item_sort_key
        )[:4]

        if not items:
            ctk.CTkLabel(
                self.milestones_rows,
                text="No upcoming milestones. Add an exam, test or pop quiz in the Schedule tab.",
                font=ctk.CTkFont(family="Inter", size=11),
                text_color=COLORS["text_muted"]
            ).pack(anchor="w", padx=8, pady=6)
            return

        for item in items:
            row = ctk.CTkFrame(self.milestones_rows, fg_color=COLORS["surface_sidebar"], corner_radius=8)
            row.pack(fill="x", padx=8, pady=4)

            tag = ctk.CTkLabel(
                row,
                text=f" {item.get('type', 'EXAM').upper()} ",
                font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
                fg_color=COLORS["primary"],
                text_color=COLORS["text_primary"],
                corner_radius=4
            )
            tag.pack(side="left", padx=8, pady=8)

            info = ctk.CTkLabel(
                row,
                text=f"{item.get('course', 'CSE')} — {item.get('title')}",
                font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
                text_color=COLORS["text_primary"]
            )
            info.pack(side="left", padx=8)

            dt_str = item.get("datetime", "")
            ctk.CTkLabel(
                row,
                text=dt_str.replace("T", " ")[:16],
                font=ctk.CTkFont(family="JetBrains Mono", size=11),
                text_color=COLORS["warning"]
            ).pack(side="right", padx=12)

    def _refresh_dashboard_metrics(self) -> None:
        """Populate the dashboard tiles from real aggregated JSON data."""
        analytics = json_db.get_today_analytics()
        study_sec = analytics.get("total_study_sec", 0)
        active_sec = analytics.get("total_active_sec", 0)
        focus_sec = sum(
            seconds for category, seconds in analytics.get("categories", {}).items()
            if "Study" in category or "Development" in category
        )

        self.dash_focus_lbl.configure(text=f"{study_sec // 3600}h {(study_sec % 3600) // 60}m")
        self.dash_sessions_lbl.configure(text=str(analytics.get("session_count", 0)))
        self.dash_ratio_lbl.configure(
            text=f"{int(focus_sec / active_sec * 100)}%" if active_sec else "—"
        )
        self.dash_context_app_lbl.configure(text=analytics.get("top_app", "None"))
        self.dash_context_title_lbl.configure(
            text=(analytics.get("top_title", "None")[:52] or "No data yet")
        )
        if self._live_context_text:
            self.dash_active_context_lbl.configure(
                text=f"Currently viewing: {self._live_context_text}"
            )
        else:
            self.dash_active_context_lbl.configure(
                text=f"Most active today: {analytics.get('top_title', 'None')[:60]}"
            )
        self._render_milestones()

    # -------------------------------------------------------------------------
    # TAB 2: Ask & Learn / Reader Assistant
    # -------------------------------------------------------------------------
    def _build_reader_tab(self) -> None:
        container = ctk.CTkScrollableFrame(self.tab_reader, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Single-line question bar
        input_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        input_card.pack(fill="x", pady=(0, 12))

        lbl_top = ctk.CTkLabel(
            input_card,
            text="Ask about what you're reading",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["accent_blue"]
        )
        lbl_top.pack(anchor="w", padx=16, pady=(12, 2))

        self.context_chip_lbl = ctk.CTkLabel(
            input_card,
            text="Detecting the active page or PDF...",
            font=ctk.CTkFont(family="Inter", size=10),
            text_color=COLORS["secondary"],
            anchor="w"
        )
        self.context_chip_lbl.pack(anchor="w", padx=16, pady=(0, 6))

        query_row = ctk.CTkFrame(input_card, fg_color="transparent")
        query_row.pack(fill="x", padx=16, pady=(0, 8))

        self.query_entry = ctk.CTkEntry(
            query_row,
            placeholder_text="Ask a question, request a quiz, or ask for a translation...",
            font=ctk.CTkFont(family="Inter", size=13),
            fg_color=COLORS["surface_input"],
            border_color=COLORS["border_subtle"],
            text_color=COLORS["text_primary"],
            height=40
        )
        self.query_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.query_entry.bind("<Return>", lambda e: self._on_natural_click())

        # Grab Clipboard button
        grab_btn = ctk.CTkButton(
            query_row,
            text="📋 Grab Clipboard",
            width=130,
            height=40,
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            fg_color=COLORS["secondary"],
            hover_color=COLORS["primary"],
            command=self._grab_clipboard
        )
        grab_btn.pack(side="right")

        # Mode Selector Buttons
        btn_row = ctk.CTkFrame(input_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))

        self.btn_explain = ctk.CTkButton(
            btn_row,
            text="Ask MoonBot",
            width=130,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._on_natural_click
        )
        self.btn_explain.pack(side="left", padx=(0, 6))

        self.btn_explicit_explain = ctk.CTkButton(
            btn_row,
            text="Explain",
            width=82,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_explain_click
        )
        self.btn_explicit_explain.pack(side="left", padx=4)

        self.btn_quiz = ctk.CTkButton(
            btn_row,
            text="🎯 Quiz",
            width=74,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_quiz_click
        )
        self.btn_quiz.pack(side="left", padx=4)

        self.btn_memo = ctk.CTkButton(
            btn_row,
            text="Make Memo",
            width=110,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_memo_click
        )
        self.btn_memo.pack(side="left", padx=4)

        self.btn_translate = ctk.CTkButton(
            btn_row,
            text="🌐 Translate",
            width=96,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_translate_click
        )
        self.btn_translate.pack(side="left", padx=4)

        self.btn_formula = ctk.CTkButton(
            btn_row,
            text="∑ Formula",
            width=82,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_formula_click
        )
        self.btn_formula.pack(side="left", padx=4)

        self.btn_links = ctk.CTkButton(
            btn_row,
            text="Search",
            width=88,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_links_click
        )
        self.btn_links.pack(side="left", padx=4)

        self.language_entry = ctk.CTkEntry(
            btn_row, placeholder_text="Target language", width=110, height=32,
            font=ctk.CTkFont(family="Inter", size=11),
            fg_color=COLORS["surface_input"], border_color=COLORS["border_subtle"]
        )
        self.language_entry.pack(side="left", padx=4)
        try:
            self.language_entry.insert(0, json_db.get_user_settings().get("translation_language", "English"))
        except Exception:
            self.language_entry.insert(0, "English")

        self.save_mem_btn = ctk.CTkButton(
            btn_row,
            text="💾 Save to Vault",
            width=120,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["success"],
            hover_color="#36966B",
            command=self._save_to_memory
        )
        self.save_mem_btn.pack(side="right")

        # Results Display Area
        self.result_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        self.result_card.pack(fill="both", expand=True, pady=6)

        self.result_title = ctk.CTkLabel(
            self.result_card,
            text="Ready for your question",
            font=ctk.CTkFont(family="Inter", size=16, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.result_title.pack(anchor="w", padx=16, pady=(16, 8))

        # Result Text Box
        self.result_text = ctk.CTkTextbox(
            self.result_card,
            height=220,
            font=ctk.CTkFont(family="Inter", size=13),
            fg_color=COLORS["surface_sidebar"],
            text_color=COLORS["text_primary"],
            wrap="word",
            corner_radius=8
        )
        self.result_text.pack(fill="both", expand=True, padx=16, pady=8)
        self.result_text.insert(
            "1.0",
            "Copy a sentence or formula from your PDF, slide, or page and ask a question here.\n\n"
            "MoonBot can explain it, make a short memo, translate it, or write a quick quiz. "
            "Your current window title is used as context; browser URLs and private tabs are never read."
        )

        # Verified Citations Bar
        self.citations_frame = ctk.CTkFrame(self.result_card, fg_color="transparent")
        self.citations_frame.pack(fill="x", padx=16, pady=(8, 16))

        header_row = ctk.CTkFrame(self.citations_frame, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            header_row,
            text="Reference links:",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")
        self.reveal_quiz_btn = ctk.CTkButton(
            header_row,
            text="👁 Show answer",
            width=110,
            height=22,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self._reveal_quiz_answer
        )
        self.reveal_quiz_btn.pack(side="right")
        self.reveal_quiz_btn.pack_forget()

        self.links_box = ctk.CTkFrame(self.citations_frame, fg_color=COLORS["surface_sidebar"], corner_radius=8)
        self.links_box.pack(fill="x")
        self._populate_reference_links([
            {"title": "Wikipedia: Chemiosmosis", "url": "https://en.wikipedia.org/wiki/Chemiosmosis"},
            {"title": "Google Scholar: Bioenergetics", "url": "https://scholar.google.com/scholar?q=Bioenergetics"},
            {"title": "GeeksforGeeks: Computer Science", "url": "https://www.geeksforgeeks.org"}
        ])

    def _grab_clipboard(self) -> None:
        text = self.reader.grab_clipboard_text()
        if text:
            self.query_entry.delete(0, "end")
            self.query_entry.insert(0, text)
            self._on_explain_click()
        else:
            self.result_text.delete("1.0", "end")
            self.result_text.insert("1.0", "⚠️ Clipboard was empty. Copy (Ctrl+C) some text from your study document first!")

    def _panel_ui_ready(self) -> bool:
        """Never write to a dashboard widget that is disposing or destroyed."""
        if self._disposed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _cancel_query_watchdog(self) -> None:
        ident, self._query_watchdog_id = self._query_watchdog_id, None
        if ident:
            ui_dispatch.cancel_after(ident)

    def _run_query(
        self,
        query: str,
        mode: str,
        status: str,
        display,
        target_language: str = ""
    ) -> None:
        if not query:
            return
        # Read all Tk state on the main thread. Touching language_entry inside
        # the worker can raise "main thread is not in main loop" and look like a
        # search crash with no visible output.
        context = self.current_context_text()
        language = self.language_entry.get().strip() if mode == "natural" else ""
        kwargs: Dict[str, Any] = {"context": context}
        if target_language or language:
            kwargs["target_language"] = target_language or language

        self._query_request_id += 1
        request_id = self._query_request_id
        self._cancel_query_watchdog()
        self._pending_query = (query, mode, dict(kwargs))
        self._query_watchdog_id = ui_dispatch.after(
            config.QUERY_WATCHDOG_MS, self._query_timeout, request_id
        )
        self.result_title.configure(text=status)
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", f"Current view: {context[:160]}\nWorking on it...\n")

        def worker():
            try:
                res = self.reader.process_query(query, mode=mode, **kwargs)
                ui_dispatch.submit(self._finish_query_result, display, res, request_id)
            except Exception as exc:
                ui_dispatch.submit(self._finish_query_error, exc, request_id)

        ui_dispatch.run_worker(worker)

    def _query_timeout(self, request_id: int) -> None:
        """Replace 'working' with a clear local answer before the user closes the app."""
        self._query_watchdog_id = None
        if request_id != self._query_request_id or not self._panel_ui_ready():
            return
        query, mode, kwargs = self._pending_query or ("", "explain", {})
        self._pending_query = None
        self._query_request_id += 1
        result = gemini_service.offline_answer(
            query,
            mode=mode,
            target_language=kwargs.get("target_language", ""),
            context=kwargs.get("context", ""),
            reason="That answer took too long; using your text for now",
        )
        display = self._display_quiz if mode == "quiz" else self._display_explanation
        self._finish_query_result(display, result, self._query_request_id)

    def _finish_query_result(self, display, data: Dict[str, Any], request_id: int) -> None:
        if request_id != self._query_request_id or not self._panel_ui_ready():
            return
        self._cancel_query_watchdog()
        self._pending_query = None
        try:
            display(data)
        except tk.TclError:
            pass

    def _finish_query_error(self, exc: Exception, request_id: int) -> None:
        if request_id != self._query_request_id or not self._panel_ui_ready():
            return
        self._cancel_query_watchdog()
        self._pending_query = None
        self._show_query_error(exc)

    def _on_natural_click(self) -> None:
        """Interpret the user's sentence, then explain / quiz / translate / memo automatically."""
        self._run_query(
            self.query_entry.get().strip(), "natural",
            "Working on your question...", self._display_explanation
        )

    def _on_memo_click(self) -> None:
        self._run_query(
            self.query_entry.get().strip(), "memo",
            "Writing your memo...", self._display_explanation
        )

    def _on_translate_click(self) -> None:
        query = self.query_entry.get().strip()
        if not query:
            return
        language = self.language_entry.get().strip() or "English"
        try:
            json_db.update_user_settings(translation_language=language)
        except Exception:
            pass
        self._run_query(
            query, "translate", f"🌐 Translating to {language}...",
            self._display_explanation, target_language=language
        )

    def _on_explain_click(self) -> None:
        self._run_query(
            self.query_entry.get().strip(), "explain",
            "Explaining this topic...", self._display_explanation
        )

    def _show_query_error(self, exc: Exception) -> None:
        if not self._panel_ui_ready():
            return
        detail = str(exc).strip().splitlines()[0][:140] if exc else ""
        message = "Couldn't finish that request right now. Try again or rephrase it."
        if detail:
            message += f"\n\n{detail}"
        try:
            self.result_title.configure(text="That request didn't finish")
            self.result_text.delete("1.0", "end")
            self.result_text.insert("1.0", message)
        except tk.TclError:
            pass

    def _on_quiz_click(self) -> None:
        self._run_query(
            self.query_entry.get().strip(), "quiz",
            "Writing a quick quiz...", self._display_quiz
        )

    def _on_links_click(self) -> None:
        self._run_query(
            self.query_entry.get().strip(), "links",
            "Finding reference links...", self._display_explanation
        )

    def _on_formula_click(self) -> None:
        query = self.query_entry.get().strip()
        if not query:
            return
        formula_query = f"Derive and explain variables in formula: {query}"
        self.query_entry.delete(0, "end")
        self.query_entry.insert(0, formula_query)
        self._on_explain_click()

    def _display_explanation(self, data: Dict[str, Any]) -> None:
        title = data.get("title", "Concept Explanation")
        expl = data.get("explanation", "")
        takeaways = data.get("takeaways", [])
        formula = data.get("formula", "")
        source = data.get("source", "gemini")
        intent = data.get("intent", "")
        source_label = {
            "gemini": "live answer",
            "offline_fallback": "local answer",
            "local": "local answer",
        }.get(str(source), str(source))

        self.result_title.configure(text=f"📌 {title} · {source_label}")
        self.result_text.delete("1.0", "end")

        out = []
        if formula:
            out.append(f"FORMULA: {formula}\n")

        if "cues" in data and "notes" in data:
            out.append(f"TOPIC: {data.get('topic', '')}")
            out.append(f"\nCUES / ACTIVE RECALL:\n{data.get('cues', '')}")
            out.append(f"\nNOTES:\n{data.get('notes', '')}")
            out.append(f"\nSUMMARY:\n{data.get('summary', '')}")
        elif "translation" in data:
            out.append(f"TRANSLATION ({data.get('language', '')}):\n{data.get('translation', '')}")
            out.append(f"\nMEANING:\n{expl}")
        else:
            out.append(expl)

        note = str(data.get("note") or "").strip()
        if note:
            out.append(f"\n{note}")

        if takeaways:
            out.append("\nKey points:")
            for t in takeaways:
                out.append(f"• {t}")

        local_matches = data.get("local_matches", [])
        if local_matches:
            out.append("\nLOCAL VAULT MATCHES:")
            for match in local_matches[:6]:
                label = match.get("title") or match.get("query") or "Note"
                out.append(f"• [{match.get('_section', 'vault')}] {str(label)[:90]}")

        self.result_text.insert("1.0", "\n".join(out))
        self._populate_reference_links(data.get("reference_links", []))
        self.reveal_quiz_btn.pack_forget()
        if intent == "memo":
            self.save_mem_btn.configure(text="💾 Save Memo")

    def _display_quiz(self, data: Dict[str, Any]) -> None:
        self._quiz_state = data
        q = data.get("question", "Pop Quiz")
        opts = data.get("options", [])
        exp = data.get("explanation", "")
        note = str(data.get("note") or "").strip()

        self.result_title.configure(text="🎯 Quick quiz")
        self.result_text.delete("1.0", "end")

        out = [f"QUESTION:\n{q}\n\nOPTIONS:"]
        for idx, opt in enumerate(opts):
            out.append(f" [{chr(65+idx)}] {opt}")

        if note:
            out.append(f"\n{note}")
        out.append("\nThink it through, then click 'Show answer' to check yourself.")
        self.result_text.insert("1.0", "\n".join(out))
        self.reveal_quiz_btn.pack(side="right")
        self._populate_reference_links(data.get("reference_links", []))

    def _reveal_quiz_answer(self) -> None:
        if not self._quiz_state:
            return
        correct = int(self._quiz_state.get("correct_index", 0))
        options = self._quiz_state.get("options", [])
        answer = options[correct] if 0 <= correct < len(options) else "—"
        self.result_text.insert("end", f"\n\nANSWER: [{chr(65 + correct)}] {answer}")
        explanation = self._quiz_state.get("explanation", "")
        if explanation:
            self.result_text.insert("end", f"\nWHY: {explanation}")
        self.reveal_quiz_btn.pack_forget()

    def _populate_reference_links(self, links: list) -> None:
        for widget in self.links_box.winfo_children():
            widget.destroy()

        if not links:
            ctk.CTkLabel(self.links_box, text="No links available.", font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack(anchor="w", padx=8, pady=4)
            return

        for link in links:
            title = link.get("title", "Link")
            url = link.get("url", "#")
            btn = ctk.CTkButton(
                self.links_box,
                text=f"🔗 {title}",
                font=ctk.CTkFont(family="Inter", size=11, underline=True),
                fg_color="transparent",
                hover_color=COLORS["surface_card_hover"],
                text_color=COLORS["accent_blue"],
                anchor="w",
                height=24,
                command=lambda u=url: webbrowser.open(u)
            )
            btn.pack(fill="x", padx=8, pady=2)

    def _restore_save_button(self) -> None:
        try:
            self.save_mem_btn.configure(text="💾 Save to Vault")
        except Exception:
            pass

    def _save_to_memory(self) -> None:
        saved = self.reader.save_last_result_to_memory(course_or_topic="Active Study")
        if saved:
            self.save_mem_btn.configure(text="✅ Saved to Vault!")
            ui_dispatch.after(2000, self._restore_save_button)
            self._refresh_memory_tab()
        else:
            self.save_mem_btn.configure(text="Nothing to save yet")
            ui_dispatch.after(2000, self._restore_save_button)

    # -------------------------------------------------------------------------
    # TAB 3: Focus Pomodoro & Emergency Reset
    # -------------------------------------------------------------------------
    def _build_timer_tab(self) -> None:
        container = ctk.CTkFrame(self.tab_timer, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        # Objective Header Card
        obj_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        obj_card.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            obj_card,
            text="CURRENT STUDY OBJECTIVE:",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self.objective_entry = ctk.CTkEntry(
            obj_card,
            placeholder_text="e.g. Derive Navier-Stokes Equation (Problem Set 3)",
            font=ctk.CTkFont(family="Inter", size=13),
            fg_color=COLORS["surface_input"],
            border_color=COLORS["border_subtle"],
            height=38
        )
        try:
            objective = json_db.get_user_settings().get(
                "last_objective", "Deep Work: Computer Systems & Architecture"
            )
        except Exception:
            objective = "Deep Work: Computer Systems & Architecture"
        self.objective_entry.insert(0, objective)
        self.objective_entry.pack(fill="x", padx=16, pady=(0, 12))

        # One-shot alarm / reminder form
        alarm_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        alarm_card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            alarm_card,
            text="⏰ ALARMS & REMINDERS",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["accent_blue"]
        ).pack(anchor="w", padx=16, pady=(10, 4))
        alarm_row = ctk.CTkFrame(alarm_card, fg_color="transparent")
        alarm_row.pack(fill="x", padx=16, pady=(0, 6))
        self.alarm_minutes_entry = ctk.CTkEntry(
            alarm_row, placeholder_text="Minutes", width=90, height=32
        )
        self.alarm_minutes_entry.insert(0, "20")
        self.alarm_minutes_entry.pack(side="left", padx=(0, 8))
        self.alarm_message_entry = ctk.CTkEntry(
            alarm_row, placeholder_text="Reminder message (e.g. Stretch + hydrate)", height=32
        )
        self.alarm_message_entry.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(
            alarm_row,
            text="+ Set Alarm",
            width=110,
            height=32,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._on_set_alarm
        ).pack(side="right", padx=(8, 0))
        self.alarm_status_lbl = ctk.CTkLabel(
            alarm_card,
            text="No pending alarms.",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color=COLORS["text_muted"]
        )
        self.alarm_status_lbl.pack(anchor="w", padx=16, pady=(0, 10))

        # Main Clock Center Card
        clock_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=16)
        clock_card.pack(fill="both", expand=True, pady=(0, 16))

        self.timer_mode_lbl = ctk.CTkLabel(
            clock_card,
            text="● DEEP FOCUS SPRINT",
            font=ctk.CTkFont(family="JetBrains Mono", size=12, weight="bold"),
            text_color=COLORS["primary_light"]
        )
        self.timer_mode_lbl.pack(pady=(24, 8))

        _remaining = max(0, int(self.timer.remaining_seconds))
        self.timer_clock_lbl = ctk.CTkLabel(
            clock_card,
            text=f"{_remaining // 60:02d}:{_remaining % 60:02d}",
            font=ctk.CTkFont(family="JetBrains Mono", size=68, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.timer_clock_lbl.pack(pady=8)

        # Preset interval selector pills
        presets_frame = ctk.CTkFrame(clock_card, fg_color="transparent")
        presets_frame.pack(pady=8)

        ctk.CTkButton(
            presets_frame, text="Classic (25/5)", width=110, height=30,
            fg_color=COLORS["surface_sidebar"], hover_color=COLORS["surface_card_hover"],
            font=ctk.CTkFont(size=11),
            command=lambda: self._set_timer_preset(25, 5)
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            presets_frame, text="Deep Work (45/10)", width=120, height=30,
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            font=ctk.CTkFont(size=11),
            command=lambda: self._set_timer_preset(45, 10)
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            presets_frame, text="Ultradian (90/20)", width=120, height=30,
            fg_color=COLORS["surface_sidebar"], hover_color=COLORS["surface_card_hover"],
            font=ctk.CTkFont(size=11),
            command=lambda: self._set_timer_preset(90, 20)
        ).pack(side="left", padx=6)

        # The user defines the first sprint; presets are only shortcuts.
        custom_row = ctk.CTkFrame(clock_card, fg_color="transparent")
        custom_row.pack(fill="x", padx=24, pady=(0, 4))
        ctk.CTkLabel(
            custom_row, text="Your timer:", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=(0, 8))
        self.focus_minutes_entry = ctk.CTkEntry(
            custom_row, width=48, height=28, justify="center",
            font=ctk.CTkFont(family="JetBrains Mono", size=11),
            fg_color=COLORS["surface_input"], border_color=COLORS["border_subtle"]
        )
        self.break_minutes_entry = ctk.CTkEntry(
            custom_row, width=48, height=28, justify="center",
            font=ctk.CTkFont(family="JetBrains Mono", size=11),
            fg_color=COLORS["surface_input"], border_color=COLORS["border_subtle"]
        )
        self.focus_minutes_entry.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(custom_row, text="focus /", font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_muted"]).pack(side="left")
        self.break_minutes_entry.pack(side="left", padx=6)
        ctk.CTkLabel(custom_row, text="break min", font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_muted"]).pack(side="left")
        ctk.CTkButton(
            custom_row, text="Apply", width=56, height=28, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            command=self._apply_custom_duration
        ).pack(side="left", padx=8)
        self.custom_duration_lbl = ctk.CTkLabel(
            clock_card, text="", font=ctk.CTkFont(size=10), text_color=COLORS["text_muted"]
        )
        self.custom_duration_lbl.pack(pady=(0, 2))
        try:
            saved = json_db.get_user_settings()
            self.focus_minutes_entry.insert(0, str(saved.get("focus_minutes", self.timer.work_minutes)))
            self.break_minutes_entry.insert(0, str(saved.get("break_minutes", self.timer.break_minutes)))
            self.custom_duration_lbl.configure(
                text=f"Your sprint · {self.timer.work_minutes}m focus / {self.timer.break_minutes}m break"
            )
        except Exception:
            self.focus_minutes_entry.insert(0, str(self.timer.work_minutes))
            self.break_minutes_entry.insert(0, str(self.timer.break_minutes))

        # Timer Controls Row
        controls_frame = ctk.CTkFrame(clock_card, fg_color="transparent")
        controls_frame.pack(pady=16)

        self.start_pause_btn = ctk.CTkButton(
            controls_frame,
            text="▶ Start Sprint",
            width=140,
            height=40,
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._toggle_timer
        )
        self.start_pause_btn.pack(side="left", padx=8)

        self.reset_btn = ctk.CTkButton(
            controls_frame,
            text="↺ Reset",
            width=90,
            height=40,
            font=ctk.CTkFont(family="Inter", size=13),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._reset_timer
        )
        self.reset_btn.pack(side="left", padx=8)

        # EMERGENCY FOCUS RESET BUTTON
        emergency_btn = ctk.CTkButton(
            controls_frame,
            text="🚨 Emergency Reset",
            width=160,
            height=40,
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            fg_color=COLORS["error"],
            hover_color="#D13B3B",
            command=self._trigger_emergency_reset
        )
        emergency_btn.pack(side="left", padx=8)

        # Distraction silencer banner
        self.silencer_lbl = ctk.CTkLabel(
            clock_card,
            text="🟢 Distraction Silencer Active — Background window tracking and session logging engaged.",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color=COLORS["success"]
        )
        self.silencer_lbl.pack(pady=(8, 20))

    def _commit_duration(self, work_min: int, break_min: int) -> None:
        self.timer.set_duration(work_min, break_min)
        self.sync_duration_inputs(work_min, break_min)
        try:
            json_db.update_user_settings(focus_minutes=work_min, break_minutes=break_min)
        except Exception:
            pass
        if self._duration_change_callback:
            try:
                self._duration_change_callback(work_min, break_min)
            except Exception:
                pass
        self.custom_duration_lbl.configure(
            text=f"Your sprint · {work_min}m focus / {break_min}m break"
            + (" (applies at next reset)" if self.timer.state != StudyTimer.STATE_STOPPED else "")
        )

    def _set_timer_preset(self, work_min: int, break_min: int) -> None:
        self._commit_duration(work_min, break_min)

    def _apply_custom_duration(self) -> None:
        try:
            work = max(1, min(600, int(float(self.focus_minutes_entry.get().strip()))))
        except (TypeError, ValueError):
            work = self.timer.work_minutes
        try:
            rest = max(1, min(180, int(float(self.break_minutes_entry.get().strip()))))
        except (TypeError, ValueError):
            rest = self.timer.break_minutes
        self._commit_duration(work, rest)

    def _on_set_alarm(self) -> None:
        if not self.scheduler:
            self.alarm_status_lbl.configure(text="Scheduler unavailable.", text_color=COLORS["error"])
            return
        try:
            minutes = float(self.alarm_minutes_entry.get().strip())
        except ValueError:
            self.alarm_status_lbl.configure(text="Enter minutes as a number.", text_color=COLORS["error"])
            return
        message = self.alarm_message_entry.get().strip() or "Study check-in"
        self.scheduler.add_alarm(minutes * 60, message, "User-defined break/reminder alarm")
        json_db.append_daily_event(
            event_type="alarm_set",
            title=f"Alarm set: {message}",
            details=f"Due in {minutes:g} minutes."
        )
        self.alarm_message_entry.delete(0, "end")
        self._refresh_alarm_status()

    def _refresh_alarm_status(self) -> None:
        if not self.scheduler:
            return
        pending = self.scheduler.list_alarms()
        if not pending:
            self.alarm_status_lbl.configure(text="No pending alarms.", text_color=COLORS["text_muted"])
            return
        earliest = min(pending, key=lambda a: a.get("target_time", ""))
        self.alarm_status_lbl.configure(
            text=f"{len(pending)} pending — next: {earliest.get('title')} at "
                 f"{earliest.get('target_time', '').replace('T', ' ')[:16]}",
            text_color=COLORS["warning"]
        )

    def _toggle_timer(self) -> None:
        obj = self.objective_entry.get().strip()
        self.timer.set_objective(obj)
        try:
            json_db.update_user_settings(last_objective=obj)
        except Exception:
            pass

        if self.timer.state == StudyTimer.STATE_RUNNING:
            self.timer.pause()
            self.start_pause_btn.configure(text="▶ Resume Sprint", fg_color=COLORS["primary"])
        else:
            self._apply_custom_duration()
            self.timer.start()
            self.start_pause_btn.configure(text="⏸ Pause Sprint", fg_color=COLORS["warning"])

    def _reset_timer(self) -> None:
        self.timer.reset()
        self.start_pause_btn.configure(text="▶ Start Sprint", fg_color=COLORS["primary"])

    def _trigger_emergency_reset(self) -> None:
        msg = self.timer.emergency_reset()
        self.start_pause_btn.configure(text="▶ Start Cooldown", fg_color=COLORS["primary"])
        self.silencer_lbl.configure(text=f"⚠️ {msg}", text_color=COLORS["error"])
        notifier = getattr(self.master, "show_notification", None)
        if notifier:
            notifier("Emergency focus reset", msg, level="warning")

    def _on_timer_tick(self, remaining_sec: int, total_sec: int, mode: str, state: str) -> None:
        mins = remaining_sec // 60
        secs = remaining_sec % 60
        clock_str = f"{mins:02d}:{secs:02d}"

        # UI updates are queued to the single main-thread dispatcher.
        ui_dispatch.submit(self._update_timer_labels, clock_str, mode, state)

    def _update_timer_labels(self, clock_str: str, mode: str, state: str) -> None:
        try:
            self.timer_clock_lbl.configure(text=clock_str)
            mode_text = "● DEEP FOCUS SPRINT" if mode == "work" else "● RECHARGE BREAK"
            mode_color = COLORS["primary_light"] if mode == "work" else COLORS["warning"]
            self.timer_mode_lbl.configure(text=mode_text, text_color=mode_color)

            if state == StudyTimer.STATE_RUNNING:
                self.start_pause_btn.configure(text="⏸ Pause", fg_color=COLORS["warning"])
            else:
                self.start_pause_btn.configure(text="▶ Start", fg_color=COLORS["primary"])
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # TAB 4: Academic Schedule (Exams, Tests, Orientations, Pop Quizzes)
    # -------------------------------------------------------------------------
    def _build_schedule_tab(self) -> None:
        container = ctk.CTkScrollableFrame(self.tab_schedule, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Add New Item Form
        form_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        form_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            form_card,
            text="ADD ACADEMIC MILESTONE (EXAM, TEST, ORIENTATION, POP QUIZ)",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["accent_blue"]
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row1 = ctk.CTkFrame(form_card, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=4)

        self.sch_title_entry = ctk.CTkEntry(row1, placeholder_text="Milestone Title (e.g. Operating Systems Final Exam)", height=34)
        self.sch_title_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.sch_course_entry = ctk.CTkEntry(row1, placeholder_text="Course (e.g. CSE 304)", width=140, height=34)
        self.sch_course_entry.pack(side="left", padx=4)

        self.sch_type_opt = ctk.CTkOptionMenu(
            row1,
            values=["exam", "test", "orientation", "pop_quiz", "reminder", "alarm"],
            width=130,
            height=34,
            fg_color=COLORS["primary"],
            button_color=COLORS["primary_hover"]
        )
        self.sch_type_opt.pack(side="left", padx=4)

        row2 = ctk.CTkFrame(form_card, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(4, 12))

        now_str = datetime.now().strftime("%Y-%m-%dT14:00:00")
        self.sch_datetime_entry = ctk.CTkEntry(row2, placeholder_text="YYYY-MM-DDTHH:MM", width=180, height=34)
        self.sch_datetime_entry.insert(0, now_str)
        self.sch_datetime_entry.pack(side="left", padx=(0, 8))

        self.sch_notes_entry = ctk.CTkEntry(row2, placeholder_text="Location / Chapters / Crib sheet notes", height=34)
        self.sch_notes_entry.pack(side="left", fill="x", expand=True, padx=4)

        add_btn = ctk.CTkButton(
            row2,
            text="+ Add Event",
            width=110,
            height=34,
            font=ctk.CTkFont(weight="bold"),
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._on_add_schedule_item
        )
        add_btn.pack(side="right", padx=(8, 0))

        # Schedule Items Container
        self.sch_list_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.sch_list_frame.pack(fill="both", expand=True)
        self._refresh_schedule_list()

    def _on_add_schedule_item(self) -> None:
        title = self.sch_title_entry.get().strip()
        if not title:
            return
        course = self.sch_course_entry.get().strip()
        itype = self.sch_type_opt.get().strip()
        dt_str = self.sch_datetime_entry.get().strip()
        notes = self.sch_notes_entry.get().strip()

        json_db.add_schedule_item(
            title=title,
            course=course,
            item_type=itype,
            item_datetime=dt_str,
            priority="high" if itype in ["exam", "test"] else "medium",
            notes=notes
        )

        self.sch_title_entry.delete(0, "end")
        self.sch_notes_entry.delete(0, "end")
        self._refresh_schedule_list()
        self._render_milestones()

    def _refresh_schedule_list(self) -> None:
        for widget in self.sch_list_frame.winfo_children():
            widget.destroy()

        sched = json_db.get_schedule()
        items = sorted(
            sched.get("items", []),
            key=lambda it: it.get("datetime", "")
        )

        if not items:
            ctk.CTkLabel(
                self.sch_list_frame,
                text="No upcoming milestones. Add your exams or tests above!",
                text_color=COLORS["text_muted"]
            ).pack(pady=20)
            return

        for it in items:
            card = ctk.CTkFrame(self.sch_list_frame, fg_color=COLORS["surface_card"], corner_radius=10)
            card.pack(fill="x", pady=6)

            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True, padx=14, pady=10)

            # Header row
            hdr = ctk.CTkFrame(left, fg_color="transparent")
            hdr.pack(fill="x")

            tag_color = COLORS["primary"] if it.get("type") == "exam" else COLORS["warning"]
            ctk.CTkLabel(
                hdr,
                text=f" {it.get('type', 'EVENT').upper()} ",
                font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
                fg_color=tag_color,
                corner_radius=4
            ).pack(side="left", padx=(0, 8))

            ctk.CTkLabel(
                hdr,
                text=f"{it.get('course', 'CSE')} — {it.get('title')}",
                font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
                text_color=COLORS["text_primary"]
            ).pack(side="left")

            # Notes
            if it.get("notes"):
                ctk.CTkLabel(
                    left,
                    text=it.get("notes"),
                    font=ctk.CTkFont(family="Inter", size=11),
                    text_color=COLORS["text_secondary"]
                ).pack(anchor="w", pady=(4, 0))

            # Right controls
            right = ctk.CTkFrame(card, fg_color="transparent")
            right.pack(side="right", padx=14, pady=10)

            ctk.CTkLabel(
                right,
                text=it.get("datetime", "").replace("T", " ")[:16],
                font=ctk.CTkFont(family="JetBrains Mono", size=11),
                text_color=COLORS["accent_blue"]
            ).pack(side="left", padx=10)

            done_btn = ctk.CTkButton(
                right,
                text="✓" if not it.get("completed") else "↺",
                width=28,
                height=28,
                fg_color=COLORS["success"] if it.get("completed") else COLORS["surface_sidebar"],
                hover_color=COLORS["primary"],
                command=lambda item_id=it.get("id"): self._toggle_schedule_item(item_id)
            )
            done_btn.pack(side="right", padx=(0, 6))

            del_btn = ctk.CTkButton(
                right,
                text="✕",
                width=28,
                height=28,
                fg_color=COLORS["surface_sidebar"],
                hover_color=COLORS["error"],
                command=lambda item_id=it.get("id"): self._delete_schedule_item(item_id)
            )
            del_btn.pack(side="right")

    def _toggle_schedule_item(self, item_id: str) -> None:
        json_db.toggle_schedule_item_completed(item_id)
        self._refresh_schedule_list()
        self._render_milestones()

    def _delete_schedule_item(self, item_id: str) -> None:
        json_db.delete_schedule_item(item_id)
        self._refresh_schedule_list()
        self._render_milestones()

    # -------------------------------------------------------------------------
    # TAB 5: Memory Vault & Notes
    # -------------------------------------------------------------------------
    def _build_memory_tab(self) -> None:
        container = ctk.CTkScrollableFrame(self.tab_memory, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Structured Cornell memo editor.
        note_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        note_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            note_card,
            text="BETTER MEMO · CORNELL STYLE · ACTIVE CONTEXT ATTACHED",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["accent_blue"]
        ).pack(anchor="w", padx=16, pady=(12, 4))

        nrow = ctk.CTkFrame(note_card, fg_color="transparent")
        nrow.pack(fill="x", padx=16, pady=(0, 6))
        self.note_title_entry = ctk.CTkEntry(
            nrow, placeholder_text="Memo title", width=230, height=34
        )
        self.note_title_entry.pack(side="left", padx=(0, 8))
        self.note_topic_entry = ctk.CTkEntry(
            nrow, placeholder_text="Course / topic (blank = active PDF or site)", width=240, height=34
        )
        self.note_topic_entry.pack(side="left", padx=4)
        ctk.CTkButton(
            nrow, text="+ Save Memo", width=110, height=34,
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            command=self._on_add_quick_note
        ).pack(side="right", padx=(8, 0))

        cues_row = ctk.CTkFrame(note_card, fg_color="transparent")
        cues_row.pack(fill="x", padx=16, pady=(0, 6))
        self.note_cues_entry = ctk.CTkEntry(
            cues_row, placeholder_text="Cues / recall questions / tags (comma separated)",
            width=340, height=30
        )
        self.note_cues_entry.pack(side="left", padx=(0, 8))
        self.note_summary_entry = ctk.CTkEntry(
            cues_row, placeholder_text="One-line exam-ready summary", height=30
        )
        self.note_summary_entry.pack(side="left", fill="x", expand=True)

        self.note_content_text = ctk.CTkTextbox(
            note_card, height=76, font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_input"], border_color=COLORS["border_subtle"],
            border_width=1
        )
        self.note_content_text.pack(fill="x", padx=16, pady=(0, 12))

        search_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        search_card.pack(fill="x", pady=(0, 12))
        search_row = ctk.CTkFrame(search_card, fg_color="transparent")
        search_row.pack(fill="x", padx=16, pady=10)
        ctk.CTkLabel(
            search_row, text="🔎", font=ctk.CTkFont(size=15)
        ).pack(side="left", padx=(0, 6))
        self.memo_search_entry = ctk.CTkEntry(
            search_row,
            placeholder_text="Search naturally across memos, notes, concepts, history and active sites...",
            height=32
        )
        self.memo_search_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.memo_search_entry.bind("<Return>", lambda e: self._refresh_memory_tab())
        ctk.CTkButton(
            search_row, text="Search", width=70, height=32,
            fg_color=COLORS["secondary"], hover_color=COLORS["primary"],
            command=self._refresh_memory_tab
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            search_row, text="Clear", width=58, height=32,
            fg_color=COLORS["surface_sidebar"], hover_color=COLORS["surface_card_hover"],
            command=self._clear_memo_search
        ).pack(side="left")

        self.mem_list_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.mem_list_frame.pack(fill="both", expand=True)
        self._refresh_memory_tab()

    def _clear_memo_search(self) -> None:
        self.memo_search_entry.delete(0, "end")
        self._refresh_memory_tab()

    def _load_into_query(self, text: str) -> None:
        """Send a saved note/highlight back to the natural-language query box."""
        if not text:
            return
        self.tabview.set("✨ Ask & Learn")
        self.query_entry.delete(0, "end")
        self.query_entry.insert(0, text[:1200])
        self.query_entry.focus_set()

    def _on_add_quick_note(self) -> None:
        title = self.note_title_entry.get().strip()
        notes = self.note_content_text.get("1.0", "end").strip()
        if not title or not notes:
            return

        context = self.current_context_text()
        topic = self.note_topic_entry.get().strip() or context
        cues = self.note_cues_entry.get().strip()
        tags = [t.strip() for t in cues.split(",") if t.strip()] or ["Manual", "Cornell"]
        json_db.add_memo_note(
            title=title,
            topic=topic,
            cues=cues,
            notes=notes,
            summary=self.note_summary_entry.get().strip(),
            source_text=notes,
            context=context,
            tags=tags
        )
        self.note_title_entry.delete(0, "end")
        self.note_topic_entry.delete(0, "end")
        self.note_cues_entry.delete(0, "end")
        self.note_summary_entry.delete(0, "end")
        self.note_content_text.delete("1.0", "end")
        self._refresh_memory_tab()

    def _refresh_memory_tab(self) -> None:
        for widget in self.mem_list_frame.winfo_children():
            widget.destroy()

        query = ""
        if hasattr(self, "memo_search_entry"):
            query = self.memo_search_entry.get().strip()

        sections = ("memos", "quick_notes", "saved_concepts", "history")
        grouped: Dict[str, list] = {section: [] for section in sections}
        if query:
            for hit in json_db.search_memory(query, limit=80):
                section = hit.get("_section", "")
                if section in grouped:
                    grouped[section].append(hit)
        else:
            mem = json_db.get_memory()
            for section in sections:
                grouped[section] = list(mem.get(section, []))[:12]

        def add_header(text: str) -> None:
            ctk.CTkLabel(
                self.mem_list_frame, text=text,
                font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
                text_color=COLORS["primary_light"]
            ).pack(anchor="w", pady=(10, 3))

        def add_card(section: str, item: Dict[str, Any], title: str, subtitle: str, body: str, load_text: str) -> None:
            card = ctk.CTkFrame(self.mem_list_frame, fg_color=COLORS["surface_card"], corner_radius=10)
            card.pack(fill="x", pady=4)
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(
                head, text=title[:100],
                font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
                text_color=COLORS["text_primary"], anchor="w"
            ).pack(side="left", fill="x", expand=True)
            if load_text:
                ctk.CTkButton(
                    head, text="↗ Ask", width=48, height=24, corner_radius=6,
                    fg_color=COLORS["surface_sidebar"], hover_color=COLORS["surface_card_hover"],
                    font=ctk.CTkFont(size=10),
                    command=lambda value=load_text: self._load_into_query(value)
                ).pack(side="left", padx=4)
            ctk.CTkButton(
                head, text="✕", width=24, height=24, corner_radius=6,
                fg_color="transparent", hover_color=COLORS["error"],
                font=ctk.CTkFont(size=10),
                command=lambda sid=section, iid=item.get("id"): self._delete_mem_item(sid, iid)
            ).pack(side="right")
            if subtitle:
                ctk.CTkLabel(
                    card, text=subtitle[:220], font=ctk.CTkFont(size=10),
                    text_color=COLORS["accent_blue"], anchor="w", justify="left",
                    wraplength=760
                ).pack(anchor="w", padx=12)
            if body:
                ctk.CTkLabel(
                    card, text=body[:1600], font=ctk.CTkFont(size=11),
                    text_color=COLORS["text_secondary"], anchor="w", justify="left",
                    wraplength=770
                ).pack(anchor="w", padx=12, pady=(2, 8))

        if query and not any(grouped.values()):
            ctk.CTkLabel(
                self.mem_list_frame,
                text="No vault matches yet. Try a topic, formula, PDF name or site.",
                font=ctk.CTkFont(size=12), text_color=COLORS["text_muted"]
            ).pack(anchor="w", pady=12)
            return

        if grouped["memos"]:
            add_header("📝 Cornell Memos (saved highlights & manual notes)")
            for item in grouped["memos"]:
                subtitle = " · ".join(filter(None, (
                    f"Topic: {item.get('topic', '')}" if item.get("topic") else "",
                    f"Cues: {str(item.get('cues', ''))[:90]}" if item.get("cues") else "",
                    f"Context: {str(item.get('context', ''))[:70]}" if item.get("context") else "",
                )))
                body = "\n".join(filter(None, (
                    f"NOTES\n{item.get('notes', '')}" if item.get("notes") else "",
                    f"SUMMARY\n{item.get('summary', '')}" if item.get("summary") else "",
                )))
                add_card(
                    "memos", item, item.get("title", "Study Memo"), subtitle, body,
                    item.get("source_text") or item.get("notes", "")
                )

        if grouped["quick_notes"]:
            add_header("⚡ Quick Crib Notes & Formulas")
            for item in grouped["quick_notes"]:
                tags = item.get("tags", [])
                subtitle = ", ".join(tags) if isinstance(tags, list) else str(tags)
                add_card(
                    "quick_notes", item, item.get("title", "Quick Note"), subtitle,
                    item.get("content", ""), item.get("content", "")
                )

        if grouped["saved_concepts"]:
            add_header("🧠 Synthesized Concept Vault & Quizzes")
            for item in grouped["saved_concepts"]:
                subtitle = f"Topic: {item.get('course_or_topic', 'General')}"
                body = "\n".join(filter(None, (
                    f"Formula: {item.get('formula')}" if item.get("formula") else "",
                    str(item.get("explanation", "")),
                )))
                add_card(
                    "saved_concepts", item, item.get("title", "Concept"), subtitle, body,
                    item.get("query") or item.get("explanation", "")
                )

        if grouped["history"]:
            add_header("🕘 Recent Natural Queries & Highlights")
            for item in grouped["history"]:
                stamp = str(item.get("timestamp", "")).replace("T", " ")[:16]
                subtitle = f"{item.get('mode', 'query')} · {item.get('source', 'local')} · {stamp}"
                add_card(
                    "history", item, str(item.get("query", "Query"))[:90], subtitle,
                    str(item.get("result", ""))[:500], item.get("query", "")
                )

    def _delete_mem_item(self, section: str, item_id: str) -> None:
        """Delete any vault item (memo, note, concept or history entry)."""
        json_db.delete_memory_item(section, item_id)
        self._refresh_memory_tab()

    # -------------------------------------------------------------------------
    # TAB 6: Daily Analytics & Trends
    # -------------------------------------------------------------------------
    def _build_analytics_tab(self) -> None:
        self.charts_frame = DailyChartsFrame(self.tab_analytics)
        self.charts_frame.pack(fill="both", expand=True, padx=8, pady=8)
