# -*- coding: utf-8 -*-
"""
T0 事前診断: メール在庫（ストア・フォルダ・月別件数・速度・索引検索）の読み取り専用診断スクリプト。

【目的】
過去スレッド台帳（輸出入トラブル）を作る前に、越智さんのOutlook環境で次を確認する。
  1. 接続済みの全ストア（現行メールボックス・オンラインアーカイブ・PST）の名前・種別・PSTファイルパス
  2. 各ストアのメールフォルダ構成と、2023-10〜2026-09 の月別件数（キャッシュ期間より古い月が0件になっていないか）
  3. Restrict の日付書式（ロケール依存）のどれが通るか
  4. Items列挙(+Restrict) と GetTable の、1か月あたり所要時間
  5. 索引検索（ci_phrasematch）と LIKE の件数が一致するか

【使い方】（Windows + Outlook 起動済み + pywin32）
    python diagnose_mail_inventory_20261008_01.py
    python diagnose_mail_inventory_20261008_01.py --from 2023-10 --to 2026-09 --probe-word invoice
  主なオプション:
    --from / --to           月別件数の期間（YYYY-MM）。既定 2023-10 〜 2026-09
    --probe-word            索引検索の確認に使う語。既定 invoice
    --date-field            月別件数に使う日付項目。ReceivedTime(既定) / SentOn
    --date-format           Restrictの日付書式。auto(既定。通る書式を自動判定) / 書式名
    --skip-stores           除外するストア名の一部（カンマ区切り）
    --no-excluded-months    削除済み・迷惑メール等の月別件数を取らない（速くなる）
    --max-test-folders      速度・索引検索を試すフォルダ数の上限（ストアごと）。既定 30
    --overlap-folders       月境界の前後1日重ね件数を取るフォルダ数（ストアごとの上位）。既定 5
    --speed-cap             速度比較で読む最大件数。既定 2000
    --mask-names            ストア名・フォルダ名・PSTファイル名を連番（Store-01 / Folder-001）に置換
    --output                結果txtの保存先ファイル（既定: outlook_total_organizer/mail_reports/ 配下）

【安全方針】
  * 読み取り専用。アイテムの変更・移動・削除・MarkAsRead、AddStore等のプロファイル変更は一切しない。
  * 件名・本文・送信者・宛先アドレスは出力も保存もしない。出すのは件数・所要時間・エラー種別・
    フォルダ名・ストア名・PSTファイル名のみ。ただし「フォルダ名・ストア名・PSTファイル名」は出力されるので、
    共有する前に内容を確認すること（--mask-names で連番化できる）。
    PSTパスのユーザー名は <USER>、メールアドレス形式は <MAIL> に置換する。
  * 1フォルダが失敗しても全体は止めず、エラー種別のみ記録して続行。Ctrl+C で途中結果を保存して終了。
  * 結果は .gitignore 済みの mail_reports/ に保存（無ければ作成）。保存できなければ一時フォルダへ退避してパスを表示。
  * ログは1フォルダ完了ごとに追記保存されるので、途中で落ちても直前までの結果が残る。

【Linuxでのテスト】
  win32com / pythoncom はCOM部分でだけ遅延importするので、純粋関数はWindows以外でもテストできる。
  COM部分もフェイクを注入して（run_inventory の com 引数）テストできる。
"""
import argparse
import gc
import getpass
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta

SCRIPT_VERSION = "20261008_01"

# ============================================================
# 定数
# ============================================================
DEFAULT_FROM = "2023-10"
DEFAULT_TO = "2026-09"
DEFAULT_PROBE_WORD = "invoice"
DEFAULT_SPEED_CAP = 2000
DEFAULT_MAX_TEST_FOLDERS = 30
DEFAULT_OVERLAP_FOLDERS = 5
BASE_DATE_FORMAT = "ISO_24h"      # 日付書式の基準（YMD系。ロケールに左右されにくい）
FALLBACK_DATE_FORMAT = "YMD_slash_24h"
TENTATIVE_DATE_FORMAT = "US_24h"  # 基準が使えないときの暫定（要確認）
MAX_FOLDER_DEPTH = 30

# 本体 _find_online_archive_root と同じ判定条件（本体は変更しない。ここは写し）
ARCHIVE_NAME_PATTERNS = ["オンライン アーカイブ", "online archive", "in-place archive", "archive -"]
ARCHIVE_EXCHANGE_STORE_TYPE = 3  # 本体が olExchangeArchiveMailbox として扱っている値

# Restrict に渡す日付書式の候補（名前, strftime書式）。先頭ほど優先
DATE_FORMATS = [
    ("US_24h", "%m/%d/%Y %H:%M"),
    ("US_12h", "%m/%d/%Y %I:%M %p"),
    ("DMY_24h", "%d/%m/%Y %H:%M"),
    ("ISO_24h", "%Y-%m-%d %H:%M"),
    ("YMD_slash_24h", "%Y/%m/%d %H:%M"),
    ("US_date", "%m/%d/%Y"),
]
DATE_FORMAT_MAP = dict(DATE_FORMATS)

# 日付項目 -> DASL(urn:schemas:httpmail)のプロパティ名
DASL_DATE_PROPS = {"ReceivedTime": "datereceived", "SentOn": "date"}

# 除外候補フォルダ（名前は小文字で比較）
EXCLUDED_FOLDER_NAMES = {
    "削除済みアイテム": "削除済み",
    "deleted items": "削除済み",
    "迷惑メール": "迷惑メール",
    "junk email": "迷惑メール",
    "junk e-mail": "迷惑メール",
    "検索フォルダー": "検索フォルダー(重複の可能性)",
    "search folders": "検索フォルダー(重複の可能性)",
    "rss フィード": "RSS",
    "rss feeds": "RSS",
    "rss subscriptions": "RSS",
}

MAIL_ADDR_RE = re.compile(r"[\w.+\-']+@[\w\-]+(?:\.[\w\-]+)+", re.UNICODE)


