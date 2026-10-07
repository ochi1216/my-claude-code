# -*- coding: utf-8 -*-
"""ポート使用中の自動解消（越智さんのご要望）— v20260924_03 で追加

document_search_manager: 起動時にポートが使用中だった場合、そのプロセスが
「自分自身（Document Search Manager）の旧起動」だと確認できたときだけ
自動終了して起動を続ける機能を検証する。確認できない場合（無関係な
プロセスかもしれない）は自動終了せず、従来どおりの中止に委ねる設計に
なっていることを重点的に確認する（誤って無関係なプロセスを終了させる
事故を防ぐための安全策）。

ネットワーク・実プロセスの起動/終了には一切アクセスせず、
`subprocess.run` / `_is_windows` / `_port_in_use` / `time.sleep` を
スタブ化して検証する。
実行: python tests/test_27_port_auto_kill.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import sys
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

# subprocess.run はモジュール共有のため、テスト終了時に必ず元へ戻す。
_ORIG_SUBPROCESS_RUN = dsm.subprocess.run
_ORIG_IS_WINDOWS = dsm._is_windows
_ORIG_PORT_IN_USE = dsm._port_in_use
_ORIG_SLEEP = dsm.time.sleep


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def restore():
    dsm.subprocess.run = _ORIG_SUBPROCESS_RUN
    dsm._is_windows = _ORIG_IS_WINDOWS
    dsm._port_in_use = _ORIG_PORT_IN_USE
    dsm.time.sleep = _ORIG_SLEEP


# 実機のnetstat -ano出力を模したサンプル（TCP/UDP混在・別ポートも含む）。
NETSTAT_SAMPLE = """
Proto  ローカル アドレス      外部アドレス           状態           PID
TCP    127.0.0.1:135          0.0.0.0:0              LISTENING       1000
TCP    127.0.0.1:5020         0.0.0.0:0              LISTENING       9999
TCP    127.0.0.1:5021         0.0.0.0:0              LISTENING       8888
UDP    127.0.0.1:5020         *:*                                    7777
"""

NETSTAT_TWO_OWNERS = """
Proto  ローカル アドレス      外部アドレス           状態           PID
TCP    127.0.0.1:5020         0.0.0.0:0              LISTENING       9999
TCP    127.0.0.1:5020         0.0.0.0:0              LISTENING       8888
"""

NETSTAT_NO_MATCH = """
Proto  ローカル アドレス      外部アドレス           状態           PID
TCP    127.0.0.1:5021         0.0.0.0:0              LISTENING       8888
"""


try:
    # ── T1: _find_port_owner_pid（netstat出力の解析） ────────────
    print("\n[T1] _find_port_owner_pid（netstatの解析）")

    dsm._is_windows = lambda: False
    check("Windows以外では常にNone（コマンドを一切呼ばない）",
          dsm._find_port_owner_pid(5020) is None)

    dsm._is_windows = lambda: True
    dsm.subprocess.run = lambda *a, **k: FakeResult(0, NETSTAT_SAMPLE)
    check("TCP/LISTENING/該当ポートの行から1件のPIDを特定する",
          dsm._find_port_owner_pid(5020) == 9999)
    check("別ポート(5021)は混ざらない", dsm._find_port_owner_pid(5021) == 8888)

    dsm.subprocess.run = lambda *a, **k: FakeResult(0, NETSTAT_TWO_OWNERS)
    check("同じポートに複数PIDが見つかったらNone（特定できない扱い・安全側）",
          dsm._find_port_owner_pid(5020) is None)

    dsm.subprocess.run = lambda *a, **k: FakeResult(0, NETSTAT_NO_MATCH)
    check("該当ポートの行が無ければNone",
          dsm._find_port_owner_pid(5020) is None)

    def raise_run(*a, **k):
        raise FileNotFoundError("netstat not found")
    dsm.subprocess.run = raise_run
    check("netstat自体が失敗したらNone（例外を投げない）",
          dsm._find_port_owner_pid(5020) is None)

    # ── T1b: ★2026-09-25 実機バグの再発防止★ ──────────────────
    # 越智さんの会社PCで実際に発生したクラッシュの再現。日本語Windowsでは
    # netstatの見出し行がCP932で出力されるため、errors="replace"が無いと
    # デコードに失敗し、result.stdoutがNoneのまま返ってくることがある
    # （subprocess.runの内部スレッドで例外が握りつぶされるため）。
    print("\n[T1b] netstatの出力がデコードできず stdout=None で返ってきた場合"
          "（2026-09-25 実機で発生したクラッシュの再現）")

    dsm.subprocess.run = lambda *a, **k: FakeResult(0, None)
    check("stdout=Noneでも例外を投げずNoneを返す（実機クラッシュの再発防止）",
          dsm._find_port_owner_pid(5020) is None)

    captured_kwargs = {}

    def capture_netstat_kwargs(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeResult(0, NETSTAT_SAMPLE)
    dsm.subprocess.run = capture_netstat_kwargs
    dsm._find_port_owner_pid(5020)
    check("netstat呼び出しに errors=\"replace\" が指定されている"
          "（デコード失敗を例外にしないための必須設定）",
          captured_kwargs.get("errors") == "replace", captured_kwargs)

    # ── T2: _process_command_line（wmic→PowerShellフォールバック） ─
    print("\n[T2] _process_command_line（自プロセス確認のための情報取得）")

    dsm._is_windows = lambda: False
    check("Windows以外では常にNone", dsm._process_command_line(9999) is None)
    dsm._is_windows = lambda: True

    WMIC_OK = ("Name=python.exe\n"
               "CommandLine=C:\\Python\\python.exe "
               "document_search_manager_20260924_03.py\n")

    def fake_run_wmic_ok(cmd, **kwargs):
        return FakeResult(0, WMIC_OK)
    dsm.subprocess.run = fake_run_wmic_ok
    info = dsm._process_command_line(9999)
    check("wmicが使えれば、そこから Name/CommandLine を取り出す",
          info is not None and info.get("name") == "python.exe", info)
    check("コマンドラインも取れる",
          "document_search_manager" in (info or {}).get("command_line", ""))

    def fake_run_wmic_fail_ps_ok(cmd, **kwargs):
        if cmd[0] == "wmic":
            return FakeResult(1, "")  # wmicが失敗（廃止環境を想定）
        return FakeResult(0, "python.exe|C:\\Python\\python.exe "
                             "document_search_manager_20260924_03.py")
    dsm.subprocess.run = fake_run_wmic_fail_ps_ok
    info2 = dsm._process_command_line(9999)
    check("wmicが失敗したらPowerShellにフォールバックする",
          info2 is not None and info2.get("name") == "python.exe", info2)

    def fake_run_both_fail(cmd, **kwargs):
        return FakeResult(1, "")
    dsm.subprocess.run = fake_run_both_fail
    check("両方失敗したらNone（確認できない扱い）",
          dsm._process_command_line(9999) is None)

    # ★2026-09-25 実機バグの再発防止★ wmic/PowerShellの出力がデコードできず
    # stdout=Noneで返ってきても、例外を投げずNoneを返すこと。
    def fake_run_wmic_stdout_none(cmd, **kwargs):
        return FakeResult(0, None)
    dsm.subprocess.run = fake_run_wmic_stdout_none
    check("wmicの stdout=None でも例外を投げずNoneを返す（実機クラッシュの再発防止）",
          dsm._process_command_line(9999) is None)

    wmic_kwargs, ps_kwargs = {}, {}

    def capture_wmic_ps_kwargs(cmd, **kwargs):
        if cmd[0] == "wmic":
            wmic_kwargs.update(kwargs)
            return FakeResult(1, "")  # フォールバックさせてPowerShellも呼ばせる
        ps_kwargs.update(kwargs)
        return FakeResult(0, "python.exe|dummy")
    dsm.subprocess.run = capture_wmic_ps_kwargs
    dsm._process_command_line(9999)
    check("wmic呼び出しに errors=\"replace\" が指定されている",
          wmic_kwargs.get("errors") == "replace", wmic_kwargs)
    check("PowerShell呼び出しにも errors=\"replace\" が指定されている",
          ps_kwargs.get("errors") == "replace", ps_kwargs)

    # ── T3: _confirm_self_process（自分自身かどうかの最終判定） ──
    print("\n[T3] _confirm_self_process（自分自身かどうかの最終判定）")

    dsm._process_command_line = lambda pid: {
        "name": "python.exe",
        "command_line": "C:\\Python\\python.exe document_search_manager_20260924_03.py"}
    check("python.exe + document_search_managerを含む → True（自分自身）",
          dsm._confirm_self_process(9999) is True)

    dsm._process_command_line = lambda pid: {
        "name": "python.exe", "command_line": "C:\\Python\\python.exe other_tool.py"}
    check("python.exeでもdocument_search_managerを含まなければFalse",
          dsm._confirm_self_process(9999) is False)

    dsm._process_command_line = lambda pid: {
        "name": "notepad.exe",
        "command_line": "notepad document_search_manager_memo.txt"}
    check("python.exe以外（別アプリ）ならFalse（誤って終了させない）",
          dsm._confirm_self_process(9999) is False)

    dsm._process_command_line = lambda pid: None
    check("情報が取れなければFalse（確認できない＝安全側）",
          dsm._confirm_self_process(9999) is False)

    # ── T4: _try_auto_kill_port_owner（一連の自動終了フロー） ────
    print("\n[T4] _try_auto_kill_port_owner（自動終了フロー全体）")

    dsm.time.sleep = lambda s: None  # テストを待たせない

    check("config.jsonでauto_kill_port_conflict=falseなら何もせずFalse",
          dsm._try_auto_kill_port_owner(5020, dict(CFG, auto_kill_port_conflict=False))
          is False)

    dsm._is_windows = lambda: False
    check("Windows以外なら常にFalse（configがtrueでも）",
          dsm._try_auto_kill_port_owner(5020, dict(CFG, auto_kill_port_conflict=True))
          is False)
    dsm._is_windows = lambda: True

    dsm._find_port_owner_pid = lambda port: None
    taskkill_calls = []
    dsm.subprocess.run = lambda cmd, **k: (
        taskkill_calls.append(cmd) or FakeResult(0))
    check("PIDを特定できなければFalse・taskkillは一切呼ばない",
          dsm._try_auto_kill_port_owner(5020, CFG) is False)
    check("taskkillが呼ばれていない", taskkill_calls == [], taskkill_calls)

    dsm._find_port_owner_pid = lambda port: 9999
    dsm._confirm_self_process = lambda pid: False
    taskkill_calls.clear()
    check("自分自身と確認できなければFalse・taskkillは呼ばない（誤終了防止の要）",
          dsm._try_auto_kill_port_owner(5020, CFG) is False)
    check("taskkillが呼ばれていない（未確認プロセスを終了させない）",
          taskkill_calls == [], taskkill_calls)

    dsm._confirm_self_process = lambda pid: True

    kill_and_free_state = {"freed": False}

    def fake_run_kill_ok(cmd, **k):
        taskkill_calls.append(cmd)
        if cmd[0] == "taskkill":
            kill_and_free_state["freed"] = True
            return FakeResult(0)
        return FakeResult(0)
    taskkill_calls.clear()
    kill_and_free_state["freed"] = False
    dsm.subprocess.run = fake_run_kill_ok
    dsm._port_in_use = lambda port: not kill_and_free_state["freed"]
    check("確認済みPIDはtaskkillで終了し、ポートが空けばTrue",
          dsm._try_auto_kill_port_owner(5020, CFG) is True)
    check("taskkill /PID 9999 /F が呼ばれた",
          any(c[:2] == ["taskkill", "/PID"] and "9999" in c for c in taskkill_calls),
          taskkill_calls)

    dsm.subprocess.run = fake_run_kill_ok
    dsm._port_in_use = lambda port: True  # 終了後も空かないケース
    check("終了はできてもポートが空かなければFalse",
          dsm._try_auto_kill_port_owner(5020, CFG) is False)

    def fake_run_kill_fail(cmd, **k):
        if cmd[0] == "taskkill":
            return FakeResult(1, "", "Access is denied.")
        return FakeResult(0)
    dsm.subprocess.run = fake_run_kill_fail
    dsm._port_in_use = lambda port: True
    check("taskkillがエラーで返ってきたらFalse",
          dsm._try_auto_kill_port_owner(5020, CFG) is False)

    def fake_run_kill_raise(cmd, **k):
        if cmd[0] == "taskkill":
            raise PermissionError("denied")
        return FakeResult(0)
    dsm.subprocess.run = fake_run_kill_raise
    check("taskkillが例外を投げても、呼び出し元は落とさずFalseを返す",
          dsm._try_auto_kill_port_owner(5020, CFG) is False)

    # ★2026-09-25 実機バグの再発防止★ taskkillが失敗した際のstderrも
    # デコードできずNoneで返ってくることがあるため、.strip()で落ちないこと。
    def fake_run_kill_fail_stderr_none(cmd, **k):
        if cmd[0] == "taskkill":
            return FakeResult(1, None, None)
        return FakeResult(0)
    dsm.subprocess.run = fake_run_kill_fail_stderr_none
    check("taskkill失敗時にstderr=Noneでも例外を投げずFalseを返す"
          "（実機クラッシュの再発防止）",
          dsm._try_auto_kill_port_owner(5020, CFG) is False)

    taskkill_kwargs = {}

    def capture_taskkill_kwargs(cmd, **k):
        if cmd[0] == "taskkill":
            taskkill_kwargs.update(k)
            return FakeResult(0)
        return FakeResult(0)
    dsm.subprocess.run = capture_taskkill_kwargs
    dsm._port_in_use = lambda port: False
    dsm._try_auto_kill_port_owner(5020, CFG)
    check("taskkill呼び出しにも errors=\"replace\" が指定されている",
          taskkill_kwargs.get("errors") == "replace", taskkill_kwargs)

finally:
    restore()


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
