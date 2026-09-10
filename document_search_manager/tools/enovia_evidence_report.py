#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Enovia認証の証拠レポート（読み取り専用）
=========================================
Enoviaにログインできなくなった／勝手に復旧した、といった事象を後から
調べるための調査用スクリプト。**何も書き換えず、何も送信しない。**

読み取るもの:
  1. enovia_session.json     … 保存済みCookieの「名前・ドメイン・有効期限」
  2. enovia_profile/         … Edgeプロファイルの履歴とCookieデータベースの時刻

出力に **Cookieの値（value）は一切含めない**。そのままITや第三者に
共有できるレポートになるよう設計している。

使い方:
    python tools/enovia_evidence_report.py                    # ツールのフォルダを見る
    python tools/enovia_evidence_report.py <保全フォルダ>      # 退避したコピーを見る
    python tools/enovia_evidence_report.py <フォルダ> -o report.txt

バージョン: 20260910_01
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9), "JST")

# Chromium系のデータベースは 1601-01-01 からのマイクロ秒で時刻を持つ。
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

# 履歴のうち、認証に関係するホストだけを拾う（無関係な閲覧履歴は出さない）。
AUTH_HOST_HINTS = ("3dpassport", "plm.nexperia.com", "dspace", "federated",
                   "login.microsoftonline.com", "sts.", "adfs")


def jst(dt: datetime) -> str:
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")


