# -*- coding: utf-8 -*-
r"""
「判断待ち」定義の診断スクリプト（読み取り専用）。

アクションタブ「⚖️ 判断待ち」(自分宛て × 承認・決裁/相談・質問/判断語 × 未完了)の定義が、実データで
「多すぎ/少なすぎ」にならないかを数秒で確かめる。Outlook・AI・ネットワークには触れない。
本体(outlook_total_organizer_*.py の名前順で最後)の関数をそのまま呼び、判定ロジックは複製しない。

使い方(tools フォルダのまま実行。本体は ../app、データは ../ を見る):
    python diagnose_action_decisions.py
    python diagnose_action_decisions.py --samples 5
        判断待ち上位5件の依頼者・依頼内容(先頭40文字)・期限・受信日も出す(既定オフ。内容が出るので共有前に確認)
    python diagnose_action_decisions.py --alias 別名 --name "表示名" --smtp "a@example.com"
        自分宛て判定の別名を足す(Outlookへ繋がないので手入力。GUIは Outlook の表示名/SMTPで同じ関数を呼ぶ)
    python diagnose_action_decisions.py --dir PATH
        json/ と analysis_cache/ のあるフォルダを指定(既定: このファイルのあるフォルダ)

出力は既定で60行以内。メール本文・件名・要約は出さない(--samples のときだけ依頼内容を出す)。
読み取り専用の担保: .pyc を書かない / 書込み・作成・削除・改名・ネットワーク・Outlook(COM)をプロセス内で遮断 /
AI共通クライアントを読み込まない / 終了コードは常に0(キャッシュが無い・読めない場合も理由を表示して終わる)。
import できない外部ライブラリだけ最小スタブで補う(実物のあるPCでは使わない)。
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # 本体(約700KB)のimportで __pycache__ へ書かない

import argparse
import importlib
import importlib.util
import os
import re
import traceback
import unicodedata
from collections import Counter
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# このスクリプトは <ツールのフォルダ>/tools/ にある。データ(json/ など)はツールのフォルダ、本体は app/ にある
TOOL_DIR = os.path.dirname(SCRIPT_DIR)
APP_DIR = os.path.join(TOOL_DIR, "app")
MAX_LINES = 60          # 既定出力の行数上限(--samples の追加行は含めない)
TOP_TARGETS = 30        # 宛先の内訳に出す上位件数
SAMPLE_CHARS = 40       # --samples で出す依頼内容の文字数
MAX_FINDINGS = 9        # 所見の最大行数
# 所見の閾値(機械的な判定。実データを見て調整してよい)
TH_ALL_MANY = 30        # 全期間の判断待ちがこの件数を超えたら「多すぎ」
TH_7D_MANY = 15         # 直近7日の判断待ちがこの件数を超えたら「毎日見るには多め」
TH_X_TARGET = 10        # 自分宛て判定×の同一宛先がこの件数以上なら「別名の可能性」
TH_EMPTY_TARGET = 0.30  # 判断に当たる自分宛てのうち target 空欄がこの割合以上なら指摘
TH_KEYWORD_ONLY = 0.50  # 判断に当たるもののうち「語だけ」で拾った割合がこの値以上なら指摘
TH_NOMETA = 0.20        # meta無し(除外)スレッドがこの割合以上なら指摘
TH_OTHERS = (20, 3)     # 判断語に当たらない自分宛てが 20件以上かつ判断待ちの3倍以上なら「少なすぎ」を疑う
MIN_ROWS = 10           # 割合系の指摘を出す最小件数
PERIODS = (("直近7日", 7), ("直近14日", 14), ("直近30日", 30), ("全期間", None))
# 本体にこれらが無ければ、判断待ち(A1)未実装の版とみなして案内して終わる
REQUIRED = ("normalize_action_target_token", "is_target_self", "is_decision_action", "build_self_aliases",
            "compute_pending_decisions", "count_recent_error_threads", "load_action_dashboard_cache",
            "load_action_last_run", "ACTION_DASHBOARD_CACHE_FILE", "ACTION_LAST_RUN_FILE", "ACTION_STATUS_FILE",
            "ACTION_SELF_TARGET_ALIASES", "ACTION_DECISION_TYPES", "ACTION_DECISION_KEYWORDS")
STUB_TARGETS = ("win32com.client", "pythoncom", "google.genai", "requests", "bs4",
                "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.font")


# ---------------------------------------------------------------- 表示ユーティリティ
def txt(value) -> str:
    """本体の `str(x or "")` と同じ流儀(None/空/0 は空文字)。"""
    return str(value) if value else ""


def one_line(value) -> str:
    return " ".join(txt(value).split())


def _w(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(text):
    return sum(_w(c) for c in text)


def pad(text, n):
    return text + " " * max(0, n - width(text))


def clip(text, n):
    """表示幅 n(全角=2桁)に収める。超えたら末尾を … にする。"""
    if width(text) <= n:
        return text
    kept, used = "", 0
    for ch in text:
        if used + _w(ch) > n - 1:
            break
        kept, used = kept + ch, used + _w(ch)
    return kept + "…"


def wrap(items, sep=" / ", limit=100, indent="   "):
    lines, cur = [], ""
    for item in items:
        if cur and width(indent + cur + sep + item) > limit:
            lines.append(indent + cur)
            cur = item
        else:
            cur = cur + sep + item if cur else item
    return lines + ([indent + cur] if cur else [])


def pct(part, whole):
    return f"{part / whole:.0%}" if whole else "-"


def stamp(ts, fmt="%m/%d %H:%M"):
    try:
        return datetime.fromtimestamp(float(ts)).strftime(fmt)
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def setup_console():
    """Windowsの cp932 などで絵文字が出力できない環境でも落ちないようにする。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            try:
                "📦⚖️".encode(stream.encoding or "utf-8")
                stream.reconfigure(errors="replace")
            except UnicodeEncodeError:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 環境の準備(スタブ・ガード・本体の読み込み)
