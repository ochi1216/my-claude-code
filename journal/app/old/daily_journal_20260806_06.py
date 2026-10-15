# -*- coding: utf-8 -*-
"""
daily_journal_20260806_06.py
学びジャーナル - ホットキー起動の入力ポップアップUI
Version: 0.15.0
"""

import ctypes
import os
import queue
import threading
import tkinter as tk
from ctypes import wintypes
from tkinter import font as tkfont

from storage import (
    OTHER_SUBITEM_LABEL,
    get_sub_item_master,
    get_tag_master,
    peek_next_time_range,
    record_check_in,
)

# ============================================================
# UI設定（ダークテーマ）
# ============================================================
BG_COLOR = "#1a1a2e"
ACCENT_COLOR = "#f4a6b8"
TEXT_COLOR = "#ffffff"
ENTRY_BG = "#0f3460"
PLACEHOLDER_COLOR = "#7c86a8"  # 入力前のプレースホルダ文字色（本文の白と区別する）
BUTTON_TEXT_COLOR = "#2b2b40"
CANCEL_BTN_BG = "#d8d8e6"
DASHBOARD_BTN_BG = "#dfeaf5"  # dashboard.pyのPERIOD_BTN_BGと揃えた配色
LKPT_TOGGLE_BG = "#cbb8f5"  # 「振り返りを書く」トグルの地色。CANCEL/DBのボタン
                             # 群とは異なる色相にして、視認性のある独立した
                             # チップとして目立たせる（他ボタンと被らないラベンダー）

# L/K/P/Tが何を意味するか毎回忘れてしまう問題への対応。
# 入力欄には薄字のプレースホルダを常設し、ラベル文字にホバーすると
# 正式な意味をツールチップで出す（両方あることで、操作しなくても
# ある程度察せるし、正確な定義も確認できる）
FIELD_PLACEHOLDERS = {
    "L": "今日わかったこと",
    "K": "続けたいこと",
    "P": "気になっている課題",
    "T": "次に挑戦したいこと",
}
FIELD_TOOLTIPS = {
    "L": "Learned - 今日の学び・気づき",
    "K": "Keep - 続けたいこと・良かったこと",
    "P": "Problem - 気になっている課題・懸念",
    "T": "Try - 次に挑戦したいこと",
}


class _Tooltip:
    """
    ウィジェットにホバーすると、少し遅延してから説明を吹き出しで出す
    簡易ツールチップ。Tkinter標準には無いため自前で実装する。
    """

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip_window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, event=None) -> None:
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self) -> None:
        if self._tip_window is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty()
        self._tip_window = tk.Toplevel(self.widget)
        self._tip_window.wm_overrideredirect(True)
        self._tip_window.wm_geometry(f"+{x}+{y}")
        self._tip_window.attributes("-topmost", True)
        tk.Label(
            self._tip_window, text=self.text, bg="#111122", fg=TEXT_COLOR,
            font=tkfont.Font(family="Yu Gothic UI", size=9),
            padx=8, pady=4, relief="solid", borderwidth=1,
        ).pack()

    def _hide(self, event=None) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip_window is not None:
            self._tip_window.destroy()
            self._tip_window = None