def from_unix(seconds) -> "datetime | None":
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def from_chrome(microseconds) -> "datetime | None":
    try:
        value = int(microseconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return _CHROME_EPOCH + timedelta(microseconds=value)
    except OverflowError:
        return None


def open_readonly(db_path: Path):
    """使用中でも読めるよう、一時フォルダへコピーしてから開く。

    Edgeが起動していると元のファイルはロックされることがあるため。
    コピー元は一切変更しない。
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="enovia_evidence_"))
    copied = temp_dir / db_path.name
    shutil.copy2(db_path, copied)
    # 付随ファイル（-wal / -shm）があれば、書きかけの内容も読めるよう一緒に運ぶ
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            shutil.copy2(side, temp_dir / side.name)
    return sqlite3.connect(f"file:{copied}?mode=ro", uri=True), temp_dir


def columns_of(conn, table) -> "set[str]":
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(r[1]) for r in rows}


# ── 1. 保存済みCookie ────────────────────────────────────────
def report_session_json(path: Path, out) -> None:
    out(f"\n{'=' * 72}")
    out("1. 保存済みCookie（enovia_session.json）")
    out("=" * 72)

    if not path.exists():
        out(f"  ファイルがありません: {path}")
        return

    stat = path.stat()
    out(f"  ファイル       : {path}")
    out(f"  最終更新       : {jst(datetime.fromtimestamp(stat.st_mtime, timezone.utc))}"
        "  ← この時刻が最後にログインした時刻")
    out(f"  サイズ         : {stat.st_size:,} バイト")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        out(f"  ❌ 読み込めませんでした: {e}")
        return

    out(f"  記録された保存時刻: {data.get('saved_at') or '(記録なし)'}")

    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        out("  ❌ cookies が配列ではありません。")
        return

    out(f"  Cookie件数     : {len(cookies)} 件")
    out("")
    out("  " + "-" * 68)
    out(f"  {'名前':<28} {'ドメイン':<26} 有効期限（JST）")
    out("  " + "-" * 68)

    now = datetime.now(timezone.utc)
    session_only = 0
    expired = 0
    earliest = None

    for cookie in cookies:
        name = str(cookie.get("name") or "")[:28]
        domain = str(cookie.get("domain") or "")[:26]
        expires = from_unix(cookie.get("expires"))
        if expires is None:
            label = "セッションCookie（ブラウザを閉じると消える）"
            session_only += 1
        else:
            label = jst(expires)
            if expires < now:
                label += "  ⛔ 期限切れ"
                expired += 1
            else:
                remaining = expires - now
                label += f"  （残り {remaining.days} 日）"
            if earliest is None or expires < earliest:
                earliest = expires
        out(f"  {name:<28} {domain:<26} {label}")

    out("  " + "-" * 68)
    out("")
    out("  【まとめ】")
    out(f"    期限切れのCookie      : {expired} 件")
    out(f"    セッションCookie      : {session_only} 件"
        "（保存した時点で既に無効になっている可能性が高い）")
    if earliest:
        state = "既に切れています" if earliest < now else "まだ有効です"
        out(f"    最も早く切れるもの    : {jst(earliest)}（{state}）")
    if expired or session_only:
        out("")
        out("    → ツールがEnoviaで invalid_grant になるのは、この期限切れだけで")
        out("       説明が付きます。「ログインし直せば直る」種類の状態です。")
        out("       手動ブラウザでのログイン不可（SAMLエラー）とは別の事象です。")


# ── 2. ブラウザ履歴（いつログイン画面を開いたか） ─────────────
def report_history(profile_dir: Path, out) -> None:
    out(f"\n{'=' * 72}")
    out("2. ブラウザ履歴（認証関連のみ・enovia_profile）")
    out("=" * 72)

    candidates = [profile_dir / "Default" / "History", profile_dir / "History"]
    db_path = next((p for p in candidates if p.exists()), None)
    if db_path is None:
        out(f"  履歴データベースが見つかりません（探した場所: "
            f"{', '.join(str(p) for p in candidates)}）")
        return

    conn = temp_dir = None
    try:
        conn, temp_dir = open_readonly(db_path)
        rows = conn.execute(
            "SELECT urls.url, urls.title, visits.visit_time "
            "FROM visits JOIN urls ON urls.id = visits.url "
            "ORDER BY visits.visit_time").fetchall()
    except Exception as e:
        out(f"  ❌ 読み込めませんでした: {e}")
        return
    finally:
        if conn is not None:
            conn.close()
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    picked = [(u, t, v) for (u, t, v) in rows
              if any(hint in str(u).lower() for hint in AUTH_HOST_HINTS)]
    out(f"  履歴の総件数           : {len(rows):,} 件")
    out(f"  うち認証関連           : {len(picked):,} 件")
    if not picked:
        out("  認証関連の履歴がありません。")
        return

    out("")
    out("  ※ URLは先頭100文字までを表示します（問い合わせ文字列に情報が入るため）")
    out("  " + "-" * 68)
    for url, title, visit_time in picked:
        when = from_chrome(visit_time)
        out(f"  {jst(when) if when else '(時刻不明)'}  {str(url)[:100]}")
    out("  " + "-" * 68)
    out("")
    first, last = from_chrome(picked[0][2]), from_chrome(picked[-1][2])
    if first and last:
        out(f"  【まとめ】認証関連の最初の記録: {jst(first)}")
        out(f"            認証関連の最後の記録: {jst(last)}")
        out("    → この2つの時刻が、ITへ調査を依頼するときの時間帯になります。")


# ── 3. プロファイル内のCookieデータベース（時刻のみ） ────────
def report_cookie_db(profile_dir: Path, out) -> None:
    out(f"\n{'=' * 72}")
    out("3. Edgeプロファイル内のCookie（時刻のみ・値は読みません）")
    out("=" * 72)

    candidates = [profile_dir / "Default" / "Network" / "Cookies",
                  profile_dir / "Default" / "Cookies",
                  profile_dir / "Network" / "Cookies"]
    db_path = next((p for p in candidates if p.exists()), None)
    if db_path is None:
        out("  Cookieデータベースが見つかりません。")
        return

    conn = temp_dir = None
    try:
        conn, temp_dir = open_readonly(db_path)
        cols = columns_of(conn, "cookies")
        needed = {"host_key", "name", "creation_utc", "expires_utc"}
        missing = needed - cols
        if missing:
            out(f"  この版のデータベースには必要な列がありません: {sorted(missing)}")
            return
        has_last_access = "last_access_utc" in cols
        select = ("SELECT host_key, name, creation_utc, expires_utc"
                  + (", last_access_utc" if has_last_access else "")
                  + " FROM cookies ORDER BY creation_utc")
        rows = conn.execute(select).fetchall()
    except Exception as e:
        out(f"  ❌ 読み込めませんでした: {e}")
        return
    finally:
        if conn is not None:
            conn.close()
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    picked = [r for r in rows
              if any(hint in str(r[0]).lower() for hint in AUTH_HOST_HINTS)]
    out(f"  Cookieの総件数         : {len(rows):,} 件")
    out(f"  うち認証関連のホスト   : {len(picked):,} 件")
    if not picked:
        return

    out("")
    out("  " + "-" * 68)
    out(f"  {'ホスト':<30} {'名前':<22} 作成（JST）")
    out("  " + "-" * 68)
    for row in picked:
        created = from_chrome(row[2])
        expires = from_chrome(row[3])
        line = (f"  {str(row[0])[:30]:<30} {str(row[1])[:22]:<22} "
                f"{jst(created) if created else '(不明)'}")
        out(line)
        out(f"  {'':<30} {'':<22} 期限 "
            f"{jst(expires) if expires else 'セッション限り'}")
    out("  " + "-" * 68)


def main() -> int:
    args = [a for a in sys.argv[1:]]
    out_path = None
    if "-o" in args:
        index = args.index("-o")
        out_path = Path(args[index + 1])
        del args[index:index + 2]

    base = Path(args[0]).expanduser() if args else Path(__file__).resolve().parent.parent
    lines = []

    def out(text=""):
        print(text)
        lines.append(text)

    out("=" * 72)
    out("Enovia認証 証拠レポート（読み取り専用・Cookieの値は含みません）")
    out("=" * 72)
    out(f"  作成日時 : {jst(datetime.now(timezone.utc))}")
    out(f"  対象     : {base}")
    if not base.exists():
        out(f"\n  ❌ フォルダがありません: {base}")
        return 1

    report_session_json(base / "enovia_session.json", out)
    profile = base / "enovia_profile"
    if profile.exists():
        report_history(profile, out)
        report_cookie_db(profile, out)
    else:
        out(f"\n  enovia_profile がありません: {profile}")

    out("")
    out("=" * 72)
    out("  このレポートに秘密情報（Cookieの値・パスワード）は含まれていません。")
    out("  そのままITへの問い合わせに添付できます。")
    out("=" * 72)

    if out_path:
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n💾 レポートを保存しました: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
