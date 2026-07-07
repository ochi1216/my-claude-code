# -*- coding: utf-8 -*-
"""
storage.py
学びジャーナル - Excel(SharePoint同期フォルダ)読み書きモジュール
Version: 0.1.0
"""

import os
import time
import shutil
from datetime import datetime
from openpyxl import Workbook, load_workbook

# ============================================================
# 設定値（要編集）
# ------------------------------------------------------------
# TODO: 越智さんのSharePoint(OneDrive)同期フォルダの実際のパスに
#       書き換えてください。例:
#       r"C:\Users\nx023836\Nexperia\JP Site - Journal\journal_data.xlsx"
# ============================================================
EXCEL_PATH = r"C:\Users\nx023836\Documents\PythonScripts\Journal\journal_data.xlsx"

ENTRIES_SHEET = "Entries"
TAGMASTER_SHEET = "TagMaster"

ENTRIES_HEADER = ["日付", "タグ", "メモ"]
TAGMASTER_HEADER = ["タグ名", "色コード"]

DEFAULT_TAGS = [
    ("R19", "#d9ae23"),
    ("JP Site", "#2fa84f"),
    ("NPI", "#c2399e"),
    ("その他", "#e08830"),
]

MAX_RETRIES = 3
RETRY_WAIT_SEC = 1.5


def ensure_workbook_exists(path: str = EXCEL_PATH) -> None:
    """
    Excelブックが存在しない場合、Entries/TagMasterシートを
    初期タグ付きで新規作成する。
    """
    if os.path.exists(path):
        print(f"📘 既存ブックを検出しました: {path}")
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)

    wb = Workbook()

    ws_entries = wb.active
    ws_entries.title = ENTRIES_SHEET
    ws_entries.append(ENTRIES_HEADER)

    ws_tags = wb.create_sheet(TAGMASTER_SHEET)
    ws_tags.append(TAGMASTER_HEADER)
    for tag_name, color_code in DEFAULT_TAGS:
        ws_tags.append([tag_name, color_code])

    wb.save(path)
    print(f"✅ 新規ブックを作成しました: {path}")