def _lighten_color(hex_color: str, factor: float = 0.78) -> str:
    """hex_colorを白方向にfactor(0〜1)だけ明るくした16進色を返す。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    factor = max(0.0, min(1.0, factor))
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(c + (255 - c) * factor) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _relative_luminance(hex_color: str) -> float:
    """WCAGの相対輝度を計算する（文字色のコントラスト判定に使う）。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)

    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAGのコントラスト比（1〜21、大きいほど読みやすい）を計算する。"""
    l1, l2 = _relative_luminance(hex1), _relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _readable_text_color(bg_hex: str) -> str:
    """
    背景色に対して、白(TEXT_COLOR)と濃紺(BUTTON_TEXT_COLOR)のどちらが
    コントラスト比が高いかを判定して返す。
    選択中バッジの文字色を、常に白固定にしていると、タグ色が明るい
    （黄・オレンジ系）場合に読みづらくなっていたための対応。
    タグの色が今後増えても、明るさによらず自動的に読みやすい方を選ぶ。
    """
    white_ratio = _contrast_ratio(bg_hex, TEXT_COLOR)
    dark_ratio = _contrast_ratio(bg_hex, BUTTON_TEXT_COLOR)
    return TEXT_COLOR if white_ratio >= dark_ratio else BUTTON_TEXT_COLOR


def _format_duration(minutes: int) -> str:
    """分数を"1h05m"形式の文字列に整形する。"""
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h{mins:02d}m"
    return f"{mins}m"


HOTKEY = "ctrl+shift+j"
VERSION = "0.15.0"

# ファイル名（daily_journal_yyyymmdd_NN.py）そのものがバージョン識別子を
# 兼ねる運用のため、ここに手で書いた文字列を置くと更新を忘れて古いまま
# 残る恐れがある。__file__から動的に取り出すことで、ファイルを
# リネームするだけで表示側も自動的に最新化される。
_FILE_STEM = os.path.splitext(os.path.basename(__file__))[0]
FILE_VERSION_LABEL = (
    _FILE_STEM[len("daily_journal_"):]
    if _FILE_STEM.startswith("daily_journal_")
    else _FILE_STEM
)

_trigger_queue = queue.Queue()

# ============================================================
# グローバルホットキー（Windows RegisterHotKey API）
# ------------------------------------------------------------
# keyboardライブラリの低レベルフックは、長時間稼働中に監視スレッドが
# 静かに停止してしまう不具合が疑われたため、OS標準のRegisterHotKey APIに
# 置き換えた。他アプリが同じ組み合わせを登録済みの場合は明示的に
# 失敗が分かるため、原因切り分けもしやすくなる。
# ============================================================
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000  # キー押しっぱなしでの連続発火を防ぐ
_WM_HOTKEY = 0x0312
_HOTKEY_ID = 1
_ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODIFIER_FLAGS = {
    "ctrl": _MOD_CONTROL,
    "alt": _MOD_ALT,
    "shift": _MOD_SHIFT,
    "win": _MOD_WIN,
}


def _parse_hotkey(hotkey: str) -> tuple:
    """"ctrl+shift+j"のような文字列を(修飾キーフラグ, 仮想キーコード)に変換する。"""
    *modifier_names, key = [part.strip().lower() for part in hotkey.split("+")]
    modifiers = 0
    for name in modifier_names:
        modifiers |= _MODIFIER_FLAGS[name]
    return modifiers, ord(key.upper())


def queue_popup_trigger() -> None:
    """
    外部モジュール（scheduler.py等）からポップアップ表示をトリガーするための
    公開関数。ホットキー検知と同じキューを使うため、スレッドセーフに扱える。
    """
    _trigger_queue.put(True)


def _hotkey_listener_loop(hotkey: str) -> None:
    """
    専用スレッドでRegisterHotKeyを登録し、WM_HOTKEYメッセージを待ち受ける。
    hWnd=NoneでRegisterHotKeyを呼ぶ場合、登録した同一スレッドでGetMessage
    ループを回す必要があるため、登録とメッセージ待受を同じ関数内で行う。
    """
    user32 = ctypes.windll.user32
    modifiers, vk = _parse_hotkey(hotkey)

    if not user32.RegisterHotKey(None, _HOTKEY_ID, modifiers | _MOD_NOREPEAT, vk):
        error_code = ctypes.GetLastError()
        hint = (
            "（他のアプリが同じキーの組み合わせを登録済みの可能性があります）"
            if error_code == _ERROR_HOTKEY_ALREADY_REGISTERED
            else ""
        )
        print(f"❌ ホットキー登録に失敗しました({hotkey})。エラーコード: {error_code} {hint}")
        return

    print(f"🔗 グローバルホットキーを登録しました: {hotkey}")

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == _WM_HOTKEY:
                _trigger_queue.put(True)
                print("⌨️ ホットキーを検知しました。")
    finally:
        user32.UnregisterHotKey(None, _HOTKEY_ID)


def register_global_hotkey(hotkey: str = HOTKEY) -> None:
    """グローバルホットキーを登録する（専用スレッドでメッセージループを待受）。"""
    thread = threading.Thread(target=_hotkey_listener_loop, args=(hotkey,), daemon=True)
    thread.start()


class PopupWindow:
    """タグ選択＋中項目＋（任意で）LKPT入力のポップアップウィンドウ。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.window = None
        self.dashboard_window = None
        self.selected_tag = None
        self.selected_subitem = None
        self.subitem_master = {}
        self.subitem_buttons = {}
        self.subitem_free_var = tk.StringVar()
        self.subitem_free_entry = None
        self.lkpt_expanded = False
        self.l_var = tk.StringVar()
        self.k_var = tk.StringVar()
        self.p_var = tk.StringVar()
        self.t_var = tk.StringVar()
        self.tag_rows = {}
        self.field_entries = {}
        self.selected_label = None
        self.time_preview_label = None
        self._popup_width = 300
        self.collapsed_height = None
        self.expanded_height = None
        self._themed_bg_widgets = []
        self._themed_fg_widgets = []

    def _register_themed(self, widget, bg: bool = True, fg: bool = False) -> None:
        """タグ選択時の背景/文字色切替に追従させるウィジェットを登録する。"""
        if bg:
            self._themed_bg_widgets.append(widget)
        if fg:
            self._themed_fg_widgets.append(widget)

    def _apply_theme(self, bg: str, fg: str) -> None:
        """登録済みウィジェットの背景色・文字色をまとめて切り替える。"""
        for widget in self._themed_bg_widgets:
            widget.configure(bg=bg)
        for widget in self._themed_fg_widgets:
            widget.configure(fg=fg)

    def show(self) -> None:
        """ポップアップを表示する。既に表示中の場合は前面化のみ行う。"""
        print("🪟 show()呼び出しを検知しました。")
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        self.selected_tag = None
        self.selected_subitem = None
        self.subitem_buttons = {}
        self.subitem_free_var.set("")
        self.subitem_free_entry = None
        self.lkpt_expanded = False
        for var in (self.l_var, self.k_var, self.p_var, self.t_var):
            var.set("")
        self.tag_rows = {}
        self.field_entries = {}
        self._themed_bg_widgets = []
        self._themed_fg_widgets = []

        try:
            tags = get_tag_master()
        except Exception as e:
            print(f"❌ タグ取得に失敗しました（Excelロック等の可能性）: {e}")
            tags = []

        try:
            self.subitem_master = get_sub_item_master()
        except Exception as e:
            print(f"❌ 中項目マスタ取得に失敗しました: {e}")
            self.subitem_master = {}

        self.window = tk.Toplevel(self.root)
        self.window.title(f"LKPT - {FILE_VERSION_LABEL}")
        self.window.configure(bg=BG_COLOR)
        self.window.attributes("-topmost", True)
        self.window.resizable(True, True)
        self._register_themed(self.window)

        row_height = 34
        # タイトル・selected_label(太字バッジ)・中項目ボタン・時間帯プレビュー・
        # LKPTトグルボタン・登録/キャンセルボタン・余白の合計目安
        # （LKPT欄自体は畳んだ状態の高さで、展開時はlkpt_block_heightを追加する）
        chrome_height = 460
        lkpt_block_height = 4 * 40 + 20
        self._popup_width = 300
        self.collapsed_height = max(360, chrome_height + row_height * len(tags))
        self.collapsed_height = min(
            self.collapsed_height, self.window.winfo_screenheight() - 100,
        )
        self.expanded_height = self.collapsed_height + lkpt_block_height

        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = screen_w - self._popup_width - 20
        y = screen_h - self.collapsed_height - 80
        self.window.geometry(f"{self._popup_width}x{self.collapsed_height}+{x}+{y}")
        min_width = int(self._popup_width * 2 / 3)
        self.window.minsize(min_width, self.collapsed_height)

        title_font = tkfont.Font(family="Yu Gothic UI", size=12, weight="bold")
        label = tk.Label(
            self.window,
            text="📝 LKPT",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=title_font,
        )
        label.pack(pady=(12, 0))
        self._register_themed(label, bg=True, fg=True)

        # 起動しているファイルが最新版かどうかを、開くたびに一目で
        # 確認できるようにする（ファイル名から動的に取り出すため、
        # 新しいバージョンのファイルを追加するだけで自動的に更新される）
        version_font = tkfont.Font(family="Consolas", size=8)
        version_label = tk.Label(
            self.window, text=FILE_VERSION_LABEL, bg=BG_COLOR, fg=PLACEHOLDER_COLOR,
            font=version_font,
        )
        version_label.pack(pady=(0, 6))
        self._register_themed(version_label, bg=True)

        tag_frame = tk.Frame(self.window, bg=BG_COLOR)
        tag_frame.pack(pady=4, fill="both", expand=True, padx=20)
        self._register_themed(tag_frame)

        dot_font = tkfont.Font(family="Yu Gothic UI", size=12)
        name_font = tkfont.Font(family="Yu Gothic UI", size=10)

        for tag_name, color_code in tags:
            row = tk.Frame(tag_frame, bg=BG_COLOR, cursor="hand2")
            row.pack(fill="x", pady=3)
            self._register_themed(row)

            dot = tk.Label(row, text="●", font=dot_font, fg=color_code, bg=BG_COLOR)
            dot.pack(side="left", padx=(4, 8))
            self._register_themed(dot)  # fgはタグ固有色のため常に固定、bgのみ追従

            name_label = tk.Label(
                row, text=tag_name, font=name_font, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w",
            )
            name_label.pack(side="left", fill="x", expand=True)
            self._register_themed(name_label, bg=True, fg=True)

            for widget in (row, dot, name_label):
                widget.bind(
                    "<Button-1>",
                    lambda e, t=tag_name, c=color_code: self._select_tag(t, c),
                )

            self.tag_rows[tag_name] = row

        selected_font = tkfont.Font(family="Yu Gothic UI", size=13, weight="bold")
        self.selected_label = tk.Label(
            self.window, text="タグ未選択", bg=BG_COLOR, fg=ACCENT_COLOR,
            font=selected_font, padx=14, pady=6,
        )
        self.selected_label.pack(pady=(10, 0))
        # 選択中バッジは一括テーマ切替(_apply_theme)の対象外にし、_select_tag内で
        # タグの生の色を直接背景に当てて目立たせる（意図的に_register_themedを呼ばない）。
        # 文字色は固定せず、_select_tag内でタグの色に応じて白/濃紺を選ぶ。

        # タグを選ぶと、そのタグの中項目（何をしていたか）をボタンで選べるように
        # なる。タグ未選択の間は空（何も表示しない）。既定は「タグ→中項目→登録」
        # の2クリックで完結させ、LKPTは別途トグルで開く任意入力にする
        # （毎時のポップアップの負荷を下げるための構成変更）
        self.subitem_frame = tk.Frame(self.window, bg=BG_COLOR)
        self.subitem_frame.pack(pady=(6, 0), padx=20, fill="x")
        self._register_themed(self.subitem_frame)
        self.subitem_font = tkfont.Font(family="Yu Gothic UI", size=10)
        self.entry_font = tkfont.Font(family="Yu Gothic UI", size=10)

        # タグ選択と同時に、これから記録される作業時間の範囲
        # （前回チェックポイント〜現在時刻）をHH:MM〜HH:MM形式で示す。
        # タグ未選択時は空文字（何も表示しない）。
        # この行はタグ選択後（＝背景がpale_bgに切り替わった後）にしか
        # 表示されないため、文字色は薄背景向けのBUTTON_TEXT_COLORで固定してよい
        preview_font = tkfont.Font(family="Consolas", size=10)
        self.time_preview_label = tk.Label(
            self.window, text="", bg=BG_COLOR, fg=BUTTON_TEXT_COLOR, font=preview_font,
            wraplength=self._popup_width - 30, justify="center",
        )
        self.time_preview_label.pack(pady=(6, 4), padx=15)
        self._register_themed(self.time_preview_label, bg=True)

        # LKPT（振り返り）は既定では畳んでおき、書きたい時だけ開く。
        # 押すたびに開閉し、ウィンドウの高さもそれに合わせて変える。
        # 以前は背景をウィンドウと同色にした「テキストリンク風」だったが、
        # ①タグ選択後の淡い背景に対してコントラスト不足になる、②地味すぎて
        # 目立たない、の両方の指摘を受けたため、独立した地色（LKPT_TOGGLE_BG）を
        # 持つ丸みのあるチップ状のボタンに変更した。タグの選択状態（テーマ）に
        # 関わらず常に同じ配色で見えるため、①の根本対応にもなっている
        toggle_font = tkfont.Font(family="Yu Gothic UI", size=10, weight="bold")
        self.lkpt_toggle_btn = tk.Button(
            self.window, text="✏️ 振り返りを書く（LKPT）",
            bg=LKPT_TOGGLE_BG, fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR, activeforeground=BUTTON_TEXT_COLOR,
            relief="flat", bd=0, highlightthickness=0, font=toggle_font, cursor="hand2",
            padx=14, pady=5,
            command=self._toggle_lkpt,
        )
        self.lkpt_toggle_btn.pack(pady=(6, 6))

        # LKPT欄自体はここで組み立てておくが、既定では畳んだ状態にするため
        # pack()はまだ呼ばない（_toggle_lkpt()で開いた時に初めてpackする）
        self._lkpt_frame = tk.Frame(self.window, bg=BG_COLOR)
        self._register_themed(self._lkpt_frame)

        lkpt_label_font = tkfont.Font(family="Yu Gothic UI", size=10, weight="bold")
        for field_label, var in (
            ("L", self.l_var), ("K", self.k_var), ("P", self.p_var), ("T", self.t_var),
        ):
            field_row = tk.Frame(self._lkpt_frame, bg=BG_COLOR)
            field_row.pack(fill="x", pady=2)
            self._register_themed(field_row)

            field_label_widget = tk.Label(
                field_row, text=field_label, font=lkpt_label_font,
                bg=BG_COLOR, fg=TEXT_COLOR, width=2,
            )
            field_label_widget.pack(side="left")
            self._register_themed(field_label_widget, bg=True, fg=True)
            _Tooltip(field_label_widget, FIELD_TOOLTIPS[field_label])

            field_entry = tk.Entry(
                field_row,
                bg=ENTRY_BG,
                fg=PLACEHOLDER_COLOR,
                insertbackground=TEXT_COLOR,
                relief="flat",
                font=self.entry_font,
                textvariable=var,
            )
            field_entry.pack(side="left", ipady=3, fill="x", expand=True)
            field_entry.insert(0, FIELD_PLACEHOLDERS[field_label])
            field_entry.bind(
                "<FocusIn>",
                lambda e, ent=field_entry, ph=FIELD_PLACEHOLDERS[field_label]:
                    self._clear_placeholder(ent, ph),
            )
            field_entry.bind(
                "<FocusOut>",
                lambda e, ent=field_entry, ph=FIELD_PLACEHOLDERS[field_label]:
                    self._restore_placeholder(ent, ph),
            )
            field_entry.bind("<Return>", lambda e: self._submit())
            self.field_entries[field_label] = field_entry

        self.btn_frame = tk.Frame(self.window, bg=BG_COLOR)
        self.btn_frame.pack(pady=6, padx=20, fill="x")
        self._register_themed(self.btn_frame)
        for col in range(3):
            # uniform="btn"を指定した3カラムに均等分割することで、
            # ボタンのテキスト長に関わらず幅を完全に揃える
            # （pack()のexpand=Trueだけでは自然サイズの差が残ってしまうため）
            self.btn_frame.columnconfigure(col, weight=1, uniform="btn")

        register_btn = tk.Button(
            self.btn_frame,
            text="✅ 登録",
            bg=ACCENT_COLOR,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            command=self._submit,
        )
        register_btn.grid(row=0, column=0, sticky="ew", padx=3)

        cancel_btn = tk.Button(
            self.btn_frame,
            text="❌ キャンセル",
            bg=CANCEL_BTN_BG,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            command=self._cancel,
        )
        cancel_btn.grid(row=0, column=1, sticky="ew", padx=3)

        dashboard_btn = tk.Button(
            self.btn_frame,
            text="📊 DB",
            bg=DASHBOARD_BTN_BG,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            command=self._open_dashboard,
        )
        dashboard_btn.grid(row=0, column=2, sticky="ew", padx=3)

        self.window.bind("<Escape>", lambda e: self._cancel())
        # Windowsが Alt キー解放をシステムメニュー呼び出しと誤認識し、
        # ウィンドウが一瞬で背面に回る不具合を防ぐための対策
        self.window.bind("<Alt-KeyPress>", lambda e: "break")
        self.window.bind("<Alt-KeyRelease>", lambda e: "break")

        # Windowsは「直前にユーザー入力の無いプロセス」からの前面化要求を
        # ブロックすることがある（タイマー発火時に顕著）。topmost属性の
        # 解除→再設定を挟むことでこの制限を回避する。
        self.window.attributes("-topmost", True)
        self.window.deiconify()
        self.window.lift()
        self.window.after(50, self._force_foreground)

    def _force_foreground(self) -> None:
        """Windowsのフォアグラウンド制限を回避しつつウィンドウを前面化する。"""
        try:
            self.window.attributes("-topmost", False)
            self.window.attributes("-topmost", True)
            self.window.lift()
            self.window.focus_force()
            print("🪟 ポップアップを前面表示しました。")
        except tk.TclError as e:
            print(f"⚠️ 前面表示に失敗しました: {e}")

    def _resize_window(self, height: int) -> None:
        """LKPT欄の開閉に合わせてウィンドウの高さを変える。幅・x座標は保つ。"""
        x = self.window.winfo_x()
        screen_h = self.window.winfo_screenheight()
        y = screen_h - height - 80
        self.window.geometry(f"{self._popup_width}x{height}+{x}+{y}")
        self.window.minsize(int(self._popup_width * 2 / 3), height)

    def _toggle_lkpt(self) -> None:
        """LKPT（振り返り）欄の開閉を切り替える。"""
        self.lkpt_expanded = not self.lkpt_expanded
        if self.lkpt_expanded:
            self._lkpt_frame.pack(pady=(4, 8), padx=20, fill="x", before=self.btn_frame)
            self.lkpt_toggle_btn.config(text="▲ 振り返りをたたむ")
            self._resize_window(self.expanded_height)
        else:
            self._lkpt_frame.pack_forget()
            self.lkpt_toggle_btn.config(text="✏️ 振り返りを書く（LKPT）")
            self._resize_window(self.collapsed_height)

    def _select_tag(self, tag_name: str, color_code: str) -> None:
        self.selected_tag = tag_name
        color_code = str(color_code).strip()
        badge_fg = _readable_text_color(color_code)
        self.selected_label.config(text=f"選択中: {tag_name}", bg=color_code, fg=badge_fg)
        try:
            pale_bg = _lighten_color(color_code, 0.78)
        except (ValueError, IndexError):
            pale_bg = "#3a3a55"
        self._apply_theme(pale_bg, BUTTON_TEXT_COLOR)
        print(f"🏷️ タグ選択: {tag_name}")
        self._build_subitem_buttons(tag_name)
        self._update_time_preview()

    def _build_subitem_buttons(self, tag_name: str) -> None:
        """
        選んだタグの中項目（何をしていたか）をボタンで選べるようにする。
        タグを切り替えるたびに作り直す（中項目の一覧自体がタグ依存のため）。
        """
        for child in self.subitem_frame.winfo_children():
            child.destroy()
        self.subitem_buttons = {}
        self.selected_subitem = None
        self.subitem_free_var.set("")
        self.subitem_free_entry = None

        items = self.subitem_master.get(tag_name, [])
        if not items:
            return

        # タグ選択によりsubitem_frame自体の背景は既にpale_bgへ切り替わって
        # いるため、新しく作る枠もそれに合わせる（テーマ管理対象外の子要素）
        current_bg = self.subitem_frame.cget("bg")

        grid = tk.Frame(self.subitem_frame, bg=current_bg)
        grid.pack(fill="x")
        for col in range(2):
            grid.columnconfigure(col, weight=1, uniform="subitem")

        for i, item in enumerate(items):
            btn = tk.Button(
                grid, text=item, bg=CANCEL_BTN_BG, fg=BUTTON_TEXT_COLOR,
                activebackground=ACCENT_COLOR, relief="flat", font=self.subitem_font,
                command=lambda it=item: self._select_subitem(it),
            )
            btn.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            self.subitem_buttons[item] = btn

        # Otherを選んだ時だけ表示する自由記述欄。他の入力欄と揃えてENTRY_BGにする
        self.subitem_free_entry = tk.Entry(
            self.subitem_frame, textvariable=self.subitem_free_var, bg=ENTRY_BG,
            fg=TEXT_COLOR, insertbackground=TEXT_COLOR, relief="flat",
            font=self.entry_font,
        )

    def _select_subitem(self, item: str) -> None:
        self.selected_subitem = item
        for name, btn in self.subitem_buttons.items():
            btn.config(bg=ACCENT_COLOR if name == item else CANCEL_BTN_BG)
        if item == OTHER_SUBITEM_LABEL:
            self.subitem_free_entry.pack(fill="x", pady=(6, 0), ipady=3)
            self.subitem_free_entry.focus_set()
        else:
            self.subitem_free_entry.pack_forget()
        print(f"🗂️ 中項目選択: {item}")

    def _resolve_subitem(self) -> str:
        """
        選択中の中項目から、TimeLogに書き込む実際の文字列を決める。
        「Other」の場合は自由記述欄の内容（未入力ならラベルそのまま）を使う。
        """
        if self.selected_subitem is None:
            return ""
        if self.selected_subitem == OTHER_SUBITEM_LABEL:
            free_text = self.subitem_free_var.get().strip()
            return free_text if free_text else OTHER_SUBITEM_LABEL
        return self.selected_subitem

    def _update_time_preview(self) -> None:
        """
        タグ選択時点で、これから記録される作業時間の範囲
        （前回チェックポイント〜現在時刻）をHH:MM〜HH:MM形式でプレビュー表示する。
        実際の登録はまだ行わないため、record_check_in()ではなく
        読み取り専用のpeek_next_time_range()を使う。
        """
        try:
            kind, start, end = peek_next_time_range()
        except Exception as e:
            print(f"⚠️ 作業時間プレビューの取得に失敗しました: {e}")
            self.time_preview_label.config(text="")
            return

        if kind == "anchor":
            self.time_preview_label.config(text="⏱ 本日の基準点として記録されます")
        else:
            self.time_preview_label.config(
                text=f"⏱ {start.strftime('%H:%M')} 〜 {end.strftime('%H:%M')} として記録されます"
            )

    def _clear_placeholder(self, entry: tk.Entry, placeholder: str) -> None:
        """フォーカスされた時、プレースホルダを表示中であれば消して入力可能にする。"""
        if str(entry.cget("fg")) == PLACEHOLDER_COLOR and entry.get() == placeholder:
            entry.delete(0, "end")
            entry.config(fg=TEXT_COLOR)

    def _restore_placeholder(self, entry: tk.Entry, placeholder: str) -> None:
        """フォーカスが外れた時、何も入力されていなければプレースホルダに戻す。"""
        if not entry.get():
            entry.insert(0, placeholder)
            entry.config(fg=PLACEHOLDER_COLOR)

    def _field_value(self, letter: str) -> str:
        """
        入力欄の実際の値を取得する。プレースホルダを表示中の場合は
        未入力（空文字）として扱う。
        """
        entry = self.field_entries[letter]
        if str(entry.cget("fg")) == PLACEHOLDER_COLOR:
            return ""
        return entry.get().strip()

    def _submit(self) -> None:
        if not self.selected_tag:
            self.selected_label.config(text="⚠️ タグを選択してください")
            return
        # そのタグに中項目が設定されている場合のみ選択を必須にする
        # （中項目未設定の新規タグ等は、従来通り中項目無しで登録できるようにする）
        if self.subitem_master.get(self.selected_tag) and not self.selected_subitem:
            self.selected_label.config(text="⚠️ 中項目を選択してください")
            return
        sub_item = self._resolve_subitem()

        l = self._field_value("L")
        k = self._field_value("K")
        p = self._field_value("P")
        t = self._field_value("T")

        success, kind, minutes = record_check_in(
            self.selected_tag, sub_item, l, k, p, t,
        )
        if not success:
            self.selected_label.config(text="⚠️ 記録に失敗しました（退避保存を確認してください）")
            print("⚠️ 記録に失敗しました（退避保存を確認してください）。")
            return

        if kind == "anchor":
            feedback = "✅ 基準点を記録しました"
        else:
            feedback = f"✅ {self.selected_tag}として記録しました ({_format_duration(minutes)})"
        self.selected_label.config(text=feedback)
        print(f"{feedback}。ポップアップを閉じます。")
        # 登録直後のフィードバックが見えるよう、少し待ってから閉じる
        self.window.after(900, self.window.destroy)

    def _cancel(self) -> None:
        """今回の入力を保存せずにポップアップを閉じる。"""
        print("🚫 入力をキャンセルしました。")
        self.window.destroy()

    def _open_dashboard(self) -> None:
        """ダッシュボードウィンドウを開く。既に開いていれば前面化のみ行う。"""
        if self.dashboard_window is not None and self.dashboard_window.winfo_exists():
            self.dashboard_window.lift()
            self.dashboard_window.focus_force()
            return

        # popup_ui側とdashboard側で同名の定数（BG_COLOR等）を持つため、
        # モジュールレベルでの衝突を避けて遅延importする
        import dashboard

        self.dashboard_window = tk.Toplevel(self.root)
        dashboard.DashboardWindow(self.dashboard_window)
        print("📊 ダッシュボードを開きました。")


