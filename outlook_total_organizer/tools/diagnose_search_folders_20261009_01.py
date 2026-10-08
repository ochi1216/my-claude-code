# -*- coding: utf-8 -*-
"""
検索フォルダー診断: 「未(ToMe)」「未(WithMe)」「未(CcMe)」等の検索フォルダーが常に0件になる
不具合の切り分け用。読み取り専用。

【目的】
各ストアの GetSearchFolders() で次を一覧表示し、「条件が壊れた」のか「評価が止まっている
(休止/未再評価/索引未完了)」のかを切り分ける材料にする。
  * 検索フォルダー名 / 親ストアの名前・種別(現行/PST/アーカイブ) / DefaultItemType
  * Search.Filter(条件。メールアドレス・引用された値はマスク) / Search.Scope(範囲) /
    Search.SearchSubFolders / Search.IsSynchronous / Search.Tag
  * Items.Count / 未読件数
  * (任意 --verify-restrict) 同じ条件を範囲フォルダーの Items.Restrict でスキャンした件数
    → 「検索フォルダー=0 なのに Restrict>0」なら、条件は正しく検索フォルダー側の評価が止まっている
  * Outlook のキャッシュモード状態(Namespace.ExchangeConnectionMode, Store.IsCachedExchange,
    Store.IsInstantSearchEnabled) ※取得できた範囲のみ

【使い方】（Windows + Outlook 起動済み + pywin32）
    python diagnose_search_folders_20261009_01.py
    python diagnose_search_folders_20261009_01.py --verify-restrict --mask-names
  主なオプション:
    --verify-restrict      同じ条件を Items.Restrict でスキャンした件数も出す（遅くなりうる）
    --verify-max-folders   Restrict 確認で読む範囲フォルダー数の上限（既定 5。サブフォルダー含む）
    --verify-timeout       検索フォルダー1個あたりの Restrict 確認の制限秒数（既定 60）。
                           ※フォルダーとフォルダーの間でしか判定できない（1フォルダーのRestrictは中断できない）
    --verify-max-items     Items.Count がこの件数を超えるフォルダーは Restrict を省略（既定 20000。0で無制限）。
                           現行メールボックスの受信トレイ等が大きい場合は引き上げる（時間がかかる）
    --only-names           対象にする検索フォルダー名の一部（カンマ区切り。既定は全部）
    --show-filter-raw      Filter のマスクを外す（既定はマスク。共有前に要確認）
                           ※マスクは引用符内の値が中心。引用符なしの値は一部残りうるので共有前に目視確認すること
    --mask-names           ストア名・フォルダー名を連番（Store-01 / SF-001）に置換
    --output               結果txtの保存先（既定: outlook_total_organizer/mail_reports/ 配下）

【安全方針】
  * 読み取り専用。Delete/Move/Save/MarkAsRead/AddStore/検索フォルダーの再作成・条件変更は一切しない。
  * 件名・本文・送信者・宛先アドレスは出力しない。Filter 内のメールアドレスは <MAIL>、引用された
    値（氏名など）は <NAME> に置換する（既定ON）。エラーは種別のみ。
  * 注意: --mask-names を付けないと、検索フォルダー名・ストア名・PSTファイルパス(ユーザー名は<USER>に置換)
    が生で出力される。共有する場合は --mask-names を付けるか内容を確認すること。
  * 1件失敗しても続行。結果は .gitignore 済みの mail_reports/ に保存。

【未確認（実機で要確認）】
  * Search.Scope の文字列は '\\\\ストア名\\フォルダー' 形式という想定。違う形式なら範囲フォルダーを解決できず
    「未解決」と表示される（Restrict確認が出ないだけで他の項目には影響しない）。
  * 範囲の解決は Namespace.Folders のトップレベル名と Store.DisplayName の一致が前提。
    同名のストアが複数あるときは最初の1つを使う。
  * ExchangeConnectionMode の数値ラベルは記憶ベース。
"""
import argparse
import gc
import getpass
import os
import re
import sys
import tempfile
import time
from datetime import datetime

SCRIPT_VERSION = "20261009_01"

DEFAULT_VERIFY_MAX_FOLDERS = 5
DEFAULT_VERIFY_TIMEOUT = 60
DEFAULT_VERIFY_MAX_ITEMS = 20000
MAX_SCOPE_DEPTH = 3
OL_FOLDER_SEARCH_FOLDER_ROOT_NAMES = {"検索フォルダー", "search folders"}

