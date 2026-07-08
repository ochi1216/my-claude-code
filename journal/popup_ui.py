# -*- coding: utf-8 -*-
"""
popup_ui.py
学びジャーナル - ホットキー起動の入力ポップアップUI
Version: 0.6.0
"""

import ctypes
import queue
import threading
import tkinter as tk
from ctypes import wintypes
from tkinter import font as tkfont
from datetime import datetime

from storage import append_entry, get_tag_master

# ============================================================
# UI設定（ダークテーマ）
# ============================================================
BG_COLOR = "#1a1a2e"
ACCENT_COLOR = "#f4a6b8"
TEXT_COLOR = "#ffffff"
ENTRY_BG = "#0f3460"
BUTTON_TEXT_COLOR = "#2b2b40"
CANCEL_BTN_BG = "#d8d8e6"

HOTKEY = "ctrl+shift+j"
VERSION = "0.6.0"

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
    """タグ選択＋1行入力のポップアップウィンドウ。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.window = None
        self.selected_tag = None
        self.memo_var = tk.StringVar()
        self.tag_buttons = {}
        self.selected_label = None

    def show(self) -> None:
        """ポップアップを表示する。既に表示中の場合は前面化のみ行う。"""
        print("🪟 show()呼び出しを検知しました。")
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        self.selected_tag = None
        self.memo_var.set("")

        self.window = tk.Toplevel(self.root)
        self.window.title("今日の学び")
        self.window.configure(bg=BG_COLOR)
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)

        width, height = 360, 220
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = screen_w - width - 20
        y = screen_h - height - 80
        self.window.geometry(f"{width}x{height}+{x}+{y}")

        title_font = tkfont.Font(family="Yu Gothic UI", size=12, weight="bold")
        label = tk.Label(
            self.window,
            text="📝 今日の気づき・学び",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=title_font,
        )
        label.pack(pady=(12, 6))

        tag_frame = tk.Frame(self.window, bg=BG_COLOR)
        tag_frame.pack(pady=4)

        try:
            tags = get_tag_master()
        except Exception as e:
            print(f"❌ タグ取得に失敗しました（Excelロック等の可能性）: {e}")
            tags = []
        for tag_name, color_code in tags:
            btn = tk.Button(
                tag_frame,
                text=tag_name,
                bg=color_code,
                fg=TEXT_COLOR,
                activebackground=ACCENT_COLOR,
                relief="flat",
                width=10,
                command=lambda t=tag_name: self._select_tag(t),
            )
            btn.pack(side="left", padx=4)
            self.tag_buttons[tag_name] = btn

        self.selected_label = tk.Label(
            self.window, text="タグ未選択", bg=BG_COLOR, fg=ACCENT_COLOR,
        )
        self.selected_label.pack(pady=(6, 2))

        entry = tk.Entry(
            self.window,
            textvariable=self.memo_var,
            width=38,
            bg=ENTRY_BG,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat",
        )
        entry.pack(pady=8, ipady=4)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._submit())

        btn_frame = tk.Frame(self.window, bg=BG_COLOR)
        btn_frame.pack(pady=6)

        cancel_btn = tk.Button(
            btn_frame,
            text="❌ キャンセル",
            bg=CANCEL_BTN_BG,
            fg=BUTTON_TEXT_COLOR,
            activebackground=ACCENT_COLOR,
            relief="flat",
            width=14,
            command=self._cancel,
        )
        cancel_btn.pack(side="left", padx=4)

        self.window.bind("<Escape>", lambda e: self.window.destroy())
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

    def _select_tag(self, tag_name: str) -> None:
        self.selected_tag = tag_name
        self.selected_label.config(text=f"選択中: {tag_name}")
        print(f"🏷️ タグ選択: {tag_name}")

    def _submit(self) -> None:
        memo = self.memo_var.get().strip()
        if not self.selected_tag:
            self.selected_label.config(text="⚠️ タグを選択してください")
            return
        if not memo:
            self.selected_label.config(text="⚠️ 1行メモを入力してください")
            return

        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        success = append_entry(date_str, self.selected_tag, memo)
        if success:
            print("✅ 記録が完了しました。ポップアップを閉じます。")
        else:
            print("⚠️ 記録に失敗しました（退避保存を確認してください）。")
        self.window.destroy()

    def _cancel(self) -> None:
        """今回の入力を保存せずにポップアップを閉じる。"""
        print("🚫 入力をキャンセルしました。")
        self.window.destroy()


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
    """popup_ui.py 単体起動用のメインループ。"""
    print(f"📦 popup_ui.py version: {VERSION}")
    root = tk.Tk()
    root.withdraw()  # メインウィンドウ本体は非表示にする

    popup = PopupWindow(root)
    register_global_hotkey()

    root.after(200, poll_trigger_queue, root, popup)

    # 循環importおよびモジュール二重読み込みを避けるため、
    # run()内で遅延importし、自モジュールの関数をコールバックとして渡す
    from scheduler import start_scheduler_loop
    start_scheduler_loop(root, queue_popup_trigger)

    print(f"🚀 ポップアップUIを起動しました。ホットキー({HOTKEY})待受中...")
    root.mainloop()


if __name__ == "__main__":
    run()
