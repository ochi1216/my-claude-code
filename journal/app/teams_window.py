# -*- coding: utf-8 -*-
"""
teams_window.py
学びジャーナル - デスクトップ版Teamsのウィンドウタイトルを見て、
「その会議のTeamsウィンドウがまだ開いているか」を確認するモジュール

背景・位置づけ：
Outlook予定表だけでは「会議が予定より延長されている」ことを検知できない
（予定表上の終了時刻は、誰かが手動で予定を編集して延ばさない限り更新
されないため）。実際に会議終了10分後の分類ポップアップが、会議が延長
されて継続中にもかかわらず出現してしまう事例が発生した。

Teamsは、会議中は常時表示のチャット窓とは別に、Outlookの会議名を
そのままタイトルに使った「会議中の窓」をデスクトップに表示する
（越智さんの環境での実際の挙動）。そこで、Outlook側で知っている
会議の件名を使って「その件名を含むタイトルのTeamsウィンドウが今も
存在するか」を確認し、Outlook予定表だけでは分からない延長を補助的に
検知する。

前提・制約：
- Windows専用。ctypes経由でuser32.dll/kernel32.dllを直接呼ぶため、
  outlook_calendar.py（pywin32必須）と異なり新規の外部依存は増えない
- Teamsのウィンドウ構成・タイトル形式は非公式な挙動であり、Microsoftの
  アップデートで変わる可能性がある（新Teams/旧Teamsでプロセス名も異なる）。
  そのため、ここでの判定はあくまで補助信号として扱い、失敗しても
  例外を外に漏らさず、呼び出し側は「検知できなければ普段通り動く
  （＝会議中とは判定しない＝ポップアップを止めない）」方向に
  フォールバックすること
- Outlook予定表を置き換えるものではない。会議の存在・自動記録・次の
  会議の予定判定は引き続きoutlook_calendar.py（Outlook予定表）が担い、
  本モジュールは「分類ポップアップを出してよいか」の最終判定を
  補強するためだけに使う

Version: 0.1.0
"""
import ctypes
from ctypes import wintypes

# 新Teams(ms-teams.exe)・旧Teams(Teams.exe、2024年に順次廃止)の両方を見る
TEAMS_PROCESS_NAMES = ("ms-teams.exe", "teams.exe")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _get_process_name(pid: int) -> str:
    """
    プロセスIDから実行ファイル名（小文字、パスなし）を取得する。
    権限不足・プロセス終了済み等で取得できない場合は空文字列を返す。
    """
    kernel32 = ctypes.windll.kernel32
    h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_process:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        buf_len = wintypes.DWORD(260)
        ok = kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(buf_len))
        if not ok:
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(h_process)


def get_teams_window_titles() -> list:
    """
    現在デスクトップに存在するTeamsプロセスの可視ウィンドウのタイトルを
    すべて返す。常時表示のチャット窓・会議中の窓が両方開いていれば、
    両方のタイトルが入る（呼び出し側でどちらかを気にする必要は無く、
    「会議名を含むタイトルが1つでもあるか」だけを見ればよい設計）。
    """
    user32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _get_process_name(pid.value) not in TEAMS_PROCESS_NAMES:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value:
            titles.append(buf.value)
        return True

    user32.EnumWindows(_enum_proc, 0)
    return titles


def is_meeting_window_open(subject: str) -> bool:
    """
    指定した会議名（Outlookの件名）を含むタイトルのTeamsウィンドウが
    今デスクトップに存在するかを返す。

    件名が空文字列の場合や、Teamsウィンドウが1つも見つからない場合は
    「開いていない」＝Falseを返す（判定できない時に会議中と誤判定して
    ポップアップを止め続けるより、安全側＝普段通り動く方向に倒す）。
    """
    subject = (subject or "").strip()
    if not subject:
        return False
    titles = get_teams_window_titles()
    return any(subject in title for title in titles)