ARCHIVE_NAME_PATTERNS = ["オンライン アーカイブ", "online archive", "in-place archive", "archive -"]

# OlExchangeConnectionMode（記憶ベース。不明な値は数値のまま表示する）
CONNECTION_MODE_LABELS = {
    0: "olNoExchange(Exchange無し)",
    100: "olOffline",
    200: "olCachedOffline",
    300: "olDisconnected",
    400: "olCachedDisconnected",
    500: "olCachedConnectedHeaders(キャッシュ:ヘッダーのみ)",
    600: "olCachedConnectedDrizzle(キャッシュ:ドリズル)",
    700: "olCachedConnectedFull(キャッシュ:フル)",
    800: "olOnline(オンライン=キャッシュ無し)",
}

# OlDefaultItemType
DEFAULT_ITEM_TYPE_LABELS = {
    0: "メール(olMailItem)", 1: "予定(olAppointmentItem)", 2: "連絡先(olContactItem)",
    3: "タスク(olTaskItem)", 4: "仕訳帳(olJournalItem)", 5: "メモ(olNoteItem)",
    6: "投稿(olPostItem)",
}

MAIL_ADDR_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+", re.UNICODE)
QUOTED_RE = re.compile(r"\"([^\"]*)\"|'([^']*)'")
FIELD_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
URN_RE = re.compile(r"urn:schemas[^\"'\s]*", re.IGNORECASE)
SAFE_KEYWORD_RE = re.compile(r"^\s*(true|false|yes|no|-?\d+(\.\d+)?)\s*$", re.IGNORECASE)
SAFE_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}( \d{1,2}:\d{2}(:\d{2})?)?$")
SAFE_SCHEMA_RE = re.compile(r"^(urn:schemas[\w:./-]*|http://schemas\.microsoft\.com/[\w/.\-]*)$", re.IGNORECASE)
MAIL_PH = "\ue000"
UNQUOTED_RHS_RE = re.compile(
    r"(?P<op><>|<=|>=|=|<|>|\bLIKE\b|\bci_phrasematch\b|\bci_startswith\b)(?P<sp>\s*)"
    r"(?P<val>[^\s'\"\[\]()=<>][^'\"()]*?)(?=\s+(?:AND|OR|NOT)\b|\s*\)|\s*$)",
    re.IGNORECASE)


# ============================================================
# 純粋関数（COM不要・Linuxでテスト可能）
# ============================================================
def mask_emails(text):
    """メールアドレス形式の文字列を <MAIL> に置換する。"""
    if not text:
        return text or ""
    return MAIL_ADDR_RE.sub("<MAIL>", str(text))


def _is_safe_value(value):
    v = value.strip()
    return bool(SAFE_SCHEMA_RE.match(v) or SAFE_DATE_RE.match(v) or SAFE_KEYWORD_RE.match(v))


def _mask_literal(value):
    """引用符内の値1つをマスクする。安全な値(スキーマ名・日付・数値・真偽値)以外は <MAIL> / <NAME>。"""
    if value == "" or _is_safe_value(value):
        return value
    replaced = MAIL_ADDR_RE.sub(MAIL_PH, value)
    if MAIL_PH in replaced:
        rest = replaced.replace(MAIL_PH, "")
        if re.fullmatch(r"[\s%*_]*", rest):   # メール(と%等のワイルドカード)だけ
            return replaced.replace(MAIL_PH, "<MAIL>")
    return "<NAME>"


def _split_literals(text):
    """引用符(' または ")を1文字ずつ走査して [(is_literal, quote, body), ...] に分ける。
    引用符の重ね書き('')とバックスラッシュのエスケープ(\\')は文字列内として扱う。
    閉じていない引用符は末尾までをリテラルとして扱う（氏名を素通しにしない）。"""
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"'):
            if buf:
                out.append((False, "", "".join(buf)))
                buf = []
            q, i, body = ch, i + 1, []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n and text[i + 1] == q:
                    body.append(c + q)
                    i += 2
                    continue
                if c == q:
                    if i + 1 < n and text[i + 1] == q:
                        body.append(q + q)
                        i += 2
                        continue
                    break
                body.append(c)
                i += 1
            out.append((True, q, "".join(body)))
            i += 1   # 閉じ引用符(無ければ範囲外で終了)
        else:
            buf.append(ch)
            i += 1
    if buf:
        out.append((False, "", "".join(buf)))
    return out


