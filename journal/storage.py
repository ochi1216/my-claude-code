# -*- coding: utf-8 -*-
"""
storage.py
学びジャーナル - Excel(SharePoint同期フォルダ)読み書きモジュール
Version: 0.8.0
"""

import os
import time
import shutil
from datetime import datetime, timedelta
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
TIMELOG_SHEET = "TimeLog"

ENTRIES_HEADER = ["日付", "タグ", "L", "K", "P", "T"]
TAGMASTER_HEADER = ["タグ名", "色コード"]
TIMELOG_HEADER = ["開始", "終了", "タグ"]

# 前回チェックポイントから長時間経過していた場合の安全弁（この時間で打ち切る）
MAX_TIMELOG_GAP_HOURS = 2

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

    ws_timelog = wb.create_sheet(TIMELOG_SHEET)
    ws_timelog.append(TIMELOG_HEADER)

    wb.save(path)
    print(f"✅ 新規ブックを作成しました: {path}")


def _ensure_timelog_sheet(wb) -> None:
    """
    TimeLogシートが無ければ作成する（既存のjournal_data.xlsxには
    自動で追加されないため、読み書き前にこの関数で自己修復する）。
    """
    if TIMELOG_SHEET not in wb.sheetnames:
        ws = wb.create_sheet(TIMELOG_SHEET)
        ws.append(TIMELOG_HEADER)
        print(f"🔧 既存ブックに'{TIMELOG_SHEET}'シートを追加しました。")


def _ensure_lkpt_columns(wb) -> None:
    """
    Entriesシートが旧形式（日付/タグ/メモの3列）のままなら、
    メモ列をL列として読み替え、K/P/T列を追加する自己修復を行う。
    既存行の値は列の移動をせずそのまま残るため、既存のメモは
    自動的にLのデータとして統合される。
    """
    ws = wb[ENTRIES_SHEET]
    header = [cell.value for cell in ws[1]]
    if len(header) >= 3 and header[2] == "メモ":
        ws.cell(row=1, column=3, value="L")
        ws.insert_cols(4, amount=3)
        ws.cell(row=1, column=4, value="K")
        ws.cell(row=1, column=5, value="P")
        ws.cell(row=1, column=6, value="T")
        print("🔧 EntriesシートをLKPT形式（L/K/P/T）に移行しました。")


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
    Entriesシートに1行追記する。memoはL列（列C）にそのまま入る
    （C列は元は「メモ」列だったが、LKPT形式移行後は「L」列として
    読み替えられている）。K/P/T列は空のままになる。

    Args:
        date_str: "YYYY-MM-DD HH:MM" 形式の日時文字列
        tag: タグ名（TagMasterに存在するものを推奨）
        memo: 1行メモ（L列に記録される）
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


def _compute_time_range(ws_timelog, now: datetime) -> tuple:
    """
    本日のTimeLogの直近チェックポイント（終了時刻が最も新しい行）から、
    今回のチェックインで記録する作業時間の範囲を計算する
    （record_check_in()の実書き込みと、peek_next_time_range()での
    書き込みなしプレビューの両方から使う共通ロジック）。

    Returns:
        tuple[str, datetime, datetime]: (kind, start, end)
            kind: "anchor"（本日最初のチェックイン。start==end==nowで
                  作業時間としては記録されない）または"interval"
    """
    today = now.date()
    last_checkpoint = None
    for row in ws_timelog.iter_rows(min_row=2, values_only=True):
        end_value = row[1]
        if not end_value:
            continue
        end_dt = (
            end_value if isinstance(end_value, datetime)
            else datetime.strptime(str(end_value), "%Y-%m-%d %H:%M")
        )
        if end_dt.date() == today and (last_checkpoint is None or end_dt > last_checkpoint):
            last_checkpoint = end_dt

    if last_checkpoint is None:
        return "anchor", now, now

    start = last_checkpoint
    max_gap = timedelta(hours=MAX_TIMELOG_GAP_HOURS)
    if now - start > max_gap:
        start = now - max_gap
    return "interval", start, now


