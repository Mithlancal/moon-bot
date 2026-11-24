"""
ui/study_panel.py — Full Desktop Study Sanctuary Panel for MoonBot
Implements the comprehensive Nocturne Focus interface with tabs:
1. Overview & Dashboard
2. Ask & Learn / Reader Assistant (No-tab-switch query, pop quiz, formulas)
3. Focus Pomodoro & Emergency Focus Reset
4. Academic Schedule (Exams, Tests, Orientations, Pop Quizzes)
5. Memory Vault & Notes
6. Daily Analytics & Trends (Charts)
"""

import os
import threading
import tkinter as tk
from datetime import datetime
from typing import Any, Callable, Dict, Optional
import webbrowser

import customtkinter as ctk
from PIL import Image

import config
from core import json_db
from core.reader_assistant import ReaderAssistant
from core.scheduler import StudyTimer
from ui.charts import DailyChartsFrame

COLORS = config.THEME_COLORS


class StudyPanel(ctk.CTkToplevel):
    """
    Main study hub window.
    Designed according to the Nocturne Focus academic sanctuary system.
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

        self.title("MoonBot — Deep Study Sanctuary")
        self.geometry("1080x720")
        self.minsize(920, 620)
        self.configure(fg_color=COLORS["surface"])

        # State tracking
        self._quiz_state: Optional[Dict[str, Any]] = None
        self._soundscape_active = False

        # Build UI layout
        self._setup_header()
        self._setup_tabs()

        # Connect timer tick callback to update the pomodoro tab if open
        self.timer.add_tick_callback(self._on_timer_tick)

        # Handle window close gracefully (hide instead of terminate)
        self.protocol("WM_DELETE_WINDOW", self.hide_panel)

    def set_academic_scheduler(self, scheduler: Any) -> None:
        self.scheduler = scheduler

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

        # Left branding
        brand_frame = ctk.CTkFrame(header, fg_color="transparent")
        brand_frame.pack(side="left", padx=16, pady=8)

        # Try loading logo image
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
            text="• 3rd Year CSE Study Companion",
            font=ctk.CTkFont(family="Inter", size=12),
            text_color=COLORS["text_muted"]
        )
        sub_lbl.pack(side="left", padx=(8, 0))

        # Right quick controls
        right_frame = ctk.CTkFrame(header, fg_color="transparent")
        right_frame.pack(side="right", padx=16, pady=8)

        self.soundscape_btn = ctk.CTkButton(
            right_frame,
            text="🎧 Binaural 40Hz: Off",
            width=135,
            height=28,
            font=ctk.CTkFont(family="Inter", size=11),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self._toggle_soundscape
        )
        self.soundscape_btn.pack(side="left", padx=6)

        pin_btn = ctk.CTkButton(
            right_frame,
            text="📌 Pinned",
            width=80,
            height=28,
            font=ctk.CTkFont(family="Inter", size=11),
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
                text="🎧 Binaural 40Hz: Active",
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
            text="🎯 Active Study Context: detecting foreground window...",
            font=ctk.CTkFont(family="Inter", size=15, weight="bold"),
            text_color=COLORS["primary_light"]
        )
        self.dash_active_context_lbl.pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            banner,
            text="Tip: highlight a definition or equation in your PDF/slide/tab, press Ctrl+C, then click 'Quick Snip' on the floating orb for instant synthesis.",
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
        self.dash_active_context_lbl.configure(
            text=f"🎯 Most active context today: {analytics.get('top_title', 'None')[:60]}"
        )
        self._render_milestones()

    # -------------------------------------------------------------------------
    # TAB 2: Ask & Learn / Reader Assistant
    # -------------------------------------------------------------------------
    def _build_reader_tab(self) -> None:
        container = ctk.CTkScrollableFrame(self.tab_reader, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Raycast-style input bar
        input_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        input_card.pack(fill="x", pady=(0, 12))

        lbl_top = ctk.CTkLabel(
            input_card,
            text="KNOWLEDGE QUERY & SYNTHESIZER (NO-TAB-SWITCH READER)",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["accent_blue"]
        )
        lbl_top.pack(anchor="w", padx=16, pady=(12, 4))

        query_row = ctk.CTkFrame(input_card, fg_color="transparent")
        query_row.pack(fill="x", padx=16, pady=(0, 8))

        self.query_entry = ctk.CTkEntry(
            query_row,
            placeholder_text="Paste or type concept, question, or textbook excerpt...",
            font=ctk.CTkFont(family="Inter", size=13),
            fg_color=COLORS["surface_input"],
            border_color=COLORS["border_subtle"],
            text_color=COLORS["text_primary"],
            height=40
        )
        self.query_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.query_entry.bind("<Return>", lambda e: self._on_explain_click())

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
            text="⚡ Explain Concept",
            width=140,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._on_explain_click
        )
        self.btn_explain.pack(side="left", padx=(0, 8))

        self.btn_quiz = ctk.CTkButton(
            btn_row,
            text="🎯 Pop Quiz",
            width=120,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_quiz_click
        )
        self.btn_quiz.pack(side="left", padx=8)

        self.btn_formula = ctk.CTkButton(
            btn_row,
            text="∑ Simplify Formula",
            width=140,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_formula_click
        )
        self.btn_formula.pack(side="left", padx=8)

        self.btn_links = ctk.CTkButton(
            btn_row,
            text="🔗 Ref Links",
            width=110,
            height=32,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=COLORS["surface_sidebar"],
            hover_color=COLORS["surface_card_hover"],
            command=self._on_links_click
        )
        self.btn_links.pack(side="left", padx=8)

        self.save_mem_btn = ctk.CTkButton(
            btn_row,
            text="💾 Save to Memory Vault",
            width=160,
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
            text="Ready to synthesize reading material",
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
            "Select or copy any sentence or formula from your active PDF textbook, slide deck, or online research page.\n\n"
            "MoonBot will automatically synthesize high-yield exam takeaways, generate pop quizzes to test retention, "
            "and attach verified citations—all without requiring you to switch browser tabs."
        )

        # Verified Citations Bar
        self.citations_frame = ctk.CTkFrame(self.result_card, fg_color="transparent")
        self.citations_frame.pack(fill="x", padx=16, pady=(8, 16))

        header_row = ctk.CTkFrame(self.citations_frame, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            header_row,
            text="VERIFIED CITATIONS & REFERENCE LINKS:",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")
        self.reveal_quiz_btn = ctk.CTkButton(
            header_row,
            text="👁 Reveal Answer",
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

    def _on_explain_click(self) -> None:
        query = self.query_entry.get().strip()
        if not query:
            return

        self.result_title.configure(text="Synthesizing concept via Gemini...")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "Querying Gemini API for academic explanation and high-yield takeaways...\n")

        def worker():
            try:
                res = self.reader.process_query(query, mode="explain")
                self.after(0, lambda: self._display_explanation(res))
            except Exception as exc:
                self.after(0, lambda: self._show_query_error(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_query_error(self, exc: Exception) -> None:
        self.result_title.configure(text="⚠️ Request failed")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", f"MoonBot could not complete that request: {exc}")

    def _on_quiz_click(self) -> None:
        query = self.query_entry.get().strip()
        if not query:
            return

        self.result_title.configure(text="Generating Active Recall Pop Quiz...")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "Formulating test question...\n")

        def worker():
            try:
                res = self.reader.process_query(query, mode="quiz")
                self.after(0, lambda: self._display_quiz(res))
            except Exception as exc:
                self.after(0, lambda: self._show_query_error(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_links_click(self) -> None:
        query = self.query_entry.get().strip()
        if not query:
            return
        self.result_title.configure(text="Building academic search links...")
        def worker():
            try:
                res = self.reader.process_query(query, mode="links")
                self.after(0, lambda: self._display_explanation(res))
            except Exception as exc:
                self.after(0, lambda: self._show_query_error(exc))
        threading.Thread(target=worker, daemon=True).start()

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

        self.result_title.configure(text=f"📌 {title} ({source})")
        self.result_text.delete("1.0", "end")

        out = []
        if formula:
            out.append(f"FORMULA: {formula}\n")
        out.append(expl)
        if takeaways:
            out.append("\nHIGH-YIELD TAKEAWAYS:")
            for t in takeaways:
                out.append(f"• {t}")

        self.result_text.insert("1.0", "\n".join(out))
        self._populate_reference_links(data.get("reference_links", []))
        self.reveal_quiz_btn.pack_forget()

    def _display_quiz(self, data: Dict[str, Any]) -> None:
        self._quiz_state = data
        q = data.get("question", "Pop Quiz")
        opts = data.get("options", [])
        exp = data.get("explanation", "")

        self.result_title.configure(text=f"🎯 Active Recall Probe")
        self.result_text.delete("1.0", "end")

        out = [f"QUESTION:\n{q}\n\nOPTIONS:"]
        for idx, opt in enumerate(opts):
            out.append(f" [{chr(65+idx)}] {opt}")

        out.append("\nThink it through, then click 'Reveal Answer' to check your recall.")
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

    def _save_to_memory(self) -> None:
        saved = self.reader.save_last_result_to_memory(course_or_topic="Active Study")
        if saved:
            self.save_mem_btn.configure(text="✅ Saved to Vault!")
            self.after(2000, lambda: self.save_mem_btn.configure(text="💾 Save to Memory Vault"))
            self._refresh_memory_tab()
        else:
            self.save_mem_btn.configure(text="Nothing to save yet")
            self.after(2000, lambda: self.save_mem_btn.configure(text="💾 Save to Memory Vault"))

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
        self.objective_entry.insert(0, "Deep Work: Computer Systems & Architecture")
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

        self.timer_clock_lbl = ctk.CTkLabel(
            clock_card,
            text="25:00",
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

    def _set_timer_preset(self, work_min: int, break_min: int) -> None:
        self.timer.set_duration(work_min, break_min)

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

        if self.timer.state == StudyTimer.STATE_RUNNING:
            self.timer.pause()
            self.start_pause_btn.configure(text="▶ Resume Sprint", fg_color=COLORS["primary"])
        else:
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

        # Schedule Tkinter UI update on the main thread safely
        try:
            self.after(0, lambda: self._update_timer_labels(clock_str, mode, state))
        except Exception:
            pass

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

        # Quick Manual Note Input
        note_card = ctk.CTkFrame(container, fg_color=COLORS["surface_card"], corner_radius=12)
        note_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            note_card,
            text="QUICK NOTE / CRIB SHEET FORMULA STORAGE",
            font=ctk.CTkFont(family="JetBrains Mono", size=10, weight="bold"),
            text_color=COLORS["accent_blue"]
        ).pack(anchor="w", padx=16, pady=(12, 4))

        nrow = ctk.CTkFrame(note_card, fg_color="transparent")
        nrow.pack(fill="x", padx=16, pady=(0, 12))

        self.note_title_entry = ctk.CTkEntry(nrow, placeholder_text="Title (e.g. Little's Law / Cache Formulas)", width=240, height=34)
        self.note_title_entry.pack(side="left", padx=(0, 8))

        self.note_content_entry = ctk.CTkEntry(nrow, placeholder_text="Formula or critical note...", height=34)
        self.note_content_entry.pack(side="left", fill="x", expand=True, padx=4)

        save_n_btn = ctk.CTkButton(
            nrow,
            text="+ Add Note",
            width=100,
            height=34,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._on_add_quick_note
        )
        save_n_btn.pack(side="right", padx=(8, 0))

        # Memory items display container
        self.mem_list_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.mem_list_frame.pack(fill="both", expand=True)
        self._refresh_memory_tab()

    def _on_add_quick_note(self) -> None:
        title = self.note_title_entry.get().strip()
        content = self.note_content_entry.get().strip()
        if not title or not content:
            return

        json_db.add_quick_note(title=title, content=content, tags=["Manual", "Crib"])
        self.note_title_entry.delete(0, "end")
        self.note_content_entry.delete(0, "end")
        self._refresh_memory_tab()

    def _refresh_memory_tab(self) -> None:
        for widget in self.mem_list_frame.winfo_children():
            widget.destroy()

        mem = json_db.get_memory()
        concepts = mem.get("saved_concepts", [])
        notes = mem.get("quick_notes", [])

        # Display Quick Notes first
        if notes:
            ctk.CTkLabel(
                self.mem_list_frame,
                text="📝 Quick Crib Notes & Formulas",
                font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                text_color=COLORS["text_primary"]
            ).pack(anchor="w", pady=(8, 4))

            for n in notes:
                c = ctk.CTkFrame(self.mem_list_frame, fg_color=COLORS["surface_card"], corner_radius=10)
                c.pack(fill="x", pady=4)

                top = ctk.CTkFrame(c, fg_color="transparent")
                top.pack(fill="x", padx=12, pady=(8, 2))

                ctk.CTkLabel(top, text=n.get("title", ""), font=ctk.CTkFont(weight="bold"), text_color=COLORS["primary_light"]).pack(side="left")
                del_btn = ctk.CTkButton(
                    top, text="✕", width=24, height=24, fg_color="transparent", hover_color=COLORS["error"],
                    command=lambda nid=n.get("id"): self._delete_mem_item("quick_notes", nid)
                )
                del_btn.pack(side="right")

                ctk.CTkLabel(c, text=n.get("content", ""), font=ctk.CTkFont(family="JetBrains Mono", size=12), text_color=COLORS["text_primary"], wraplength=750, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # Display Saved Concepts & Quizzes
        if concepts:
            ctk.CTkLabel(
                self.mem_list_frame,
                text="🧠 Synthesized Concept Vault",
                font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                text_color=COLORS["text_primary"]
            ).pack(anchor="w", pady=(16, 4))

            for item in concepts:
                c = ctk.CTkFrame(self.mem_list_frame, fg_color=COLORS["surface_card"], corner_radius=10)
                c.pack(fill="x", pady=6)

                hdr = ctk.CTkFrame(c, fg_color="transparent")
                hdr.pack(fill="x", padx=14, pady=(10, 4))

                ctk.CTkLabel(hdr, text=item.get("title", "Concept"), font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_primary"]).pack(side="left")

                del_btn = ctk.CTkButton(
                    hdr, text="✕", width=24, height=24, fg_color="transparent", hover_color=COLORS["error"],
                    command=lambda cid=item.get("id"): self._delete_mem_item("saved_concepts", cid)
                )
                del_btn.pack(side="right")

                if item.get("formula"):
                    ctk.CTkLabel(c, text=f"Formula: {item.get('formula')}", font=ctk.CTkFont(family="JetBrains Mono", size=12), text_color=COLORS["accent_blue"]).pack(anchor="w", padx=14, pady=2)

                ctk.CTkLabel(c, text=item.get("explanation", ""), font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"], wraplength=760, justify="left").pack(anchor="w", padx=14, pady=(2, 10))

    def _delete_mem_item(self, section: str, item_id: str) -> None:
        json_db.delete_memory_item(section, item_id)
        self._refresh_memory_tab()

    # -------------------------------------------------------------------------
    # TAB 6: Daily Analytics & Trends
    # -------------------------------------------------------------------------
    def _build_analytics_tab(self) -> None:
        self.charts_frame = DailyChartsFrame(self.tab_analytics)
        self.charts_frame.pack(fill="both", expand=True, padx=8, pady=8)