def _mask_unquoted(segment):
    """引用符の外側: メールを <MAIL>、比較演算子/LIKEの右辺の引用符なし値(安全な値以外)を <NAME> に。"""
    seg = MAIL_ADDR_RE.sub(MAIL_PH, segment)

    def repl(m):
        val = m.group("val")
        if val.strip() == MAIL_PH or _is_safe_value(val):
            return m.group(0)
        return f"{m.group('op')}{m.group('sp')}<NAME>"

    seg = UNQUOTED_RHS_RE.sub(repl, seg)
    return seg.replace(MAIL_PH, "<MAIL>")


def mask_filter(flt, enabled=True):
    """Search.Filter 文字列のマスク。
    enabled=True: 引用符(' ")を先に走査して値を切り出し、リテラル内のメールだけを <MAIL>、
    安全な値(スキーマ名・日付・数値・真偽値。全体一致のみ)以外のリテラルは <NAME> に置換する。
    引用符の外のメールは <MAIL>、比較演算子/LIKEの右辺の引用符なし値も <NAME> にする
    （ただし書式が特殊な引用符なしの値は残りうる。共有前に目視確認すること）。
    enabled=False: そのまま返す。"""
    if flt is None:
        return ""
    text = str(flt)
    if not enabled:
        return text
    parts = []
    for is_lit, q, body in _split_literals(text):
        if is_lit:
            parts.append(f"{q}{_mask_literal(body)}{q}")
        else:
            parts.append(_mask_unquoted(body))
    return "".join(parts)


def summarize_filter(flt):
    """条件文字列の要約（値は含めない）: 形式(DASL/DASLでない)、参照項目、論理演算子の数、長さ。"""
    if not flt:
        return "条件なし(空)"
    text = str(flt)
    is_dasl = text.lstrip().lower().startswith("@sql") or "urn:schemas" in text.lower()
    fields = []
    for f in URN_RE.findall(text):
        short = f.rstrip(")").split(":")[-1].split("/")[-1]
        if short and short not in fields:
            fields.append(short)
    for f in FIELD_BRACKET_RE.findall(text):
        if f not in fields:
            fields.append(f)
    upper = text.upper()
    n_and = len(re.findall(r"\bAND\b", upper))
    n_or = len(re.findall(r"\bOR\b", upper))
    n_not = len(re.findall(r"\bNOT\b", upper))
    kind = "DASL(@SQL)" if is_dasl else "Restrict形式"
    fl = ",".join(fields[:12]) if fields else "(項目名を抽出できず)"
    if len(fields) > 12:
        fl += f"…他{len(fields) - 12}"
    flags = []
    if re.search(r"unread|isread", text, re.IGNORECASE):
        flags.append("未読条件あり")
    if re.search(r"flag", text, re.IGNORECASE):
        flags.append("フラグ条件あり")
    extra = f" / {'・'.join(flags)}" if flags else ""
    return f"{kind} / 項目: {fl} / AND×{n_and} OR×{n_or} NOT×{n_not} / {len(text)}文字{extra}"


def parse_scope(scope):
    """Search.Scope 文字列 "'\\\\Mailbox\\Inbox','\\\\Mailbox\\Sent'" をフォルダーパスのリストにする。"""
    if not scope:
        return []
    items = re.findall(r"'([^']*)'|\"([^\"]*)\"", str(scope))
    out = [(a or b).strip() for a, b in items if (a or b).strip()]
    if not out:
        out = [p.strip() for p in str(scope).split(",") if p.strip()]
    return out


def split_scope_path(path):
    """'\\\\StoreName\\Folder\\Sub' -> ['StoreName', 'Folder', 'Sub']"""
    return [p for p in re.split(r"[\\/]+", path or "") if p]


def summarize_scope(scope, store_fn=None, folder_fn=None):
    """範囲の要約文。store_fn は先頭のストア名部分、folder_fn は2番目以降のフォルダー名部分に適用する
    (None なら生のまま。メール形式は常に <MAIL>)。"""
    paths = parse_scope(scope)
    if not paths:
        return "範囲なし(空)"
    store_fn = store_fn or (lambda s: s)
    folder_fn = folder_fn or (lambda s: s)
    shown = []
    for p in paths[:6]:
        parts = split_scope_path(p)
        masked = [mask_emails(store_fn(x) if k == 0 else folder_fn(x)) for k, x in enumerate(parts)]
        shown.append("\\" + "\\".join(masked))
    more = f" …他{len(paths) - 6}" if len(paths) > 6 else ""
    stores = []
    for p in paths:
        parts = split_scope_path(p)
        if parts and parts[0] not in stores:
            stores.append(parts[0])
    return f"{len(paths)}フォルダー / {len(stores)}ストア: " + " ; ".join(shown) + more