def install_stubs_if_missing():
    """import できない外部ライブラリだけ、何でも受ける最小スタブ(MagicMock)を入れる。入れた対象名を返す。"""
    stubbed = []
    for full in STUB_TARGETS:
        try:
            importlib.import_module(full)
            continue
        except Exception:
            stubbed.append(full)
        from unittest import mock
        parts = full.split(".")
        for i in range(len(parts)):
            name = ".".join(parts[:i + 1])
            try:
                importlib.import_module(name)
            except Exception:
                sys.modules[name] = mock.MagicMock(name=name)
                if i:
                    setattr(sys.modules[".".join(parts[:i])], parts[i], sys.modules[name])
    return stubbed


def install_readonly_guard():
    """診断中は「読む」以外を塞ぐ(書込み・作成・削除・改名、ネットワーク、Outlook(COM)起動)。
    正常動作では発動しない。発動したら、その関数が副作用を持っている証拠になる。"""
    import builtins
    import io
    import socket

    def deny(what):
        def _blocked(*args, **kwargs):
            raise PermissionError("[読み取り専用ガード] 診断では禁止された操作です: " + what)
        return _blocked

    real_open, real_os_open = builtins.open, os.open
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            deny("ファイルの書き込み open(%r)" % mode)()
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & write_flags:
            deny("ファイルの書き込み os.open")()
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_makedirs(name, mode=0o777, exist_ok=False):
        if not (exist_ok and os.path.isdir(name)):  # 既存フォルダへの exist_ok=True だけ通す(本体の読込関数が呼ぶ)
            deny("フォルダの作成 " + str(name))()

    builtins.open = io.open = guarded_open
    os.open, os.makedirs = guarded_os_open, guarded_makedirs
    targets = ((os, ("remove", "unlink", "rename", "renames", "replace", "rmdir", "removedirs",
                     "mkdir", "truncate", "symlink", "link")),
               (socket, ("create_connection", "getaddrinfo")),
               (socket.socket, ("connect", "connect_ex")),
               (sys.modules.get("win32com.client"), ("Dispatch", "DispatchEx", "GetObject", "GetActiveObject")))
    for owner, names in targets:
        for name in names:
            if owner is not None and hasattr(owner, name):
                setattr(owner, name, deny(name))


def load_latest_revision():
    """app/ の outlook_total_organizer_<日付>*.py を名前順で最後のものにして import する。"""
    names = sorted(n for n in (os.listdir(APP_DIR) if os.path.isdir(APP_DIR) else [])
                   if re.match(r"outlook_total_organizer_\d{8}.*\.py$", n))
    if not names:
        return None, None
    name = names[-1][:-3]
    spec = importlib.util.spec_from_file_location(name, os.path.join(APP_DIR, names[-1]))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, names[-1]


