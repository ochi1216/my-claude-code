# -*- coding: utf-8 -*-
"""
run_latest.py
学びジャーナル - 常に最新版のdaily_journal_*.pyを自動選択して起動する
固定名のランチャー。

本体のファイル名は daily_journal_yyyymmdd_NN.py の形式でバージョン管理する
（ファイル名がバージョン識別子を兼ねる）。バッチファイル（RunConsole.bat、
Windowsスタートアップのバッチファイル）はファイル名を直接指定せず、この
run_latest.pyだけを呼ぶようにしておけば、新しいバージョンのファイルを
追加するだけで、バッチファイル側の修正なしに常に最新版が起動する。

スタートアップからはコンソールを持たないpythonw.exeで起動されるため、
起動に失敗しても画面には何も出ずに終わってしまう。それを防ぐため、
起動の成否をログに残し、失敗時はダイアログで知らせる。

また、起動のたびに「自分以外のrun_latest.py」を自動的に終了してから
起動する。古いプロセスを残したまま新しいプロセスを起動すると、
RegisterHotKeyは同じキー組み合わせを1プロセスしか保持できないため、
先に起動していた古いプロセスの方にホットキーを奪われたままになり、
「コードを更新したのに動作が変わらない」という混乱の元になるため。
Version: 1.2.0
"""

import glob
import importlib.util
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PATTERN = os.path.join(SCRIPT_DIR, "daily_journal_*.py")

# daily_journal_yyyymmdd_NN.py だけを起動対象とする。
# 「daily_journal_20260805_01 - コピー.py」「..._01_backup.py」のような
# 派生ファイルを誤って最新版と判定しないための絞り込み。
FILENAME_RE = re.compile(r"^daily_journal_(\d{8})_(\d{2})\.py$")

STARTUP_LOG = os.path.join(SCRIPT_DIR, "startup.log")


def _log(message: str) -> None:
    """起動の記録を1行追記する（「今朝ちゃんと起動したか」を後から確認するため）。"""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")
    except OSError:
        pass  # ログが書けないこと自体で起動を止めない


def _report_failure(summary: str, detail: str) -> None:
    """
    起動失敗をログに残し、ダイアログでも知らせる。
    pythonw.exe経由だとコンソールが無く、例外が完全に見えなくなるため。
    """
    _log(f"起動失敗: {summary}")
    try:
        with open(STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write(detail.rstrip() + "\n")
    except OSError:
        pass

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "学びジャーナル 起動失敗",
            f"{summary}\n\n詳細はこのログに記録しました:\n{STARTUP_LOG}",
        )
        root.destroy()
    except Exception:
        pass  # ダイアログすら出せない環境でも、ログは残っている


def _terminate_previous_instances() -> None:
    """
    自分以外のrun_latest.pyプロセスを終了する。コマンドラインに"run_latest.py"を
    含むpython.exe/pythonw.exeプロセスをPowerShell経由で列挙し、自分自身のPIDは
    除外してtaskkillする。この仕組み自体が起動を止めないよう、失敗しても
    ログに残すだけで処理は続ける。
    """
    current_pid = os.getpid()
    ps_command = (
        "Get-CimInstance Win32_Process "
        "-Filter \"Name='python.exe' or Name='pythonw.exe'\" "
        "| Where-Object { $_.CommandLine -like '*run_latest.py*' } "
        "| Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        _log(f"旧プロセスの検索に失敗しました（無視して続行します）: {e}")
        return

    killed = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        if pid == current_pid:
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True, text=True,
        )
        killed.append(pid)

    if killed:
        _log(f"旧プロセスを終了しました: PID {killed}")


def find_latest_script() -> str:
    """
    daily_journal_yyyymmdd_NN.py形式のファイルのうち、日付・連番が
    最も新しいものを返す。

    Returns:
        str: 最新版と判定したファイルの絶対パス

    Raises:
        FileNotFoundError: 対象ファイルが1件も見つからない場合
    """
    candidates = []
    for path in glob.glob(PATTERN):
        matched = FILENAME_RE.match(os.path.basename(path))
        if matched:
            candidates.append(((matched.group(1), matched.group(2)), path))

    if not candidates:
        raise FileNotFoundError(
            "起動対象のファイルが見つかりません。\n"
            f"探した場所: {SCRIPT_DIR}\n"
            "daily_journal_yyyymmdd_NN.py という名前のファイルが必要です。"
        )

    candidates.sort()
    return candidates[-1][1]


def main() -> None:
    _terminate_previous_instances()

    try:
        script_path = find_latest_script()
    except FileNotFoundError as e:
        _report_failure("起動する本体ファイルが見つかりませんでした。", str(e))
        raise

    name = os.path.basename(script_path)
    print(f"📦 最新版を起動します: {name}")

    try:
        module_name = os.path.splitext(name)[0]
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        _report_failure(
            f"{name} の読み込み中にエラーが発生しました。", traceback.format_exc(),
        )
        raise

    _log(f"起動しました: {name}")
    module.run()


if __name__ == "__main__":
    main()