def peek_next_time_range(path: str = EXCEL_PATH, now: datetime = None) -> tuple:
    """
    次にrecord_check_in()を呼んだ場合に記録される作業時間の範囲を、
    実際には書き込まずに事前計算する。タグ選択時にポップアップUIへ
    「何時から何時までの作業として記録されるか」をプレビュー表示するために使う。

    Args:
        path: Excelファイルパス
        now: 基準時刻（省略時はdatetime.now()）

    Returns:
        tuple[str, datetime, datetime]: (kind, start, end)
            kind: "anchor"（本日最初のチェックイン。作業時間としては
                  記録されない）または"interval"（start〜endが作業時間として
                  記録される）
    """
    if now is None:
        now = datetime.now()
    now = now.replace(second=0, microsecond=0)

    ensure_workbook_exists(path)
    wb = _load_with_retry(path)
    if TIMELOG_SHEET not in wb.sheetnames:
        return "anchor", now, now
    return _compute_time_range(wb[TIMELOG_SHEET], now)


def record_check_in(tag: str, l: str, k: str, p: str, t: str,
                     path: str = EXCEL_PATH, now: datetime = None) -> tuple:
    """
    タイムログのチェックインを記録する。

    本日まだTimeLogに記録が無ければ、これを「基準点」として
    開始=終了=nowの0分行を記録するだけに留める（作業記録は作らない）。
    2回目以降のチェックインでは、本日分の直近の終了時刻から今までを
    1件の作業記録として記録する（経過がMAX_TIMELOG_GAP_HOURSを超える
    場合は打ち切る）。
    l/k/p/tのいずれかが空でなければ、既存のEntriesシートにもLKPTとして
    記録する。TimeLog・Entriesへの追記は1回のload/saveにまとめ、
    部分成功を防ぐ。

    Args:
        tag: タグ名
        l: Learned（学び）1行メモ（空文字列可）
        k: Keep（継続すべき事）1行メモ（空文字列可）
        p: Problem（課題）1行メモ（空文字列可）
        t: Try（次に挑戦したい事）1行メモ（空文字列可）
        path: Excelファイルパス
        now: 基準時刻（省略時はdatetime.now()）

    Returns:
        tuple[bool, str, int | None]:
            (保存に成功したか, "anchor"（基準点のみ）または"interval"（作業記録あり）,
             "interval"の場合の経過分数)
    """
    if now is None:
        now = datetime.now()
    now = now.replace(second=0, microsecond=0)

    ensure_workbook_exists(path)
    wb = _load_with_retry(path)
    _ensure_timelog_sheet(wb)
    _ensure_lkpt_columns(wb)
    ws_timelog = wb[TIMELOG_SHEET]

    kind, start, end = _compute_time_range(ws_timelog, now)
    if kind == "anchor":
        ws_timelog.append([now, now, tag])
        minutes = None
    else:
        ws_timelog.append([start, end, tag])
        minutes = int((end - start).total_seconds() // 60)

    has_lkpt = bool(l or k or p or t)
    if has_lkpt:
        if ENTRIES_SHEET not in wb.sheetnames:
            print(f"❌ シート'{ENTRIES_SHEET}'が見つかりません。")
        else:
            ws_entries = wb[ENTRIES_SHEET]
            ws_entries.append([now.strftime("%Y-%m-%d %H:%M"), tag, l, k, p, t])

    success = _save_with_retry(wb, path)
    if success:
        if kind == "anchor":
            print(f"⏱️ 本日の基準点を記録しました → {now.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(
                f"⏱️ 作業記録: [{start.strftime('%H:%M')}-{now.strftime('%H:%M')}] "
                f"{tag} ({minutes}分)"
            )
        if has_lkpt:
            print(f"📝 LKPTを記録しました → [{now.strftime('%Y-%m-%d %H:%M')}] [{tag}] "
                  f"L={l} K={k} P={p} T={t}")
    return success, kind, minutes


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
