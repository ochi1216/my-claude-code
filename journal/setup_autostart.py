# -*- coding: utf-8 -*-
"""
setup_autostart.py
学びジャーナル - PCログオン時の自動起動をセットアップする（1回実行するだけ）

Windowsが起動時に自動実行するのは「スタートアップフォルダ」に置かれた
ファイルだけで、Journalフォルダにバッチファイルを置いても何も起きない。
この取り違えが起きやすいため、正しい場所へバッチファイルを書き出す作業を
このスクリプトに集約する。

scheduler.write_startup_batch_file()と役割は重なるが、あちらは
「どこからも呼ばれていないライブラリ関数」であるのに対し、こちらは
ユーザーが直接実行して結果を目で確認するための入口として用意している。
書き出したあとに検証まで行うので、成功したかどうかがその場で分かる。

Version: 1.0.0
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BATCH_NAME = "LearningJournalAutoStart.bat"
LAUNCHER = "run_latest.py"


def find_pythonw() -> str:
    """
    コンソールを表示しないpythonw.exeのパスを返す。

    見つからない場合はpython.exe（sys.executable）をそのまま返す。
    その場合ログオンのたびに黒い画面が一瞬出るが、起動自体はできる。
    """
    exe = sys.executable

    # sys.executableがpython.exeなら、同じフォルダのpythonw.exeを狙う
    candidate = exe.replace("python.exe", "pythonw.exe")
    if candidate != exe and os.path.exists(candidate):
        return candidate

    # 既にpythonw.exeで実行されている場合はそのまま使える
    if os.path.basename(exe).lower() == "pythonw.exe":
        return exe

    return exe


def get_startup_folder() -> str:
    """Windowsのスタートアップフォルダのパスを返す。"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError(
            "環境変数APPDATAが取得できませんでした。"
            "このスクリプトはWindows上で実行してください。"
        )
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )


def build_batch_content(python_exe: str, script_path: str) -> str:
    """
    スタートアップに置くバッチファイルの中身を組み立てる。

    起動対象はrun_latest.pyに固定する。run_latest.pyが常に最新の
    daily_journal_*.pyを選ぶため、本体のファイル名が変わっても
    このバッチファイルを作り直す必要はない。
    """
    return (
        "@echo off\r\n"
        f'cd /d "{SCRIPT_DIR}"\r\n'
        f'start "" "{python_exe}" "{script_path}"\r\n'
    )


def write_batch(content: str, batch_path: str) -> None:
    """
    バッチファイルを書き出す。

    日本語Windowsのコマンドプロンプトはバッチファイルをcp932として読むため、
    cp932で書き出す（中身はASCIIのみだが、パスに日本語が含まれる環境でも
    壊れないようにする）。

    改行コードはcontent側で"\\r\\n"を明示しているので、テキストモードの
    自動変換（Windowsでは"\\n"->"\\r\\n"）を切っておく。切らないと
    "\\r\\r\\n"という壊れた改行になる。
    """
    os.makedirs(os.path.dirname(batch_path), exist_ok=True)
    with open(batch_path, "w", encoding="cp932", newline="") as f:
        f.write(content)


def verify(batch_path: str, python_exe: str, script_path: str) -> list:
    """書き出した結果を読み直して検証し、問題点のリストを返す。"""
    problems = []

    if not os.path.exists(batch_path):
        problems.append("バッチファイルが作成されていません")
        return problems

    try:
        with open(batch_path, "r", encoding="cp932", errors="replace") as f:
            content = f.read()
    except OSError as e:
        problems.append(f"バッチファイルを読み直せませんでした: {e}")
        return problems

    if LAUNCHER not in content:
        problems.append(f"バッチファイルが{LAUNCHER}を指していません")

    if not os.path.exists(python_exe):
        problems.append(f"Python実行ファイルが見つかりません: {python_exe}")

    if not os.path.exists(script_path):
        problems.append(f"{LAUNCHER}が見つかりません: {script_path}")

    return problems


def main() -> None:
    print("=" * 60)
    print(" 学びジャーナル 自動起動セットアップ")
    print("=" * 60)

    script_path = os.path.join(SCRIPT_DIR, LAUNCHER)
    python_exe = find_pythonw()

    try:
        startup_folder = get_startup_folder()
    except RuntimeError as e:
        print(f"\n[NG] {e}")
        return

    batch_path = os.path.join(startup_folder, BATCH_NAME)

    print("\n[1] 設定内容")
    print("-" * 60)
    print(f"  Journalフォルダ  : {SCRIPT_DIR}")
    print(f"  起動対象         : {script_path}")
    print(f"  Python           : {python_exe}")
    if os.path.basename(python_exe).lower() != "pythonw.exe":
        print("      ※pythonw.exeが見つからなかったため、python.exeを使います。")
        print("        ログオン時に黒い画面が一瞬表示されますが、動作に支障はありません。")
    print(f"  書き出し先       : {batch_path}")

    print("\n[2] バッチファイルの書き出し")
    print("-" * 60)
    content = build_batch_content(python_exe, script_path)
    try:
        write_batch(content, batch_path)
        print("  [OK] 書き出しました。中身は次の通りです:")
        for line in content.splitlines():
            if line.strip():
                print(f"       {line}")
    except OSError as e:
        print(f"  [NG] 書き出しに失敗しました: {e}")
        print("       スタートアップフォルダへの書き込みが")
        print("       社内ポリシーで禁止されている可能性があります。")
        return

    print("\n[3] 検証")
    print("-" * 60)
    problems = verify(batch_path, python_exe, script_path)
    if problems:
        for i, p in enumerate(problems, 1):
            print(f"  [NG] {i}. {p}")
    else:
        print("  [OK] 自動起動の設定は正しくつながっています。")
        print("       次回のPC起動（ログオン）から自動的に立ち上がります。")

    # Journalフォルダに紛れ込んだ同名バッチは、置いてあっても何も起きない。
    # 消すかどうかはユーザーの判断に委ねるが、存在は必ず知らせる。
    stray = os.path.join(SCRIPT_DIR, BATCH_NAME)
    if os.path.exists(stray):
        print("\n[4] 注意")
        print("-" * 60)
        print(f"  Journalフォルダにも{BATCH_NAME}があります:")
        print(f"       {stray}")
        print("  こちらは置いてあっても自動実行されません（紛らわしいだけです）。")
        print("  削除して構いません。再度必要になれば、このスクリプトを")
        print("  もう一度実行すれば作り直せます。")

    print()


if __name__ == "__main__":
    main()
    input("Enterキーで終了します...")