def scope_store_names(scope):
    """範囲に含まれるストア名（重複なし・出現順）。"""
    out = []
    for p in parse_scope(scope):
        parts = split_scope_path(p)
        if parts and parts[0] not in out:
            out.append(parts[0])
    return out


def connection_mode_label(value):
    try:
        v = int(value)
    except Exception:
        return "不明(取得不可)"
    return CONNECTION_MODE_LABELS.get(v, f"不明な値({v})")


def default_item_type_label(value):
    try:
        v = int(value)
    except Exception:
        return "不明"
    return DEFAULT_ITEM_TYPE_LABELS.get(v, f"その他({v})")


def store_kind_label(is_default, file_path, display_name, is_data_file=None):
    """ストア種別: アーカイブ / PST / OST / 現行(既定) / その他。"""
    name = (display_name or "").lower()
    if not is_default and any(p in name for p in ARCHIVE_NAME_PATTERNS):
        return "アーカイブ"
    fp = (file_path or "").lower()
    if fp.endswith(".pst"):
        return "PST"
    if fp.endswith(".ost"):
        return "現行(既定)" if is_default else "OST(Exchange等)"
    if is_default:
        return "現行(既定)"
    if is_data_file:
        return "データファイル(PST/OST?)"
    return "その他"


def error_kind(exc):
    """例外の種別のみ（メッセージは出さない）。com_error なら HRESULT の16進を付ける。"""
    name = type(exc).__name__
    try:
        hr = getattr(exc, "hresult", None)
        if hr is None and exc.args and isinstance(exc.args[0], int):
            hr = exc.args[0]
        if hr is not None:
            return f"{name}(0x{hr & 0xFFFFFFFF:08X})"
    except Exception:
        pass
    return name


def mask_display_name(text, user_names=()):
    out = mask_emails(text or "")
    for n in sorted({n for n in user_names if n and len(n) >= 3}, key=len, reverse=True):
        out = re.sub(re.escape(n), "<USER>", out, flags=re.IGNORECASE)
    return out


def mask_user_path(path, extra_user_names=()):
    if not path:
        return path or ""
    text = str(path)
    text = re.sub(r"(?i)([\\/](?:Users|home)[\\/])([^\\/]+)", r"\1<USER>", text)
    text = re.sub(r"(?i)(OneDrive\s*-\s*)([^\\/]+)", r"\1<ORG>", text)
    return mask_display_name(text, extra_user_names)


class NameMasker:
    """--mask-names 用。同じ名前には同じ連番（Store-01 / SF-001）を割り当てる。"""

    def __init__(self, enabled, prefix, width=2):
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


def diagnose_hints(rec):
    """1つの検索フォルダー結果(dict)から、解釈のヒント文のリストを作る（推測を含む。断定しない）。
    rec のキー: items_count, unread_count, restrict_count(None可), restrict_capped(bool), filter_empty,
                scope_empty, is_synchronous, default_item_type, errors(list)"""
    hints = []
    cnt = rec.get("items_count")
    rc = rec.get("restrict_count")
    if rec.get("filter_empty"):
        hints.append("⚠️ 条件(Filter)が空です。条件が失われた/壊れた疑い(要再設定)")
    if rec.get("scope_empty"):
        hints.append("⚠️ 範囲(Scope)が空です。対象フォルダーが無い疑い")
    dit = rec.get("default_item_type")
    if dit is not None and dit != 0:
        hints.append(f"ℹ️ DefaultItemType がメール以外です({default_item_type_label(dit)})")
    if cnt == 0 and rc is not None and rc > 0:
        suffix = "以上" if rec.get("restrict_capped") else ""
        hints.append(f"🔎 検索フォルダー0件だが同条件のRestrictは{rc}件{suffix}: 条件は有効で、"
                     f"検索フォルダー側の評価が止まっている/休止の疑い（クリックで再評価されるか確認）")
    elif cnt == 0 and rc == 0:
        hints.append("🔎 検索フォルダーもRestrictも0件: 条件と範囲を確認（範囲のフォルダーが空/別ストアでないか）")
    elif cnt is not None and cnt > 0 and rc is not None and rc >= 0 and not rec.get("restrict_capped") and rc != cnt:
        hints.append(f"ℹ️ 検索フォルダー{cnt}件とRestrict{rc}件に差があります（評価途中/範囲の解釈差の可能性）")
    if rec.get("is_synchronous") is False and cnt == 0:
        hints.append("ℹ️ IsSynchronous=False（非同期検索）。0件は検索未完了の状態かもしれません")
    if rec.get("errors"):
        hints.append("⚠️ 取得エラー: " + ", ".join(rec["errors"]))
    return hints


