# -*- coding: utf-8 -*-
"""
outlook_calendar.py
学びジャーナル - デスクトップ版OutlookのローカルCOMインターフェースを使って
今の予定表の状態（会議中かどうか）を判定するモジュール

前提・制約：
- Windows専用。デスクトップ版Outlookが起動できる環境が必要
  （`pip install pywin32` が別途必要）
- Web版Outlook・Outlook未インストールの環境では動作しない
- Outlookが開いていない・COMエラー等が起きた場合は例外を投げるので、
  呼び出い側は必ずtry/exceptで包み、「判定できない場合は普段通り
  動く（＝ポップアップを抑制しない）」方向にフォールバックすること。
  会議検知は「あれば嬉しい」機能であり、これが原因で本体の動作を
  止めてはいけない

Version: 0.1.0
"""
from datetime import datetime, timedelta

# Outlookオブジェクトモデルのメンバー定数（OlBusyStatus / 既定フォルダID）。
# win32comのタイプライブラリを介さず直接値を書く（早期バインディング用の
# makepy生成が要らず、pywin32さえ入っていれば動く）
OL_FREE = 0
OL_TENTATIVE = 1
OL_BUSY = 2
OL_OUT_OF_OFFICE = 3
OL_WORKING_ELSEWHERE = 4

OL_FOLDER_CALENDAR = 9

# 「会議中」とみなす予定のBusyStatus。Tentative（仮）は本人が未回答なだけで
# 実際には参加しないことも多いため、あえて含めない
BUSY_STATUSES = (OL_BUSY, OL_OUT_OF_OFFICE)


def _get_calendar_items():
    """
    Outlookの既定の予定表フォルダのItemsコレクションを返す。
    呼び出しのたびにCOM接続を作る（ポップアップ本体と違って常駐しない
    定期チェックから断続的に呼ばれるため、接続を使い回すより毎回作った
    方がOutlookの再起動等の変化に強い）。
    """
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    calendar = namespace.GetDefaultFolder(OL_FOLDER_CALENDAR)
    items = calendar.Items
    items.IncludeRecurrences = True
    items.Sort("[Start]")
    return items


def _format_ol_datetime(dt: datetime) -> str:
    """OutlookのItems.Restrict()が要求する日時文字列形式に変換する。"""
    return dt.strftime("%m/%d/%Y %I:%M %p")


def _com_to_datetime(value) -> datetime:
    """
    pywintypes.datetime（タイムゾーン付き）をナイーブなdatetimeに変換する。
    本体側のdatetime（timezone無し、ローカル時刻扱い）と比較できるようにする
    """
    return datetime(
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
    )


def get_meetings_in_range(start: datetime, end: datetime) -> list:
    """
    指定した期間に重なる予定を返す。会議中判定・自動記録の両方が使う
    唯一の入口（実際のCOM呼び出しはここだけに集約し、他の関数はこれを
    使って判定するだけにする。テスト時はこの関数だけ差し替えればよい）。

    Outlookが起動していない・COMエラー等の場合は例外を投げるので、
    呼び出し側で必ずtry/exceptすること。

    Returns:
        list[dict]: [{"subject": str, "start": datetime, "end": datetime,
                       "busy_status": int, "is_meeting": bool}, ...]
    """
    items = _get_calendar_items()
    restriction = (
        f"[Start] < '{_format_ol_datetime(end)}' "
        f"AND [End] > '{_format_ol_datetime(start)}'"
    )
    restricted = items.Restrict(restriction)

    meetings = []
    for item in restricted:
        try:
            item_start = _com_to_datetime(item.Start)
            item_end = _com_to_datetime(item.End)
            busy_status = int(item.BusyStatus)
        except Exception:
            # 個々の予定の読み取りに失敗しても、他の予定の判定は続ける
            continue
        meetings.append({
            "subject": str(item.Subject or ""),
            "start": item_start,
            "end": item_end,
            "busy_status": busy_status,
            "is_meeting": busy_status in BUSY_STATUSES,
        })
    return meetings


def is_in_meeting(now: datetime = None) -> bool:
    """今この瞬間、Busy/Out of Officeの予定に入っているか。"""
    if now is None:
        now = datetime.now()
    meetings = get_meetings_in_range(now, now + timedelta(minutes=1))
    return any(m["is_meeting"] and m["start"] <= now < m["end"] for m in meetings)


def has_meeting_starting_within(minutes: int, now: datetime = None) -> bool:
    """今から指定分数以内に開始予定のBusy/Out of Officeの予定があるか。"""
    if now is None:
        now = datetime.now()
    window_end = now + timedelta(minutes=minutes)
    meetings = get_meetings_in_range(now, window_end)
    return any(m["is_meeting"] and now <= m["start"] < window_end for m in meetings)


def is_free_to_interrupt(lookahead_minutes: int = 5, now: datetime = None) -> bool:
    """
    「今、ポップアップを出してよい状況か」をまとめて判定する。
    ①今まさに会議中でない、②これから数分以内に別の会議が始まらない、
    の両方を満たす時だけTrueになる。

    会議終了後の分類ポップアップは、これがTrueになるまで発火を
    見送り続ける（1回だけ狙い撃ちするのではなく、条件が揃うまで
    毎回チェックし直す設計。次の会議が同じタイミングで始まる場合や、
    会議が予定より延長された場合の両方に対応するため）
    """
    if now is None:
        now = datetime.now()
    return (
        not is_in_meeting(now)
        and not has_meeting_starting_within(lookahead_minutes, now)
    )


def get_recently_ended_meetings(since: datetime, until: datetime = None) -> list:
    """
    since（より後）からuntil（省略時は現在時刻）までの間に終了した
    Busy/Out of Officeの予定を返す。TimeLogへの自動記録の対象探しに使う。
    sinceちょうどに終わった予定は含めない（前回チェック時に処理済みの
    可能性があるため、境界は開区間にする）
    """
    if until is None:
        until = datetime.now()
    if until <= since:
        return []
    meetings = get_meetings_in_range(since, until)
    return [m for m in meetings if m["is_meeting"] and since < m["end"] <= until]
