# -*- coding: utf-8 -*-
"""
scheduler.py
学びジャーナル - 定時強制リマインド＋ログオン時自動起動登録
Version: 0.8.0

v0.8.0での変更点：
Outlookの予定表と連携する3つの仕組みを追加した（outlook_calendar.py・
storage.pyと組み合わせて使う。いずれもOutlook/pywin32が使えない環境では
自動的に何もせず、既存のリマインド機能には影響しない）。

1. 定時リマインドが、Outlookの予定表で今が会議中と判定できる間は
   発火を抑制する（check_reminders内、_is_in_outlook_meeting()）。
2. 終了した会議の時間を、タグ未分類のままTimeLogへ自動記録する
   （check_and_record_ended_meetings）。
3. 分類待ちの会議について、①会議終了予定からCLASSIFY_AFTER_MINUTES分
   経過し、②今は会議中でなく、③数分以内に次の会議も無い、の3条件が
   揃った時だけポップアップを開かせる（check_pending_meeting_classification）。
   1点ずつ全条件を毎回チェックし直す設計のため、次の会議が同じ
   タイミングで始まる場合や、会議が延長された場合も自動的に見送られる。
   実際に「どの会議をどう分類するか」のUIはポップアップ側(show())が
   持ち、ここでは「今、開いてよいタイミングか」だけを判断する
"""

import os
import sys
import subprocess
from datetime import datetime, timedelta

# ============================================================
# 定時リマインド設定（要編集可）
# ------------------------------------------------------------
# ここに"HH:MM"形式で追加すれば、その時刻に強制ポップアップが
# 表示されます。後から自由に追加・削除してください。
# ============================================================
REMINDER_TIMES = [
    "08:00", "09:00", "10:00", "11:00", "12:00",
    "13:00", "14:00", "15:00", "16:00", "17:00", "18:00",
]

# 時刻ごとに「本日既に発火したか」を記録する内部辞書
_last_triggered = {}


def _is_in_outlook_meeting() -> bool:
    """
    Outlook連携が使える場合だけ、今が会議中かどうかを返す。
    pywin32未導入・Outlook未起動・COMエラー等、連携が使えない場合は
    常にFalse（＝これまで通り普段通りにリマインドを発火させる）を返す。
    「会議検知は、あれば嬉しい機能。これが原因で本体の動作を止めない」
    という方針のため、ここで例外を外に漏らさない
    """
    try:
        import outlook_calendar
        return outlook_calendar.is_in_meeting()
    except Exception as e:
        print(f"ℹ️ Outlookの会議中判定が使えないため、通常通り動作します: {e}")
        return False


def check_reminders(trigger_callback) -> None:
    """
    現在時刻がREMINDER_TIMESのいずれかと一致し、
    かつ本日まだ発火していない場合、trigger_callback()を呼び出す。
    ただし、Outlook連携が使える環境で今が会議中と判定できる間は、
    その時刻の発火を抑制する（本日分としては消費済み扱いにし、
    同じ時刻に何度もOutlookへ問い合わせない）。

    Args:
        trigger_callback: 発火時に呼び出す引数無しの関数
            （ポップアップUI側の queue_popup_trigger を渡す想定。本体のファイル名は
            daily_journal_yyyymmdd_NN.py形式でバージョン管理されており、
            scheduler.py自体はどのファイル名からも独立して動作する）
    """
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    for reminder_time in REMINDER_TIMES:
        if current_time_str == reminder_time:
            if _last_triggered.get(reminder_time) != today_str:
                _last_triggered[reminder_time] = today_str
                if _is_in_outlook_meeting():
                    print(f"⏰ 定時リマインド({reminder_time})はOutlookの会議中のため抑制しました。")
                    continue
                print(f"⏰ 定時リマインド({reminder_time})を発火します。")
                trigger_callback()


def start_scheduler_loop(root, trigger_callback, interval_ms: int = 30000) -> None:
    """
    Tkinterのroot.after()を用いて、定時リマインドの監視ループを開始する。
    例外が発生してもループ自体は必ず継続する（自己修復設計）。

    Args:
        root: Tkinterのルートウィンドウ
        trigger_callback: 発火時に呼び出す引数無しの関数
        interval_ms: 監視間隔（ミリ秒）。既定30秒。
    """
    try:
        check_reminders(trigger_callback)
    except Exception as e:
        print(f"❌ start_scheduler_loopで例外が発生しました: {e}")
    finally:
        root.after(interval_ms, start_scheduler_loop, root, trigger_callback, interval_ms)


# ============================================================
# Outlook会議連携（自動記録・分類の声かけ）
# ------------------------------------------------------------
# 定時リマインドとは別の監視ループにする。Outlook/pywin32が使えない
# 環境でも、こちらのループが例外を出すだけで定時リマインド自体には
# 一切影響しないようにするため
# ============================================================

