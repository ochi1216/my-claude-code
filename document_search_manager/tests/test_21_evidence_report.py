# -*- coding: utf-8 -*-
"""Enovia認証 証拠レポート（tools/enovia_evidence_report.py）

このスクリプトは調査用で、扱うのは**本物のセッションCookie**である。
したがって最も重要な検証は「秘密情報を出力しないこと」。
見本データを作って実際に動かし、値が1文字も出ないことを確かめる。

ネットワークには一切アクセスしない。
実行: python tests/test_21_evidence_report.py
"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import Checker  # noqa: E402

check = Checker()

TOOL_DIR = Path(__file__).resolve().parent.parent
SCRIPT = TOOL_DIR / "tools" / "enovia_evidence_report.py"

spec = importlib.util.spec_from_file_location("enovia_evidence_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

JST = timezone(timedelta(hours=9))
BASE = datetime(2026, 9, 4, 13, 37, tzinfo=JST)
CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
SECRET = "THIS-VALUE-MUST-NEVER-BE-PRINTED"


def chrome_time(dt):
    return int((dt - CHROME_EPOCH).total_seconds() * 1_000_000)


def build_sample(root: Path, with_profile=True):
    """Playwrightが保存する形と、Edgeのデータベースを模した見本を作る。"""
    cookies = [
        {"name": "JSESSIONID", "value": SECRET,
         "domain": "dspace.plm.nexperia.com", "path": "/", "expires": -1},
        {"name": "CASTGC", "value": SECRET + "-2", "domain": ".plm.nexperia.com",
         "path": "/", "expires": (BASE + timedelta(hours=8)).timestamp()},
        {"name": "tok", "value": SECRET + "-3",
         "domain": "federated.plm.nexperia.com", "path": "/",
         "expires": (BASE + timedelta(days=3650)).timestamp()},
    ]
    session_path = root / "enovia_session.json"
    session_path.write_text(json.dumps(
        {"cookies": cookies, "saved_at": "2026-09-04 13:37:05"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    os.utime(session_path, (BASE.timestamp(), BASE.timestamp()))

    if not with_profile:
        return
    default = root / "enovia_profile" / "Default"
    (default / "Network").mkdir(parents=True, exist_ok=True)

    history = sqlite3.connect(default / "History")
    history.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, "
                    "title TEXT, visit_count INT, last_visit_time INTEGER)")
    history.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, "
                    "visit_time INTEGER)")
    rows = [(1, "https://dpassport.plm.nexperia.com/3dpassport/cas/login"),
            (2, "https://dspace.plm.nexperia.com/3dspace/"),
            (3, "https://www.example.com/mypage-private")]
    for url_id, url in rows:
        history.execute("INSERT INTO urls VALUES (?,?,?,1,?)",
                        (url_id, url, "t", chrome_time(BASE)))
    for visit_id, (url_id, offset) in enumerate([(1, 0), (2, 40), (3, 300)], 1):
        history.execute("INSERT INTO visits VALUES (?,?,?)",
                        (visit_id, url_id,
                         chrome_time(BASE + timedelta(seconds=offset))))
    history.commit()
    history.close()

    cookie_db = sqlite3.connect(default / "Network" / "Cookies")
    cookie_db.execute("CREATE TABLE cookies (creation_utc INTEGER, host_key TEXT, "
                      "name TEXT, encrypted_value BLOB, expires_utc INTEGER, "
                      "last_access_utc INTEGER)")
    cookie_db.execute("INSERT INTO cookies VALUES (?,?,?,?,?,?)",
                      (chrome_time(BASE), ".plm.nexperia.com", "CASTGC",
                       SECRET.encode(), chrome_time(BASE + timedelta(hours=8)),
                       chrome_time(BASE)))
    cookie_db.execute("INSERT INTO cookies VALUES (?,?,?,?,?,?)",
                      (chrome_time(BASE), "www.example.com", "private_cookie",
                       SECRET.encode(), 0, chrome_time(BASE)))
    cookie_db.commit()
    cookie_db.close()


def run(path) -> str:
    """スクリプトを実行し、標準出力を文字列で返す。"""
    import io
    import contextlib
    argv = sys.argv
    sys.argv = ["enovia_evidence_report.py", str(path)]
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            report.main()
    finally:
        sys.argv = argv
    return buffer.getvalue()


# ── H1 時刻の変換 ────────────────────────────────────────────
print("\n[H1] 時刻の変換")
check("Unix時刻をJSTに直せる",
      report.jst(report.from_unix(BASE.timestamp())) == "2026-09-04 13:37:00",
      report.jst(report.from_unix(BASE.timestamp())))
check("Chromiumの時刻（1601年起点のマイクロ秒）をJSTに直せる",
      report.jst(report.from_chrome(chrome_time(BASE))) == "2026-09-04 13:37:00",
      report.jst(report.from_chrome(chrome_time(BASE))))
check("セッションCookieの -1 は「期限なし」として扱う",
      report.from_unix(-1) is None)
check("0 も「期限なし」として扱う（Chromium側の表現）",
      report.from_chrome(0) is None)
check("壊れた値でも落ちない",
      report.from_unix("abc") is None and report.from_chrome(None) is None)
check("桁あふれした値でも落ちない",
      report.from_unix(10 ** 20) is None and report.from_chrome(10 ** 25) is None)


# ── H2 出力の中身 ────────────────────────────────────────────
print("\n[H2] レポートの中身")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "evidence"
    root.mkdir()
    build_sample(root)
    text = run(root)

    check("★秘密★ Cookieの値が1文字も出力されない", SECRET not in text,
          "値が漏れています")
    check("最後にログインした時刻を示す", "2026-09-04 13:37:00" in text, text[:200])
    check("記録された保存時刻も出す", "2026-09-04 13:37:05" in text)
    check("Cookieの件数を出す", "3 件" in text)
    check("期限切れのCookieに印を付ける", "⛔ 期限切れ" in text)
    check("セッションCookieはそうと分かるように書く",
          "セッションCookie" in text)
    check("まだ有効なCookieは残り日数を出す", "残り" in text)
    check("期限切れであれば、ログインし直しで直る旨を伝える",
          "ログインし直せば直る" in text)
    check("手動ログイン不可とは別事象であることを明記する",
          "別の事象" in text, text[-400:])

    check("認証に関係する履歴は出す",
          "dpassport.plm.nexperia.com" in text)
    check("★秘密★ 認証と無関係な閲覧履歴は出さない",
          "mypage-private" not in text)
    check("★秘密★ 認証と無関係なCookieのホストは出さない",
          "private_cookie" not in text)
    check("ITへ伝えるべき時間帯を示す", "時間帯になります" in text)
    check("秘密情報を含まない旨を明記する（そのまま共有できる）",
          "秘密情報" in text)

# ── H3 異常系 ────────────────────────────────────────────────
print("\n[H3] 異常系（無いもの・壊れたものに強いか）")
with tempfile.TemporaryDirectory() as tmp:
    empty = Path(tmp) / "empty"
    empty.mkdir()
    text = run(empty)
    check("ファイルが無くても落ちない", "ファイルがありません" in text, text[-300:])
    check("プロファイルが無くても落ちない", "enovia_profile がありません" in text)

with tempfile.TemporaryDirectory() as tmp:
    broken = Path(tmp) / "broken"
    broken.mkdir()
    (broken / "enovia_session.json").write_text("{ これはJSONではない",
                                                encoding="utf-8")
    text = run(broken)
    check("JSONが壊れていても落ちない", "読み込めませんでした" in text, text[-300:])

with tempfile.TemporaryDirectory() as tmp:
    odd = Path(tmp) / "odd"
    odd.mkdir()
    (odd / "enovia_session.json").write_text('{"cookies": "配列ではない"}',
                                             encoding="utf-8")
    text = run(odd)
    check("cookiesが配列でなくても落ちない", "配列ではありません" in text)

with tempfile.TemporaryDirectory() as tmp:
    nodb = Path(tmp) / "nodb"
    (nodb / "enovia_profile" / "Default").mkdir(parents=True)
    build_sample(nodb, with_profile=False)
    text = run(nodb)
    check("プロファイルはあるがデータベースが無くても落ちない",
          "履歴データベースが見つかりません" in text
          and "Cookieデータベースが見つかりません" in text, text[-500:])


# ── H4 読み取り専用であること ────────────────────────────────
print("\n[H4] 読み取り専用であること（証拠を壊さない）")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "readonly"
    root.mkdir()
    build_sample(root)
    before = {p: (p.stat().st_mtime, p.stat().st_size)
              for p in root.rglob("*") if p.is_file()}
    run(root)
    after = {p: (p.stat().st_mtime, p.stat().st_size)
             for p in root.rglob("*") if p.is_file()}
    check("実行しても、対象のファイルが1つも変わらない", before == after,
          [p.name for p in before if before.get(p) != after.get(p)])
    check("ファイルが増えも減りもしない", set(before) == set(after))

source = SCRIPT.read_text(encoding="utf-8")
check("書き込み用にファイルを開いている箇所が無い（-o の保存を除く）",
      source.count('"w"') == 0 and source.count("'w'") == 0, "書き込みがあります")
check("ネットワークを使うライブラリを読み込んでいない",
      "requests" not in source and "urllib" not in source)

check.finish()