# ---------------------------------------------------------------- 集計(判定は全て本体の関数に任せる)
def scan_cache(mod, cache, aliases):
    """キャッシュを1回なめて、件数・宛先・種別・「自分宛て→判断に当たる」の内訳を数える。"""
    r = {"valid": 0, "nometa": 0, "error": 0, "broken": 0, "actions": 0, "empty": 0, "text": 0, "ts": [],
         "types": Counter(), "targets": Counter(), "is_self": {},
         "n_self": 0, "by_type": 0, "by_kw": 0, "both": 0, "union": 0, "empty_union": 0}
    type_hit = {}
    for cached in cache["threads"].values():
        data = cached.get("data") if isinstance(cached, dict) else None
        if not isinstance(data, dict) or not data:
            r["broken"] += 1
            continue
        if data.get("_error"):
            r["error"] += 1
            continue
        meta = cached.get("meta")
        if not isinstance(meta, dict) or not meta:
            r["nometa"] += 1
            continue
        r["valid"] += 1
        if isinstance(meta.get("latest_ts"), (int, float)) and meta["latest_ts"] > 0:
            r["ts"].append(meta["latest_ts"])
        label = txt(data.get("action_type")).strip() or "(未設定)"
        r["types"][label] += 1
        if label not in type_hit:
            type_hit[label] = bool(mod.is_decision_action("", label))  # 種別だけの判定(語は空)
        actions = data.get("actions")
        for a in (actions if isinstance(actions, list) else []):
            if not isinstance(a, dict):
                continue
            r["actions"] += 1
            text = txt(a.get("action")).strip()
            if not text:
                r["empty"] += 1
                continue
            r["text"] += 1
            raw = a.get("target", "")
            key = txt(raw).strip()
            r["targets"][key] += 1
            if key not in r["is_self"]:
                r["is_self"][key] = bool(mod.is_target_self(raw, aliases))
            if not r["is_self"][key]:
                continue
            r["n_self"] += 1
            by_type, by_kw = type_hit[label], bool(mod.is_decision_action(text, ""))  # 語だけの判定(種別は空)
            r["by_type"] += by_type
            r["by_kw"] += by_kw
            r["both"] += by_type and by_kw
            if by_type or by_kw:
                r["union"] += 1
                r["empty_union"] += not key
    return r


def get_snapshot(mod, now, aliases):
    """GUIのタブ見出しと同じ本体関数で、見出し・older・others などを再現する。(snap, 失敗理由)。"""
    fn = getattr(mod, "build_action_decision_snapshot", None)
    if not callable(fn):
        return None, "本体に build_action_decision_snapshot がありません"
    if not os.path.isdir("json"):
        return None, "json/ フォルダが無いため省略"
    try:
        snap = fn(now, aliases)
    except Exception as e:
        return None, f"再現に失敗: {type(e).__name__}: {clip(one_line(e), 80)}"
    return (snap, "") if isinstance(snap, dict) and "heading" in snap else (None, "戻り値の形式が想定外")


# ---------------------------------------------------------------- 出力
def section_cache(r, n_threads, last_run, last_run_file, statuses, status_ok):
    parts = [f"有効{r['valid']:,}", f"meta無し(除外){r['nometa']:,}", f"解析失敗(_error){r['error']:,}"]
    if r["broken"]:
        parts.append(f"破損{r['broken']:,}")
    span = f" ／ 受信日 {stamp(min(r['ts']), '%Y-%m-%d')}〜{stamp(max(r['ts']), '%Y-%m-%d')}" if r["ts"] else ""
    L = [f"📦 キャッシュ: スレッド{n_threads:,}件 = " + " + ".join(parts),
         f"   アクション総数{r['actions']:,}件（有効スレッド内。依頼内容が空の{r['empty']:,}件は対象外）{span}"]
    name = os.path.basename(last_run_file)
    if last_run:
        days = f"（{last_run['days']}日分）" if last_run["days"] > 0 else ""  # GUIの「24H」選択は days=0
        L.append(f"   最終解析({name}): {last_run['finished_at'].replace('T', ' ')} 範囲={clip(one_line(last_run['period_label']), 24)}{days}")
    elif os.path.isfile(last_run_file):
        L.append(f"   最終解析({name}): ⚠️ ファイルはあるが読めません（形式不正）")
    else:
        L.append(f"   最終解析({name}): なし（本体でアクション集計を1回実行すると記録されます）")
    if not status_ok:
        L.append("   進捗記録: ⚠️ action_status.json を読めません（壊れている/書込み中）。以降の数は完了/無視を除外していません")
    else:
        c = Counter(v.get("progress") for v in statuses.values() if isinstance(v, dict))
        L.append(f"   進捗記録(action_status.json): {len(statuses):,}件（完了{c['done']:,} / 無視{c['ignored']:,} / 進行中{c['in_progress']:,}）")
    return L