# 初回起動時、last_meeting_checkが未設定の場合にどこまで遡って会議を
# 探すか（大きくしすぎると、導入日にその日の会議が一気に記録される）
INITIAL_LOOKBACK_MINUTES = 120

# 会議終了予定から何分空けて分類を尋ねるか
CLASSIFY_AFTER_MINUTES = 10

# 分類ポップアップを開いてよいと判断する際、この分数以内に次の会議が
# 開始する場合は見送る（is_free_to_interrupt()に渡すlookahead）
CLASSIFY_FREE_LOOKAHEAD_MINUTES = 5

# このプロセス内で既に一度声をかけた（ポップアップを開かせた）
# 会議のTimeLog行番号。同じ会議に何度も声をかけ続けないための記録。
# プロセスを再起動すれば自然にリセットされ、「次回起動時に改めて聞く」
# という仕様に合致する
_already_nudged_rows = set()


def check_and_record_ended_meetings(storage_path: str = None) -> None:
    """
    Outlookの予定表を見て、前回チェック以降に終了した会議を
    タグ未分類のままTimeLogへ自動記録する。Outlook連携が使えない場合は
    何もしない。
    """
    try:
        import storage
        import outlook_calendar
    except Exception:
        return

    path = storage_path or storage.EXCEL_PATH
    now = datetime.now()
    try:
        since = storage.get_last_meeting_check(
            default=now - timedelta(minutes=INITIAL_LOOKBACK_MINUTES), path=path,
        )
        ended = outlook_calendar.get_recently_ended_meetings(since, now)
        for meeting in ended:
            storage.append_meeting_time_log(
                meeting["subject"], meeting["start"], meeting["end"], path=path,
            )
        storage.set_last_meeting_check(now, path=path)
    except Exception as e:
        print(f"⚠️ 会議の自動記録チェックに失敗しました: {e}")


def check_pending_meeting_classification(trigger_callback, storage_path: str = None) -> None:
    """
    分類待ちの会議があり、かつ「今、声をかけてよい状況」（会議終了予定から
    CLASSIFY_AFTER_MINUTES分経過・今は会議中でない・数分以内に次の会議も
    無い）なら、trigger_callback()を呼んでポップアップを開かせる。
    実際の分類UIはポップアップ側(show())が持つため、ここでは開かせる
    タイミングの判断だけを行う。

    Args:
        trigger_callback: ポップアップを開かせる引数無しの関数
            （queue_popup_trigger を渡す想定）
        storage_path: Excelファイルパス（省略時はstorage.EXCEL_PATH）
    """
    try:
        import storage
        import outlook_calendar
    except Exception:
        return

    path = storage_path or storage.EXCEL_PATH
    try:
        pending = storage.get_pending_meetings(path=path)
    except Exception as e:
        print(f"⚠️ 分類待ちの会議一覧の取得に失敗しました: {e}")
        return

    now = datetime.now()
    for meeting in pending:
        row = meeting["row"]
        end = meeting["end"]
        if row in _already_nudged_rows or end is None:
            continue
        if now < end + timedelta(minutes=CLASSIFY_AFTER_MINUTES):
            continue
        try:
            free = outlook_calendar.is_free_to_interrupt(
                lookahead_minutes=CLASSIFY_FREE_LOOKAHEAD_MINUTES, now=now,
            )
        except Exception as e:
            print(f"⚠️ 会議中判定に失敗しました（分類の声かけを見送ります）: {e}")
            continue
        if not free:
            continue
        _already_nudged_rows.add(row)
        print(f"📅 会議「{meeting['subject']}」の分類を確認するため、ポップアップを開きます。")
        trigger_callback()
        return  # 1回のチェックにつき1件だけ開かせる


def start_meeting_sync_loop(
    root, trigger_callback, storage_path: str = None, interval_ms: int = 60000,
) -> None:
    """
    Outlook会議連携（自動記録＋分類の声かけ）を定期実行する監視ループ。
    start_scheduler_loop()（定時リマインド）とは独立したループにする。
    例外が発生してもループ自体は必ず継続する。

    Args:
        root: Tkinterのルートウィンドウ
        trigger_callback: 分類ポップアップを開かせる引数無しの関数
        storage_path: Excelファイルパス（省略時はstorage.EXCEL_PATH）
        interval_ms: 監視間隔（ミリ秒）。既定60秒
    """
    try:
        check_and_record_ended_meetings(storage_path)
    except Exception as e:
        print(f"❌ 会議の自動記録チェックで例外が発生しました: {e}")
    try:
        check_pending_meeting_classification(trigger_callback, storage_path)
    except Exception as e:
        print(f"❌ 会議の分類確認チェックで例外が発生しました: {e}")
    finally:
        root.after(
            interval_ms, start_meeting_sync_loop, root, trigger_callback,
            storage_path, interval_ms,
        )