def poll_trigger_queue(root: tk.Tk, popup: "PopupWindow") -> None:
    """
    トリガーキューを定期的に確認し、通知があればポップアップを表示する。
    Tkinterのメインスレッド上でroot.after()により定期実行される。
    例外が発生してもループ自体は必ず継続する（自己修復設計）。
    """
    try:
        _trigger_queue.get_nowait()
        # 修飾キー（Ctrl/Alt/L）が完全に離されるのを待ってから表示する。
        # 直後に表示すると、Windowsが Alt キー解放をシステムメニュー呼び出しと
        # 誤認識し、ウィンドウが一瞬で背面に回る不具合が発生するため。
        root.after(150, popup.show)
    except queue.Empty:
        pass
    except Exception as e:
        print(f"❌ poll_trigger_queueで例外が発生しました: {e}")
    finally:
        root.after(200, poll_trigger_queue, root, popup)


def run() -> None:
    """このファイル単体起動用のメインループ。"""
    print(f"📦 {os.path.basename(__file__)} version: {VERSION}")
    root = tk.Tk()
    root.withdraw()  # メインウィンドウ本体は非表示にする

    popup = PopupWindow(root)
    register_global_hotkey()

    root.after(200, poll_trigger_queue, root, popup)

    # 循環importおよびモジュール二重読み込みを避けるため、
    # run()内で遅延importし、自モジュールの関数をコールバックとして渡す
    from scheduler import start_scheduler_loop
    start_scheduler_loop(root, queue_popup_trigger)

    # 起動直後に一度ポップアップを表示し、本日最初のチェックイン（基準点）を
    # すぐに促す。Windowsスタートアップから自動起動された場合、次の定時
    # リマインドまで何も表示されず待たされてしまうのを防ぐため
    queue_popup_trigger()

    print(f"🚀 ポップアップUIを起動しました。ホットキー({HOTKEY})待受中...")
    root.mainloop()


if __name__ == "__main__":
    run()