def format_record(rec, idx=None):
    """検索フォルダー1件の表示行リスト（件名等は含まない）。"""
    head = f"  [{idx}] " if idx is not None else "  "
    lines = [f"{head}📂 {rec.get('name', '?')}"]
    lines.append(f"      親ストア: {rec.get('store_label', '?')} ({rec.get('store_kind', '?')})")
    lines.append(f"      DefaultItemType: {default_item_type_label(rec.get('default_item_type'))}")
    lines.append(f"      件数: Items.Count={_fmt(rec.get('items_count'))} / 未読={_fmt(rec.get('unread_count'))}")
    lines.append(f"      IsSynchronous={_fmt(rec.get('is_synchronous'))} / SearchSubFolders={_fmt(rec.get('search_subfolders'))}")
    lines.append(f"      条件の要約: {rec.get('filter_summary', '?')}")
    lines.append(f"      条件(マスク済み): {rec.get('filter_masked', '')}")
    lines.append(f"      範囲: {rec.get('scope_summary', '?')}")
    if rec.get("restrict_count") is not None or rec.get("restrict_note"):
        rc = rec.get("restrict_count")
        s = _fmt(rc) + ("以上(上限/時間切れ)" if rec.get("restrict_capped") else "")
        note = f" / {rec['restrict_note']}" if rec.get("restrict_note") else ""
        lines.append(f"      Restrict再スキャン: {s}{note}")
    for h in diagnose_hints(rec):
        lines.append(f"      {h}")
    return lines


def _fmt(v):
    return "取得不可" if v is None else str(v)


def default_output_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "mail_reports")


def default_output_name(now=None):
    now = now or datetime.now()
    return f"diagnose_search_folders_{now.strftime('%Y%m%d_%H%M%S')}.txt"


def resolve_output_path(output_arg, now=None):
    name = default_output_name(now)
    if not output_arg:
        return os.path.join(default_output_dir(), name)
    if os.path.isdir(output_arg) or output_arg.endswith(("/", "\\")):
        return os.path.join(output_arg, name)
    return output_arg


def name_matches(name, only_names):
    """--only-names（部分一致・大文字小文字無視）に合うか。only_names が空なら常にTrue。"""
    if not only_names:
        return True
    n = (name or "").lower()
    return any(k.strip().lower() in n for k in only_names if k.strip())


def parse_only_names(text):
    return [t.strip() for t in (text or "").split(",") if t.strip()]


# ============================================================
# 出力
# ============================================================
class Reporter:
    """コンソール表示 + 1行ごとにファイルへ追記・flush。書けなければ一時フォルダへ退避。"""

    def __init__(self, path=None):
        self.lines = []
        self.path = path
        self.fh = None
        if path:
            self._open(path)

    def _open(self, path):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.fh = open(path, "w", encoding="utf-8-sig", newline="\n")
        except Exception:
            self._fallback()

    def _fallback(self):
        try:
            if self.fh:
                self.fh.close()
        except Exception:
            pass
        self.fh = None
        try:
            p = os.path.join(tempfile.gettempdir(), os.path.basename(self.path or "") or default_output_name())
            fh = open(p, "w", encoding="utf-8-sig", newline="\n")
            fh.write("\n".join(self.lines) + ("\n" if self.lines else ""))
            fh.flush()
            self.fh, self.path = fh, p
            print("⚠️ 保存先に書けないため一時フォルダへ退避しました", flush=True)
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
    try:
        import win32com.client as client  # noqa: WPS433
        import pythoncom  # noqa: WPS433
        return client, pythoncom
    except Exception:
        return None, None


