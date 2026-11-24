"""
ui/floating_orb.py — Draggable Always-on-Top Floating Desktop Companion
Stays on top of PDFs, PowerPoint slides, and browser windows.
Provides instant timer controls, emergency focus reset, quick clipboard capture,
and seamless one-click expansion into the full StudyPanel.
"""

import logging
import tkinter as tk
from typing import Any, Callable, Optional
import customtkinter as ctk
from PIL import Image

import config
from core.activity_tracker import ActivityTracker
from core.reader_assistant import ReaderAssistant
from core.scheduler import StudyTimer
from ui.study_panel import StudyPanel

logger = logging.getLogger("MoonBot.FloatingOrb")
COLORS = config.THEME_COLORS


class FloatingOrb(ctk.CTk):
    """
    Floating, frameless, always-on-top desktop study companion.
    Draggable by mouse across multi-monitor setups.
    """

    def __init__(
        self,
        study_timer: StudyTimer,
        reader_assistant: ReaderAssistant,
        activity_tracker: ActivityTracker
    ):
        super().__init__()
        self.timer = study_timer
        self.reader = reader_assistant
        self.tracker = activity_tracker

        # Window configuration
        self.title("MoonBot HUD")
        self.overrideredirect(True)       # Frameless
        self.attributes("-topmost", True)  # Always-on-top
        self.configure(fg_color=COLORS["surface_sidebar"])

        # Default size and positioning (top-right of screen)
        screen_w = self.winfo_screenwidth()
        x_pos = max(50, screen_w - 400)
        y_pos = 60
        self.geometry(f"360x180+{x_pos}+{y_pos}")

        # Drag coordinates
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Full Study Panel instance
        self.study_panel: Optional[StudyPanel] = None
        self._shutdown_callback: Optional[Callable[[], None]] = None
        self._shutting_down = False
        self._compact = False
        self._toast_windows = []

        # Build UI layout
        self._setup_ui()

        # Connect callbacks
        self.timer.add_tick_callback(self._on_timer_tick)
        self.tracker.set_activity_changed_callback(self._on_activity_changed)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

    def set_study_panel(self, panel: StudyPanel) -> None:
        self.study_panel = panel

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        """Register main.py's cleanup routine for graceful shutdown."""
        self._shutdown_callback = callback

    def _setup_ui(self) -> None:
        # Outer border frame to simulate fluent acrylic container
        self.main_border = ctk.CTkFrame(
            self,
            fg_color=COLORS["surface_sidebar"],
            border_color=COLORS["border_highlight"],
            border_width=1.5,
            corner_radius=14
        )
        self.main_border.pack(fill="both", expand=True, padx=2, pady=2)

        # Drag bar / Top Header
        self.drag_header = ctk.CTkFrame(self.main_border, fg_color="transparent", height=32)
        self.drag_header.pack(fill="x", padx=10, pady=(8, 2))

        # Make header and border draggable
        self._make_draggable(self.main_border)
        self._make_draggable(self.drag_header)

        # Left brand info
        left_box = ctk.CTkFrame(self.drag_header, fg_color="transparent")
        left_box.pack(side="left")
        self._make_draggable(left_box)

        # Logo glyph
        if config.LOGO_PATH.exists():
            try:
                pil_img = Image.open(config.LOGO_PATH).resize((22, 22), Image.Resampling.LANCZOS)
                self.logo_ctk = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(22, 22))
                logo_lbl = ctk.CTkLabel(left_box, image=self.logo_ctk, text="")
                logo_lbl.pack(side="left", padx=(0, 6))
                self._make_draggable(logo_lbl)
            except Exception:
                pass

        name_lbl = ctk.CTkLabel(
            left_box,
            text="MoonBot",
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        name_lbl.pack(side="left")
        self._make_draggable(name_lbl)

        # Status badge pill
        self.status_pill = ctk.CTkLabel(
            left_box,
            text=" ● IDLE ",
            font=ctk.CTkFont(family="JetBrains Mono", size=9, weight="bold"),
            fg_color=COLORS["surface_card"],
            text_color=COLORS["accent_blue"],
            corner_radius=6
        )
        self.status_pill.pack(side="left", padx=(8, 0))
        self._make_draggable(self.status_pill)

        # Right buttons (Expand panel & Close app)
        btn_box = ctk.CTkFrame(self.drag_header, fg_color="transparent")
        btn_box.pack(side="right")

        self.compact_btn = ctk.CTkButton(
            btn_box,
            text="—",
            width=24,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self.toggle_compact
        )
        self.compact_btn.pack(side="left", padx=(0, 4))

        self.expand_btn = ctk.CTkButton(
            btn_box,
            text="⤢ Dashboard",
            width=80,
            height=24,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self.toggle_study_panel
        )
        self.expand_btn.pack(side="left", padx=(0, 4))

        close_btn = ctk.CTkButton(
            btn_box,
            text="✕",
            width=24,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["error"],
            command=self.quit_app
        )
        close_btn.pack(side="left")

        # Active Document & Window Title snippet
        self.active_context_lbl = ctk.CTkLabel(
            self.main_border,
            text="📄 Detecting reading context...",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.active_context_lbl.pack(fill="x", padx=12, pady=(0, 4))
        self._make_draggable(self.active_context_lbl)

        # Center Section: Timer & Quick Snippet Grab
        center_row = ctk.CTkFrame(self.main_border, fg_color="transparent")
        self.center_row = center_row
        center_row.pack(fill="x", padx=12, pady=2)
        self._make_draggable(center_row)

        self.orb_clock_lbl = ctk.CTkLabel(
            center_row,
            text="25:00",
            font=ctk.CTkFont(family="JetBrains Mono", size=32, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.orb_clock_lbl.pack(side="left", padx=(0, 10))
        self._make_draggable(self.orb_clock_lbl)

        # Quick action pills
        quick_actions = ctk.CTkFrame(center_row, fg_color="transparent")
        quick_actions.pack(side="right", fill="y")

        snip_btn = ctk.CTkButton(
            quick_actions,
            text="📋 Quick Snip",
            width=95,
            height=28,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["secondary"],
            hover_color=COLORS["primary"],
            command=self._quick_snip_from_screen
        )
        snip_btn.pack(side="top", pady=(0, 4))

        quiz_btn = ctk.CTkButton(
            quick_actions,
            text="🎯 Pop Quiz",
            width=95,
            height=28,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self._quick_quiz_from_screen
        )
        quiz_btn.pack(side="top")

        # Bottom Controls Row
        bottom_row = ctk.CTkFrame(self.main_border, fg_color="transparent")
        self.bottom_row = bottom_row
        bottom_row.pack(fill="x", padx=12, pady=(6, 8))

        self.orb_toggle_btn = ctk.CTkButton(
            bottom_row,
            text="▶ Start Study",
            width=110,
            height=30,
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            command=self._toggle_study_timer
        )
        self.orb_toggle_btn.pack(side="left", padx=(0, 6))

        # EMERGENCY FOCUS RESET BUTTON
        self.orb_emergency_btn = ctk.CTkButton(
            bottom_row,
            text="🚨 Emergency",
            width=100,
            height=30,
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            fg_color=COLORS["error"],
            hover_color="#D13B3B",
            command=self._on_emergency_click
        )
        self.orb_emergency_btn.pack(side="left", padx=4)

        reset_btn = ctk.CTkButton(
            bottom_row,
            text="↺ Reset",
            width=65,
            height=30,
            font=ctk.CTkFont(family="Inter", size=11),
            fg_color=COLORS["surface_card"],
            hover_color=COLORS["surface_card_hover"],
            command=self._reset_study_timer
        )
        reset_btn.pack(side="right")

        # Compact mode: only clock + emergency stay visible while studying
        self.compact_row = ctk.CTkFrame(self.main_border, fg_color="transparent")
        self.compact_clock_lbl = ctk.CTkLabel(
            self.compact_row,
            text="25:00",
            font=ctk.CTkFont(family="JetBrains Mono", size=20, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.compact_clock_lbl.pack(side="left", padx=(4, 8))
        self._make_draggable(self.compact_clock_lbl)
        self.compact_emergency_btn = ctk.CTkButton(
            self.compact_row,
            text="🚨 Emergency",
            width=100,
            height=28,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["error"],
            hover_color="#D13B3B",
            command=self._on_emergency_click
        )
        self.compact_emergency_btn.pack(side="left")

    # -------------------------------------------------------------------------
    # Compact mode & Notifications
    # -------------------------------------------------------------------------
    def toggle_compact(self) -> None:
        """Shrink the HUD to a clock + emergency button, or restore the full orb."""
        x, y = self.winfo_x(), self.winfo_y()
        if not self._compact:
            self.active_context_lbl.pack_forget()
            self.center_row.pack_forget()
            self.bottom_row.pack_forget()
            self.compact_row.pack(fill="x", padx=12, pady=(2, 10))
            self.geometry(f"300x92+{x}+{y}")
            self.compact_btn.configure(text="⤢")
            self._compact = True
        else:
            self.compact_row.pack_forget()
            self.active_context_lbl.pack(fill="x", padx=12, pady=(0, 4))
            self.center_row.pack(fill="x", padx=12, pady=2)
            self.bottom_row.pack(fill="x", padx=12, pady=(6, 8))
            self.geometry(f"360x180+{x}+{y}")
            self.compact_btn.configure(text="—")
            self._compact = False

    def show_notification(self, title: str, message: str, level: str = "info") -> None:
        """Show a transient, non-focus-stealing in-app alert on top of the study material."""
        level_colors = {
            "info": COLORS["accent_blue"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"]
        }
        accent = level_colors.get(level, COLORS["accent_blue"])

        def build_toast():
            toast = ctk.CTkToplevel(self)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.configure(fg_color=COLORS["surface_hud"])
            toast.resizable(False, False)

            x = self.winfo_x() + 20
            y = self.winfo_y() + self.winfo_height() + 8
            toast.geometry(f"+{x}+{y}")

            bar = ctk.CTkFrame(toast, fg_color=accent, width=4, corner_radius=0)
            bar.pack(side="left", fill="y")

            body = ctk.CTkFrame(toast, fg_color="transparent")
            body.pack(side="left", fill="both", expand=True, padx=10, pady=8)

            ctk.CTkLabel(
                body, text=title,
                font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
                text_color=accent
            ).pack(anchor="w")
            ctk.CTkLabel(
                body, text=message, wraplength=270, justify="left",
                font=ctk.CTkFont(family="Inter", size=11),
                text_color=COLORS["text_primary"]
            ).pack(anchor="w", pady=(4, 0))

            self._toast_windows.append(toast)
            if len(self._toast_windows) > 3:
                old = self._toast_windows.pop(0)
                try:
                    old.destroy()
                except Exception:
                    pass

            def close_toast():
                if toast in self._toast_windows:
                    self._toast_windows.remove(toast)
                try:
                    toast.destroy()
                except Exception:
                    pass

            toast._moonbot_dismiss_id = toast.after(9000, close_toast)

        self.after(0, build_toast)

    # -------------------------------------------------------------------------
    # Draggable Window Handlers
    # -------------------------------------------------------------------------
    def _make_draggable(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._on_drag)

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_start_x = event.x_root - self.winfo_x()
        self._drag_start_y = event.y_root - self.winfo_y()

    def _on_drag(self, event: tk.Event) -> None:
        new_x = event.x_root - self._drag_start_x
        new_y = event.y_root - self._drag_start_y
        self.geometry(f"+{new_x}+{new_y}")

    # -------------------------------------------------------------------------
    # Controls & Callbacks
    # -------------------------------------------------------------------------
    def toggle_study_panel(self) -> None:
        if self.study_panel:
            if self.study_panel.winfo_viewable():
                self.study_panel.hide_panel()
                self.expand_btn.configure(text="⤢ Dashboard")
            else:
                self.study_panel.show_panel()
                self.expand_btn.configure(text="⤡ Hide")

    def _toggle_study_timer(self) -> None:
        if self.timer.state == StudyTimer.STATE_RUNNING:
            self.timer.pause()
            self.orb_toggle_btn.configure(text="▶ Resume", fg_color=COLORS["primary"])
            self.status_pill.configure(text=" ● PAUSED ", text_color=COLORS["warning"])
        else:
            self.timer.start()
            self.orb_toggle_btn.configure(text="⏸ Pause", fg_color=COLORS["warning"])
            self.status_pill.configure(text=" ● STUDYING ", text_color=COLORS["success"])

    def _reset_study_timer(self) -> None:
        self.timer.reset()
        self.orb_toggle_btn.configure(text="▶ Start Study", fg_color=COLORS["primary"])
        self.status_pill.configure(text=" ● IDLE ", text_color=COLORS["accent_blue"])

    def _on_emergency_click(self) -> None:
        msg = self.timer.emergency_reset()
        self.status_pill.configure(text=" 🚨 RESET ", text_color=COLORS["error"])
        self.orb_toggle_btn.configure(text="▶ Breath (3m)", fg_color=COLORS["primary"])
        self.active_context_lbl.configure(text=f"⚠️ {msg}")
        self.show_notification("Emergency focus reset", msg, level="warning")

    def _quick_snip_from_screen(self) -> None:
        """Grab clipboard and open study panel directly on Ask & Learn tab."""
        if self.study_panel:
            self.study_panel.show_panel()
            self.study_panel.tabview.set("✨ Ask & Learn")
            self.study_panel._grab_clipboard()

    def _quick_quiz_from_screen(self) -> None:
        """Grab clipboard and generate pop quiz."""
        if self.study_panel:
            self.study_panel.show_panel()
            self.study_panel.tabview.set("✨ Ask & Learn")
            text = self.reader.grab_clipboard_text()
            if text:
                self.study_panel.query_entry.delete(0, "end")
                self.study_panel.query_entry.insert(0, text)
                self.study_panel._on_quiz_click()

    def _on_timer_tick(self, remaining_sec: int, total_sec: int, mode: str, state: str) -> None:
        mins = remaining_sec // 60
        secs = remaining_sec % 60
        clock_str = f"{mins:02d}:{secs:02d}"

        try:
            self.after(0, lambda: self._update_orb_timer(clock_str, mode, state))
        except Exception:
            pass  # window already closed

    def _update_orb_timer(self, clock_str: str, mode: str, state: str) -> None:
        try:
            self.orb_clock_lbl.configure(text=clock_str)
            self.compact_clock_lbl.configure(text=clock_str)
            if state == StudyTimer.STATE_RUNNING:
                if mode == "work":
                    self.status_pill.configure(text=" ● STUDYING ", text_color=COLORS["success"])
                else:
                    self.status_pill.configure(text=" ● BREAK ", text_color=COLORS["warning"])
                self.orb_toggle_btn.configure(text="⏸ Pause", fg_color=COLORS["warning"])
            elif state == StudyTimer.STATE_PAUSED:
                self.status_pill.configure(text=" ● PAUSED ", text_color=COLORS["warning"])
                self.orb_toggle_btn.configure(text="▶ Resume", fg_color=COLORS["primary"])
            else:
                self.status_pill.configure(text=" ● IDLE ", text_color=COLORS["accent_blue"])
                self.orb_toggle_btn.configure(text="▶ Start Study", fg_color=COLORS["primary"])
        except Exception:
            pass

    def _on_activity_changed(self, app_name: str, window_title: str, category: str) -> None:
        # Display clean snippet of current reading material
        clean_title = window_title if len(window_title) <= 42 else window_title[:39] + "..."
        icon = "📄" if "Study" in category else ("💻" if "Coding" in category else "🌐")
        display_str = f"{icon} {clean_title}"

        try:
            self.after(0, lambda: self._update_activity_label(display_str))
        except Exception:
            pass  # window already closed

    def _update_activity_label(self, text: str) -> None:
        try:
            self.active_context_lbl.configure(text=text)
        except Exception:
            pass

    def quit_app(self) -> None:
        """Gracefully shut down background threads and close application."""
        if self._shutting_down:
            return
        self._shutting_down = True
        try:
            for toast in list(self._toast_windows):
                try:
                    toast.after_cancel(toast._moonbot_dismiss_id)
                except Exception:
                    pass
            self._toast_windows.clear()
            if self._shutdown_callback:
                self._shutdown_callback()
            self.destroy()
        except Exception as e:
            logger.error(f"Error during app shutdown: {e}")
            self.destroy()
