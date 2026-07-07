# -*- coding: utf-8 -*-
"""
dashboard.py
学びジャーナル - 日次〜年次の集計ダッシュボード
Version: 0.5.0
"""

import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime, timedelta
from collections import Counter

from openpyxl import load_workbook

from storage import EXCEL_PATH, ENTRIES_SHEET, TAGMASTER_SHEET

# ============================================================
# UI設定（ダークテーマ）
# ============================================================
BG_COLOR = "#1a1a2e"
ACCENT_COLOR = "#f4a6b8"
TEXT_COLOR = "#ffffff"
PANEL_BG = "#0f3460"
BUTTON_TEXT_COLOR = "#2b2b40"
PERIOD_BTN_BG = "#dfeaf5"

PERIODS = ["日次", "週次", "月次", "四半期", "年次"]


def load_entries(path: str = EXCEL_PATH) -> list:
    """
    Entriesシートから全記録を読み込み、日時付き辞書のリストとして返す。
    """
    wb = load_workbook(path, data_only=True)
    ws = wb[ENTRIES_SHEET]

    entries = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        date_value, tag, memo = row[0], row[1], row[2]
        if not date_value:
            continue
        try:
            if isinstance(date_value, datetime):
                dt = date_value
            else:
                dt = datetime.strptime(str(date_value), "%Y-%m-%d %H:%M")
        except ValueError:
            print(f"⚠️ 日時の解析に失敗した行をスキップしました: {date_value}")
            continue
        entries.append({"datetime": dt, "tag": tag, "memo": memo})

    print(f"📊 記録を読み込みました（{len(entries)}件）")
    return entries


def load_tag_colors(path: str = EXCEL_PATH) -> dict:
    """
    TagMasterシートからタグ名→色コードの辞書を取得する。
    """
    wb = load_workbook(path, data_only=True)
    ws = wb[TAGMASTER_SHEET]

    colors = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            colors[row[0]] = row[1] or "#888888"
    return colors


def _period_range(period: str, reference: datetime = None) -> tuple:
    """
    指定された期間種別に対応する開始日時・終了日時（終了は含まない）を返す。
    """
    reference = reference or datetime.now()
    today = reference.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "日次":
        start = today
        end = today + timedelta(days=1)

    elif period == "週次":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)

    elif period == "月次":
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)

    elif period == "四半期":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=quarter_start_month, day=1)
        end_month = quarter_start_month + 3
        if end_month > 12:
            end = start.replace(year=start.year + 1, month=end_month - 12)
        else:
            end = start.replace(month=end_month)

    elif period == "年次":
        start = today.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)

    else:
        raise ValueError(f"不明な期間種別です: {period}")

    return start, end


def filter_entries_by_period(entries: list, period: str,
                              reference: datetime = None) -> list:
    """
    指定期間種別に該当する記録のみを抽出する。
    """
    start, end = _period_range(period, reference)
    return [e for e in entries if start <= e["datetime"] < end]


def aggregate_by_tag(entries: list) -> dict:
    """
    タグ別の件数を集計する。
    """
    counter = Counter(e["tag"] for e in entries)
    return dict(counter)


class DashboardWindow:
    """日次〜年次の集計ダッシュボードウィンドウ。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.current_period = "日次"
        self.tag_colors = {}
        self.entries = []
        self.period_buttons = {}

        self.root.title("学びダッシュボード")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("640x560")

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        title_font = tkfont.Font(family="Yu Gothic UI", size=14, weight="bold")
        title = tk.Label(
            self.root,
            text="📊 学びダッシュボード",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=title_font,
        )
        title.pack(pady=(12, 6))

        period_frame = tk.Frame(self.root, bg=BG_COLOR)
        period_frame.pack(pady=4)

        for period in PERIODS:
            btn = tk.Button(
                period_frame,
                text=period,
                bg=PERIOD_BTN_BG,
                fg=BUTTON_TEXT_COLOR,
                activebackground=ACCENT_COLOR,
                relief="flat",
                width=8,
                command=lambda p=period: self._on_period_change(p),
            )
            btn.pack(side="left", padx=3)
            self.period_buttons[period] = btn

        self.summary_label = tk.Label(
            self.root, text="", bg=BG_COLOR, fg=ACCENT_COLOR,
        )
        self.summary_label.pack(pady=(8, 2))

        self.canvas = tk.Canvas(
            self.root, width=600, height=220, bg=BG_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(pady=8)

        list_label = tk.Label(
            self.root, text="📝 記録一覧", bg=BG_COLOR, fg=TEXT_COLOR,
        )
        list_label.pack(pady=(4, 2))

        list_frame = tk.Frame(self.root, bg=BG_COLOR)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_frame,
            bg=PANEL_BG,
            fg=TEXT_COLOR,
            relief="flat",
            yscrollcommand=scrollbar.set,
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)

        self._highlight_period_button()

    def _highlight_period_button(self) -> None:
        for period, btn in self.period_buttons.items():
            if period == self.current_period:
                btn.config(bg=ACCENT_COLOR, fg=BUTTON_TEXT_COLOR)
            else:
                btn.config(bg=PERIOD_BTN_BG, fg=BUTTON_TEXT_COLOR)

    def _on_period_change(self, period: str) -> None:
        self.current_period = period
        self._highlight_period_button()
        self.refresh()

    def refresh(self) -> None:
        """Excelからデータを再読込し、グラフ・一覧を再描画する。"""
        try:
            all_entries = load_entries()
            self.tag_colors = load_tag_colors()
        except Exception as e:
            self.summary_label.config(text=f"❌ 読込エラー: {e}")
            print(f"❌ ダッシュボードのデータ読込に失敗しました: {e}")
            return

        filtered = filter_entries_by_period(all_entries, self.current_period)
        self.entries = sorted(filtered, key=lambda e: e["datetime"])
        counts = aggregate_by_tag(self.entries)

        self.summary_label.config(
            text=f"{self.current_period}: 全{len(self.entries)}件"
        )
        self._draw_chart(counts)
        self._update_list()

    def _draw_chart(self, counts: dict) -> None:
        self.canvas.delete("all")
        if not counts:
            self.canvas.create_text(
                300, 110, text="記録がありません", fill=TEXT_COLOR,
            )
            return

        max_count = max(counts.values())
        bar_width = 80
        gap = 30
        base_y = 200
        max_bar_height = 160
        x = 40

        for tag, count in counts.items():
            color = self.tag_colors.get(tag, "#888888")
            bar_height = (
                int((count / max_count) * max_bar_height) if max_count else 0
            )
            self.canvas.create_rectangle(
                x, base_y - bar_height, x + bar_width, base_y,
                fill=color, outline="",
            )
            self.canvas.create_text(
                x + bar_width / 2, base_y - bar_height - 12,
                text=str(count), fill=TEXT_COLOR,
            )
            self.canvas.create_text(
                x + bar_width / 2, base_y + 14,
                text=tag, fill=TEXT_COLOR,
            )
            x += bar_width + gap

    def _update_list(self) -> None:
        self.listbox.delete(0, tk.END)
        for entry in self.entries:
            date_str = entry["datetime"].strftime("%Y-%m-%d %H:%M")
            line = f"[{date_str}] [{entry['tag']}] {entry['memo']}"
            self.listbox.insert(tk.END, line)


def run() -> None:
    """dashboard.py 単体起動用のエントリポイント。"""
    root = tk.Tk()
    DashboardWindow(root)
    print("🚀 ダッシュボードを起動しました。")
    root.mainloop()


if __name__ == "__main__":
    run()