def safe_attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _com_iter(coll):
    """COMコレクションを1始まりインデックスで安全に列挙する（失敗は打ち切り）。"""
    try:
        n = int(coll.Count)
    except Exception:
        return
    for i in range(1, n + 1):
        try:
            yield coll.Item(i)
        except Exception:
            continue


def resolve_scope_folder(namespace, path):
    """'\\\\Store\\A\\B' をたどって Folder を返す。見つからなければ None（読み取りのみ）。"""
    parts = split_scope_path(path)
    if not parts:
        return None
    cur = None
    try:
        for st in _com_iter(namespace.Folders):
            if safe_attr(st, "Name") == parts[0]:
                cur = st
                break
    except Exception:
        return None
    if cur is None:
        return None
    for p in parts[1:]:
        nxt = None
        try:
            for sub in _com_iter(cur.Folders):
                if safe_attr(sub, "Name") == p:
                    nxt = sub
                    break
        except Exception:
            return None
        if nxt is None:
            return None
        cur = nxt
    return cur


def collect_scope_folders(namespace, scope, search_subfolders, max_folders):
    """範囲のフォルダー（SearchSubFolders なら浅い階層のサブフォルダーも）を max_folders まで集める。
    戻り値: (folders, truncated, unresolved_count)"""
    out, unresolved, truncated = [], 0, False
    queue = []
    for p in parse_scope(scope):
        f = resolve_scope_folder(namespace, p)
        if f is None:
            unresolved += 1
        else:
            queue.append((f, 0))
    while queue:
        f, depth = queue.pop(0)
        if len(out) >= max_folders:
            truncated = True
            break
        out.append(f)
        if search_subfolders and depth < MAX_SCOPE_DEPTH:
            subs = safe_attr(f, "Folders")
            if subs is not None:
                for sub in _com_iter(subs):
                    queue.append((sub, depth + 1))
    return out, truncated, unresolved


def restrict_scan(folders, flt, timeout_sec, max_items=0, clock=time.time):
    """各フォルダーの Items.Restrict(flt).Count を合計する。
    ・timeout_sec は「フォルダーとフォルダーの間」でしか判定できない（1フォルダーのRestrictは中断できない）。
    ・max_items>0 のとき、Items.Count がそれを超えるフォルダーは Restrict せず省略する。
    戻り値: (合計, capped(打ち切り/省略/一部失敗), エラー種別リスト, 省略数, 走査したフォルダー数)"""
    total, capped, errs, skipped, scanned = 0, False, [], 0, 0
    t0 = clock()
    for f in folders:
        if clock() - t0 > timeout_sec:
            capped = True
            break
        try:
            if max_items and int(f.Items.Count) > max_items:
                skipped += 1
                capped = True
                continue
            total += int(f.Items.Restrict(flt).Count)
            scanned += 1
        except Exception as e:  # noqa: BLE001
            errs.append(error_kind(e))
            capped = True
    return total, capped, errs, skipped, scanned


def describe_store(store, is_default, masker):
    name = safe_attr(store, "DisplayName", "") or ""
    path = safe_attr(store, "FilePath", "") or ""
    is_df = safe_attr(store, "IsDataFileStore", None)
    kind = store_kind_label(is_default, path, name, is_df)
    return {"name": name, "label": masker.mask(mask_emails(name)), "kind": kind, "path": path}


