# -*- coding: utf-8 -*-
"""検証ハーネス共通モジュール

各テストはこのモジュール経由で本体を読み込む。
バージョンをファイル名で管理している都合上、テスト側にバージョンを直書きすると
版が上がるたびに全テストの修正が必要になるため、**最新版を自動検出**する。
（フォルダ直下に最新版だけが残る運用のため、通常は1つしか見つからない）
"""
import importlib
import re
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent

_VERSION_RE = re.compile(r"^document_search_manager_(\d{8})_(\d+)\.py$")


def load_latest():
    """フォルダ直下で最も新しいバージョンの本体スクリプトを読み込む。"""
    candidates = []
    for path in TOOL_DIR.glob("document_search_manager_*.py"):
        match = _VERSION_RE.match(path.name)
        if match:
            candidates.append(((match.group(1), int(match.group(2))), path))

    if not candidates:
        raise SystemExit(
            f"本体スクリプトが見つかりません: {TOOL_DIR}\n"
            "document_search_manager_YYYYMMDD_NN.py を配置してください。"
        )

    candidates.sort()
    target = candidates[-1][1]
    if str(TOOL_DIR) not in sys.path:
        sys.path.insert(0, str(TOOL_DIR))
    return importlib.import_module(target.stem), target.name


dsm, DSM_FILENAME = load_latest()


class Checker:
    """テスト結果を数え上げる小さなヘルパー。"""

    def __init__(self):
        self.ok = 0
        self.ng = 0

    def __call__(self, label, condition, detail=""):
        if condition:
            self.ok += 1
            print(f"  OK   {label}")
        else:
            self.ng += 1
            print(f"  NG   {label}  {detail}")

    def finish(self):
        print(f"\n{'=' * 46}")
        print(f"  成功 {self.ok} 件 / 失敗 {self.ng} 件")
        print(f"{'=' * 46}")
        sys.exit(1 if self.ng else 0)


class DummyAuth:
    """Graph API を呼ばずにテストするためのダミー認証。"""

    def get_token(self, scopes):
        return "dummy-token"
