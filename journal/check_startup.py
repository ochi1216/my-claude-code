# -*- coding: utf-8 -*-
"""
check_startup.py
学びジャーナル - 自動起動シーケンスの診断ツール

PCログオン時の自動起動は
    スタートアップフォルダのバッチファイル
        -> pythonw.exe run_latest.py
            -> daily_journal_yyyymmdd_NN.py のうち最新版
という流れで動く。このうちバッチファイルだけはリポジトリの外
（Windowsのスタートアップフォルダ）にあり、手で置き換える必要があるため、
ファイル名を変更した際に更新漏れが起きやすい。

このスクリプトは上記の連鎖を順に確認し、どこが切れているかを指摘する。
Version: 1.0.0
"""

import glob
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BATCH_NAME = "LearningJournalAutoStart.bat"
LAUNCHER = "run_latest.py"

problems = []


def title(text: str) -> None:
    print()
    print(text)
    print("-" * 58)


def ok(text: str) -> None:
    print(f"  [OK] {text}")


def ng(text: str) -> None:
    print(f"  [NG] {text}")
    problems.append(text)


def info(text: str) -> None:
    print(f"       {text}")


def get_startup_folder() -> str:
    """Windowsのスタートアップフォルダのパスを返す（scheduler.pyと同じ場所）。"""
    try:
        from scheduler import get_startup_folder as _f
        return _f()
    except Exception:
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(
            appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
        )


def check_journal_folder() -> None:
    title(f"[1] Journalフォルダ  {SCRIPT_DIR}")

    if os.path.exists(os.path.join(SCRIPT_DIR, LAUNCHER)):
        ok(f"{LAUNCHER} があります")
    else:
        ng(f"{LAUNCHER} がありません。Journalフォルダに配置してください")

    bodies = sorted(glob.glob(os.path.join(SCRIPT_DIR, "daily_journal_*.py")))
    if bodies:
        ok(f"本体ファイルが {len(bodies)} 件あります")
        for path in bodies:
            info(os.path.basename(path))
    else:
        ng("daily_journal_*.py がありません。本体ファイルを配置してください")

    # run_latest.py がどれを最新と判定するかを、実際の関数で確かめる
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from run_latest import find_latest_script
        info(f"-> 起動対象と判定: {os.path.basename(find_latest_script())}")
    except Exception as e:
        ng(f"最新版の判定に失敗しました: {e}")

    if os.path.exists(os.path.join(SCRIPT_DIR, "popup_ui.py")):
        info("旧popup_ui.py が残っています（削除して構いません）")


def check_startup_batch() -> None:
    folder = get_startup_folder()
    title(f"[2] スタートアップフォルダ  {folder}")

    batch_path = os.path.join(folder, BATCH_NAME)
    if not os.path.exists(batch_path):
        ng(f"{BATCH_NAME} がありません。ログオン時に何も起動しません")
        return

    ok(f"{BATCH_NAME} があります")
    try:
        with open(batch_path, "r", encoding="cp932", errors="replace") as f:
            content = f.read()
    except OSError as e:
        ng(f"バッチファイルを読めませんでした: {e}")
        return

    info("中身:")
    for line in content.splitlines():
        if line.strip():
            info(f"  {line}")

    if LAUNCHER in content:
        ok(f"{LAUNCHER} を正しく指しています")
    else:
        ng(
            f"バッチファイルが {LAUNCHER} を指していません。"
            "★これが自動起動しなかった原因です"
        )
        if "popup_ui.py" in content:
            info("古い popup_ui.py を指したままです。このファイルは"
                 "リネーム済みで存在しないため、無言で失敗します")

    # バッチが指しているpython実行ファイルが実在するか。
    # "C:\Program Files\Python\..." のようにパス自体に空白を含むため、
    # 空白分割ではなく引用符で囲まれた区間をそのまま取り出す。
    # start コマンドの第1引数 "" (ウィンドウタイトル、空文字列) を挟むと
    # 単純な"([^"]+)"では引用符の対応がずれるため、ドライブレターで
    # 始まる区間だけを対象にする
    for token in re.findall(r'"([A-Za-z]:[^"]*)"', content):
        if token.lower().endswith(("python.exe", "pythonw.exe")):
            if os.path.exists(token):
                ok(f"Python実行ファイルがあります: {token}")
            else:
                ng(f"Python実行ファイルが見つかりません: {token}")


def check_startup_log() -> None:
    title("[3] 起動ログ（最近10件）")
    log_path = os.path.join(SCRIPT_DIR, "startup.log")
    if not os.path.exists(log_path):
        info("まだログがありません。")
        info("新しいrun_latest.pyで一度起動すると作られます。")
        return

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [l.rstrip() for l in f if l.strip()]
    for line in lines[-10:]:
        info(line)


def main() -> None:
    print("=" * 58)
    print(" 学びジャーナル 自動起動シーケンス 診断")
    print("=" * 58)

    check_journal_folder()
    check_startup_batch()
    check_startup_log()

    title("診断結果")
    if problems:
        print(f"  {len(problems)} 件の問題が見つかりました:")
        for i, p in enumerate(problems, 1):
            print(f"    {i}. {p}")
    else:
        print("  問題は見つかりませんでした。")
        print("  自動起動の設定は正しくつながっています。")
    print()


if __name__ == "__main__":
    main()
    input("Enterキーで終了します...")