def section_targets(r, max_cells):
    items = sorted(r["targets"].items(), key=lambda kv: (-kv[1], kv[0]))
    shown, rest = items[:max_cells], items[max_cells:]
    L = [f"🎯 宛先(target)の内訳（アクション単位・生の値。上位{len(shown)}／全{len(items):,}種・{r['text']:,}件。○=自分宛て判定 ×=他の人）"]
    if not items:
        return L + ["   （依頼内容のあるアクションがありません）"]
    cells = [f"{'○' if r['is_self'][v] else '×'} {pad(clip(v or '(空欄=あなた扱い)', 22), 22)}{n:>6,}件" for v, n in shown]
    half = (len(cells) + 1) // 2
    for i in range(half):
        L.append("   " + cells[i] + ("    " + cells[half + i] if half + i < len(cells) else ""))
    if rest:
        L.append(f"   …他{len(rest):,}種 計{sum(n for _, n in rest):,}件（うち×判定 {sum(1 for v, _ in rest if not r['is_self'][v]):,}種）")
    return L


def section_types(mod, r):
    items = sorted(r["types"].items(), key=lambda kv: (-kv[1], kv[0]))
    cells = [f"{clip(k, 16)}{'★' if mod.is_decision_action('', k) else ''} {n:,}" for k, n in items[:10]]
    if len(items) > 10:
        cells.append(f"他{len(items) - 10}種 {sum(n for _, n in items[10:]):,}")
    return [f"🏷 スレッドのaction_type別（有効{r['valid']:,}件。★=判断待ち対象の種別）"] + wrap(cells)


def section_funnel(mod, r, pending, snap):
    types, words = "/".join(mod.ACTION_DECISION_TYPES), "/".join(mod.ACTION_DECISION_KEYWORDS)
    closed = r["union"] - len(pending)  # 未完了は本体の compute_pending_decisions の結果から数える(完了/無視で除外された分)
    note = f"うち再浮上{sum(1 for x in pending if x.get('resurfaced')):,}件／完了・無視で除外{closed:,}件" if closed >= 0 \
        else "⚠️ 内訳の合計が合いません: 本体関数と集計の食い違い"
    L = ["⚖️ 判断待ちの内訳（全期間）",
         f"   定義: 自分宛て × [種別={types} または 語={words}] × 未完了",
         f"   自分宛て(is_target_self)と判定: {r['n_self']:,}件 ／ 依頼ありのアクション{r['text']:,}件中（{pct(r['n_self'], r['text'])}）",
         f"   → 判断に当たる: 種別一致{r['by_type']:,} / 語一致{r['by_kw']:,} / 両方{r['both']:,} → どちらか{r['union']:,}件",
         f"   → 未完了(ignored以外。doneは完了後に新着があれば再浮上): {len(pending):,}件 ＝ 判断待ち（{note}）"]
    if snap and snap.get("rows") is not None:
        L.append(f"   タブの対象範囲({snap.get('horizon_days')}日以内): 判断待ち{len(snap['rows']):,}件"
                 f" ／ 古い未対応(older){len(snap.get('older_rows') or []):,}件"
                 f" ／ 判断語に当たらない自分宛て(others){snap.get('others_count') or 0:,}件")
    return L


def section_periods(periods, snap, snap_note):
    L = ["📅 期間別の判断待ち件数（受信日が範囲内のスレッドのみ。解析失敗スレッドは別掲・meta無しは数えない）"]
    L += [f"   {pad(label, 8)}: {len(rows):>4,}件（解析失敗スレッド {errors:,}）" for label, rows, errors in periods]
    if snap:
        L.append(f"   🖥 現在のタブ見出し: {snap['heading']}")
        L.append(f"   🖥 短縮見出し(タブ幅が足りないとき): {snap.get('heading_compact')} ／ 集計範囲: {stamp(snap.get('since_ts'))}以降")
    else:
        L.append(f"   🖥 タブ見出しは再現できません（{snap_note}）")
    return L