# ============================================================
# 純粋関数（COM不要・Linuxでテスト可能）
# ============================================================
def parse_ym(text):
    """'YYYY-MM'（または 'YYYY/MM'）を (年, 月) に変換する。不正なら ValueError。"""
    if not isinstance(text, str):
        raise ValueError(f"年月の形式が不正です: {text!r}")
    m = re.fullmatch(r"\s*(\d{4})[-/](\d{1,2})\s*", text)
    if not m:
        raise ValueError(f"年月は YYYY-MM の形式で指定してください: {text!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12) or not (1900 <= y <= 2200):
        raise ValueError(f"年月の範囲が不正です: {text!r}")
    return (y, mo)


def month_range(start, end):
    """(年,月) の start から end まで（両端含む）を古い順のリストで返す。start>end は ValueError。"""
    (sy, sm), (ey, em) = start, end
    if (sy, sm) > (ey, em):
        raise ValueError("開始月が終了月より後になっています")
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def month_bounds(year, month):
    """暦月の [開始, 翌月開始) を datetime で返す。"""
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def overlap_bounds(year, month, days=1):
    """月境界を前後 days 日ずつ広げた [開始, 終了) を返す（境界の取りこぼし可視化用）。"""
    start, end = month_bounds(year, month)
    return start - timedelta(days=days), end + timedelta(days=days)


def format_dt(dt, fmt_name_or_pattern):
    """datetime を書式名（DATE_FORMATS のキー）または strftime 書式で文字列化する。"""
    pattern = DATE_FORMAT_MAP.get(fmt_name_or_pattern, fmt_name_or_pattern)
    return dt.strftime(pattern)


def build_range_filter(field, start_dt, end_dt, fmt_name_or_pattern):
    """Restrict用の期間フィルタ文字列: [field] >= 'S' AND [field] < 'E'"""
    s = format_dt(start_dt, fmt_name_or_pattern)
    e = format_dt(end_dt, fmt_name_or_pattern)
    return f"[{field}] >= '{s}' AND [{field}] < '{e}'"


def build_month_filter_variants(field, year, month, overlap_days=0):
    """1つの月について、全書式のフィルタを [(書式名, フィルタ文字列), ...] で返す。
    overlap_days>0 のときは月境界を前後その日数ぶん広げる。"""
    if overlap_days > 0:
        s, e = overlap_bounds(year, month, overlap_days)
    else:
        s, e = month_bounds(year, month)
    return [(name, build_range_filter(field, s, e, pattern)) for name, pattern in DATE_FORMATS]


def build_dasl_date_clause(field, start_dt, end_dt):
    """DASL(@SQL=)用の期間条件（ISO形式。ロケール非依存を期待）。"""
    prop = DASL_DATE_PROPS.get(field, "datereceived")
    s = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    e = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    return (f'"urn:schemas:httpmail:{prop}" >= \'{s}\' AND '
            f'"urn:schemas:httpmail:{prop}" < \'{e}\'')


def sanitize_probe_word(word):
    """索引検索の語から、DASLを壊す文字（引用符・%・バックスラッシュ・制御文字）を除く。空になれば ValueError。"""
    cleaned = re.sub(r"[\'\"%\\\x00-\x1f]", "", word or "").strip()
    if not cleaned:
        raise ValueError("--probe-word が空、または使えない文字だけです")
    return cleaned


def build_dasl_filters(field, year, month, word):
    """索引検索確認用の3つのフィルタを返す: {'baseline','like','phrase'}。
    baseline=期間のみ（DASL日付がISOで通るかの確認）、like=LIKE '%語%'、phrase=ci_phrasematch '語'。"""
    word = sanitize_probe_word(word)
    s, e = month_bounds(year, month)
    date_clause = build_dasl_date_clause(field, s, e)
    return {
        "baseline": f"@SQL={date_clause}",
        "like": f"@SQL={date_clause} AND \"urn:schemas:httpmail:subject\" LIKE '%{word}%'",
        "phrase": f"@SQL={date_clause} AND \"urn:schemas:httpmail:subject\" ci_phrasematch '{word}'",
    }


def mask_user_path(path, extra_user_names=()):
    """ファイルパスの個人情報を伏せる。
      ・\\Users\\<名前>\\ , /Users/<名前>/ , /home/<名前>/ , Documents and Settings\\<名前> の <名前> を <USER> に
      ・'OneDrive - 会社名' の会社名を <ORG> に
      ・extra_user_names に指定した名前と一致するパス区切り単位の部分を <USER> に
      ・メールアドレス形式を <MAIL> に"""
    if not path:
        return path or ""
    text = str(path)
    text = re.sub(r"(?i)([\\/](?:Users|home)[\\/])([^\\/]+)", r"\1<USER>", text)
    text = re.sub(r"(?i)(Documents and Settings[\\/])([^\\/]+)", r"\1<USER>", text)
    text = re.sub(r"(?i)(OneDrive\s*-\s*)([^\\/]+)", r"\1<ORG>", text)
    names = {n.lower() for n in extra_user_names if n and len(n) >= 2}
    if names:
        parts = re.split(r"([\\/])", text)
        parts = ["<USER>" if (p.lower() in names) else p for p in parts]
        text = "".join(parts)
    return mask_emails(text)


def mask_emails(text):
    """メールアドレス形式の文字列を <MAIL> に置換する（ストア名がアドレスのことがあるため）。"""
    if not text:
        return text or ""
    return MAIL_ADDR_RE.sub("<MAIL>", str(text))


def is_archive_store(is_default, exch_type, display_name):
    """本体 _find_online_archive_root と同じ条件でオンラインアーカイブか判定する。
    既定ストアは対象外 / ExchangeStoreType==3 / 表示名がパターンを含む。"""
    if is_default:
        return False
    try:
        if exch_type is not None and int(exch_type) == ARCHIVE_EXCHANGE_STORE_TYPE:
            return True
    except Exception:
        pass
    name = (display_name or "").lower()
    return any(p in name for p in ARCHIVE_NAME_PATTERNS)


def archive_evidence(is_default, exch_type, display_name):
    """アーカイブ判定の根拠を別々に返す: {'by_type': bool, 'by_name': bool}。既定ストアは両方 False。"""
    if is_default:
        return {"by_type": False, "by_name": False}
    by_type = False
    try:
        by_type = exch_type is not None and int(exch_type) == ARCHIVE_EXCHANGE_STORE_TYPE
    except Exception:
        by_type = False
    name = (display_name or "").lower()
    by_name = any(p in name for p in ARCHIVE_NAME_PATTERNS)
    return {"by_type": bool(by_type), "by_name": bool(by_name)}


def archive_verdict(is_default, exch_type, display_name):
    """根拠別の判定文字列。型の値だけ一致した場合は「要確認」にする（値の意味が未確認のため）。"""
    ev = archive_evidence(is_default, exch_type, display_name)
    if ev["by_type"] and ev["by_name"]:
        return "アーカイブ(型値・表示名とも一致)"
    if ev["by_name"]:
        return "アーカイブ(表示名のみ一致)"
    if ev["by_type"]:
        return "要確認(ExchangeStoreType値のみ一致)"
    return ""


def store_kind_label(is_default, exch_type, display_name, file_path):
    """ストア種別の表示用ラベル: アーカイブ / アーカイブ要確認 / PST / OST / 現行(既定) / その他。"""
    ev = archive_evidence(is_default, exch_type, display_name)
    if ev["by_name"]:
        return "アーカイブ"
    if ev["by_type"]:
        return "アーカイブ要確認"
    fp = (file_path or "").lower()
    if fp.endswith(".pst"):
        return "PST"
    if fp.endswith(".ost"):
        return "現行(既定)" if is_default else "OST(Exchange等)"
    if is_default:
        return "現行(既定)"
    return "その他"


def classify_folder_name(name):
    """フォルダ名が除外候補なら理由文字列、通常なら None を返す。"""
    return EXCLUDED_FOLDER_NAMES.get((name or "").strip().lower())


def leading_zero_months(counts):
    """古い順の件数リストの先頭から続く0件の月数。ただし全部0ならリスト長を返す。"""
    n = 0
    for c in counts:
        if c == 0:
            n += 1
        else:
            break
    return n


def build_zero_warning(store_label, months, counts):
    """件数配列（months と同じ並び・古い順）から警告文を作る。問題なければ None。
      ・先頭（古い側）が0件で、後ろに件数がある → キャッシュ期間外・保持ポリシーの可能性
      ・全期間0件 → 空、または期間外の可能性"""
    if not months or len(months) != len(counts):
        return None
    lead = leading_zero_months(counts)
    if lead == 0:
        return None
    first = f"{months[0][0]}-{months[0][1]:02d}"
    if lead >= len(months):
        return (f"⚠️ {store_label}: 全期間({first}〜{months[-1][0]}-{months[-1][1]:02d})が0件です。"
                f"空のストア、またはキャッシュ期間外・保持ポリシーの可能性があります。")
    last_zero = months[lead - 1]
    first_data = months[lead]
    return (f"⚠️ {store_label}: 古い月 {first}〜{last_zero[0]}-{last_zero[1]:02d} ({lead}か月) が0件です"
            f"（最初に件数が出るのは {first_data[0]}-{first_data[1]:02d}）。"
            f"キャッシュ期間外・保持ポリシーの可能性があります。")


def build_probe_windows(months, n_mid=6):
    """日付書式の判別用の期間窓 [(ラベル, 開始, 終了), ...]。
    全期間(1日始まりで日/月が曖昧)に加え、月の13日〜27日の窓を期間内の数か月分入れる。
    13日以降を含むので、日/月の取り違え(DMYとUS)でエラーまたは件数差が出る。"""
    start = month_bounds(*months[0])[0]
    end = month_bounds(*months[-1])[1]
    wins = [("全期間", start, end)]
    n = len(months)
    if n == 1:
        idxs = [0]
    else:
        idxs = sorted({round(i * (n - 1) / (n_mid - 1)) for i in range(n_mid)}) if n_mid > 1 else [0]
    for i in idxs:
        y, m = months[i]
        wins.append((f"{y}-{m:02d}の13〜27日", datetime(y, m, 13), datetime(y, m, 28)))
    return wins


def compare_date_formats(results, base_name=BASE_DATE_FORMAT):
    """書式ごとの試験結果を基準(ISO系)と比較する。多数決は使わない。
    results: [(書式名, 件数のtuple or None(エラー)), ...]
    戻り値: {'adopted': 採用書式 or None, 'review': 要確認か, 'statuses': {書式名: 状態}, 'notes': [文]}
    採用は ISO_24h、不可なら YMD_slash_24h。どちらも使えなければ採用なし(要確認)。
    基準と一致する書式が他に無い場合、および差のある書式がある場合は要確認とする。"""
    res = dict(results)
    adopted = None
    if res.get(base_name) is not None:
        adopted = base_name
    elif res.get(FALLBACK_DATE_FORMAT) is not None:
        adopted = FALLBACK_DATE_FORMAT
    statuses, notes = {}, []
    review = False
    if adopted is None:
        for name, _v in results:
            statuses[name] = "エラー" if res[name] is None else "基準なし"
        notes.append("⚠️ 基準(YMD系)の書式が通りません。自動採用せず要確認です")
        return {"adopted": None, "review": True, "statuses": statuses, "notes": notes}
    base_val = res[adopted]
    others_ok = 0
    others_same = 0
    for name, v in results:
        if name == adopted:
            statuses[name] = "基準"
        elif v is None:
            statuses[name] = "エラー"
        elif v == base_val:
            statuses[name] = "一致"
            others_ok += 1
            others_same += 1
        else:
            delta = sum(v) - sum(base_val)
            statuses[name] = f"差あり(要確認, 合計差{delta:+d})"
            others_ok += 1
            notes.append(f"⚠️ 書式 {name} は基準 {adopted} と件数が異なります"
                         f"（合計差{delta:+d}）。ロケール依存の疑い。自動採用しません（要確認）")
            review = True
    if others_ok and not others_same:
        notes.append(f"⚠️ 基準 {adopted} と一致する書式が他にありません。基準の件数が正しいか要確認です")
        review = True
    if not others_ok:
        notes.append(f"基準 {adopted} 以外の書式はエラーです（基準を採用。裏付けとなる一致書式はありません）")
    elif not review:
        notes.append(f"基準 {adopted} と他の書式が全窓で一致しました")
    if sum(base_val) == 0:
        notes = [n for n in notes if "全窓で一致" not in n]
        notes.append(f"⚠️ 基準 {adopted} の件数が全窓で0件のため、書式を判別できません（要確認）。"
                     "件数のあるフォルダ・期間で再実行するか --date-format で指定してください")
        review = True
    return {"adopted": adopted, "review": review, "statuses": statuses, "notes": notes}


def latest_nonzero_index(counts):
    """件数リスト(古い順)で、0でない最後の添字。無ければ None。"""
    for i in range(len(counts) - 1, -1, -1):
        if counts[i]:
            return i
    return None


def select_test_folders(folder_counts, n):
    """速度・索引試験の対象選定（ストア単位）。folder_counts=[(キー, 試験月の件数), ...]。
    件数が1以上のものを件数の多い順に最大 n 個、キーのリストで返す。"""
    cand = [(k, c) for k, c in folder_counts if c and c > 0]
    cand.sort(key=lambda kc: -kc[1])
    return [k for k, _c in cand[:max(0, n)]]


def judge_index_result(like, phrase, baseline=None):
    """索引検索の結果判定。各引数は {'count': int|None, 'error': str|None}。
    戻り値: ('一致'|'不一致'|'エラー', 説明)。baselineがエラーなら日付条件(DASL)側の問題として区別する。"""
    if baseline is not None and baseline.get("error"):
        return "エラー", f"DASL日付条件がエラー({baseline['error']})"
    errs = []
    if like.get("error"):
        errs.append(f"LIKE={like['error']}")
    if phrase.get("error"):
        errs.append(f"ci_phrasematch={phrase['error']}")
    if errs:
        return "エラー", " / ".join(errs)
    if like.get("count") == phrase.get("count"):
        return "一致", f"LIKE={like['count']}件 / ci_phrasematch={phrase['count']}件"
    return "不一致", f"LIKE={like['count']}件 / ci_phrasematch={phrase['count']}件"


def error_kind(exc):
    """例外から「種別」だけを返す（メッセージは件名等を含みうるので出さない）。
    COMエラーは HRESULT 付き: 'com_error(0x80040107)'"""
    name = type(exc).__name__
    try:
        args = getattr(exc, "args", ())
        if args and isinstance(args[0], int):
            return f"{name}(0x{args[0] & 0xFFFFFFFF:08X})"
    except Exception:
        pass
    return name


def format_duration(seconds):
    """秒数を '0.123秒' / '12.3秒' / '3分05秒' に整形する。"""
    if seconds is None:
        return "-"
    if seconds < 10:
        return f"{seconds:.3f}秒"
    if seconds < 60:
        return f"{seconds:.1f}秒"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}分{s:02d}秒"


