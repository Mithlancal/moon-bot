"""
ui/floating_orb.py — Circular floating MoonBot logo, mini dashboard and full-panel launcher.

States:
  1. Orb: a small circular logo floating above PDFs, slides and browser tabs.
     Click it to open the mini dashboard; drag it to move it anywhere.
  2. Mini dashboard: compact timer, live PDF/site context, user-defined focus
     length, quick snip / memo / quiz, and a Maximize button.
  3. Full dashboard: the StudyPanel Toplevel opened by Maximize.
"""

import logging
import tkinter as tk
from typing import Any, Callable, Dict, Optional
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

import config
from core import gemini_service, json_db, web_context
from core.activity_tracker import ActivityTracker
from core.reader_assistant import ReaderAssistant
from core.scheduler import StudyTimer
from ui import ui_dispatch
from ui.study_panel import StudyPanel

logger = logging.getLogger("MoonBot.FloatingOrb")
COLORS = config.THEME_COLORS

ORB_SIZE = 128
MINI_WIDTH = 430
MINI_HEIGHT = 470
TRANSPARENT = "#000000"


def _logo_image(size: int, background: str) -> Image.Image:
    """Return moon-bot-logo.png cropped into a circle on a solid background.

    CustomTkinter's button/label canvas can cover its own image label. A plain
    Tk label with this pre-composited RGB image renders the real logo reliably,
    and the solid background keeps the corners clean for Windows colour-key
    transparency (or blends into the HUD when transparency is unavailable).
    """
    image: Image.Image
    if config.LOGO_PATH.exists():
        try:
            image = Image.open(config.LOGO_PATH).convert("RGB").resize(
                (size, size), Image.Resampling.LANCZOS
            )
        except Exception:
            image = Image.new("RGB", (size, size), background)
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, size - 8, size - 8), fill=(190, 194, 255))
            draw.ellipse((size // 2, 2, size - 2, size - 4), fill=(24, 28, 33))
    else:
        image = Image.new("RGB", (size, size), background)
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, size - 8, size - 8), fill=(190, 194, 255))
        draw.ellipse((size // 2, 2, size - 2, size - 4), fill=(24, 28, 33))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, size - 2, size - 2), fill=255)
    canvas = Image.new("RGB", (size, size), background)
    canvas.paste(image, (0, 0), mask)
    return canvas


class FloatingOrb(ctk.CTk):
    """Frameless always-on-top circular companion for desktop study sessions."""

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

        self.title("MoonBot HUD")
        try:
            icon_pil = Image.open(config.LOGO_PATH).convert("RGBA").resize(
                (32, 32), Image.Resampling.LANCZOS
            )
            self._icon_photo = ImageTk.PhotoImage(icon_pil)
            self.iconphoto(True, self._icon_photo)
        except Exception:
            self._icon_photo = None
        # Keep the window unmapped until it has the final geometry. Otherwise
        # Windows can show it at (32, 32) or leave it hidden behind other apps.
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        # Windows layered-window transparency hides the square corners around the logo.
        self._transparent_supported = False
        try:
            self.attributes("-transparentcolor", TRANSPARENT)
            self.configure(fg_color=TRANSPARENT)
            self._transparent_supported = True
        except Exception:
            self.configure(fg_color=COLORS["surface_hud"])

        # The real pixel size is only available once Tk processes its first idle
        # callback. Stay withdrawn until _initial_show() can place us correctly.
        self.update_idletasks()
        self._initial_x = 12
        self._initial_y = 64
        self._initial_shown = False
        self.geometry(f"{ORB_SIZE}x{ORB_SIZE}+{self._initial_x}+{self._initial_y}")

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_moved = False

        self.study_panel: Optional[StudyPanel] = None
        self._shutdown_callback: Optional[Callable[[], None]] = None
        self._shutting_down = False
        self._compact = True
        self._view = "orb"
        self._toast_windows = []
        self._context: dict = {}
        self._duration_applied = False
        self._duration_change_callback: Optional[Callable[[int, int], None]] = None
        self._mini_request_id = 0
        self._mini_watchdog_id: Optional[str] = None
        self._mini_pending_query: Optional[tuple] = None

        logo_bg = TRANSPARENT if self._transparent_supported else COLORS["surface_hud"]
        self._logo_pil = _logo_image(ORB_SIZE, logo_bg)
        self._small_logo_pil = _logo_image(24, COLORS["surface_hud"])
        self._mini_logo_pil = _logo_image(18, COLORS["surface_card"])
        self._logo_photo = ImageTk.PhotoImage(self._logo_pil)
        self._small_logo_photo = ImageTk.PhotoImage(self._small_logo_pil)
        self._mini_logo_photo = ImageTk.PhotoImage(self._mini_logo_pil)
        self._photo_images = [
            photo for photo in (
                getattr(self, "_icon_photo", None),
                self._logo_photo,
                self._small_logo_photo,
                self._mini_logo_photo,
            ) if photo is not None
        ]

        self._setup_orb_view()
        self._setup_mini_view()
        self._show_orb_view()

        # Map it now: waiting for mainloop() made startup look like a crash while
        # the full dashboard was still being constructed.
        self._initial_show()

        self.timer.add_tick_callback(self._on_timer_tick)
        self.tracker.set_activity_changed_callback(self._on_activity_changed)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def _screen_size(self) -> tuple[int, int]:
        """Return the real pixel size of the virtual desktop."""
        try:
            return (
                max(int(self.winfo_vrootwidth()), int(self.winfo_screenwidth())),
                max(int(self.winfo_vrootheight()), int(self.winfo_screenheight())),
            )
        except Exception:
            return 1920, 1080

    def _apply_geometry(self, logical_w: int, logical_h: int, x: int, y: int, margin: int = 12) -> tuple[int, int]:
        """Set geometry, then correct x/y for CustomTkinter's window scaling.

        CTk scales the width/height but not the x/y coordinates in a geometry
        string, so `screen_w - logical_width` can still leave the real window
        partly off-screen. Querying the mapped size and moving once keeps the
        orb and mini HUD inside the visible desktop.
        """
        self.geometry(f"{logical_w}x{logical_h}+{x}+{y}")
        if not self.winfo_viewable():
            return x, y
        try:
            self.update_idletasks()
            screen_w, screen_h = self._screen_size()
            actual_w = self.winfo_width() or logical_w
            actual_h = self.winfo_height() or logical_h
            x = min(max(margin, int(x)), max(margin, screen_w - actual_w - margin))
            y = min(max(margin, int(y)), max(margin, screen_h - actual_h - margin))
            self.geometry(f"+{x}+{y}")
        except (tk.TclError, ValueError):
            pass
        return x, y

    def _initial_show(self) -> None:
        """Show the orb at the real top-right corner once Tk knows the desktop size."""
        if self._shutting_down:
            return
        screen_w, _ = self._screen_size()
        self.deiconify()
        self.lift()
        self._initial_x, self._initial_y = self._apply_geometry(
            ORB_SIZE, ORB_SIZE, max(12, screen_w - ORB_SIZE - 24), self._initial_y
        )
        self.attributes("-topmost", True)
        # We mapped the window ourselves. Mark it so CTk.mainloop() does not run
        # its own deiconify/update() path (which can re-enter quit_app).
        self._window_exists = True
        self.update_idletasks()
        self._initial_shown = True
        self.after(180, self._reassert_initial_placement)

    def _reassert_initial_placement(self) -> None:
        """Re-apply top-right placement/topmost after the window has mapped."""
        if self._shutting_down or not self._initial_shown or self._view != "orb" or self._drag_moved:
            return
        try:
            self._initial_x, self._initial_y = self._apply_geometry(
                ORB_SIZE, ORB_SIZE, self._initial_x, self._initial_y
            )
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def _setup_orb_view(self) -> None:
        bg = TRANSPARENT if self._transparent_supported else COLORS["surface_hud"]
        self.orb_frame = ctk.CTkFrame(
            self, fg_color=bg, corner_radius=ORB_SIZE // 2, width=ORB_SIZE, height=ORB_SIZE
        )
        self.orb_frame.pack_propagate(False)
        self._make_draggable(self.orb_frame)

        self.logo_btn = tk.Label(
            self.orb_frame,
            image=self._logo_photo,
            bg=bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.logo_btn.pack(fill="both", expand=True)
        self.logo_btn.bind("<ButtonPress-1>", self._start_drag)
        self.logo_btn.bind("<B1-Motion>", self._on_drag)
        self.logo_btn.bind("<ButtonRelease-1>", self._on_orb_release)

    def _setup_mini_view(self) -> None:
        self.mini_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["surface_hud"],
            border_color=COLORS["border_highlight"],
            border_width=1,
            corner_radius=16,
        )

        header = ctk.CTkFrame(self.mini_frame, fg_color="transparent", height=34)
        header.pack(fill="x", padx=10, pady=(8, 2))
        self._make_draggable(header)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left")
        self._make_draggable(brand)
        tk.Label(
            brand, image=self._small_logo_photo, bg=COLORS["surface_hud"],
            bd=0, highlightthickness=0
        ).pack(side="left", padx=(0, 6))
        name = ctk.CTkLabel(
            brand,
            text="MoonBot",
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        name.pack(side="left")
        self._make_draggable(name)

        self.status_pill = ctk.CTkLabel(
            brand,
            text=" ● IDLE ",
            font=ctk.CTkFont(family="JetBrains Mono", size=9, weight="bold"),
            fg_color=COLORS["surface_card"],
            text_color=COLORS["accent_blue"],
            corner_radius=6
        )
        self.status_pill.pack(side="left", padx=(8, 0))

        buttons = ctk.CTkFrame(header, fg_color="transparent")
        buttons.pack(side="right")
        self.compact_btn = tk.Label(
            buttons, image=self._mini_logo_photo, bg=COLORS["surface_card"],
            bd=0, highlightthickness=0, cursor="hand2"
        )
        self.compact_btn.pack(side="left", padx=(0, 4))
        self.compact_btn.bind("<Button-1>", lambda _event: self.toggle_compact())
        self.expand_btn = ctk.CTkButton(
            buttons, text="⤢ Open Full Dashboard", width=150, height=24, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["surface_card"], hover_color=COLORS["surface_card_hover"],
            command=self.toggle_study_panel
        )
        self.expand_btn.pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            buttons, text="✕", width=22, height=22, corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=COLORS["surface_card"], hover_color=COLORS["error"],
            command=self.quit_app
        ).pack(side="left")

        self.active_context_lbl = ctk.CTkLabel(
            self.mini_frame,
            text="Detecting the active page or PDF...",
            font=ctk.CTkFont(family="Inter", size=11),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.active_context_lbl.pack(fill="x", padx=12, pady=(0, 2))
        self._make_draggable(self.active_context_lbl)

        timer_row = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        timer_row.pack(fill="x", padx=12, pady=(2, 2))
        self._make_draggable(timer_row)
        self.orb_clock_lbl = ctk.CTkLabel(
            timer_row,
            text=self._format_seconds(self.timer.remaining_seconds),
            font=ctk.CTkFont(family="JetBrains Mono", size=30, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.orb_clock_lbl.pack(side="left", padx=(0, 10))
        self._make_draggable(self.orb_clock_lbl)
        self.orb_target_lbl = ctk.CTkLabel(
            timer_row,
            text=f"Your focus block · {self.timer.work_minutes}m",
            font=ctk.CTkFont(family="Inter", size=10),
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left"
        )
        self.orb_target_lbl.pack(side="left", fill="x", expand=True)

        # User-defined timer: the first sprint length is never forced.
        duration_row = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        duration_row.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkLabel(
            duration_row, text="Focus", font=ctk.CTkFont(family="Inter", size=10),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=(0, 4))
        self.focus_minutes_entry = ctk.CTkEntry(
            duration_row, width=44, height=26, justify="center",
            font=ctk.CTkFont(family="JetBrains Mono", size=11),
            fg_color=COLORS["surface_input"], border_color=COLORS["border_subtle"]
        )
        self.focus_minutes_entry.insert(0, str(self.timer.work_minutes))
        self.focus_minutes_entry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            duration_row, text="Break", font=ctk.CTkFont(family="Inter", size=10),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=(0, 4))
        self.break_minutes_entry = ctk.CTkEntry(
            duration_row, width=44, height=26, justify="center",
            font=ctk.CTkFont(family="JetBrains Mono", size=11),
            fg_color=COLORS["surface_input"], border_color=COLORS["border_subtle"]
        )
        self.break_minutes_entry.insert(0, str(self.timer.break_minutes))
        self.break_minutes_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            duration_row, text="Apply", width=52, height=26, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            command=self._apply_custom_duration
        ).pack(side="left", padx=(0, 6))
        self.auto_capture_btn = ctk.CTkButton(
            duration_row, text="📋 Auto: On", width=84, height=26, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"], hover_color=COLORS["surface_card_hover"],
            command=self._toggle_auto_capture
        )
        self.auto_capture_btn.pack(side="left")
        try:
            settings = json_db.get_user_settings()
            self.focus_minutes_entry.delete(0, "end")
            self.focus_minutes_entry.insert(0, str(settings.get("focus_minutes", self.timer.work_minutes)))
            self.break_minutes_entry.delete(0, "end")
            self.break_minutes_entry.insert(0, str(settings.get("break_minutes", self.timer.break_minutes)))
            self._refresh_auto_capture_button(bool(settings.get("auto_clipboard_capture", True)))
        except Exception:
            pass

        quick = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        quick.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkButton(
            quick, text="📋 Snip", width=78, height=28, corner_radius=8,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["secondary"], hover_color=COLORS["primary"],
            command=self._quick_snip_from_screen
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            quick, text="📝 Memo", width=78, height=28, corner_radius=8,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"], hover_color=COLORS["surface_card_hover"],
            command=self._quick_memo_from_screen
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            quick, text="🌐 Translate", width=86, height=28, corner_radius=8,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"], hover_color=COLORS["surface_card_hover"],
            command=self._quick_translate_from_screen
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            quick, text="🎯 Quiz", width=72, height=28, corner_radius=8,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card"], hover_color=COLORS["surface_card_hover"],
            command=self._quick_quiz_from_screen
        ).pack(side="left", padx=4)

        # Compact Ask & Learn: works in the small HUD without opening the full panel.
        ask_card = ctk.CTkFrame(self.mini_frame, fg_color=COLORS["surface_card"], corner_radius=10)
        ask_card.pack(fill="both", expand=True, padx=12, pady=(4, 4))
        ctk.CTkLabel(
            ask_card,
            text="Ask about what you're viewing",
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", padx=10, pady=(8, 2))

        ask_row = ctk.CTkFrame(ask_card, fg_color="transparent")
        ask_row.pack(fill="x", padx=10, pady=(0, 4))
        self.mini_query_entry = ctk.CTkEntry(
            ask_row,
            placeholder_text="Ask a question or type 'quiz me'...",
            height=30,
            font=ctk.CTkFont(family="Inter", size=11),
            fg_color=COLORS["surface_input"],
            border_color=COLORS["border_subtle"]
        )
        self.mini_query_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.mini_query_entry.bind("<Return>", lambda _event: self._mini_ask())
        ctk.CTkButton(
            ask_row, text="Ask", width=52, height=30, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            command=self._mini_ask
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            ask_row, text="Quiz", width=52, height=30, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card_hover"], hover_color=COLORS["primary_hover"],
            command=self._mini_quiz
        ).pack(side="left")

        self.mini_answer_box = ctk.CTkTextbox(
            ask_card,
            height=92,
            font=ctk.CTkFont(family="Inter", size=11),
            fg_color=COLORS["surface_input"],
            text_color=COLORS["text_primary"],
            wrap="word",
            corner_radius=8
        )
        self.mini_answer_box.pack(fill="both", expand=True, padx=10, pady=(2, 6))
        self.mini_answer_box.insert(
            "1.0", "Ask a question about your current page, or tap Quiz for a quick check."
        )
        self.mini_answer_box.configure(state="disabled")
        self.mini_answer_state: Optional[Dict[str, Any]] = None
        self.mini_reveal_btn = ctk.CTkButton(
            ask_card, text="👁 Show answer", height=22, width=104, corner_radius=6,
            font=ctk.CTkFont(family="Inter", size=10),
            fg_color=COLORS["surface_card_hover"], hover_color=COLORS["primary_hover"],
            command=self._mini_reveal_answer
        )
        self.mini_reveal_btn.pack(anchor="e", padx=10, pady=(0, 6))
        self.mini_reveal_btn.pack_forget()

        bottom = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(2, 10))
        self.orb_toggle_btn = ctk.CTkButton(
            bottom, text="▶ Start Study", width=112, height=30, corner_radius=8,
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            command=self._toggle_study_timer
        )
        self.orb_toggle_btn.pack(side="left", padx=(0, 6))
        self.orb_emergency_btn = ctk.CTkButton(
            bottom, text="🚨 Emergency", width=100, height=30, corner_radius=8,
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
            fg_color=COLORS["error"], hover_color="#D13B3B",
            command=self._on_emergency_click
        )
        self.orb_emergency_btn.pack(side="left", padx=4)
        ctk.CTkButton(
            bottom, text="↺", width=34, height=30, corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["surface_card"], hover_color=COLORS["surface_card_hover"],
            command=self._reset_study_timer
        ).pack(side="right")

        # Kept for compatibility with older callers; not packed in the orb view.
        self.compact_row = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        self.compact_clock_lbl = ctk.CTkLabel(
            self.compact_row, text="25:00",
            font=ctk.CTkFont(family="JetBrains Mono", size=20, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.compact_clock_lbl.pack(side="left", padx=(4, 8))
        self.compact_emergency_btn = ctk.CTkButton(
            self.compact_row, text="🚨 Emergency", width=100, height=28,
            fg_color=COLORS["error"], hover_color="#D13B3B",
            command=self._on_emergency_click
        )
        self.compact_emergency_btn.pack(side="left")

    def _show_orb_view(self) -> None:
        self._view = "orb"
        self._compact = True
        self.mini_frame.pack_forget()
        self.orb_frame.pack(fill="both", expand=True)
        x, y = self.winfo_x(), self.winfo_y()
        self._apply_geometry(ORB_SIZE, ORB_SIZE, x, y)

    def _show_mini_view(self) -> None:
        self._view = "mini"
        self._compact = False
        self.sync_duration_inputs(self.timer.work_minutes, self.timer.break_minutes)
        self.orb_frame.pack_forget()
        self.mini_frame.pack(fill="both", expand=True, padx=1, pady=1)
        x, y = self.winfo_x(), self.winfo_y()
        screen_w, _ = self._screen_size()
        max_x = max(10, screen_w - MINI_WIDTH - 10)
        x = min(max(10, x), max_x)
        self._apply_geometry(MINI_WIDTH, MINI_HEIGHT, x, y, margin=10)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def mainloop(self, *args, **kwargs) -> None:
        """Run Tk's loop, ignoring Tcl errors raised by teardown re-entrancy."""
        try:
            super().mainloop(*args, **kwargs)
        except tk.TclError:
            if not self._shutting_down:
                raise

    def set_study_panel(self, panel: StudyPanel) -> None:
        self.study_panel = panel

    def set_duration_change_callback(self, callback: Callable[[int, int], None]) -> None:
        """Notify the full dashboard when the user changes the sprint length here."""
        self._duration_change_callback = callback

    def sync_duration_inputs(self, work_minutes: int, break_minutes: int) -> None:
        """Mirror a duration chosen in the full dashboard without firing callbacks."""
        try:
            self.focus_minutes_entry.delete(0, "end")
            self.focus_minutes_entry.insert(0, str(max(1, int(work_minutes))))
            self.break_minutes_entry.delete(0, "end")
            self.break_minutes_entry.insert(0, str(max(1, int(break_minutes))))
            self.orb_target_lbl.configure(
                text=f"Your focus block · {int(work_minutes)}m / {int(break_minutes)}m break"
            )
        except Exception:
            pass

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        """Register main.py's cleanup routine for graceful shutdown."""
        self._shutdown_callback = callback

    def set_live_context(self, context: dict) -> None:
        """Accept the parsed PDF/site context from ActivityTracker."""
        self._context = dict(context or {})
        ui_dispatch.submit(self._update_activity_label, web_context.site_summary(self._context))

    def set_auto_capture_enabled(self, enabled: bool) -> None:
        self._refresh_auto_capture_button(bool(enabled))

    def _refresh_auto_capture_button(self, enabled: bool) -> None:
        try:
            self.auto_capture_btn.configure(
                text="📋 Auto: On" if enabled else "📋 Auto: Off",
                fg_color=COLORS["success"] if enabled else COLORS["surface_card"]
            )
        except Exception:
            pass

    def _toggle_auto_capture(self) -> None:
        enabled = "Off" in self.auto_capture_btn.cget("text")
        self._refresh_auto_capture_button(enabled)
        try:
            json_db.update_user_settings(auto_clipboard_capture=enabled)
        except Exception:
            pass
        watcher = getattr(self, "clipboard_watcher", None)
        if watcher:
            watcher.set_enabled(enabled)
        self.show_notification(
            "Highlight capture",
            "Auto-capture is on. Copy text from a PDF or page and MoonBot will prepare it." if enabled
            else "Auto-capture paused.",
            level="success" if enabled else "info"
        )

    # ------------------------------------------------------------------
    # Dragging / click detection
    # ------------------------------------------------------------------
    def _make_draggable(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._on_drag)

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_start_x = event.x_root - self.winfo_x()
        self._drag_start_y = event.y_root - self.winfo_y()
        self._drag_moved = False

    def _on_drag(self, event: tk.Event) -> None:
        new_x = event.x_root - self._drag_start_x
        new_y = event.y_root - self._drag_start_y
        if abs(new_x - self.winfo_x()) + abs(new_y - self.winfo_y()) > 3:
            self._drag_moved = True
        self.geometry(f"+{new_x}+{new_y}")

    def _on_orb_release(self, event: tk.Event) -> None:
        if not self._drag_moved:
            self._show_mini_view()
        self._drag_moved = False

    def toggle_compact(self) -> None:
        """Toggle between the circular logo and the mini dashboard."""
        if self._view == "orb":
            self._show_mini_view()
        else:
            self._show_orb_view()

    # ------------------------------------------------------------------
    # Timer controls
    # ------------------------------------------------------------------
    @staticmethod
    def _format_seconds(seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _read_custom_durations(self) -> tuple[int, int]:
        try:
            focus = max(1, int(float(self.focus_minutes_entry.get().strip())))
        except (ValueError, TypeError):
            focus = self.timer.work_minutes
        try:
            break_min = max(1, int(float(self.break_minutes_entry.get().strip())))
        except (ValueError, TypeError):
            break_min = self.timer.break_minutes
        return min(focus, 600), min(break_min, 180)

    def _apply_custom_duration(self, force: bool = False) -> None:
        focus, break_min = self._read_custom_durations()
        if not force and self._duration_applied and focus == self.timer.work_minutes and break_min == self.timer.break_minutes:
            return
        self.timer.set_duration(focus, break_min)
        self._duration_applied = True
        self.orb_target_lbl.configure(text=f"Your focus block · {focus}m / {break_min}m break")
        try:
            json_db.update_user_settings(focus_minutes=focus, break_minutes=break_min)
        except Exception:
            pass
        if self._duration_change_callback:
            try:
                self._duration_change_callback(focus, break_min)
            except Exception:
                pass

    def _toggle_study_timer(self) -> None:
        self._apply_custom_duration()
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

    # ------------------------------------------------------------------
    # Reader shortcuts
    # ------------------------------------------------------------------
    def _open_ask_tab(self, mode: str) -> bool:
        if not self.study_panel:
            return False
        self.study_panel.show_panel()
        self.study_panel.tabview.set("✨ Ask & Learn")
        if mode == "memo":
            self.study_panel._on_memo_click()
        elif mode == "quiz":
            self.study_panel._on_quiz_click()
        else:
            self.study_panel._grab_clipboard()
        return True

    def _quick_snip_from_screen(self) -> None:
        self._open_ask_tab("explain")

    def _quick_memo_from_screen(self) -> None:
        """Capture highlighted PDF text and turn it into a Cornell-style memo."""
        text = self.reader.grab_clipboard_text()
        if not self.study_panel or not text:
            self.show_notification("Highlight capture", "Copy text from your PDF first.", level="warning")
            return
        self.study_panel.show_panel()
        self.study_panel.tabview.set("✨ Ask & Learn")
        self.study_panel.query_entry.delete(0, "end")
        self.study_panel.query_entry.insert(0, text)
        self.study_panel._on_memo_click()

    def _quick_translate_from_screen(self) -> None:
        """Translate a copied highlight from a PDF/page using the active context."""
        text = self.reader.grab_clipboard_text()
        if not self.study_panel or not text:
            self.show_notification("Highlight capture", "Copy text from your PDF first.", level="warning")
            return
        self.study_panel.show_panel()
        self.study_panel.tabview.set("✨ Ask & Learn")
        self.study_panel.query_entry.delete(0, "end")
        self.study_panel.query_entry.insert(0, text)
        self.study_panel._on_translate_click()

    def _quick_quiz_from_screen(self) -> None:
        text = self.reader.grab_clipboard_text()
        if not self.study_panel:
            return
        self.study_panel.show_panel()
        self.study_panel.tabview.set("✨ Ask & Learn")
        if text:
            self.study_panel.query_entry.delete(0, "end")
            self.study_panel.query_entry.insert(0, text)
        self.study_panel._on_quiz_click()

    def _mini_ui_ready(self) -> bool:
        """Never write to a Tk widget that is closing or already destroyed."""
        if self._shutting_down:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _cancel_mini_watchdog(self) -> None:
        ident, self._mini_watchdog_id = self._mini_watchdog_id, None
        if ident:
            ui_dispatch.cancel_after(ident)

    def _set_mini_answer(self, text: str) -> None:
        """Update the read-only answer box without touching Tk from a worker."""
        if not self._mini_ui_ready():
            return
        try:
            self.mini_answer_box.configure(state="normal")
            self.mini_answer_box.delete("1.0", "end")
            self.mini_answer_box.insert("1.0", text)
            self.mini_answer_box.configure(state="disabled")
        except tk.TclError:
            pass

    def _mini_ask(self) -> None:
        query = self.mini_query_entry.get().strip()
        if not query:
            self._set_mini_answer("Type a question first, then press Ask.")
            return
        self._set_mini_answer("Working on it...")
        self._run_mini_query(query, mode="natural")

    def _mini_quiz(self) -> None:
        query = self.mini_query_entry.get().strip() or "this topic"
        self._set_mini_answer("Writing a quick quiz...")
        self._run_mini_query(query, mode="quiz")

    def _run_mini_query(self, query: str, mode: str) -> None:
        context = web_context.context_for_prompt(self._context)
        self._mini_request_id += 1
        request_id = self._mini_request_id
        self._cancel_mini_watchdog()
        self._mini_pending_query = (query, mode)
        self._mini_watchdog_id = ui_dispatch.after(
            config.QUERY_WATCHDOG_MS, self._mini_query_timeout, request_id
        )

        def worker() -> None:
            try:
                result = self.reader.process_query(query, mode=mode, context=context)
                ui_dispatch.submit(self._display_mini_result, result, request_id)
            except Exception as exc:
                ui_dispatch.submit(self._mini_query_failed, exc, request_id)

        ui_dispatch.run_worker(worker)

    def _mini_query_timeout(self, request_id: int) -> None:
        """Replace 'working' with a real local answer if the live call runs long."""
        self._mini_watchdog_id = None
        if request_id != self._mini_request_id or not self._mini_ui_ready():
            return
        query, mode = self._mini_pending_query or ("", "explain")
        self._mini_pending_query = None
        # Invalidate the late result so it cannot overwrite this answer.
        self._mini_request_id += 1
        result = gemini_service.offline_answer(
            query,
            mode=mode,
            context=web_context.context_for_prompt(self._context),
            reason="That answer took too long; using your text for now",
        )
        self._display_mini_result(result, self._mini_request_id)

    def _mini_query_failed(self, exc: Exception, request_id: int) -> None:
        if request_id != self._mini_request_id or not self._mini_ui_ready():
            return
        self._cancel_mini_watchdog()
        self._mini_pending_query = None
        self.mini_answer_state = None
        self.mini_reveal_btn.pack_forget()
        detail = str(exc).strip().splitlines()[0][:140] if exc else ""
        message = "Couldn't finish that request right now. Try again or rephrase it."
        if detail:
            message += f"\n\n{detail}"
        self._set_mini_answer(message)

    def _display_mini_result(self, result: Dict[str, Any], request_id: Optional[int] = None) -> None:
        if request_id is not None and request_id != self._mini_request_id:
            return
        if not self._mini_ui_ready():
            return
        self._cancel_mini_watchdog()
        self._mini_pending_query = None
        self.mini_answer_state = None
        self.mini_reveal_btn.pack_forget()

        if "question" in result:
            self.mini_answer_state = result
            lines = [str(result.get("question") or "Quick quiz"), "", "Options:"]
            for index, option in enumerate(result.get("options") or []):
                lines.append(f" [{chr(65 + index)}] {option}")
            note = str(result.get("note") or "").strip()
            if note:
                lines.extend(["", note])
            self._set_mini_answer("\n".join(lines))
            self.mini_reveal_btn.pack(anchor="e", padx=10, pady=(0, 6))
            return

        source = str(result.get("source", "gemini"))
        source_label = {
            "gemini": "live answer",
            "offline_fallback": "local answer",
            "local": "local answer",
        }.get(source, source)
        lines = [f"{result.get('title', 'Answer')} · {source_label}", ""]
        if result.get("formula"):
            lines.extend([f"Formula: {result['formula']}", ""])
        explanation = str(result.get("explanation") or "").strip()
        if explanation:
            lines.append(explanation)
        note = str(result.get("note") or "").strip()
        if note:
            lines.extend(["", note])
        takeaways = result.get("takeaways") or []
        if takeaways:
            lines.extend(["", "Key points:"])
            lines.extend(f"• {item}" for item in takeaways[:3])
        self._set_mini_answer("\n".join(lines)[:1600])

    def _mini_reveal_answer(self) -> None:
        if not self.mini_answer_state:
            return
        options = self.mini_answer_state.get("options") or []
        try:
            correct = int(self.mini_answer_state.get("correct_index", 0))
        except (TypeError, ValueError):
            correct = 0
        answer = options[correct] if 0 <= correct < len(options) else "—"
        current = self.mini_answer_box.get("1.0", "end").rstrip()
        explanation = str(self.mini_answer_state.get("explanation") or "").strip()
        lines = [current, "", f"Answer: [{chr(65 + correct)}] {answer}"]
        if explanation:
            lines.append(f"Why: {explanation}")
        self._set_mini_answer("\n".join(lines))
        self.mini_reveal_btn.pack_forget()
        self.mini_answer_state = None

    def handle_highlight(self, text: str, context: dict) -> None:
        """Called by the clipboard watcher on the Tk thread."""
        if not self.study_panel:
            return
        self.set_live_context(context)
        self.study_panel.set_live_context(context)
        description = web_context.site_summary(context)
        self.active_context_lbl.configure(text=f"📋 {description} · highlight ready")
        self.study_panel.query_entry.delete(0, "end")
        self.study_panel.query_entry.insert(0, text[:1200])
        self.mini_query_entry.delete(0, "end")
        self.mini_query_entry.insert(0, text[:1200])
        self._set_mini_answer(
            f"Highlight captured from {description}.\n\nPress Ask for an explanation, or Quiz for a quick check."
        )
        self.show_notification(
            "Highlight captured",
            f"{description}\nReady to explain, translate, or make a memo.",
            level="info"
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _on_timer_tick(self, remaining_sec: int, total_sec: int, mode: str, state: str) -> None:
        ui_dispatch.submit(
            self._update_orb_timer,
            self._format_seconds(remaining_sec), mode, state, total_sec
        )

    def _update_orb_timer(self, clock_str: str, mode: str, state: str, total_sec: int = 0) -> None:
        try:
            self.orb_clock_lbl.configure(text=clock_str)
            self.compact_clock_lbl.configure(text=clock_str)
            if state == StudyTimer.STATE_RUNNING:
                color = COLORS["success"] if mode == "work" else COLORS["warning"]
                self.status_pill.configure(
                    text=" ● STUDYING " if mode == "work" else " ● BREAK ", text_color=color
                )
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
        # Kept as a legacy callback; main.py supplies richer parsed contexts via
        # set_live_context().
        pass

    def _update_activity_label(self, text: str) -> None:
        try:
            self.active_context_lbl.configure(text=text)
        except Exception:
            pass

    def toggle_study_panel(self) -> None:
        """Maximize button: open the full dashboard, or hide it if already open."""
        if not self.study_panel:
            return
        if self.study_panel.winfo_viewable():
            self.study_panel.hide_panel()
            self.expand_btn.configure(text="⤢ Open Full Dashboard")
        else:
            self.study_panel.show_panel()
            self.expand_btn.configure(text="⤡ Hide Dashboard")

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def show_notification(self, title: str, message: str, level: str = "info") -> None:
        """Show a transient, non-focus-stealing in-app alert."""
        level_colors = {
            "info": COLORS["accent_blue"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"]
        }
        accent = level_colors.get(level, COLORS["accent_blue"])

        def build_toast():
            if self._shutting_down:
                return
            toast = None
            try:
                toast = ctk.CTkToplevel(self)
                toast.overrideredirect(True)
                toast.attributes("-topmost", True)
                toast.configure(fg_color=COLORS["surface_hud"])
                toast.resizable(False, False)

                x = max(10, self.winfo_x() + 20)
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

                if self._shutting_down:
                    if toast:
                        toast.destroy()
                    return

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
            except tk.TclError:
                if toast is not None:
                    try:
                        toast.destroy()
                    except Exception:
                        pass

        ui_dispatch.submit(build_toast)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def quit_app(self) -> None:
        """Gracefully shut down background threads and close application."""
        if self._shutting_down:
            return
        self._shutting_down = True
        # Ignore any answer that arrives after the close button was pressed.
        self._mini_request_id += 1
        self._mini_pending_query = None
        self._cancel_mini_watchdog()
        try:
            for toast in list(self._toast_windows):
                ui_dispatch.cancel_widget_after(toast)
                try:
                    toast.after_cancel(toast._moonbot_dismiss_id)
                except Exception:
                    pass
            self._toast_windows.clear()
            if self._shutdown_callback:
                self._shutdown_callback()
        except Exception as e:
            logger.error(f"Error during app shutdown: {e}")
        finally:
            # ui_dispatch owns ordered teardown and destroys the root itself.
            # Do not touch winfo/destroy here: the Tcl interpreter is already gone.
            try:
                ui_dispatch.shutdown([self])
            except Exception as e:
                logger.error(f"Error during UI teardown: {e}")