def build_findings(mod, r, periods, snap, status_ok):
    """機械的な閾値で、定義の調整が必要そうな点を優先度順に並べる。"""
    pa, p7, union = len(periods[-1][1]), len(periods[0][1]), r["union"]
    f = []
    if not status_ok:
        f.append("⚠️ 進捗記録を読めないため、完了/無視を除外していません（判断待ちが実際より多く出ています）")
    if pa > TH_ALL_MANY:
        f.append(f"⚠️ 全期間の判断待ちが多い: {pa:,}件（{TH_ALL_MANY}件超）／ 完了・無視で除外済み {max(union - pa, 0):,}件")
        f.append("   調整案: 集計期間を絞る／「相談・質問」を種別から外す／判断語(承認・決裁・判断)を絞る")
    if p7 > TH_7D_MANY:
        f.append(f"⚠️ 直近7日だけで{p7:,}件（{TH_7D_MANY}件超）: 毎日見るには多め")
    if pa == 0 and not r["n_self"]:
        f.append("⚠️ 判断待ち0件: 自分宛て判定が0件。🎯の宛先の値と別名（--alias/--name/--smtp）を確認")
    elif pa == 0 and not union:
        f.append(f"⚠️ 判断待ち0件: 自分宛て{r['n_self']:,}件のうち種別にも判断語にも当たるものが0件（定義が厳しすぎる可能性）")
    elif pa == 0:
        f.append(f"ℹ️ 判断待ち0件: 判断に当たる{union:,}件はすべて完了/無視済み")
    elif p7 == 0:
        f.append(f"ℹ️ 直近7日は0件（全期間{pa:,}件）: 受信日の新しい該当案件が無い")
    if union >= MIN_ROWS and r["empty_union"] / union >= TH_EMPTY_TARGET:
        f.append(f"⚠️ 判断に当たる自分宛て{union:,}件のうちtarget空欄が{r['empty_union']:,}件（{pct(r['empty_union'], union)}）: 空欄は自分宛て扱いなので多めの可能性")
    xs = [(v, n) for v, n in r["targets"].most_common() if not r["is_self"][v] and n >= TH_X_TARGET][:3]
    if xs:
        f.append("⚠️ 自分宛て判定×で件数の多い宛先: " + " / ".join(f"{clip(v, 20)} {n:,}" for v, n in xs)
                 + f" → 自分の別名なら --alias \"{clip(xs[0][0], 20)}\" で再実行して比較")
    kw_only = union - r["by_type"]
    if union >= MIN_ROWS and kw_only / union >= TH_KEYWORD_ONLY:
        f.append(f"ℹ️ 判断に当たる{union:,}件のうち{kw_only:,}件（{pct(kw_only, union)}）は「語だけ」で一致: 拾い過ぎなら語(承認・決裁・判断)を絞る候補")
    if snap:  # 以下は本体のsnapshot(=GUIのタブ見出しと同じ計算)の返り値
        rows, others = snap.get("rows"), snap.get("others_count") or 0
        if rows is not None and others >= TH_OTHERS[0] and others >= TH_OTHERS[1] * max(len(rows), 1):
            f.append(f"⚠️ 判断語に当たらない自分宛ての依頼が{others:,}件（判断待ち{len(rows):,}件の{others / max(len(rows), 1):.0f}倍）: 種別/語が狭すぎる可能性")
        if snap.get("older_rows"):
            f.append(f"ℹ️ {snap.get('horizon_days')}日より前に届いた未対応が{len(snap['older_rows']):,}件: 既定の一覧には出ません（GUIの「🕰 古い案件も表示」で確認）")
        last_run = snap.get("last_run") or {}
        if snap.get("partial"):
            f.append(f"ℹ️ 最終解析の範囲が7日未満（{last_run.get('period_label') or str(last_run.get('days')) + '日'}）: 見出しの件数は「N+」（それより前の依頼は解析していない）")
        if snap.get("error_count"):
            f.append(f"ℹ️ 範囲内に解析失敗スレッドが{snap['error_count']:,}件: 見出しの件数は「N+」（実際はそれ以上の可能性。その期間を含めて一覧を生成し直すと再試行される）")
        if snap.get("freshness_unknown"):
            f.append("ℹ️ 最終解析の" + ("記録がありません" if not snap.get("last_run") else "日時が不正、または未来(時計ずれ)です")
                     + ": 見出しは「(判断待ち?・要更新)」（本体でアクション集計を1回実行すると記録される）")
        elif snap.get("stale"):
            f.append(f"ℹ️ 最終解析が{getattr(mod, 'ACTION_DECISION_STALE_HOURS', 24)}時間以上前: 見出しは「(判断待ち?・要更新)」")
    if r["nometa"] >= MIN_ROWS and r["nometa"] / (r["valid"] + r["nometa"] + r["error"] + r["broken"]) >= TH_NOMETA:
        f.append(f"ℹ️ meta無し(除外)が{r['nometa']:,}件: 旧形式のキャッシュで判断待ちに入らない（対象期間を広げて再取得すると解消）")
    if not f:
        return [f"✅ 目立った偏りなし（判断待ち 全期間{pa:,}件／直近7日{p7:,}件）"]
    if len(f) > MAX_FINDINGS:
        f = f[:MAX_FINDINGS - 1] + [f"…ほか{len(f) - MAX_FINDINGS + 1}行の所見を省略"]
    return f


