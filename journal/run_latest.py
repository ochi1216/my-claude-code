# -*- coding: utf-8 -*-
"""
run_latest.py
学びジャーナル - 常に最新版のdaily_journal_*.pyを自動選択して起動する
固定名のランチャー。

本体のファイル名は今後 daily_journal_yyyymmdd_NN.py の形式でバージョン管理する
（ファイル名がバージョン識別子を兼ねる）。バッチファイル（RunConsole.bat、
Windowsスタートアップのバッチファイル）はファイル名を直接指定せず、この
run_latest.pyだけを呼ぶようにしておけば、新しいバージョンのファイルを
追加するだけで、バッチファイル側の修正なしに常に最新版が起動する。
Version: 1.0.0
"""

import glob
import importlib.util
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PATTERN = os.path.join(SCRIPT_DIR, "daily_journal_*.py")


def find_latest_script() -> str:
    """
    daily_journal_yyyymmdd_NN.py形式のファイルのうち、ファイル名の文字列比較で
    最も新しいものを返す。yyyymmdd・NNともゼロ埋め桁数を揃えて運用する前提のため、
    文字列としてソートするだけで日付・連番の新しい順に並ぶ。

    Returns:
        str: 最新版と判定したファイルの絶対パス

    Raises:
        FileNotFoundError: daily_journal_*.pyが1件も見つからない場合
    """
    candidates = sorted(glob.glob(PATTERN))
    if not candidates:
        raise FileNotFoundError(
            f"起動対象のdaily_journal_*.pyが見つかりません（検索パターン: {PATTERN}）"
        )
    return candidates[-1]


def main() -> None:
    script_path = find_latest_script()
    module_name = os.path.splitext(os.path.basename(script_path))[0]
    print(f"📦 最新版を起動します: {os.path.basename(script_path)}")

    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module.run()


if __name__ == "__main__":
    main()