def ym_label(ym):
    """(年,月) -> 'YYYY-MM'"""
    return f"{ym[0]}-{ym[1]:02d}"


def format_month_table(months, counts, overlap_counts):
    """月別の合計表（テキスト）。counts/overlap_counts は months と同じ並びの int のリスト。
    境界差 = 前後1日重ねた件数 - 通常件数（前後の隣接日の分。負なら取得異常）。"""
    lines = ["  年月      件数   前後1日重ね  境界差"]
    for ym, c, o in zip(months, counts, overlap_counts):
        lines.append(f"  {ym_label(ym)}  {c:>7}  {o:>10}  {o - c:>+6}")
    lines.append(f"  合計      {sum(counts):>7}  {sum(overlap_counts):>10}  {sum(overlap_counts) - sum(counts):>+6}")
    return "\n".join(lines)


def format_folder_line(path, total, months, counts):
    """フォルダ1件の要約行。月別は件数のある月だけ並べ、0件月の数を添える。"""
    nonzero = [f"{ym_label(ym)}={c}" for ym, c in zip(months, counts) if c]
    zero_n = sum(1 for c in counts if not c)
    body = ", ".join(nonzero) if nonzero else "（期間内0件）"
    return f"  - {path} | 総{total}件 | 月別: {body} | 0件月={zero_n}"