def section_samples(rows, n, scope):
    L = [f"🔎 判断待ち上位{min(n, len(rows))}件（{scope}。依頼内容を含むため、共有する前に中身を確認すること）"]
    for i, row in enumerate(rows[:n], 1):
        action = one_line(row.get("action"))
        action = action[:SAMPLE_CHARS] + ("…" if len(action) > SAMPLE_CHARS else "")
        tag = "【新着】" if row.get("resurfaced") else ""  # 完了後に新着があって再浮上した行(GUIの進捗列は「新着」)
        L.append(f"   {i:>2}. {tag}{clip(one_line(row.get('owner')) or '-', 16)} ｜ {action}"
                 f" ｜ 期限:{clip(one_line(row.get('deadline')) or '-', 14)} ｜ 受信:{one_line(row.get('date_mmdd')) or '-'}")
    return L if rows else L + ["   （判断待ちなし）"]


# ---------------------------------------------------------------- 本体
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="「判断待ち」定義の診断（読み取り専用。Outlook・AI・ネットワークには触れません）")
    p.add_argument("--dir", metavar="PATH", help="json/ と analysis_cache/ があるフォルダ（既定: このスクリプトのあるフォルダ）")
    p.add_argument("--samples", type=int, default=0, metavar="N",
                   help="判断待ち上位N件の依頼者・依頼内容(先頭40文字)・期限・受信日も表示（既定オフ。内容が出るので共有前に確認）")
    p.add_argument("--alias", action="append", default=[], metavar="NAME", help="自分の別名を追加（複数回指定可）")
    p.add_argument("--name", default="", metavar="NAME", help="Outlook上の自分の表示名（別名の自動生成に使う）")
    p.add_argument("--smtp", default="", metavar="ADDR", help="自分のSMTPアドレス（別名の自動生成に使う）")
    return p.parse_args(argv)


