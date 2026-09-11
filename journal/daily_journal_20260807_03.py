# -*- coding: utf-8 -*-
"""
daily_journal_20260807_03.py
学びジャーナル - ホットキー起動の入力ポップアップUI
Version: 0.24.0
"""

import ctypes
import os
import queue
import threading
import tkinter as tk
from ctypes import wintypes
from tkinter import font as tkfont

from storage import (
    ACTION_STATUS_PENDING,
    OTHER_SUBITEM_LABEL,
    add_action,
    complete_action,
    get_actions,
    get_sub_item_master,
    get_tag_master,
    peek_next_time_range,
    record_check_in,
    set_action_priority,
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

# たまっているアクション一覧（MS To Do風の1行カード）の配色。
# ○チェックは左端・★優先は右端という参考画像のレイアウトに合わせて選定した
ACTION_CARD_BG = "#2a2a44"        # 各行の地色（BG_COLORより一段明るいダーク）
ACTION_CARD_DONE_FLASH = "#3a5a45"  # チェック直後に一瞬光らせる完了フィードバック色
ACTION_STAR_ON_COLOR = "#4a90e2"    # ★（優先）点灯時の色
ACTION_STAR_OFF_COLOR = "#7c86a8"   # ☆（未優先）の色
ACTION_CHECK_COLOR = "#9aa4c8"      # ○チェックアイコンの色

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

QUICK_ACTION_PLACEHOLDER = "気になったことをすぐ書き留める（Enterで登録）"
P_TO_ACTION_LABEL = "→ アクションにする"


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


def _blend_toward(hex_color: str, target_hex: str, ratio: float) -> str:
    """
    hex_colorをtarget_hex方向にratio(0〜1)だけ混ぜた16進色を返す。
    大項目タグチップの未選択時の地色（タグの色をうっすら地色BG_COLORに
    混ぜたもの）を作るのに使う。サブ項目ボタン（常に無彩色）との
    見分けが付くよう、未選択の間もタグ固有の色味を残しておくため
    """
    hex_color = hex_color.lstrip("#")
    target_hex = target_hex.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    ratio = max(0.0, min(1.0, ratio))
    r1, g1, b1 = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r2, g2, b2 = (int(target_hex[i:i + 2], 16) for i in (0, 2, 4))
    r = round(r1 + (r2 - r1) * ratio)
    g = round(g1 + (g2 - g1) * ratio)
    b = round(b1 + (b2 - b1) * ratio)
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
VERSION = "0.24.0"

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
        self.tag_chips = {}
        self.field_entries = {}
        self.selected_label = None
        self.time_preview_label = None
        self.pending_actions = []
        self.action_list_canvas = None
        self.action_list_inner = None
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
        self.tag_chips = {}
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

        self.pending_actions = self._fetch_pending_actions()

        self.window = tk.Toplevel(self.root)
        self.window.title(f"LKPT - {FILE_VERSION_LABEL}")
        self.window.configure(bg=BG_COLOR)
        self.window.attributes("-topmost", True)
        self.window.resizable(True, True)
        self._register_themed(self.window)

        row_height = 34
        # タイトル・selected_label(太字バッジ)・中項目ボタン・時間帯プレビュー・
        # LKPTトグルボタン・登録/キャンセル/DBボタン・＋アクション欄・
        # たまっているアクション一覧（固定4行分）・余白の合計目安
        # （LKPT欄自体は畳んだ状態の高さで、展開時はlkpt_block_heightを追加する）
        chrome_height = 650
        lkpt_block_height = 4 * 40 + 20
        self._popup_width = 300
        self.collapsed_height = max(360, chrome_height + row_height * len(tags))
        self.collapsed_height = min(
            self.collapsed_height, self.window.winfo_screenheight() - 100,
        )
        # collapsed_height同様、画面の縦幅を超えないようクランプする。
        # クランプにより画面が低い環境ではLKPT欄の下部が見切れる場合が
        # あるが、ウィンドウはresizable=Trueのため手動リサイズで対応できる
        self.expanded_height = min(
            self.collapsed_height + lkpt_block_height,
            self.window.winfo_screenheight() - 40,
        )

        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = screen_w - self._popup_width - 20
        y = max(10, screen_h - self.collapsed_height - 80)
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

        # 「選択中」バッジはタグ一覧の上に固定表示する（以前は下に表示して
        # いたが、タグ一覧を見てから選択結果を確認するまでの視線移動を
        # 減らすため、選ぶ前から見えている位置に変更した）
        selected_font = tkfont.Font(family="Yu Gothic UI", size=13, weight="bold")
        self.selected_label = tk.Label(
            self.window, text="未選択", bg=BG_COLOR, fg=ACCENT_COLOR,
            font=selected_font, padx=14, pady=6,
        )
        self.selected_label.pack(pady=(4, 4))
        # 選択中バッジは一括テーマ切替(_apply_theme)の対象外にし、_select_tag内で
        # タグの生の色を直接背景に当てて目立たせる（意図的に_register_themedを呼ばない）。
        # 文字色は固定せず、_select_tag内でタグの色に応じて白/濃紺を選ぶ。

        # タグ一覧：縦積みの行ではなく、2列のチップボタンで横に並べる
        # （「タグを横に並べませんか」との要望）。チップは未選択の間も
        # タグの色をうっすら地色に混ぜ、同色の縁取りを付ける。これにより、
        # 常に無彩色（CANCEL_BTN_BG）のサブ項目ボタンとの見分けが一目で
        # 付くようにしている（当初の「サブ項目と区別が付かない」という
        # 指摘への対応）
        self.tag_frame = tk.Frame(self.window, bg=BG_COLOR)
        self.tag_frame.pack(pady=(0, 0), fill="x", padx=20)
        self._register_themed(self.tag_frame)

        chip_font = tkfont.Font(family="Yu Gothic UI", size=10, weight="bold")
        dot_font = tkfont.Font(family="Yu Gothic UI", size=11)
        tag_cols = 2
        tag_row_frame = None

        for i, (tag_name, color_code) in enumerate(tags):
            if i % tag_cols == 0:
                tag_row_frame = tk.Frame(self.tag_frame, bg=BG_COLOR)
                tag_row_frame.pack(fill="x", pady=3)
                self._register_themed(tag_row_frame)

            chip = tk.Frame(
                tag_row_frame, bg=BG_COLOR, cursor="hand2",
                highlightthickness=1,
            )
            chip.pack(
                side="left", padx=(0 if i % tag_cols == 0 else 6, 0),
                fill="x", expand=True,
            )
            inner = tk.Frame(chip, bg=BG_COLOR)
            inner.pack(pady=7)
            dot = tk.Label(inner, text="●", font=dot_font, fg=color_code, bg=BG_COLOR)
            dot.pack(side="left", padx=(10, 4))
            name_label = tk.Label(
                inner, text=tag_name, font=chip_font, bg=BG_COLOR, fg=TEXT_COLOR,
            )
            name_label.pack(side="left", padx=(0, 10))

            for widget in (chip, inner, dot, name_label):
                widget.bind(
                    "<Button-1>",
                    lambda e, t=tag_name, c=color_code: self._select_tag(t, c),
                )

            # チップ自身の配色はテーマ一括切替(_apply_theme)の対象外にし、
            # _select_tag内で個別に塗り分ける（タグごとに異なる色を保つため、
            # 全ウィジェット一律の pale_bg/BUTTON_TEXT_COLOR には乗せない）
            self.tag_chips[tag_name] = {
                "chip": chip, "inner": inner, "dot": dot, "name": name_label,
                "color": color_code,
            }
            self._recolor_tag_chip(tag_name, selected=False)

        # 中項目（何をしていたか）ボタンと時間帯プレビューは、タググループ
        # 全体（2列チップの並び）の下にまとめて表示する。以前は選んだタグの
        # 行の直後に割り込ませていたが、「大項目タグをまとめて上に揃えた
        # 方がスッキリする」との指摘を受け、タグ一覧を最後まで表示してから
        # その下に固定表示する構成に変更した
        self.tag_detail_frame = tk.Frame(self.window, bg=BG_COLOR)
        self._register_themed(self.tag_detail_frame)

        self.subitem_frame = tk.Frame(self.tag_detail_frame, bg=BG_COLOR)
        self.subitem_frame.pack(pady=(6, 0), fill="x")
        self._register_themed(self.subitem_frame)
        self.subitem_font = tkfont.Font(family="Yu Gothic UI", size=10)
        self.entry_font = tkfont.Font(family="Yu Gothic UI", size=10)

        # タグ選択と同時に、これから記録される作業時間の範囲
        # （前回チェックポイント〜現在時刻）をHH:MM〜HH:MM形式で示す。
        # この行はタグ選択後（＝背景がpale_bgに切り替わった後）にしか
        # 表示されないため、文字色は薄背景向けのBUTTON_TEXT_COLORで固定してよい
        preview_font = tkfont.Font(family="Consolas", size=10)
        self.time_preview_label = tk.Label(
            self.tag_detail_frame, text="", bg=BG_COLOR, fg=BUTTON_TEXT_COLOR,
            font=preview_font, wraplength=self._popup_width - 30, justify="center",
        )
        self.time_preview_label.pack(pady=(6, 4))
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
            self.window, text="LKPT",
            bg=LKPT_TOGGLE_BG, fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR, activeforeground=BUTTON_TEXT_COLOR,
            relief="flat", bd=0, highlightthickness=0, font=toggle_font, cursor="hand2",
            padx=14, pady=5,
            command=self._toggle_lkpt,
        )
        # 直前の要素（時間帯プレビュー）との間に固定の間隔を空けて配置する
        self.lkpt_toggle_btn.pack(pady=(14, 6))

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

            # P（課題）だけ、そのままアクションアイテムとしても登録できる
            # チェックを添える。登録時にPの内容が空でなければ、チェックが
            # 入っている場合に限りActionsシートへも1件追加する
            if field_label == "P":
                self.p_to_action_var = tk.BooleanVar(value=False)
                check_row = tk.Frame(self._lkpt_frame, bg=BG_COLOR)
                check_row.pack(fill="x", pady=(0, 4))
                self._register_themed(check_row)
                p_to_action_check = tk.Checkbutton(
                    check_row, text=P_TO_ACTION_LABEL, variable=self.p_to_action_var,
                    bg=BG_COLOR, fg=PLACEHOLDER_COLOR, selectcolor=ENTRY_BG,
                    activebackground=BG_COLOR, activeforeground=PLACEHOLDER_COLOR,
                    font=tkfont.Font(family="Yu Gothic UI", size=9), bd=0,
                    highlightthickness=0, cursor="hand2",
                )
                p_to_action_check.pack(side="left", padx=(28, 0))
                self._register_themed(p_to_action_check, bg=True, fg=True)

        self.btn_frame = tk.Frame(self.window, bg=BG_COLOR)
        self.btn_frame.pack(pady=6, padx=20, fill="x")
        self._register_themed(self.btn_frame)
        for col in range(3):
            # uniform="btn"を指定した3カラムに均等分割することで、
            # ボタンのテキスト長に関わらず幅を完全に揃える
            # （pack()のexpand=Trueだけでは自然サイズの差が残ってしまうため）
            self.btn_frame.columnconfigure(col, weight=1, uniform="btn")

        # 登録・キャンセル・DBはアイコンのみの表示にする。同じfont=を明示的に
        # 指定して3つとも揃えないと、絵文字ごとにグリフの自然な大きさが
        # 異なり（📊が✅❌より小さく見える等）、サイズが不揃いになるため
        icon_btn_font = tkfont.Font(family="Yu Gothic UI", size=14)

        register_btn = tk.Button(
            self.btn_frame,
            text="✅",
            font=icon_btn_font,
            bg=ACCENT_COLOR,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            command=self._submit,
        )
        register_btn.grid(row=0, column=0, sticky="ew", padx=3)

        cancel_btn = tk.Button(
            self.btn_frame,
            text="❌",
            font=icon_btn_font,
            bg=CANCEL_BTN_BG,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            command=self._cancel,
        )
        cancel_btn.grid(row=0, column=1, sticky="ew", padx=3)

        dashboard_btn = tk.Button(
            self.btn_frame,
            text="📊",
            font=icon_btn_font,
            bg=DASHBOARD_BTN_BG,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            command=self._open_dashboard,
        )
        dashboard_btn.grid(row=0, column=2, sticky="ew", padx=3)

        # 「今すぐ書き留めたい」思いつきを、タグ選択の有無に関わらずいつでも
        # 記録できる常設欄。登録ボタンとは独立しており、追加してもポップアップは
        # 閉じない（1回開いている間に複数件メモできるようにするため）
        quick_action_font = tkfont.Font(family="Yu Gothic UI", size=10)
        quick_action_frame = tk.Frame(self.window, bg=BG_COLOR)
        quick_action_frame.pack(pady=(10, 2), padx=20, fill="x")
        self._register_themed(quick_action_frame)

        self.quick_action_var = tk.StringVar()
        self.quick_action_entry = tk.Entry(
            quick_action_frame, textvariable=self.quick_action_var, bg=ENTRY_BG,
            fg=PLACEHOLDER_COLOR, insertbackground=TEXT_COLOR, relief="flat",
            font=quick_action_font,
        )
        self.quick_action_entry.pack(side="left", ipady=3, fill="x", expand=True)
        self.quick_action_entry.insert(0, QUICK_ACTION_PLACEHOLDER)
        self.quick_action_entry.bind(
            "<FocusIn>",
            lambda e: self._clear_placeholder(
                self.quick_action_entry, QUICK_ACTION_PLACEHOLDER,
            ),
        )
        self.quick_action_entry.bind(
            "<FocusOut>",
            lambda e: self._restore_placeholder(
                self.quick_action_entry, QUICK_ACTION_PLACEHOLDER,
            ),
        )
        # 登録は＋ボタンではなく、基本的にEnterキーで行う仕様にする
        # （＋ボタンは廃止。プレースホルダに「Enterで登録」と明示することで
        # 押せるボタンが無くても操作方法が伝わるようにする）
        self.quick_action_entry.bind("<Return>", lambda e: self._add_quick_action())

        feedback_font = tkfont.Font(family="Yu Gothic UI", size=9)
        self.quick_action_feedback_label = tk.Label(
            self.window, text="", bg=BG_COLOR, fg=ACCENT_COLOR, font=feedback_font,
        )
        self.quick_action_feedback_label.pack(pady=(0, 2))
        self._register_themed(self.quick_action_feedback_label, bg=True, fg=True)

        # たまっているアクション一覧。MS To Doの参考画像に合わせ、○チェックは
        # 左端・★優先は右端、行は横幅いっぱいの1行カードとして縦に積む。
        # ポップアップの高さがアクション件数に比例して伸び続けないよう、
        # visible_rows件分の高さで固定し、それ以上は縦スクロールで見せる。
        # アクションを入力してもこのUI自体は閉じない前提のため、複数件
        # 書き留めた直後でもこの一覧がその場で増えていく様子が見える
        action_section_label = tk.Label(
            self.window, text="タスク", bg=BG_COLOR,
            fg=PLACEHOLDER_COLOR, font=tkfont.Font(family="Yu Gothic UI", size=9, weight="bold"),
            anchor="w",
        )
        action_section_label.pack(pady=(8, 2), padx=20, fill="x")
        self._register_themed(action_section_label, bg=True)

        action_scroll_outer = tk.Frame(self.window, bg=BG_COLOR)
        action_scroll_outer.pack(pady=(0, 10), padx=20, fill="both", expand=True)
        self._register_themed(action_scroll_outer)

        visible_rows = 4
        self.action_row_height = 40
        self.action_list_canvas = tk.Canvas(
            action_scroll_outer, bg=BG_COLOR,
            height=self.action_row_height * visible_rows, highlightthickness=0,
        )
        action_vbar = tk.Scrollbar(
            action_scroll_outer, orient="vertical", command=self.action_list_canvas.yview,
        )
        self.action_list_canvas.configure(yscrollcommand=action_vbar.set)
        # スクロールバーを先に、幅固定(fill="y"のみ)でpackしてから、
        # 残りの領域いっぱいにCanvas(fill="both", expand=True)をpackする。
        # 逆順（Canvasを先にexpand=Trueでpack）だと、Canvasがcavityを
        # 全て使い切ってしまい、後からpackするスクロールバーの幅が
        # 確保されず実質見えなくなる不具合があったため、この順序にしている
        action_vbar.pack(side="right", fill="y")
        self.action_list_canvas.pack(side="left", fill="both", expand=True)
        self._register_themed(self.action_list_canvas, bg=True)

        self.action_list_inner = tk.Frame(self.action_list_canvas, bg=BG_COLOR)
        self._action_list_window = self.action_list_canvas.create_window(
            (0, 0), window=self.action_list_inner, anchor="nw",
        )
        self.action_list_inner.bind(
            "<Configure>",
            lambda e: self.action_list_canvas.configure(
                scrollregion=self.action_list_canvas.bbox("all"),
            ),
        )
        self.action_list_canvas.bind(
            "<Configure>",
            lambda e: self.action_list_canvas.itemconfig(self._action_list_window, width=e.width),
        )
        self._register_themed(self.action_list_inner, bg=True)

        # マウスホイールでもスクロールできるようにする（スクロールバーを
        # 見つけてドラッグしなくても、一覧の上にカーソルを置いてホイールを
        # 回すだけで見られるようにするための補助）。個々の行にも
        # _render_action_rows()内で同じハンドラを紐づけている
        self.action_list_canvas.bind("<MouseWheel>", self._on_action_list_mousewheel)
        self.action_list_inner.bind("<MouseWheel>", self._on_action_list_mousewheel)

        self._render_action_rows()

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
        # 画面が低い環境でheightが大きいと、上端がマイナス座標になり
        # ウィンドウが画面外に出てしまう（存在自体は消えないが操作不能に
        # 見える）ため、上端は画面内に収まる位置でクランプする
        y = max(10, screen_h - height - 80)
        self.window.geometry(f"{self._popup_width}x{height}+{x}+{y}")
        self.window.minsize(int(self._popup_width * 2 / 3), height)

    def _toggle_lkpt(self) -> None:
        """LKPT（振り返り）欄の開閉を切り替える。"""
        self.lkpt_expanded = not self.lkpt_expanded
        if self.lkpt_expanded:
            self._lkpt_frame.pack(pady=(4, 8), padx=20, fill="x", before=self.btn_frame)
            self.lkpt_toggle_btn.config(text="LKPT")
            self._resize_window(self.expanded_height)
        else:
            self._lkpt_frame.pack_forget()
            self.lkpt_toggle_btn.config(text="LKPT")
            self._resize_window(self.collapsed_height)

    def _recolor_tag_chip(self, tag_name: str, selected: bool) -> None:
        """
        タグチップ1個分の配色を選択状態に応じて塗り分ける。
        選択中: タグの色をそのまま地色に、縁取りも同色で少し太くする。
        未選択: タグの色をうっすら地色BG_COLORに混ぜたものを地色にし、
        縁取りは同色のまま細くする（サブ項目ボタンの無彩色と区別するため、
        未選択でも色味を完全には消さない）。
        """
        widgets = self.tag_chips[tag_name]
        color = widgets["color"]
        if selected:
            bg = color
            fg = _readable_text_color(color)
            border_w = 2
        else:
            bg = _blend_toward(color, BG_COLOR, 0.72)
            fg = TEXT_COLOR
            border_w = 1
        widgets["chip"].config(bg=bg, highlightbackground=color, highlightcolor=color, highlightthickness=border_w)
        widgets["inner"].config(bg=bg)
        widgets["dot"].config(bg=bg)
        widgets["name"].config(bg=bg, fg=fg)

    def _select_tag(self, tag_name: str, color_code: str) -> None:
        self.selected_tag = tag_name
        color_code = str(color_code).strip()
        badge_fg = _readable_text_color(color_code)
        self.selected_label.config(text=tag_name, bg=color_code, fg=badge_fg)
        try:
            pale_bg = _lighten_color(color_code, 0.78)
        except (ValueError, IndexError):
            pale_bg = "#3a3a55"
        self._apply_theme(pale_bg, BUTTON_TEXT_COLOR)
        print(f"🏷️ タグ選択: {tag_name}")

        # 選ばれたタグのチップだけを選択色にし、他のチップは未選択配色に戻す
        for name in self.tag_chips:
            self._recolor_tag_chip(name, selected=(name == tag_name))

        # 中項目＋時間帯プレビューのブロックは、タググループ全体の下の
        # 固定位置に表示する。初回選択時にpackし、以降タグを切り替えても
        # 位置は動かさず、中身（_build_subitem_buttons）だけを差し替える
        if not self.tag_detail_frame.winfo_ismapped():
            self.tag_detail_frame.pack(after=self.tag_frame, fill="x", pady=(6, 0))

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

    def _quick_action_value(self) -> str:
        """＋アクション欄の実際の値を取得する（プレースホルダ表示中は空扱い）。"""
        if str(self.quick_action_entry.cget("fg")) == PLACEHOLDER_COLOR:
            return ""
        return self.quick_action_entry.get().strip()

    def _fetch_pending_actions(self) -> list:
        """
        未着手アクションの一覧を、★優先を先頭・その中は登録順（古い順）で
        取得する（取得失敗時は空リストを返す）。
        """
        try:
            pending = [
                a for a in get_actions() if a["status"] == ACTION_STATUS_PENDING
            ]
        except Exception as e:
            print(f"⚠️ 未着手アクション一覧の取得に失敗しました: {e}")
            return []
        pending.sort(key=lambda a: (not a["starred"], a["created_at"]))
        return pending

    def _on_action_list_mousewheel(self, event) -> None:
        """
        アクション一覧の上でマウスホイールを回した時にスクロールする。
        Windowsの<MouseWheel>はevent.deltaが120単位で来るため、120で割って
        1行分の単位に変換する。
        """
        self.action_list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _render_action_rows(self) -> None:
        """
        たまっているアクション一覧を、MS To Do風の1行カードとして
        縦に積んで描画し直す。★優先の切替・チェックでの完了のたびに呼ばれる。
        """
        if self.action_list_inner is None:
            return
        for child in self.action_list_inner.winfo_children():
            child.destroy()

        icon_font = tkfont.Font(family="Yu Gothic UI", size=13)
        text_font = tkfont.Font(family="Yu Gothic UI", size=10)

        for action in self.pending_actions:
            row_id = action["row"]
            row = tk.Frame(self.action_list_inner, bg=ACTION_CARD_BG)
            row.pack(side="top", fill="x", pady=(0, 3))
            row.bind("<MouseWheel>", self._on_action_list_mousewheel)

            # ○チェック（左端）。クリックで即完了＝一覧から消える
            check_btn = tk.Label(
                row, text="○", bg=ACTION_CARD_BG, fg=ACTION_CHECK_COLOR,
                font=icon_font, cursor="hand2", padx=10, pady=8,
            )
            check_btn.pack(side="left")
            check_btn.bind(
                "<Button-1>", lambda e, r=row_id: self._complete_pending_action(r),
            )
            check_btn.bind("<MouseWheel>", self._on_action_list_mousewheel)

            content = action["content"]
            label = tk.Label(
                row, text=content, bg=ACTION_CARD_BG, fg=TEXT_COLOR, font=text_font,
                anchor="w",
            )
            label.pack(side="left", fill="x", expand=True)
            # 固定文字数での省略をやめ、実際にこのラベルへ割り当てられた
            # ピクセル幅に収まる分だけ表示し、収まらない分だけ省略記号(…)を
            # 付ける。ラベルはfill="x", expand=Trueで親の残り幅いっぱいに
            # 広がるため、ウィンドウを横に広げるほど<Configure>で通知される
            # 幅が増え、表示できる文字数も連動して増える
            label.bind(
                "<Configure>",
                lambda e, lbl=label, full=content, fnt=text_font:
                    self._fit_action_row_text(lbl, full, fnt, e.width),
            )
            label.bind("<MouseWheel>", self._on_action_list_mousewheel)

            # ★優先（右端）。オンで青塗り、オフで灰アウトライン
            star_color = ACTION_STAR_ON_COLOR if action["starred"] else ACTION_STAR_OFF_COLOR
            star_char = "★" if action["starred"] else "☆"
            star_btn = tk.Label(
                row, text=star_char, bg=ACTION_CARD_BG, fg=star_color, font=icon_font,
                cursor="hand2", padx=10,
            )
            star_btn.pack(side="right")
            star_btn.bind(
                "<Button-1>", lambda e, r=row_id: self._toggle_action_star(r),
            )
            star_btn.bind("<MouseWheel>", self._on_action_list_mousewheel)

    def _fit_action_row_text(
        self, label: tk.Label, full_text: str, font: tkfont.Font, width: int,
    ) -> None:
        """
        アクション一覧の行テキストを、実際に割り当てられたピクセル幅
        （<Configure>のe.width）に収まる最大の長さまで表示し、収まらない
        場合だけ末尾に省略記号(…)を付ける。二分探索で「full_text[:n]+…」が
        widthに収まる最大のnを求める。
        """
        if width <= 4:
            return
        ellipsis = "…"
        if font.measure(full_text) <= width:
            label.config(text=full_text)
            return
        lo, hi = 0, len(full_text)
        best = ellipsis
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = full_text[:mid] + ellipsis
            if font.measure(candidate) <= width:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        label.config(text=best)

    def _complete_pending_action(self, row: int) -> None:
        """
        ○チェックをクリックしたアクションを完了にする。ポップアップ自体は
        閉じず、一覧からその行だけがその場で消える。
        """
        try:
            ok = complete_action(row)
        except Exception as e:
            print(f"❌ アクションの完了処理に失敗しました: {e}")
            ok = False
        if not ok:
            return
        self.pending_actions = [a for a in self.pending_actions if a["row"] != row]
        self._render_action_rows()

    def _toggle_action_star(self, row: int) -> None:
        """
        ★優先マークをクリックしたアクションの優先度を切り替える。
        保存に成功した場合のみ、★付きが先頭に来るよう並び替えて再描画する。
        """
        target = next((a for a in self.pending_actions if a["row"] == row), None)
        if target is None:
            return
        new_starred = not target["starred"]
        try:
            ok = set_action_priority(row, new_starred)
        except Exception as e:
            print(f"❌ 優先度の更新に失敗しました: {e}")
            ok = False
        if not ok:
            return
        target["starred"] = new_starred
        self.pending_actions.sort(key=lambda a: (not a["starred"], a["created_at"]))
        self._render_action_rows()

    def _add_quick_action(self) -> None:
        """
        ＋アクション欄の内容をActionsシートに追加する。登録ボタンとは独立して
        おり、追加してもポップアップは閉じない（続けて何件でもメモできる）。
        追加後は一覧を取得し直し、その場でカードが増えた様子を見せる。
        """
        content = self._quick_action_value()
        if not content:
            return
        try:
            ok = add_action(content, tag=self.selected_tag or "", origin="manual")
        except Exception as e:
            print(f"❌ アクションの追加に失敗しました: {e}")
            ok = False

        if ok:
            # 追加直後にプレースホルダ文字とPLACEHOLDER_COLORへ戻していたが、
            # このときEntryはまだフォーカスを持ったままなので<FocusIn>が
            # 発火せず、_clear_placeholder()が呼ばれないままfgだけが
            # PLACEHOLDER_COLORに戻ってしまっていた。続けて2件目を入力して
            # Enter/＋を押しても_quick_action_value()がfg==PLACEHOLDER_COLORを
            # 「プレースホルダ表示中＝未入力」と誤判定し、常に空文字を返して
            # 何も追加されないバグになっていた（連続入力を想定した機能なのに
            # 1件目までしか効かない状態）。
            # 空にするだけにとどめ、プレースホルダの再表示はフォーカスが
            # 外れた時の_restore_placeholder()に任せることで解消する
            self.quick_action_entry.delete(0, "end")
            self.quick_action_entry.config(fg=TEXT_COLOR)
            self._flash_quick_action_feedback("✅ アクションに追加しました")
            self.pending_actions = self._fetch_pending_actions()
            self._render_action_rows()
        else:
            self._flash_quick_action_feedback("⚠️ 追加に失敗しました")

    def _flash_quick_action_feedback(self, message: str) -> None:
        """＋アクション欄の下に一瞬だけメッセージを出し、少し待って消す。"""
        self.quick_action_feedback_label.config(text=message)
        self.window.after(
            1800, lambda: self.quick_action_feedback_label.config(text=""),
        )

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

        # Pの内容を「→ アクションにする」にチェックしていれば、Actionsにも
        # 1件追加する。LKPTの記録自体が成功した後に行うため、こちらが
        # 失敗してもチェックイン自体の結果には影響しない
        if p and self.p_to_action_var.get():
            try:
                add_action(p, tag=self.selected_tag, origin="P")
            except Exception as e:
                print(f"❌ Pのアクション化に失敗しました: {e}")

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

    def _open_dashboard(self, mode: str = "LKPT") -> None:
        """
        ダッシュボードウィンドウを開く。既に開いていれば前面化のみ行う
        （この場合、既存ウィンドウのモードはそのまま維持する）。
        modeを指定すると、その表示モードで直接開く（未着手アクション
        バッジからの1クリック遷移用。既定は従来通りLKPT）。
        """
        if self.dashboard_window is not None and self.dashboard_window.winfo_exists():
            self.dashboard_window.lift()
            self.dashboard_window.focus_force()
            return

        # popup_ui側とdashboard側で同名の定数（BG_COLOR等）を持つため、
        # モジュールレベルでの衝突を避けて遅延importする
        import dashboard

        self.dashboard_window = tk.Toplevel(self.root)
        dashboard.DashboardWindow(self.dashboard_window, initial_mode=mode)
        print(f"📊 ダッシュボードを開きました（{mode}モード）。")


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