INDEX_NOTE = ("※ LIKE は部分一致、ci_phrasematch は語（トークン）一致のため、"
              "部分一致と語一致の違いで件数が異なる（不一致）こともあり、直ちに異常とは限りません。")


def mask_display_name(text, user_names=()):
    """ストア名・フォルダ名用のマスク: メールアドレス形式を <MAIL>、ユーザー名(3文字以上)を <USER> に置換。"""
    out = mask_emails(text or "")
    for n in sorted({n for n in user_names if n and len(n) >= 3}, key=len, reverse=True):
        out = re.sub(re.escape(n), "<USER>", out, flags=re.IGNORECASE)
    return out


class NameMasker:
    """--mask-names 用。同じ名前には同じ連番を割り当てる（Store-01 / Folder-001 など）。"""

    def __init__(self, enabled, prefix, width=3):
        self.enabled = bool(enabled)
        self.prefix = prefix
        self.width = width
        self._map = {}

    def mask(self, name):
        if not self.enabled:
            return name
        if name not in self._map:
            self._map[name] = f"{self.prefix}-{len(self._map) + 1:0{self.width}d}"
        return self._map[name]


def format_total_table(months, counts):
    """月別の件数だけの表（テキスト）。"""
    lines = ["  年月      件数"]
    for ym, c in zip(months, counts):
        lines.append(f"  {ym_label(ym)}  {c:>7}")
    lines.append(f"  合計      {sum(counts):>7}")
    return "\n".join(lines)