def run(args, out, samples):
    now = datetime.now()
    data_dir = os.path.abspath(args.dir) if args.dir else TOOL_DIR
    out.append("🩺 判断待ちの診断（読み取り専用）  実行 " + now.strftime("%Y-%m-%d %H:%M"))
    if not os.path.isdir(data_dir):
        out.append("⚠️ --dir のフォルダが見つかりません: " + data_dir)
        return
    os.chdir(data_dir)  # 本体の json/ と analysis_cache/ は相対パス
    stubbed = install_stubs_if_missing()
    sys.modules["gemini_client"] = None  # AI共通クライアントは読み込ませない(本体側のtry/exceptが吸収する)
    install_readonly_guard()

    try:
        mod, rev = load_latest_revision()
    except (Exception, SystemExit) as e:
        out.append(f"⚠️ 本体の読み込みに失敗: {type(e).__name__}: {clip(one_line(e), 120)}")
        return
    if mod is None:
        out += ["⚠️ 本体 outlook_total_organizer_<日付>*.py が見つかりません（探した場所: " + APP_DIR + "）",
                "   このスクリプトは tools フォルダ(app フォルダと同じ階層)に置いて実行してください。"]
        return
    out[0] += "  本体=" + rev
    missing = [n for n in REQUIRED if not hasattr(mod, n)]
    if missing:
        out += ["⚠️ 判断待ちの関数が本体に見つかりません（A1未実装の版、または古い版を読んでいる可能性）", "   不足: " + ", ".join(missing)]
        return

    extra = list(mod.build_self_aliases(args.name, args.smtp)) if (args.name or args.smtp) else []
    aliases = tuple(dict.fromkeys(a for a in extra + [mod.normalize_action_target_token(a) for a in args.alias] if a))
    out.append(f"📂 データ場所: {os.path.basename(data_dir) or data_dir}{'（--dir指定）' if args.dir else ''}"
               f" ／ 自分宛て判定の別名: 既定{len(mod.ACTION_SELF_TARGET_ALIASES)}語 + 追加{len(aliases)}語")
    if stubbed:
        out.append("ℹ️ 未導入のためスタブ化(実物のある環境では出ません): " + ", ".join(stubbed))

    if not os.path.isfile(mod.ACTION_DASHBOARD_CACHE_FILE):
        out += [f"📭 キャッシュなし: {mod.ACTION_DASHBOARD_CACHE_FILE} が見つかりません（探した場所: {data_dir}）",
                "   アクション集計(📋タブ)を一度も実行していないか、実行フォルダ/--dir が違います。判断待ちは数えられません。"]
        return
    cache = mod.load_action_dashboard_cache()
    if cache is None:
        out += [f"⚠️ キャッシュを読めません: {mod.ACTION_DASHBOARD_CACHE_FILE}"
                f"（{os.path.getsize(mod.ACTION_DASHBOARD_CACHE_FILE):,}バイト。JSON不正・0バイト・形式不正のいずれか）",
                "   本体のGUIは「(判断待ち?・読込失敗)」と表示します（0件とは区別）。解析の書込み中、またはファイルの破損が疑われます。"]
        return

    last_run = mod.load_action_last_run()
    statuses, status_ok = {}, True  # 進捗は本体の厳密な読込(壊れていれば例外)で読む。読めなければ「読込失敗」扱い
    reader = getattr(mod, "_load_action_status_strict", None) or getattr(mod, "load_action_status", None)
    if reader and os.path.isdir("json"):
        try:
            statuses = reader()
        except (OSError, ValueError):
            status_ok = False
    statuses = statuses if isinstance(statuses, dict) else {}

    r = scan_cache(mod, cache, aliases)
    cache_lines = section_cache(r, len(cache["threads"]), last_run, mod.ACTION_LAST_RUN_FILE, statuses, status_ok)
    if not r["valid"]:
        out += cache_lines + ["📭 有効スレッドが0件（キャッシュが空、またはmeta無し/解析失敗のみ）: 判断待ちは0件（数える対象がありません）"]
        return

    periods = []  # 本体の compute_pending_decisions / count_recent_error_threads の結果(受信日が範囲内のスレッドのみ)
    for label, days in PERIODS:
        since = None if days is None else now.timestamp() - days * 86400
        periods.append((label, mod.compute_pending_decisions(cache, statuses, aliases, since),
                        mod.count_recent_error_threads(cache, since)))
    snap, snap_note = get_snapshot(mod, now, aliases)

    after = (section_types(mod, r) + section_funnel(mod, r, periods[-1][1], snap) + section_periods(periods, snap, snap_note)
             + ["💡 所見（機械的な閾値判定）"] + ["   " + x for x in build_findings(mod, r, periods, snap, status_ok)])
    # 宛先の表は、60行の枠に収まるように残りの行数で上位件数を決める(通常は30件=15行)
    max_cells = max(4, min(TOP_TARGETS, (MAX_LINES - len(out) - len(cache_lines) - len(after) - 2) * 2))
    out += cache_lines + section_targets(r, max_cells) + after

    if args.samples > 0:
        use_snap = bool(snap) and isinstance(snap.get("rows"), list)
        samples += section_samples(snap["rows"] if use_snap else periods[-1][1], args.samples,
                                   "タブ見出しと同じ集計範囲・本体の並び順" if use_snap else "全期間・本体の並び順")


def main(argv=None) -> int:
    setup_console()
    args = parse_args(argv)
    out, samples = [], []
    try:
        run(args, out, samples)
    except Exception as e:
        tb = traceback.extract_tb(sys.exc_info()[2])
        where = f"（{os.path.basename(tb[-1].filename)}:{tb[-1].lineno}）" if tb else ""
        out.append(f"⚠️ 診断中に予期しないエラー: {type(e).__name__}: {clip(one_line(e), 160)}{where}")
    if len(out) > MAX_LINES:
        out = out[:MAX_LINES - 1] + [f"…（{MAX_LINES}行を超えた分は省略）"]
    print("\n".join(out + samples))
    return 0


if __name__ == "__main__":
    sys.exit(main())