def get_startup_folder() -> str:
    """
    現在のユーザーのスタートアップフォルダのパスを返す。
    """
    appdata = os.environ.get("APPDATA")
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )


def write_startup_batch_file(
    python_exe: str = None,
    script_path: str = None,
    batch_name: str = "LearningJournalAutoStart.bat",
) -> bool:
    """
    Windowsのスタートアップフォルダに、ログオン時自動起動用の
    バッチファイルを作成する。schtasksコマンドを使わないため、
    社内ポリシーでタスクスケジューラのコマンドライン登録が
    ブロックされている環境でも動作する。

    Args:
        python_exe: 使用するpython実行ファイルのパス（既定: pythonw.exeを自動探索）
        script_path: 起動対象スクリプト（既定: run_latest.py の絶対パス。
            run_latest.pyは常に最新のdaily_journal_*.pyを自動選択して起動するため、
            本体のファイル名が変わってもこの既定値を変更する必要はない）
        batch_name: 作成するバッチファイル名

    Returns:
        bool: 作成成功時True
    """
    if python_exe is None:
        python_exe = sys.executable
        pythonw_candidate = python_exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw_candidate):
            python_exe = pythonw_candidate
            print(f"🔇 コンソール非表示のpythonw.exeを使用します: {python_exe}")

    if script_path is None:
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "run_latest.py")
        )

    startup_folder = get_startup_folder()
    batch_path = os.path.join(startup_folder, batch_name)
    content = f'@echo off\nstart "" "{python_exe}" "{script_path}"\n'

    try:
        os.makedirs(startup_folder, exist_ok=True)
        with open(batch_path, "w") as f:
            f.write(content)
        print(f"✅ スタートアップフォルダにバッチファイルを作成しました: {batch_path}")
        return True
    except Exception as e:
        print(f"❌ バッチファイル作成に失敗しました: {e}")
        return False


def remove_startup_batch_file(
    batch_name: str = "LearningJournalAutoStart.bat",
) -> bool:
    """
    作成済みの自動起動バッチファイルを削除する。
    """
    startup_folder = get_startup_folder()
    batch_path = os.path.join(startup_folder, batch_name)
    try:
        if os.path.exists(batch_path):
            os.remove(batch_path)
            print(f"🗑️ バッチファイルを削除しました: {batch_path}")
            return True
        print("⚠️ 削除対象のバッチファイルが見つかりません。")
        return False
    except Exception as e:
        print(f"❌ バッチファイル削除に失敗しました: {e}")
        return False


def register_startup_task(
    python_exe: str = None,
    script_path: str = None,
    task_name: str = "LearningJournalAutoStart",
) -> bool:
    """
    Windowsタスクスケジューラに、ログオン時自動起動タスクを登録する。
    コンソール画面を表示させないため、可能な場合はpythonw.exeを使用する。

    Args:
        python_exe: 使用するpython実行ファイルのパス（既定: pythonw.exeを自動探索）
        script_path: 起動対象スクリプト（既定: run_latest.py の絶対パス。
            run_latest.pyは常に最新のdaily_journal_*.pyを自動選択して起動するため、
            本体のファイル名が変わってもこの既定値を変更する必要はない）
        task_name: タスク名

    Returns:
        bool: 登録成功時True
    """
    if python_exe is None:
        python_exe = sys.executable
        pythonw_candidate = python_exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw_candidate):
            python_exe = pythonw_candidate
            print(f"🔇 コンソール非表示のpythonw.exeを使用します: {python_exe}")
        else:
            print("⚠️ pythonw.exeが見つからないため、python.exeを使用します"
                  "（ログオン時に一瞬コンソールが表示される場合があります）。")

    if script_path is None:
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "run_latest.py")
        )

    command = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "\\"{python_exe}\\" \\"{script_path}\\"" '
        f'/sc onlogon /rl limited /f'
    )

    try:
        subprocess.run(command, shell=True, check=True)
        print(f"✅ ログオン時自動起動タスクを登録しました: {task_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ タスク登録に失敗しました: {e}")
        return False


def unregister_startup_task(task_name: str = "LearningJournalAutoStart") -> bool:
    """
    登録済みの自動起動タスクを削除する。
    """
    command = f'schtasks /delete /tn "{task_name}" /f'
    try:
        subprocess.run(command, shell=True, check=True)
        print(f"🗑️ 自動起動タスクを削除しました: {task_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ タスク削除に失敗しました: {e}")
        return False


if __name__ == "__main__":
    print("🔧 scheduler.py 単体動作確認を開始します。")
    print(f"⏰ 現在設定されているリマインド時刻: {REMINDER_TIMES}")
    print("ℹ️ 実際の定時発火はrun_latest.py（daily_journal_*.py）経由での"
          "起動時（コールバック渡し）で有効になります。")
