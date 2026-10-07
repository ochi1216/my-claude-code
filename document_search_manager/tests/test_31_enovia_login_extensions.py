# -*- coding: utf-8 -*-
"""Enoviaログイン用Edgeで拡張機能を使えるようにする — v20260929_01 で追加

document_search_manager: Enoviaの旧画面がXSLT廃止の警告を出し、拡張機能
「XSLT Polyfill」を求めるようになった（2026-09-29 越智さんの報告）。
Playwrightは既定で --disable-extensions を付けて起動するため、ツールが開く
ログイン用Edgeでは拡張を入れても動かない。起動時にこの既定の引数だけを外す
ことを検証する。自動操作の目印（--enable-automation など）は外さないこと、
ログインの流れ（Cookie保存・メッセージ）が従来どおりであることも確認する。

実ブラウザは起動せず、playwright.sync_api をスタブに差し替えて検証する。
Cookie・プロファイルの保存先は一時フォルダに差し替え、実ファイルには触れない。
実行: python tests/test_31_enovia_login_extensions.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import json
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm  # noqa: E402

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


CFG = dict(dsm.DEFAULT_CFG)
CFG["enovia_base_url"] = "https://dspace.plm.nexperia.com/3dspace/"
CFG["enovia_login_timeout_sec"] = 1

_ORIG_COOKIE_PATH = dsm.ENOVIA_COOKIE_PATH
_ORIG_PROFILE_DIR = dsm.ENOVIA_PROFILE_DIR
_ORIG_SLEEP = dsm.time.sleep
_ORIG_PW_MODULES = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}

# テスト用の値（実在のCookieではない）。
FAKE_COOKIES = [
    {"name": "JSESSIONID", "value": "dummy", "domain": "dspace.plm.nexperia.com"},
    {"name": "JSESSIONID", "value": "dummy", "domain": "federated.plm.nexperia.com"},
]


class FakePage:
    # 1回目の確認では開いている（Cookieを読む）→ 2回目で閉じた扱いにする。
    def __init__(self):
        self.polls = 0

    def goto(self, url, timeout=None):
        return None

    def is_closed(self):
        self.polls += 1
        return self.polls > 1


class FakeContext:
    def __init__(self):
        self.closed = False

    def new_page(self):
        return FakePage()

    def cookies(self):
        return list(FAKE_COOKIES)

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
        self.context = FakeContext()

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.calls.append((user_data_dir, kwargs))
        if self.fail:
            raise self.fail
        return self.context


class FakePW:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def install_fake_playwright(chromium):
    mod_root = types.ModuleType("playwright")
    mod_sync = types.ModuleType("playwright.sync_api")
    mod_sync.sync_playwright = lambda: FakePW(chromium)
    mod_root.sync_api = mod_sync
    sys.modules["playwright"] = mod_root
    sys.modules["playwright.sync_api"] = mod_sync


def restore():
    dsm.time.sleep = _ORIG_SLEEP
    dsm.ENOVIA_COOKIE_PATH = _ORIG_COOKIE_PATH
    dsm.ENOVIA_PROFILE_DIR = _ORIG_PROFILE_DIR
    for k, v in _ORIG_PW_MODULES.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


tmp = tempfile.TemporaryDirectory()
try:
    tmp_dir = Path(tmp.name)
    dsm.ENOVIA_COOKIE_PATH = tmp_dir / "enovia_session.json"
    dsm.ENOVIA_PROFILE_DIR = tmp_dir / "enovia_profile"
    dsm.time.sleep = lambda sec: None  # Cookie待ちの1秒待機を省く

    print("■ 定数：外す起動引数")
    check("ENOVIA_LOGIN_IGNORE_DEFAULT_ARGS が定義されている",
          hasattr(dsm, "ENOVIA_LOGIN_IGNORE_DEFAULT_ARGS"))
    ignore = tuple(getattr(dsm, "ENOVIA_LOGIN_IGNORE_DEFAULT_ARGS", ()))
    check("--disable-extensions を外す", "--disable-extensions" in ignore, ignore)
    check("外すのは --disable-extensions だけ（最小変更）",
          ignore == ("--disable-extensions",), ignore)
    check("自動操作の目印 --enable-automation は外さない",
          "--enable-automation" not in ignore, ignore)
    check("ignore_default_args=True（既定引数を全部外す）にしていない",
          ignore is not True)

    print("■ ログイン用Edgeの起動引数")
    chromium = FakeChromium()
    install_fake_playwright(chromium)
    ep = dsm.EnoviaProvider(dict(CFG), None)
    result = ep.login_interactive()
    check("起動は1回", len(chromium.calls) == 1, chromium.calls)
    user_data_dir, kwargs = chromium.calls[0] if chromium.calls else ("", {})
    check("専用プロファイル（enovia_profile）で起動する",
          user_data_dir == str(dsm.ENOVIA_PROFILE_DIR), user_data_dir)
    check("ignore_default_args が渡されている", "ignore_default_args" in kwargs, kwargs)
    passed = kwargs.get("ignore_default_args")
    check("ignore_default_args はリスト（Playwrightの受け取る型）",
          isinstance(passed, list), type(passed))
    check("ignore_default_args = ['--disable-extensions']",
          passed == ["--disable-extensions"], passed)
    check("channel は既定の msedge のまま", kwargs.get("channel") == "msedge", kwargs)
    check("headless=False のまま（手動ログインのため）",
          kwargs.get("headless") is False, kwargs)
    check("args で自動操作の目印を消すような指定をしていない",
          not any("AutomationControlled" in str(a) for a in (kwargs.get("args") or [])),
          kwargs.get("args"))
    check("enovia_profile フォルダが作られる", dsm.ENOVIA_PROFILE_DIR.is_dir())

    print("■ ログインの流れは従来どおり")
    check("ログインは成功扱い", result.get("ok") is True, result)
    check("メッセージに件数が出る（うち検索に使えるもの）",
          "うち検索に使えるもの" in str(result.get("message")), result)
    check("ブラウザは閉じられる", chromium.context.closed is True)
    saved = {}
    try:
        with open(dsm.ENOVIA_COOKIE_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception as e:  # noqa: BLE001
        saved = {"error": str(e)}
    check("Cookieが保存先に保存される",
          len(saved.get("cookies") or []) == len(FAKE_COOKIES), saved.keys())

    print("■ channel を config で変えた場合も同じ引数で起動する")
    chromium2 = FakeChromium()
    install_fake_playwright(chromium2)
    cfg2 = dict(CFG)
    cfg2["enovia_browser_channel"] = "chrome"
    dsm.EnoviaProvider(cfg2, None).login_interactive()
    kw2 = chromium2.calls[0][1] if chromium2.calls else {}
    check("channel=chrome が渡る", kw2.get("channel") == "chrome", kw2)
    check("chrome でも ignore_default_args が同じ",
          kw2.get("ignore_default_args") == ["--disable-extensions"], kw2)

    print("■ 起動に失敗した場合の案内は従来どおり")
    chromium3 = FakeChromium(fail=RuntimeError("Executable doesn't exist"))
    install_fake_playwright(chromium3)
    r3 = dsm.EnoviaProvider(dict(CFG), None).login_interactive()
    check("失敗は ok=False", r3.get("ok") is False, r3)
    check("案内文は _enovia_launch_error_message と同じ",
          r3.get("message") == dsm._enovia_launch_error_message(
              RuntimeError("Executable doesn't exist")), r3)

    print("■ ソース上の確認")
    src = Path(dsm.__file__).read_text(encoding="utf-8")
    check("launch_persistent_context の呼び出しは1か所",
          src.count("launch_persistent_context(") == 1)
    check("--enable-automation を外す記述がない",
          'ignore_default_args=["--enable-automation"' not in src
          and "'--enable-automation'" not in src)

finally:
    restore()
    tmp.cleanup()


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