def collect_search_folder_record(sf, store_info, namespace, args, sf_masker, store_masker, folder_masker):
    rec = {"name": sf_masker.mask(mask_emails(safe_attr(sf, "Name", "?") or "?")),
           "store_label": store_info["label"], "store_kind": store_info["kind"], "errors": []}
    rec["default_item_type"] = _to_int(safe_attr(sf, "DefaultItemType", None))
    try:
        items = sf.Items
        rec["items_count"] = int(items.Count)
    except Exception as e:  # noqa: BLE001
        rec["items_count"] = None
        rec["errors"].append("Items.Count:" + error_kind(e))
    uc = safe_attr(sf, "UnReadItemCount", None)
    rec["unread_count"] = _to_int(uc)
    search = safe_attr(sf, "Search", None)
    flt, scope = "", ""
    if search is None:
        rec["errors"].append("Search取得不可")
    else:
        flt = safe_attr(search, "Filter", "") or ""
        scope = safe_attr(search, "Scope", "") or ""
        rec["is_synchronous"] = safe_attr(search, "IsSynchronous", None)
        rec["search_subfolders"] = safe_attr(search, "SearchSubFolders", None)
    rec["filter_empty"] = not str(flt).strip()
    rec["scope_empty"] = not str(scope).strip()
    rec["filter_summary"] = summarize_filter(flt)
    rec["filter_masked"] = mask_filter(flt, not args.show_filter_raw)
    rec["scope_summary"] = summarize_scope(
        scope, store_masker.mask if store_masker.enabled else None,
        folder_masker.mask if folder_masker.enabled else None)
    rec["restrict_count"], rec["restrict_capped"], rec["restrict_note"] = None, False, ""
    if args.verify_restrict and not rec["filter_empty"] and not rec["scope_empty"]:
        try:
            folders, trunc, unres = collect_scope_folders(
                namespace, scope, bool(rec.get("search_subfolders")), args.verify_max_folders)
            if not folders:
                rec["restrict_note"] = f"範囲フォルダーを解決できず(未解決{unres})"
            else:
                total, capped, errs, skipped, scanned = restrict_scan(
                    folders, str(flt), args.verify_timeout, args.verify_max_items)
                rec["restrict_count"] = total if scanned > 0 else None
                rec["restrict_capped"] = bool(capped or trunc)
                notes = [f"{scanned}/{len(folders)}フォルダーを走査"]
                if skipped:
                    notes.append(f"大きいため{skipped}フォルダー省略(--verify-max-items={args.verify_max_items})")
                if trunc:
                    notes.append("上限で打ち切り")
                if unres:
                    notes.append(f"未解決{unres}")
                if errs:
                    notes.append("エラー:" + ",".join(sorted(set(errs))))
                rec["restrict_note"] = " / ".join(notes)
        except Exception as e:  # noqa: BLE001
            rec["restrict_note"] = "Restrict確認失敗:" + error_kind(e)
    return rec


def _to_int(v):
    try:
        return int(v)
    except Exception:
        return None


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="検索フォルダー診断（読み取り専用）")
    ap.add_argument("--verify-restrict", action="store_true", help="同じ条件をItems.Restrictで走査した件数も出す")
    ap.add_argument("--verify-max-folders", type=int, default=DEFAULT_VERIFY_MAX_FOLDERS)
    ap.add_argument("--verify-timeout", type=int, default=DEFAULT_VERIFY_TIMEOUT,
                    help="Restrict確認の制限秒数。フォルダー間でしか判定できず、1フォルダーのRestrictは中断できない")
    ap.add_argument("--verify-max-items", type=int, default=DEFAULT_VERIFY_MAX_ITEMS,
                    help="Items.Count がこの件数を超えるフォルダーはRestrictを省略（0で無制限。大きいフォルダーは時間がかかる）")
    ap.add_argument("--only-names", default="", help="対象の検索フォルダー名の一部（カンマ区切り）")
    ap.add_argument("--show-filter-raw", action="store_true", help="Filterのマスクを外す（共有前に要確認）")
    ap.add_argument("--mask-names", action="store_true", help="ストア名・フォルダー名を連番に置換")
    ap.add_argument("--output", default="", help="結果txtの保存先（既定: mail_reports/ 配下）")
    return ap.parse_args(argv)


