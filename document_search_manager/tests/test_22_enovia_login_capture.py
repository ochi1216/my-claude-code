# -*- coding: utf-8 -*-
"""Enoviaログイン：セッションCookieの取り逃がし（v20260911_01で修正）

【背景・2026-09-11に実機で確認した事実】
3DSpace / federated のセッションは、いずれも**セッションCookie**
（JSESSIONID / SERVERID など、有効期限を持たないもの）で維持されている。
DevToolsで確認したところ、次の7件がすべて Expires=Session だった。
  dspace    : eno-bps-client-time-offset / eno-bps-server-expiry /
              eno-bps-server-time / JSESSIONID / SERVERID
  federated : JSESSIONID / SERVERID
セッションCookieはブラウザのメモリ上にしか無く、**ウィンドウを閉じた時点で
破棄される**。従来の実装は「閉じるのを待つ→取り出す」の順だったため、
取り出したときには既に消えており、ディスク保存済みの無関係なCookie
（Bing/M365等）だけが保存されていた。結果、検索は必ず invalid_grant。

また federated は dspace とは別のセッションで、**Enovia画面で1回検索して
初めて発行される**（検索前は dspace 側だけ）。

このテストは、ブラウザを模した見本で次を確かめる。
  ① 閉じる前に取り続け、セッションCookieを取り逃がさないこと
  ② 検索後（federatedが増えた時点）の内容を採用すること
  ③ 閉じた後に取得できなくなっても、直前の内容を活かすこと
  ④ 取得できていない場合に、黙って成功扱いにせず対処を伝えること

ネットワークにもブラウザにもアクセスしない。
実行: python tests/test_22_enovia_login_capture.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, Checker  # noqa: E402

check = Checker()

CFG = dict(dsm.DEFAULT_CFG)


def cookie(name, domain, expires=-1):
    return {"name": name, "value": "SECRET", "domain": domain,
            "path": "/", "expires": expires}


# ブラウザの状態を時間の流れで再現する
NOISE = [cookie("MUID", ".bing.com", 1.9e9),
         cookie("EdgeAuth", "m365.cloud.microsoft", 1.8e9)]
AFTER_LOGIN = NOISE + [cookie("JSESSIONID", "dspace.plm.nexperia.com"),
                       cookie("SERVERID", "dspace.plm.nexperia.com"),
                       cookie("eno-bps-server-time", "dspace.plm.nexperia.com")]
AFTER_SEARCH = AFTER_LOGIN + [cookie("JSESSIONID", "federated.plm.nexperia.com"),
                              cookie("SERVERID", "federated.plm.nexperia.com")]


class FakePage:
    """指定した回数だけ開いていて、その後閉じるページ。"""

    def __init__(self, open_rounds):
        self.open_rounds = open_rounds
        self.checks = 0

    def is_closed(self):
        self.checks += 1
        return self.checks > self.open_rounds


class FakeContext:
    """時間の経過に合わせて、返すCookieを変えるコンテキスト。"""

    def __init__(self, timeline, raise_after=None):
        self.timeline = timeline
        self.calls = 0
        self.raise_after = raise_after

    def cookies(self):
        self.calls += 1
        if self.raise_after is not None and self.calls > self.raise_after:
            raise RuntimeError("ブラウザは既に終了しています")
        index = min(self.calls - 1, len(self.timeline) - 1)
        return list(self.timeline[index])


def collect(timeline, open_rounds, raise_after=None, timeout=30.0):
    provider = dsm.EnoviaProvider(CFG, auth=None)
    context = FakeContext(timeline, raise_after=raise_after)
    page = FakePage(open_rounds)
    orig_sleep = dsm.time.sleep
    dsm.time.sleep = lambda _sec: None      # 待たずに回す
    try:
        return provider._collect_cookies_while_open(context, page, timeout)
    finally:
        dsm.time.sleep = orig_sleep


# ── H1 ホストの判定 ──────────────────────────────────────────
print("\n[H1] どのホスト宛のCookieかを判定する")
check("dspace宛を検索用と数える",
      dsm._enovia_session_cookie_count([cookie("JSESSIONID", "dspace.plm.nexperia.com")]) == 1)
check("federated宛も検索用と数える",
      dsm._enovia_session_cookie_count([cookie("JSESSIONID", "federated.plm.nexperia.com")]) == 1)
check("親ドメイン（.plm.nexperia.com）は両方に届くので数える",
      dsm._enovia_session_cookie_count([cookie("x", ".plm.nexperia.com")]) == 1)
check("dpassport宛は認証の途中経過なので数えない",
      dsm._enovia_session_cookie_count([cookie("afs", "dpassport.plm.nexperia.com")]) == 0)
check("bing等の無関係なものは数えない",
      dsm._enovia_session_cookie_count(NOISE) == 0)
check("空でも落ちない", dsm._enovia_session_cookie_count([]) == 0
      and dsm._enovia_session_cookie_count(None) == 0)
check("部分一致で誤判定しない",
      dsm._enovia_cookie_domain_covers("plm.nexperia.com", "evilplm.nexperia.com") is False)


# ── H2 取り逃がさないこと（今回の修正の本体） ────────────────
print("\n[H2] ウィンドウを閉じる前に取り続ける")

# ログイン → 検索 → 閉じる直前にセッションCookieが消える、という流れ
timeline = [NOISE, AFTER_LOGIN, AFTER_SEARCH, NOISE]
cookies, closed = collect(timeline, open_rounds=4)
names = sorted((c["name"], c["domain"]) for c in cookies)
check("★閉じる直前に消えても、取り逃がさない",
      dsm._enovia_session_cookie_count(cookies) == 5,
      dsm._enovia_session_cookie_count(cookies))
check("dspaceのセッションCookieを保持している",
      ("JSESSIONID", "dspace.plm.nexperia.com") in names, names)
check("federatedのセッションCookieも保持している",
      ("JSESSIONID", "federated.plm.nexperia.com") in names, names)
check("利用者が閉じたことを検出する", closed is True)

# 従来の実装（閉じた後に1回だけ取る）だと何が起きていたかの再現
check("（参考）最後の1回だけ取ると、無関係なCookieしか残らない",
      dsm._enovia_session_cookie_count(timeline[-1]) == 0)

# 検索しなかった場合：dspaceだけ取れて federated が無い
cookies, _closed = collect([NOISE, AFTER_LOGIN, AFTER_LOGIN], open_rounds=3)
check("検索しなければ federated 宛は取得できない（実機の挙動どおり）",
      not any(c["domain"] == "federated.plm.nexperia.com" for c in cookies),
      [c["domain"] for c in cookies])
check("その場合でも dspace 宛は取得できている",
      dsm._enovia_session_cookie_count(cookies) == 3)


# ── H3 異常系 ────────────────────────────────────────────────
print("\n[H3] 終了処理に入った後でも壊れないこと")
cookies, closed = collect([NOISE, AFTER_SEARCH, AFTER_SEARCH],
                          open_rounds=10, raise_after=2)
check("取得できなくなっても、直前の内容を活かす",
      dsm._enovia_session_cookie_count(cookies) == 5,
      dsm._enovia_session_cookie_count(cookies))
check("取得できなくなった時点で終了扱いにする", closed is True)

cookies, closed = collect([[]], open_rounds=2)
check("1件も取れなくても落ちない", cookies == [] and closed is True, (cookies, closed))

cookies, closed = collect([AFTER_SEARCH], open_rounds=10 ** 6, timeout=1.0)
check("時間切れでも、それまでの内容を返す",
      dsm._enovia_session_cookie_count(cookies) == 5 and closed is False,
      (len(cookies), closed))


# ── H4 画面への案内 ─────────────────────────────────────────
print("\n[H4] 画面とログの案内（黙って失敗させない）")
html = dsm.INDEX_HTML
for label, needle in [
    ("ログイン手順に「検索を1回」を明記している", "画面上部の検索ボックスで1回検索"),
    ("手順を番号付きで出している", '"　3) そのウィンドウを閉じる'),
    ("ボタンの説明にも理由を書いている", "federated"),
]:
    check(label, needle in html, needle)

source = Path(dsm.__file__).read_text(encoding="utf-8")
check("取得できなかった場合に警告を出す実装がある",
      "検索に使えるCookieが取得できていません" in source)
check("federatedだけ欠けている場合の警告もある",
      "検索API（federated）のCookieが取得できていません" in source)
check("保存時に、使えるCookieの件数を伝える",
      "うち検索に使えるもの" in source)
check("閉じた後に1回だけ取る実装が残っていない（元の不具合）",
      'page.wait_for_event("close", timeout=timeout_ms)' not in source)

check.finish()