def _load_with_retry(path: str, max_retries: int = MAX_RETRIES,
                      retry_wait: float = RETRY_WAIT_SEC):
    """
    OneDrive同期等によるファイルロックを考慮し、
    リトライ付きでワークブックを読み込む内部関数。
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            wb = load_workbook(path)
            return wb
        except PermissionError as e:
            last_error = e
            print(f"⏳ ファイルがロック中です。{retry_wait}秒後に再試行します "
                  f"({attempt}/{max_retries})")
            time.sleep(retry_wait)
    print(f"❌ ファイルを開けませんでした（ロック解除待ちタイムアウト）: {last_error}")
    raise last_error


def _save_with_retry(wb, path: str, max_retries: int = MAX_RETRIES,
                      retry_wait: float = RETRY_WAIT_SEC) -> bool:
    """
    保存時のロック競合に対してリトライを行う内部関数。
    最終的に失敗した場合はローカル一時ファイルへ退避保存する。
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            wb.save(path)
            print(f"💾 保存に成功しました: {path}")
            return True
        except PermissionError as e:
            last_error = e
            print(f"⏳ 保存時にロック中です。{retry_wait}秒後に再試行します "
                  f"({attempt}/{max_retries})")
            time.sleep(retry_wait)

    # 最終フォールバック: ローカル退避ファイルに保存し、後で手動マージできるようにする
    fallback_dir = os.path.join(os.path.dirname(path), "_unsynced_fallback")
    os.makedirs(fallback_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fallback_path = os.path.join(
        fallback_dir, f"fallback_{timestamp}.xlsx"
    )
    try:
        wb.save(fallback_path)
        print(f"⚠️ 本保存に失敗したため、退避ファイルに保存しました: {fallback_path}")
        print("⚠️ 後ほど手動でマージしてください。")
    except Exception as fallback_error:
        print(f"❌ 退避保存にも失敗しました: {fallback_error}")
        raise fallback_error from last_error

    return False


def append_entry(date_str: str, tag: str, memo: str,
                  path: str = EXCEL_PATH) -> bool:
    """
    Entriesシートに1行追記する。

    Args:
        date_str: "YYYY-MM-DD HH:MM" 形式の日時文字列
        tag: タグ名（TagMasterに存在するものを推奨）
        memo: 1行メモ
        path: Excelファイルパス

    Returns:
        bool: 保存に成功した場合True
    """
    ensure_workbook_exists(path)
    wb = _load_with_retry(path)

    if ENTRIES_SHEET not in wb.sheetnames:
        print(f"❌ シート'{ENTRIES_SHEET}'が見つかりません。")
        return False

    ws = wb[ENTRIES_SHEET]
    ws.append([date_str, tag, memo])

    success = _save_with_retry(wb, path)
    if success:
        print(f"📝 記録しました → [{date_str}] [{tag}] {memo}")
    return success


def undo_last_entry(path: str = EXCEL_PATH) -> bool:
    """
    Entriesシートの最終行（直近の記録1件）を削除する。

    Returns:
        bool: 削除に成功した場合True。削除対象が無い場合False。
    """
    ensure_workbook_exists(path)
    wb = _load_with_retry(path)
    ws = wb[ENTRIES_SHEET]

    if ws.max_row <= 1:
        print("ℹ️ 取り消せる記録がありません。")
        return False

    ws.delete_rows(ws.max_row)
    success = _save_with_retry(wb, path)
    if success:
        print("↩️ 直近の記録を取り消しました。")
    return success


def get_tag_master(path: str = EXCEL_PATH) -> list:
    """
    TagMasterシートからタグ一覧を取得する。

    Returns:
        list[tuple[str, str]]: (タグ名, 色コード) のリスト
    """
    ensure_workbook_exists(path)
    wb = _load_with_retry(path)
    ws = wb[TAGMASTER_SHEET]

    tags = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            tags.append((row[0], row[1]))

    print(f"🏷️ タグ一覧を取得しました（{len(tags)}件）")
    return tags


def add_tag(tag_name: str, color_code: str, path: str = EXCEL_PATH) -> bool:
    """
    TagMasterシートに新規タグを追加する。既存の場合は追加しない。
    """
    ensure_workbook_exists(path)
    wb = _load_with_retry(path)
    ws = wb[TAGMASTER_SHEET]

    existing = [row[0] for row in ws.iter_rows(min_row=2, values_only=True)]
    if tag_name in existing:
        print(f"⚠️ タグ'{tag_name}'は既に存在します。追加をスキップしました。")
        return False

    ws.append([tag_name, color_code])
    success = _save_with_retry(wb, path)
    if success:
        print(f"➕ タグ'{tag_name}'を追加しました。")
    return success


def remove_tag(tag_name: str, path: str = EXCEL_PATH) -> bool:
    """
    TagMasterシートから指定タグを削除する。
    """
    ensure_workbook_exists(path)
    wb = _load_with_retry(path)
    ws = wb[TAGMASTER_SHEET]

    target_row = None
    for idx, row in enumerate(
        ws.iter_rows(min_row=2, values_only=True), start=2
    ):
        if row[0] == tag_name:
            target_row = idx
            break

    if target_row is None:
        print(f"⚠️ タグ'{tag_name}'が見つかりませんでした。")
        return False

    ws.delete_rows(target_row)
    success = _save_with_retry(wb, path)
    if success:
        print(f"➖ タグ'{tag_name}'を削除しました。")
    return success


if __name__ == "__main__":
    print("🔧 storage.py 単体動作確認を開始します。")
    ensure_workbook_exists()
    tags = get_tag_master()
    for name, color in tags:
        print(f"  ・{name} ({color})")
    print("✅ 単体動作確認が完了しました。")