def _diagnose_core(args, rep, client):
    names = [n for n in (getpass.getuser(), os.environ.get("USERNAME")) if n]
    only = parse_only_names(args.only_names)
    store_masker = NameMasker(args.mask_names, "Store")
    sf_masker = NameMasker(args.mask_names, "SF", 3)
    folder_masker = NameMasker(args.mask_names, "Folder", 3)
    rep.log(f"🩺 検索フォルダー診断 v{SCRIPT_VERSION}（読み取り専用）")
    rep.log(f"🕒 実行: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    rep.log("ℹ️ 件名・本文・アドレスは出力しません。Filterは既定でマスクします。")
    if args.verify_restrict:
        rep.log(f"⏳ --verify-restrict: 大きいフォルダーでは時間がかかります（{args.verify_max_items}件超のフォルダーは省略。"
                f"タイムアウトはフォルダー間でのみ判定）。途中で止めるには Ctrl+C。")
    outlook = client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    ver = safe_attr(outlook, "Version", None)
    rep.log(f"🧭 Outlook バージョン: {ver if ver else '取得不可'}")
    mode = safe_attr(namespace, "ExchangeConnectionMode", None)
    rep.log(f"🌐 Exchange接続モード(Namespace.ExchangeConnectionMode): "
            f"{connection_mode_label(mode)}（数値={_fmt(_to_int(mode))}）")
    default_store_name = None
    try:
        default_store_name = namespace.GetDefaultFolder(6).Store.DisplayName
    except Exception as e:  # noqa: BLE001
        rep.log(f"⚠️ 既定の受信トレイのストアを取得できません: {error_kind(e)}")
    stores = list(_com_iter(namespace.Stores))
    rep.log(f"🗄️ 接続中のストア数: {len(stores)}（Outlook上の並び順）")
    rep.log("=" * 60)
    total_sf = zero_sf = 0
    errors = []
    for si, store in enumerate(stores, 1):
        sname = safe_attr(store, "DisplayName", "") or ""
        info = describe_store(store, sname == default_store_name and sname != "", store_masker)
        cached = safe_attr(store, "IsCachedExchange", None)
        isearch = safe_attr(store, "IsInstantSearchEnabled", None)
        rep.log(f"🗄️ ストア{si}: {info['label']} 種別={info['kind']} / キャッシュモード(IsCachedExchange)={_fmt(cached)}"
                f" / 即時検索(IsInstantSearchEnabled)={_fmt(isearch)}")
        if info["path"]:
            rep.log(f"      ファイル: {mask_display_name(mask_user_path(info['path'], names), names) if not args.mask_names else '<masked>'}")
        try:
            sfs = list(_com_iter(store.GetSearchFolders()))
        except Exception as e:  # noqa: BLE001
            k = error_kind(e)
            errors.append((info["label"], k))
            rep.log(f"   ❌ GetSearchFolders 失敗: {k}")
            continue
        rep.log(f"   検索フォルダー数: {len(sfs)}")
        for i, sf in enumerate(sfs, 1):
            raw_name = safe_attr(sf, "Name", "") or ""
            if not name_matches(raw_name, only):
                continue
            try:
                rec = collect_search_folder_record(sf, info, namespace, args, sf_masker, store_masker, folder_masker)
            except Exception as e:  # noqa: BLE001
                k = error_kind(e)
                errors.append((info["label"], k))
                rep.log(f"   ❌ [{i}] 取得失敗: {k}")
                continue
            total_sf += 1
            if rec.get("items_count") == 0:
                zero_sf += 1
            for ln in format_record(rec, i):
                rep.log(ln)
        rep.log("-" * 60)
    rep.log(f"📊 集計: 検索フォルダー {total_sf} 個中、Items.Count=0 が {zero_sf} 個")
    if errors:
        counts = {}
        for _w, k in errors:
            counts[k] = counts.get(k, 0) + 1
        rep.log("⚠️ エラー種別: " + ", ".join(f"{k}:{v}件" for k, v in sorted(counts.items())))
    rep.log("💡 読み方: 「検索フォルダー0件・Restrict>0」→ 条件は有効で検索フォルダー側の評価停止/休止。"
            "「どちらも0件」→ 条件・範囲・ストアの中身を確認。")
    return 0


def run_diagnosis(args, rep, com=None):
    """診断の入口。com=(client, pythoncom) を渡すとフェイク注入できる（テスト用）。"""
    client, pythoncom = com if com is not None else import_com()
    if client is None:
        rep.log("❌ win32com / pythoncom が import できません。Windows + Outlook + pywin32 の環境で実行してください。")
        return 2
    pythoncom.CoInitialize()
    exc, code = None, 1
    try:
        code = _diagnose_core(args, rep, client)
    except BaseException as e:  # noqa: BLE001
        exc = e
    if exc is not None:
        exc.__traceback__ = None
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
    rep = Reporter(resolve_output_path(args.output))
    code = 1
    try:
        code = run_diagnosis(args, rep)
    except KeyboardInterrupt:
        rep.log("⛔ Ctrl+C を受け付けました。途中結果は保存済みです。")
    except Exception as e:  # noqa: BLE001
        rep.log(f"❌ 想定外のエラー: {error_kind(e)}（途中結果は保存済みです）")
    finally:
        rep.close()
        if rep.path:
            names = [n for n in (getpass.getuser(), os.environ.get("USERNAME")) if n]
            print(f"💾 結果を保存しました: {mask_display_name(mask_user_path(rep.path, names), names)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
