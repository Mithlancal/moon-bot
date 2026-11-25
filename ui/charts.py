"""
ui/charts.py — Matplotlib Analytics Canvas for MoonBot
Renders study analytics (category donut, hourly time graph and top-application
bar chart) embedded directly inside CustomTkinter.
All data comes from the local daily JSON log — no demo numbers are invented.
"""

from typing import Dict

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import customtkinter as ctk

import config
from core import json_db

# Chart palette from the study dashboard theme
CHART_BG = "#181C21"
CARD_BG = "#21262D"
TEXT_COLOR = "#E2E2E8"
MUTED_TEXT = "#9BA3AF"
SLICE_COLORS = ["#5865F2", "#43B581", "#FAA61A", "#8EA1FF", "#F04747", "#7289DA"]


class DailyChartsFrame(ctk.CTkFrame):
    """
    Embedded analytics widget containing:
    1. Donut chart of tracked activity categories.
    2. Time graph of study minutes per hour of the day.
    3. Bar chart of the top applications by tracked time.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=CARD_BG, corner_radius=12, **kwargs)
        self.figure = None
        self.canvas = None
        self._disposed = False
        self._setup_ui()
        self.refresh_data()

    def dispose(self) -> None:
        """Close the Matplotlib figure and detach the Tk canvas (main thread only)."""
        self._disposed = True
        canvas, self.canvas = self.canvas, None
        figure, self.figure = self.figure, None
        if canvas is not None:
            try:
                widget = canvas.get_tk_widget()
                widget.pack_forget()
                widget.destroy()
            except Exception:
                pass
        if figure is not None:
            try:
                plt.close(figure)
            except Exception:
                pass

    def _setup_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 6))

        title = ctk.CTkLabel(
            header,
            text="📊 Daily Study Analytics & Screen Time",
            font=ctk.CTkFont(family="Inter", size=16, weight="bold"),
            text_color=config.THEME_COLORS["text_primary"]
        )
        title.pack(side="left")

        self.date_lbl = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(family="JetBrains Mono", size=11),
            text_color=MUTED_TEXT
        )
        self.date_lbl.pack(side="left", padx=12)

        refresh_btn = ctk.CTkButton(
            header,
            text="🔄 Refresh",
            width=80,
            height=28,
            font=ctk.CTkFont(family="Inter", size=12),
            fg_color=config.THEME_COLORS["primary"],
            hover_color=config.THEME_COLORS["primary_hover"],
            command=self.refresh_data
        )
        refresh_btn.pack(side="right")

        self.chart_container = ctk.CTkFrame(self, fg_color=CHART_BG, corner_radius=8)
        self.chart_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def refresh_data(self) -> None:
        """Fetch today's JSON log data and rebuild matplotlib plots."""
        if self._disposed:
            return
        daily_log = json_db.get_daily_log()
        summary = json_db.get_daily_aggregates(daily_log.get("date"))
        hourly = json_db.get_hourly_study_distribution(daily_log.get("date"))

        self.date_lbl.configure(text=str(daily_log.get("date", "")))
        self._render_charts(
            summary.get("categories", {}),
            summary.get("apps", {}),
            hourly
        )

    def _render_charts(
        self,
        categories: Dict[str, int],
        apps: Dict[str, int],
        hourly: Dict[int, int]
    ) -> None:
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
            plt.close(self.figure)

        plt.style.use("dark_background")
        self.figure, (ax_donut, ax_time, ax_apps) = plt.subplots(
            1, 3, figsize=(12.6, 3.6), dpi=100, facecolor=CHART_BG
        )
        self.figure.subplots_adjust(left=0.045, right=0.98, top=0.84, bottom=0.18, wspace=0.38)

        self._render_donut(ax_donut, categories)
        self._render_time_graph(ax_time, hourly)
        self._render_apps(ax_apps, apps, sum(categories.values()) / 60 if categories else 0)

        self.canvas = FigureCanvasTkAgg(self.figure, master=self.chart_container)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    @staticmethod
    def _render_donut(ax, categories: Dict[str, int]) -> None:
        cat_values = [v / 60 for v in categories.values()]  # seconds -> minutes
        total_mins = sum(cat_values)
        labels = list(categories.keys())

        if total_mins > 0:
            colors = [SLICE_COLORS[i % len(SLICE_COLORS)] for i in range(len(labels))]
            _, _, autotexts = ax.pie(
                cat_values,
                labels=None,
                autopct=lambda p: f"{p:.0f}%" if p >= 5 else "",
                pctdistance=0.75,
                colors=colors,
                startangle=140,
                wedgeprops=dict(width=0.45, edgecolor=CHART_BG, linewidth=2)
            )
            for at in autotexts:
                at.set_color(TEXT_COLOR)
                at.set_fontsize(8)
                at.set_weight("bold")

            study_mins = int(categories.get("Study / Reading", 0) / 60)
            ax.text(
                0, 0, f"{study_mins}m\nStudy",
                ha="center", va="center",
                color=config.THEME_COLORS["accent_blue"],
                fontsize=10, fontweight="bold"
            )
            ax.legend(
                [label.split("/")[0].strip() for label in labels],
                loc="upper center", bbox_to_anchor=(0.5, -0.04),
                ncol=2, fontsize=7, frameon=False, labelcolor=MUTED_TEXT
            )
        else:
            ax.text(0, 0, "No activity\nlogged yet", ha="center", va="center", color=MUTED_TEXT, fontsize=10)

        ax.set_title("Time by Category", color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=8)

    @staticmethod
    def _render_time_graph(ax, hourly: Dict[int, int]) -> None:
        minutes = [hourly.get(h, 0) / 60 for h in range(24)]
        hours = list(range(24))
        peak_hour = max(hours, key=lambda h: minutes[h])

        if sum(minutes) > 0:
            colors = [
                config.THEME_COLORS["accent_blue"] if h == peak_hour else config.THEME_COLORS["primary"]
                for h in hours
            ]
            ax.bar(hours, minutes, color=colors, width=0.72)
            ax.plot(hours, minutes, color=config.THEME_COLORS["accent_blue"], linewidth=1.2, alpha=0.8)
            ax.annotate(
                f"peak {peak_hour:02d}:00",
                xy=(peak_hour, minutes[peak_hour]),
                xytext=(0, 6), textcoords="offset points",
                ha="center", color=MUTED_TEXT, fontsize=8
            )
        else:
            ax.text(0.5, 0.5, "No study time logged yet", transform=ax.transAxes,
                    ha="center", va="center", color=MUTED_TEXT, fontsize=10)
            ax.set_ylim(0, 1)

        ax.set_title("Study Time by Hour", color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=8)
        ax.set_xlabel("Hour of Day", color=MUTED_TEXT, fontsize=9)
        ax.set_ylabel("Minutes", color=MUTED_TEXT, fontsize=9)
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks([0, 4, 8, 12, 16, 20, 23])
        ax.tick_params(colors=MUTED_TEXT, labelsize=8)
        ax.grid(axis="y", color="#2B313A", linewidth=0.6, alpha=0.7)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(CARD_BG)

    @staticmethod
    def _render_apps(ax, apps: Dict[str, int], total_mins: float) -> None:
        top_apps = sorted(apps.items(), key=lambda kv: kv[1], reverse=True)[:5]
        if top_apps:
            names = [name.replace(".exe", "") for name, _ in top_apps][::-1]
            values = [seconds / 60 for _, seconds in top_apps][::-1]
            bars = ax.barh(names, values, color=config.THEME_COLORS["primary"], height=0.55, edgecolor="none")
            ax.set_xlim(0, max(values) * 1.3 if max(values) > 0 else 1)
            for bar in bars:
                width = bar.get_width()
                ax.text(
                    width + max(0.5, total_mins * 0.01),
                    bar.get_y() + bar.get_height() / 2,
                    f"{int(width)}m",
                    ha="left", va="center", color=TEXT_COLOR, fontsize=8
                )
        else:
            ax.text(0.5, 0.5, "No apps tracked yet", transform=ax.transAxes,
                    ha="center", va="center", color=MUTED_TEXT, fontsize=10)

        ax.set_title("Top Applications", color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=8)
        ax.set_xlabel("Minutes Spent", color=MUTED_TEXT, fontsize=9)
        ax.tick_params(colors=MUTED_TEXT, labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(CARD_BG)