def default_output_dir():
    """既定の保存先: outlook_total_organizer/mail_reports/（tools の1つ上。.gitignore済み）"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "mail_reports")


def resolve_output_path(output_arg, now=None):
    """--output の解決。未指定は mail_reports/ 配下の既定名。ディレクトリ指定ならその下に既定名。"""
    name = default_output_name(now)
    if not output_arg:
        return os.path.join(default_output_dir(), name)
    if os.path.isdir(output_arg) or output_arg.endswith(("/", "\\")):
        return os.path.join(output_arg, name)
    return output_arg


def default_output_name(now=None):
    """出力ファイル名: diagnose_mail_inventory_<YYYYMMDD_HHMMSS>.txt"""
    now = now or datetime.now()
    return f"diagnose_mail_inventory_{now.strftime('%Y%m%d_%H%M%S')}.txt"


def summarize_errors(error_records):
    """エラー記録 [(場所, 種別), ...] を種別ごとの件数文字列リストにする（多い順）。"""
    counts = {}
    for _where, kind in error_records:
        counts[kind] = counts.get(kind, 0) + 1
    return [f"{k}: {v}件" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# ============================================================
# 出力（コンソール + 追記保存ファイル）
# ============================================================
class Reporter:
    """コンソールに出しつつ、1行ごとにファイルへ追記・flushする。
    保存先を開けない／書けないときは一時フォルダ(tempfile.gettempdir())へ退避する。
    渡されるのは件数・所要時間・エラー種別・フォルダ名・ストア名のみ（件名等は渡さない）。"""

    def __init__(self, path=None):
        self.lines = []
        self.path = path
        self.fh = None
        self.fallback_path = None
        if path:
            self._open(path)

    def _open(self, path):
        try:
            d = os.path.dirname(os.path.abspath(path))
            os.makedirs(d, exist_ok=True)
            self.fh = open(path, "w", encoding="utf-8-sig", newline="\n")
            self.path = path
        except Exception:
            self._fallback()

    def _fallback(self):
        """一時フォルダへ退避し、ここまでの全行を書き直す。"""
        try:
            if self.fh:
                self.fh.close()
        except Exception:
            pass
        self.fh = None
        try:
            base = os.path.basename(self.path or "") or default_output_name()
            p = os.path.join(tempfile.gettempdir(), base)
            fh = open(p, "w", encoding="utf-8-sig", newline="\n")
            fh.write("\n".join(self.lines) + ("\n" if self.lines else ""))
            fh.flush()
            self.fh = fh
            self.path = p
            self.fallback_path = p
            names = [n for n in (getpass.getuser(), os.environ.get("USERNAME")) if n]
            print(f"⚠️ 保存先に書けないため一時フォルダへ退避しました: "
                  f"{mask_display_name(mask_user_path(p, names), names)}", flush=True)
        except Exception:
            self.fh = None
            print("❌ 結果ファイルを保存できません（コンソール表示のみ）", flush=True)

    def log(self, text=""):
        self.lines.append(text)
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"), flush=True)
        if self.fh:
            try:
                self.fh.write(text + "\n")
                self.fh.flush()
            except Exception:
                self._fallback()

    def close(self):
        try:
            if self.fh:
                self.fh.close()
        except Exception:
            pass
        self.fh = None


# ============================================================
# COM 部分（Windows + Outlook 専用。importは遅延）
# ============================================================
def import_com():
    """win32com / pythoncom を遅延import。無ければ (None, None)。"""
    try:
        import win32com.client as client  # noqa: WPS433
        import pythoncom  # noqa: WPS433
        return client, pythoncom
    except Exception:
        return None, None


def safe_attr(obj, name, default=None):
    """COM属性を安全に取得（失敗は default）。"""
    try:
        return getattr(obj, name)
    except Exception:
        return default


def count_restrict(folder, flt):
    """Restrict して件数だけ返す（アイテム内容は読まない）。"""
    return int(folder.Items.Restrict(flt).Count)


def enumerate_folders(root, errors, store_label, namer=None):
    """ストアのルート配下を再帰列挙し、メールフォルダ(DefaultItemType==0)の記録リストを返す。
    予定表・連絡先・タスク等は含めない。除外候補（削除済み等）は kind='excluded' で配下も除外扱い。
    除外判定は実名で行い、表示名は namer(実名) を通す。
    記録: {'path','name','kind','reason','total','com'}"""
    namer = namer or (lambda n: n)
    result = []

    def walk(folder, path, depth, excluded_reason):
        if depth > MAX_FOLDER_DEPTH:
            return
        try:
            subfolders = folder.Folders
            n = int(subfolders.Count)
        except Exception as e:
            errors.append((f"{store_label}{path}", f"フォルダ列挙:{error_kind(e)}"))
            return
        for i in range(1, n + 1):
            try:
                sub = subfolders.Item(i)
                raw = safe_attr(sub, "Name", "(名前取得不可)") or "(名前なし)"
                name = namer(raw)
                sub_path = f"{path}\\{name}"
                reason = excluded_reason or classify_folder_name(raw)
                item_type = safe_attr(sub, "DefaultItemType", None)
                if item_type == 0:  # olMailItem のみ
                    try:
                        total = int(sub.Items.Count)
                    except Exception as e:
                        total = None
                        errors.append((f"{store_label}{sub_path}", f"件数取得:{error_kind(e)}"))
                    result.append({
                        "path": sub_path, "name": name,
                        "kind": "excluded" if reason else "mail",
                        "reason": reason or "", "total": total, "com": sub,
                    })
                walk(sub, sub_path, depth + 1, reason)
            except Exception as e:
                errors.append((f"{store_label}[{i}]", f"フォルダ取得:{error_kind(e)}"))

    walk(root, "", 1, None)
    return result


def time_items_restrict(folder, flt, cap):
    """(a) Items.Restrict で1件ずつ Subject だけ読む（内容は保持しない）。
    戻り値: (読んだ件数, 秒, 読み失敗件数)"""
    t0 = time.perf_counter()
    n = 0
    bad = 0
    restricted = folder.Items.Restrict(flt)
    item = restricted.GetFirst()
    while item is not None and n < cap:
        try:
            _ = item.Subject  # 読むだけ。保持・出力しない
        except Exception:
            bad += 1
        n += 1
        item = restricted.GetNext()
    return n, time.perf_counter() - t0, bad


def time_gettable(folder, flt, cap):
    """(b) GetTable で Subject/ReceivedTime の列だけ読む。
    戻り値: (読んだ件数, 秒, 使った列名の説明)"""
    t0 = time.perf_counter()
    table = folder.GetTable(flt)
    table.Columns.RemoveAll()
    table.Columns.Add("Subject")
    note = "Subject,ReceivedTime"
    try:
        table.Columns.Add("ReceivedTime")
    except Exception:
        table.Columns.Add("urn:schemas:httpmail:datereceived")
        note = "Subject,datereceived(URI)"
    n = 0
    while (not table.EndOfTable) and n < cap:
        row = table.GetNextRow()
        _ = row.Item(1)  # 読むだけ。保持・出力しない
        _ = row.Item(2)
        n += 1
    return n, time.perf_counter() - t0, note


def timed_count(folder, flt):
    """Restrict件数と所要秒を {'count','error','sec'} で返す。"""
    t0 = time.perf_counter()
    try:
        c = count_restrict(folder, flt)
        return {"count": c, "error": None, "sec": time.perf_counter() - t0}
    except Exception as e:
        return {"count": None, "error": error_kind(e), "sec": time.perf_counter() - t0}


def log_store_summary(rep, s, months, warnings, partial=False):
    """ストア1件の月別集計を出力する（途中中断時は partial=True）。警告があれば warnings に積む。"""
    allmail = [f for f in s["folders"] if f["kind"] == "mail" and "counts" in f]
    mail = [f for f in allmail if not f.get("month_error")]
    incomplete = len(allmail) - len(mail)
    exc = [f for f in s["folders"] if f["kind"] == "excluded" and "counts" in f and not f.get("month_error")]
    n = len(months)
    s["sum_counts"] = [sum(f["counts"][i] for f in mail) for i in range(n)]
    sample = [f for f in mail if f.get("overlap") is not None]
    s["exc_counts"] = [sum(f["counts"][i] for f in exc) for i in range(n)]
    s["summarized"] = True
    rep.log("")
    rep.log(f"📊 ストア別 月別件数{'（途中まで）' if partial else ''}: [{s['index']}] {s['display']} ({s['kind_label']})")
    rep.log("  ■ メールフォルダ合計（除外候補を含まない）")
    if incomplete:
        rep.log(f"  ⚠️ 月別取得がエラーで止まった不完全フォルダ {incomplete}個は合計から除外しています（実際より少ない可能性）")
    rep.log(format_total_table(months, s["sum_counts"]))
    if exc:
        rep.log(f"  ■ 除外候補フォルダ合計（別集計）: 期間内 {sum(s['exc_counts'])}件")
    if sample:
        sc = [sum(f["counts"][i] for f in sample) for i in range(n)]
        so = [sum(f["overlap"][i] for f in sample) for i in range(n)]
        rep.log(f"  ■ 月境界の確認（前後1日重ね。件数上位{len(sample)}フォルダのみ）")
        rep.log(format_month_table(months, sc, so))
    if not partial:
        w = build_zero_warning(f"[{s['index']}] {s['display']}", months, s["sum_counts"])
        if w:
            warnings.append(w)
            rep.log(w)


# ============================================================
# 本体処理
# ============================================================
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="T0 メール在庫診断（読み取り専用）")
    ap.add_argument("--from", dest="from_ym", default=DEFAULT_FROM, help="開始月 YYYY-MM")
    ap.add_argument("--to", dest="to_ym", default=DEFAULT_TO, help="終了月 YYYY-MM")
    ap.add_argument("--probe-word", default=DEFAULT_PROBE_WORD, help="索引検索の確認に使う語")
    ap.add_argument("--date-field", default="ReceivedTime", choices=["ReceivedTime", "SentOn"])
    ap.add_argument("--date-format", default="auto", help="auto または " + "/".join(n for n, _ in DATE_FORMATS))
    ap.add_argument("--skip-stores", default="", help="除外するストア名の一部（カンマ区切り）")
    ap.add_argument("--no-excluded-months", action="store_true", help="除外候補フォルダの月別件数を取らない")
    ap.add_argument("--max-test-folders", type=int, default=DEFAULT_MAX_TEST_FOLDERS,
                    help="速度・索引検索を試すフォルダ数の上限（ストアごと）")
    ap.add_argument("--overlap-folders", type=int, default=DEFAULT_OVERLAP_FOLDERS,
                    help="月境界の前後1日重ね件数を取るフォルダ数（ストアごとの上位）")
    ap.add_argument("--speed-cap", type=int, default=DEFAULT_SPEED_CAP)
    ap.add_argument("--mask-names", action="store_true", help="ストア名・フォルダ名・PSTファイル名を連番に置換")
    ap.add_argument("--output", default="", help="結果txtの保存先（既定: mail_reports/ 配下）")
    args = ap.parse_args(argv)
    if args.date_format != "auto" and args.date_format not in DATE_FORMAT_MAP:
        ap.error(f"--date-format は auto または {', '.join(DATE_FORMAT_MAP)} のいずれか")
    return args


def _inventory_core(args, rep, client, stores):
    """診断本体。COM参照はこの関数の中だけで持ち、戻った後に呼び出し側が解放する。戻り値: 終了コード。"""
    months = month_range(parse_ym(args.from_ym), parse_ym(args.to_ym))
    probe_word = sanitize_probe_word(args.probe_word)
    field = args.date_field
    user_names = [n for n in (getpass.getuser(), os.environ.get("USERNAME")) if n]
    skip_words = [w.strip().lower() for w in args.skip_stores.split(",") if w.strip()]
    store_masker = NameMasker(args.mask_names, "Store", 2)
    folder_masker = NameMasker(args.mask_names, "Folder", 3)

    def namer(raw):
        return folder_masker.mask(mask_display_name(raw, user_names))

    errors = []          # (場所, 種別)
    warnings = []
    test_info = []       # (ストア表示名, 試験月 or None, フォルダ数, 理由)
    speed_rows, index_rows = [], []
    state = {"summary_done": False, "date_fmt": None, "date_review": False}

    rep.log("=" * 78)
    rep.log(f"🩺 T0 メール在庫診断 (v{SCRIPT_VERSION}) 読み取り専用")
    rep.log(f"   実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    rep.log(f"   期間: {ym_label(months[0])} 〜 {ym_label(months[-1])} ({len(months)}か月) / 日付項目: {field}")
    rep.log("   🔒 件名・本文・送信者・宛先アドレスは出力・保存しません。")
    rep.log("      ただしフォルダ名・ストア名・PSTファイル名は出力されます。共有する前に内容を確認してください"
            "（--mask-names で連番に置換できます）。")
    rep.log("   ℹ️ 件数には会話履歴・同期の問題・下書き・送信トレイなどのフォルダも含まれます（メールフォルダ扱い）。")
    rep.log("=" * 78)

    outlook = namespace = com_stores = None
    try:
        try:
            outlook = client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
        except Exception as e:
            rep.log(f"❌ Outlookに接続できません: {error_kind(e)}  (Outlookを起動してから再実行してください)")
            return 2

        def final_summary(interrupted):
            rep.log("")
            rep.log("=" * 78)
            rep.log("🧾 [総括]" + ("（途中まで）" if interrupted else ""))
            for disp, ym, nf, why in test_info:
                if ym:
                    rep.log(f"   🧪 試験対象: {disp}: 試験月 {ym} / {nf}フォルダ")
                else:
                    rep.log(f"   ⏭️ 試験対象なし: {disp}: {why}")
            if speed_rows:
                a_ok = [r for r in speed_rows if "a" in r]
                b_ok = [r for r in speed_rows if "b" in r]
                a_n, a_t = sum(r["a"][0] for r in a_ok), sum(r["a"][1] for r in a_ok)
                b_n, b_t = sum(r["b"][0] for r in b_ok), sum(r["b"][1] for r in b_ok)
                rep.log(f"   ⏱️ 試験分の合計: Items+Restrict {a_n}件/{format_duration(a_t)}"
                        f"  vs  GetTable {b_n}件/{format_duration(b_t)}")
            if index_rows:
                cnt = {"一致": 0, "不一致": 0, "エラー": 0}
                for r in index_rows:
                    cnt[r["verdict"]] += 1
                rep.log(f"   🔎 索引検索: 一致{cnt['一致']} / 不一致{cnt['不一致']} / エラー{cnt['エラー']}")
                rep.log(f"      {INDEX_NOTE}")
            if warnings:
                rep.log("   ⚠️ 警告:")
                for w in warnings:
                    rep.log(f"      {w}")
            else:
                rep.log("   ✅ 警告なし")
            if errors:
                rep.log(f"   ❌ エラー記録 {len(errors)}件（種別別）:")
                for line in summarize_errors(errors):
                    rep.log(f"      {line}")
                for where, kind in errors[:50]:
                    rep.log(f"      · {where}: {kind}")
                if len(errors) > 50:
                    rep.log(f"      … 他{len(errors) - 50}件")
            else:
                rep.log("   ✅ エラーなし")

        targets = []
        try:
            try:
                default_store_id = namespace.GetDefaultFolder(6).Store.StoreID
            except Exception as e:
                default_store_id = None
                errors.append(("既定ストアID", error_kind(e)))

            # ---------- STEP 1: ストア列挙 ----------
            rep.log("")
            rep.log("📦 [STEP 1] 接続済みストアの一覧")
            try:
                com_stores = namespace.Stores
                n_stores = int(com_stores.Count)
            except Exception as e:
                rep.log(f"❌ ストア一覧を取得できません: {error_kind(e)}")
                return 2
            rep.log(f"   検出ストア数: {n_stores}")
            for i in range(1, n_stores + 1):
                try:
                    st = com_stores.Item(i)
                except Exception as e:
                    errors.append((f"ストア[{i}]", f"Item取得:{error_kind(e)}"))
                    rep.log(f"   ⚠️ [{i}] 取得エラー: {error_kind(e)}")
                    continue
                display_raw = safe_attr(st, "DisplayName", "") or "(名前取得不可)"
                display = store_masker.mask(mask_display_name(display_raw, user_names))
                store_id = safe_attr(st, "StoreID", None)
                exch = safe_attr(st, "ExchangeStoreType", None)
                file_path = safe_attr(st, "FilePath", "") or ""
                is_default = bool(default_store_id and store_id == default_store_id)
                label = store_kind_label(is_default, exch, display_raw, file_path)
                skipped = any(w in display_raw.lower() for w in skip_words)
                if file_path and args.mask_names:
                    shown_path = "<MASKED>" + os.path.splitext(file_path)[1]
                else:
                    shown_path = mask_display_name(mask_user_path(file_path, user_names), user_names)
                rec = {"index": i, "display": display, "exch": exch, "kind_label": label,
                       "is_default": is_default, "file_path": shown_path,
                       "skipped": skipped, "com": st, "folders": [], "summarized": False}
                stores.append(rec)
                icon = {"アーカイブ": "🗄️", "PST": "💾"}.get(label, "📬")
                rep.log(f"   {icon} [{i}] {display}")
                rep.log(f"        種別={label} / 既定ストア={'はい' if is_default else 'いいえ'}")
                rep.log(f"        ExchangeStoreType(実機の生の値)={exch!r}")
                ev = archive_evidence(is_default, exch, display_raw)
                rep.log(f"        アーカイブ判定の根拠: 型値が{ARCHIVE_EXCHANGE_STORE_TYPE}: "
                        f"{'はい' if ev['by_type'] else 'いいえ'} / 表示名パターン一致: {'はい' if ev['by_name'] else 'いいえ'}")
                verdict = archive_verdict(is_default, exch, display_raw)
                if verdict:
                    mark = "⚠️" if verdict.startswith("要確認") else "✅"
                    rep.log(f"        {mark} 判定: {verdict}")
                if file_path:
                    rep.log(f"        ファイル: {shown_path}")
                if skipped:
                    rep.log("        ⏭️ --skip-stores により走査対象外")
            rep.log("   ※ ExchangeStoreType の数値の意味はOutlookのバージョンで確認が必要です"
                    f"（本体は {ARCHIVE_EXCHANGE_STORE_TYPE}=アーカイブとして扱っています）。"
                    "型値のみ一致のストアは「要確認」です。")

            targets = [s for s in stores if not s["skipped"]]

            # ---------- STEP 2: フォルダ列挙 ----------
            rep.log("")
            rep.log("📂 [STEP 2] メールフォルダの再帰列挙（DefaultItemType=メールのみ）")
            for k, s in enumerate(targets, 1):
                rep.log(f"   ⏳ [{k}/{len(targets)}] {s['display']} を列挙中...")
                t0 = time.perf_counter()
                try:
                    root = s["com"].GetRootFolder()
                    s["folders"] = enumerate_folders(root, errors, f"[{s['index']}]", namer)
                except Exception as e:
                    errors.append((f"[{s['index']}] ルート", error_kind(e)))
                    rep.log(f"   ❌ ルートフォルダ取得エラー: {error_kind(e)}")
                    continue
                n_mail = sum(1 for f in s["folders"] if f["kind"] == "mail")
                n_exc = sum(1 for f in s["folders"] if f["kind"] == "excluded")
                tot_mail = sum((f["total"] or 0) for f in s["folders"] if f["kind"] == "mail")
                tot_exc = sum((f["total"] or 0) for f in s["folders"] if f["kind"] == "excluded")
                rep.log(f"   ✅ メールフォルダ {n_mail}個 (総{tot_mail}件) / 除外候補 {n_exc}個 (総{tot_exc}件)"
                        f"  所要 {format_duration(time.perf_counter() - t0)}")
                for f in s["folders"]:
                    note = f"  ← 除外候補: {f['reason']}" if f["kind"] == "excluded" else ""
                    tot = "?" if f["total"] is None else f["total"]
                    rep.log(f"      · {f['path']}  [{tot}件]{note}")

            # ---------- STEP 3: 日付書式の判定 ----------
            rep.log("")
            rep.log("🕒 [STEP 3] Restrict の日付書式（ロケール依存）の確認")
            all_mail = [(s, f) for s in targets for f in s["folders"]
                        if f["kind"] == "mail" and (f["total"] or 0) > 0]
            probe_folders = []
            if args.date_format == "auto":
                # 全期間の件数が1以上のフォルダから選ぶ（0件フォルダでは書式を判別できないため）
                rs, re_ = month_bounds(*months[0])[0], month_bounds(*months[-1])[1]
                for s_, f_ in sorted(all_mail, key=lambda sf: -(sf[1]["total"] or 0))[:12]:
                    c_ = None
                    for nm in (BASE_DATE_FORMAT, FALLBACK_DATE_FORMAT, TENTATIVE_DATE_FORMAT):
                        r_ = timed_count(f_["com"], build_range_filter(field, rs, re_, DATE_FORMAT_MAP[nm]))
                        if not r_["error"]:
                            c_ = r_["count"]
                            break
                    if c_:
                        probe_folders.append((s_, f_))
                    if len(probe_folders) >= 3:
                        break
                if not probe_folders:
                    probe_folders = sorted(all_mail, key=lambda sf: -(sf[1]["total"] or 0))[:3]
            date_fmt = None
            if args.date_format != "auto":
                date_fmt = args.date_format
                rep.log(f"   指定により書式 {date_fmt} ({DATE_FORMAT_MAP[date_fmt]}) を使用（自動判定なし）")
            elif not probe_folders:
                date_fmt = TENTATIVE_DATE_FORMAT
                msg = "⚠️ 件数のあるメールフォルダが無く書式を試験できません。暫定で US_24h を使います（要確認）"
                warnings.append(msg)
                rep.log(f"   {msg}")
                state["date_review"] = True
            else:
                windows = build_probe_windows(months)
                rep.log(f"   試験窓 {len(windows)}個（全期間 + 月の13〜27日。日/月の取り違えを判別するため）、"
                        f"試験フォルダ {len(probe_folders)}個（基準={BASE_DATE_FORMAT}）")
                results = []
                for name, pattern in DATE_FORMATS:
                    vec = [0] * len(windows)
                    bad = None
                    for s, f in probe_folders:
                        for wi, (_lbl, ws, we) in enumerate(windows):
                            r = timed_count(f["com"], build_range_filter(field, ws, we, pattern))
                            if r["error"]:
                                bad = r["error"]
                                break
                            vec[wi] += r["count"]
                        if bad:
                            break
                    results.append((name, None if bad else tuple(vec)))
                    if bad:
                        rep.log(f"      ❌ {name:<14} {pattern:<20} エラー {bad}")
                    else:
                        rep.log(f"      · {name:<14} {pattern:<20} 窓別件数 {list(vec)} (合計{sum(vec)})")
                cmp_ = compare_date_formats(results)
                for name, _p in DATE_FORMATS:
                    rep.log(f"      → {name:<14} {cmp_['statuses'][name]}")
                for note in cmp_["notes"]:
                    rep.log(f"   {note}")
                    if note.startswith("⚠️"):
                        warnings.append(f"日付書式: {note}")
                date_fmt = cmp_["adopted"]
                if date_fmt is None:
                    date_fmt = TENTATIVE_DATE_FORMAT
                    rep.log(f"   ➡️ 採用書式なし（要確認）。暫定で {date_fmt} を使いますが月別件数は信用できません。"
                            "--date-format で指定して再実行してください")
                else:
                    rep.log(f"   ➡️ 採用書式: {date_fmt} ({DATE_FORMAT_MAP[date_fmt]})"
                            + ("  ※要確認あり" if cmp_["review"] else ""))
                state["date_review"] = cmp_["review"] or cmp_["adopted"] is None
            state["date_fmt"] = date_fmt

            # ---------- STEP 4: 月別件数 ----------
            rep.log("")
            rep.log("📅 [STEP 4] 月別件数（Restrictで件数のみ取得。先に全期間で1回数え、0件のフォルダは月別を省略）")
            range_start = month_bounds(*months[0])[0]
            range_end = month_bounds(*months[-1])[1]
            range_filter = build_range_filter(field, range_start, range_end, date_fmt)
            t_start = time.perf_counter()
            for s in targets:
                for f in s["folders"]:
                    f["range_count"] = None
                    if f["kind"] == "excluded" and args.no_excluded_months:
                        continue
                    if f["total"] == 0:
                        f["range_count"] = 0
                        continue
                    if f["total"] is None:
                        continue
                    r = timed_count(f["com"], range_filter)
                    if r["error"]:
                        f["month_error"] = r["error"]
                        errors.append((f"[{s['index']}]{f['path']}", f"全期間件数:{r['error']}"))
                    else:
                        f["range_count"] = r["count"]
            for s in targets:
                mail_sorted = sorted([f for f in s["folders"] if f["kind"] == "mail" and (f.get("range_count") or 0) > 0],
                                     key=lambda f: -f["range_count"])
                sample_ids = {id(f) for f in mail_sorted[:max(0, args.overlap_folders)]}
                todo = [f for f in s["folders"] if f.get("range_count") is not None
                        and not (f["kind"] == "excluded" and args.no_excluded_months)]
                skipped0 = 0
                rep.log(f"   ▶ [{s['index']}] {s['display']}: {len(todo)}フォルダ（境界重ねは上位{len(sample_ids)}個のみ）")
                for idx, f in enumerate(todo, 1):
                    f["counts"] = [0] * len(months)
                    f["overlap"] = None
                    if f["range_count"] == 0:
                        skipped0 += 1
                        continue
                    do_overlap = id(f) in sample_ids
                    if do_overlap:
                        f["overlap"] = [0] * len(months)
                    t0 = time.perf_counter()
                    try:
                        for mi, (y, m) in enumerate(months):
                            ms, me = month_bounds(y, m)
                            f["counts"][mi] = count_restrict(f["com"], build_range_filter(field, ms, me, date_fmt))
                            if do_overlap:
                                os_, oe = overlap_bounds(y, m, 1)
                                f["overlap"][mi] = count_restrict(f["com"], build_range_filter(field, os_, oe, date_fmt))
                    except Exception as e:
                        if isinstance(e, KeyboardInterrupt):
                            raise
                        f["month_error"] = error_kind(e)
                        errors.append((f"[{s['index']}]{f['path']}", f"月別件数:{f['month_error']}"))
                    line = format_folder_line(f["path"], f["total"], months, f["counts"])
                    if f["kind"] == "excluded":
                        line += f" [除外候補:{f['reason']}]"
                    if f.get("month_error"):
                        line += f" [エラー:{f['month_error']}]"
                    rep.log(f"   {'⚠️' if f.get('month_error') else '✅'} [{idx}/{len(todo)}]"
                            f" ({format_duration(time.perf_counter() - t0)})")
                    rep.log(line)
                if skipped0:
                    rep.log(f"   ⏭️ 期間内0件のため月別を省略したフォルダ: {skipped0}個")
                log_store_summary(rep, s, months, warnings)
            rep.log(f"   月別件数の合計所要: {format_duration(time.perf_counter() - t_start)}")

            # ---------- STEP 5/6: 速度比較・索引検索（ストア単位） ----------
            rep.log("")
            rep.log(f"⏱️ [STEP 5] 速度比較 / [STEP 6] 索引検索の確認 （ストアごとに「データのある最新月」で試験、"
                    f"最大{args.speed_cap}件、語='{probe_word}'）")
            rep.log("   ※ 速度は (a)(b) を交互に2回ずつ実行し、2回目の値を採用します（1回目はキャッシュ温め）。")
            rep.log(f"   {INDEX_NOTE}")
            for s in targets:
                sums = s.get("sum_counts")
                midx = latest_nonzero_index(sums) if sums else None
                if midx is None:
                    why = "期間内に件数のあるメールフォルダがありません"
                    test_info.append((s["display"], None, 0, why))
                    rep.log(f"   ⏭️ [{s['index']}] {s['display']}: 試験対象なし（{why}）")
                    continue
                ym = months[midx]
                fc = [(id(f), f["counts"][midx]) for f in s["folders"]
                      if f["kind"] == "mail" and "counts" in f and not f.get("month_error")]
                chosen_ids = select_test_folders(fc, args.max_test_folders)
                by_id = {id(f): f for f in s["folders"]}
                cands = [by_id[k] for k in chosen_ids]
                test_info.append((s["display"], ym_label(ym), len(cands), ""))
                rep.log(f"   ▶ [{s['index']}] {s['display']}: 試験月 {ym_label(ym)} / 対象 {len(cands)}フォルダ"
                        f"（件数上位。--max-test-folders={args.max_test_folders}）")
                ms, me = month_bounds(*ym)
                month_filter = build_range_filter(field, ms, me, date_fmt)
                dasl = build_dasl_filters(field, ym[0], ym[1], probe_word)
                for k, f in enumerate(cands, 1):
                    tag = f"[{s['index']}] {f['path']}"
                    rep.log(f"   ⏳ [{k}/{len(cands)}] {tag} (月内{f['counts'][midx]}件)")
                    row = {"tag": tag, "month_count": f["counts"][midx]}
                    for rnd in (1, 2):  # 交互に2回、後者を採用
                        try:
                            row["a"] = time_items_restrict(f["com"], month_filter, args.speed_cap)
                        except Exception as e:
                            if isinstance(e, KeyboardInterrupt):
                                raise
                            row.pop("a", None)
                            row["a_err"] = error_kind(e)
                            if rnd == 2:
                                errors.append((tag, f"速度(a):{row['a_err']}"))
                        try:
                            row["b"] = time_gettable(f["com"], month_filter, args.speed_cap)
                        except Exception as e:
                            if isinstance(e, KeyboardInterrupt):
                                raise
                            row.pop("b", None)
                            row["b_err"] = error_kind(e)
                            if rnd == 2:
                                errors.append((tag, f"速度(b):{row['b_err']}"))
                    speed_rows.append(row)
                    if "a" in row:
                        a_txt = f"{row['a'][0]}件 {format_duration(row['a'][1])}" + \
                                (f" (読込失敗{row['a'][2]})" if row['a'][2] else "")
                    else:
                        a_txt = f"エラー {row.get('a_err')}"
                    b_txt = f"{row['b'][0]}件 {format_duration(row['b'][1])}" if "b" in row else f"エラー {row.get('b_err')}"
                    rep.log(f"      (a) Items+Restrict: {a_txt}")
                    rep.log(f"      (b) GetTable      : {b_txt}")
                    if "a" in row and "b" in row and row["b"][1] > 0 and row["a"][1] > 0:
                        rep.log(f"      ➡️ GetTable は Items列挙の約 {row['a'][1] / row['b'][1]:.1f}倍速")
                    base = timed_count(f["com"], dasl["baseline"])
                    like = timed_count(f["com"], dasl["like"])
                    phrase = timed_count(f["com"], dasl["phrase"])
                    verdict, detail = judge_index_result(like, phrase, base)
                    if base["error"] is None and base["count"] != f["counts"][midx]:
                        detail += f" / ⚠️ DASL日付のみ={base['count']}件(Restrict月別={f['counts'][midx]}件と差)"
                    index_rows.append({"tag": tag, "verdict": verdict, "detail": detail})
                    icon = {"一致": "✅", "不一致": "⚠️", "エラー": "❌"}[verdict]
                    rep.log(f"      {icon} 索引検索: {verdict} ({detail}) "
                            f"[LIKE {format_duration(like['sec'])} / phrase {format_duration(phrase['sec'])}]")

            if state["date_review"]:
                warnings.append("日付書式は要確認です（上の STEP 3 を確認してください）")
            final_summary(False)
            state["summary_done"] = True
        except KeyboardInterrupt:
            rep.log("")
            rep.log("⛔ Ctrl+C を受け付けました。ここまでの途中結果を出力して保存します。")
            for s in targets:
                if (not s.get("summarized")) and any("counts" in f for f in s["folders"]):
                    try:
                        log_store_summary(rep, s, months, warnings, partial=True)
                    except Exception as e:
                        rep.log(f"   ⚠️ 途中集計エラー: {error_kind(e)}")
            final_summary(True)
    finally:
        outlook = namespace = com_stores = None
    rep.log("")
    rep.log("✅ 診断完了（読み取りのみ。Outlookのデータは何も変更していません）" if state["summary_done"]
            else "⚠️ 診断は途中までです（読み取りのみ。Outlookのデータは何も変更していません）")
    return 0


def run_inventory(args, rep, com=None):
    """診断の入口。com=(client, pythoncom) を渡すとフェイク注入できる（テスト用）。
    本体処理は別関数に切り出し、関数を抜けてCOM参照を解放してから gc.collect() → CoUninitialize する。"""
    client, pythoncom = com if com is not None else import_com()
    if client is None:
        rep.log("❌ win32com / pythoncom が import できません。Windows + Outlook + pywin32 の環境で実行してください。")
        return 2
    stores = []
    pythoncom.CoInitialize()
    exc = None
    code = 1
    try:
        code = _inventory_core(args, rep, client, stores)
    except BaseException as e:  # noqa: BLE001  解放後に再送出する
        exc = e
    # 全フォルダ・全ストアのCOM参照を先に外す（dictは共有されている）
    try:
        for st in stores:
            for fo in st.get("folders", []):
                fo["com"] = None
            st["folders"] = []
            st["com"] = None
        stores.clear()
    except Exception:
        pass
    st = fo = None
    if exc is not None:
        exc.__traceback__ = None   # フレーム（COM参照を持つローカル）を保持しない
    gc.collect()
    try:
        pythoncom.CoUninitialize()
    except Exception:
        pass
    if exc is not None:
        raise exc
    return code


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    args = parse_args(argv)
    try:
        month_range(parse_ym(args.from_ym), parse_ym(args.to_ym))
        sanitize_probe_word(args.probe_word)
    except ValueError as e:
        print(f"❌ 引数エラー: {e}")
        return 2
    rep = Reporter(resolve_output_path(args.output))
    code = 1
    try:
        code = run_inventory(args, rep)
    except KeyboardInterrupt:
        rep.log("⛔ Ctrl+C を受け付けました。途中結果は保存済みです。")
    except Exception as e:
        rep.log(f"❌ 想定外のエラー: {error_kind(e)}（途中結果は保存済みです）")
    finally:
        rep.close()
        if rep.path:
            names = [n for n in (getpass.getuser(), os.environ.get("USERNAME")) if n]
            print(f"💾 結果を保存しました: {mask_display_name(mask_user_path(rep.path, names), names)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
