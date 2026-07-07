# -*- coding: utf-8 -*-
"""
scheduler.py
学びジャーナル - 定時強制リマインド＋ログオン時自動起動登録
Version: 0.3.0
"""

import os
import sys
import subprocess
from datetime import datetime

# ============================================================
# 定時リマインド設定（要編集可）
# ------------------------------------------------------------
# ここに"HH:MM"形式で追加すれば、その時刻に強制ポップアップが
# 表示されます。後から自由に追加・削除してください。
# ============================================================
REMINDER_TIMES = ["12:00", "17:30"]

# 時刻ごとに「本日既に発火したか」を記録する内部辞書
_last_triggered = {}


def check_reminders(trigger_callback) -> None:
    """
    現在時刻がREMINDER_TIMESのいずれかと一致し、
    かつ本日まだ発火していない場合、trigger_callback()を呼び出す。

    Args:
        trigger_callback: 発火時に呼び出す引数無しの関数
            （popup_ui.pyの queue_popup_trigger を渡す想定）
    """
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    for reminder_time in REMINDER_TIMES:
        if current_time_str == reminder_time:
            if _last_triggered.get(reminder_time) != today_str:
                _last_triggered[reminder_time] = today_str
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
        script_path: 起動対象スクリプト（既定: popup_ui.py の絶対パス）
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
            os.path.join(os.path.dirname(__file__), "popup_ui.py")
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
        script_path: 起動対象スクリプト（既定: popup_ui.py の絶対パス）
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
            os.path.join(os.path.dirname(__file__), "popup_ui.py")
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
    print("ℹ️ 実際の定時発火はpopup_ui.py経由での起動時（コールバック渡し）で有効になります。")
