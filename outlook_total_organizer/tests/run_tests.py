# -*- coding: utf-8 -*-
"""A1「判断待ち」テストランナー (unittest のみ。pytest は使わない)。

使い方 (outlook_total_organizer フォルダで):
    python tests/run_tests.py                 # tests/ 内の test_*.py を全部実行
    python tests/run_tests.py snapshot gui    # ファイル名に snapshot / gui を含むものだけ
    python tests/run_tests.py -v              # 1件ずつ結果を表示
    python tests/run_tests.py --tb            # 失敗の詳細(トレースバック)も表示
    xvfb-run -a python tests/run_tests.py     # Linux でGUIテストも実行 (ディスプレイが無いとGUIはスキップ)

環境変数:
    OTO_TARGET=<ファイル名>   テスト対象のリビジョンを指定 (既定: outlook_total_organizer_*.py の名前順で最後)

終了コード: 失敗/エラー/想定外の成功が1件でもあれば 1、無ければ 0 (スキップ・想定内の失敗は 0)。
  --ignore-specgap を付けると、SpecGap (仕様が曖昧な点を自然な解釈で書いたテスト) の失敗だけは終了コードに含めない。
"""
import sys

sys.dont_write_bytecode = True      # tests/ 配下に __pycache__ を作らない (他のimportより先に設定)

import argparse
import faulthandler
import os
import re
import time
import unittest
from collections import OrderedDict

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

import _loader  # noqa: E402

_SUB_RE = re.compile(r"\((.+?)\.(\w+)\)")


def _split_id(test):
    """(module, class, method) を返す。クラス単位のスキップ/エラー (_ErrorHolder) にも対応。"""
    tid = test.id() if hasattr(test, "id") else str(test)
    parts = tid.split(".")
    if len(parts) >= 3:
        return parts[0], parts[-2], parts[-1]
    m = _SUB_RE.search(tid)
    if m:
        return m.group(1), m.group(2), tid.split(" ")[0]
    return "(読込)", "-", tid


def _short(err, limit=260):
    exc_type, exc_value, _tb = err
    text = f"{exc_type.__name__}: {exc_value}"
    text = " ".join(text.split("\n")[:3]).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


class A1Result(unittest.TestResult):
    """1テストメソッド=1レコードで結果を集める (subTest の失敗は親メソッドの失敗として数える)。"""

    def __init__(self, verbose=False, show_tb=False):
        super().__init__()
        self.verbose = verbose
        self.show_tb = show_tb
        self.records = OrderedDict()
        self.buffer = True            # 成功したテストの標準出力/標準エラーは捨てる (雑音防止)
        self._t0 = {}

    # ---- レコード ------------------------------------------------------
    def _rec(self, test):
        tid = test.id() if hasattr(test, "id") else str(test)
        if tid not in self.records:
            mod, cls, name = _split_id(test)
            doc = (getattr(test, "_testMethodDoc", None) or "").strip().split("\n")[0]
            self.records[tid] = {"id": tid, "module": mod, "cls": cls, "name": name, "status": None,
                                 "details": [], "doc": doc, "reason": ""}
        return self.records[tid]

    def _pending(self, err):
        exc_type, exc_value, _ = err
        if not issubclass(exc_type, AttributeError):
            return False
        msg = str(exc_value)
        return any(f"'{n}'" in msg for n in _loader.A1_ALL_NAMES)

    def _set(self, test, status, detail=None, reason=""):
        r = self._rec(test)
        order = ["pass", "skip", "xfail", "xpass", "fail", "error", "pending"]
        if r["status"] is None or order.index(status) > order.index(r["status"]):
            r["status"] = status
        if detail:
            r["details"].append(detail)
        if reason:
            r["reason"] = reason
        return r

    # ---- unittest フック -----------------------------------------------
    def startTest(self, test):
        super().startTest(test)
        self._rec(test)
        self._t0[test.id()] = time.time()

    def stopTest(self, test):
        super().stopTest(test)
        if self.verbose:
            r = self._rec(test)
            icon = {"pass": "✅", "fail": "❌", "error": "💥", "skip": "⏭ ", "xfail": "🧪", "xpass": "🎉",
                    "pending": "⏳", None: "?"}[r["status"]]
            print(f"  {icon} {r['cls']}.{r['name']}")

    def addSuccess(self, test):
        super().addSuccess(test)
        self._set(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._set(test, "fail", (None, _short(err), self._exc_info_to_string(err, test)))

    def addError(self, test, err):
        super().addError(test, err)
        status = "pending" if self._pending(err) else "error"
        self._set(test, status, (None, _short(err), self._exc_info_to_string(err, test)))

    def addSubTest(self, test, subtest, err):
        # 基底の実装は failures/errors に積むだけなので、ここでは自前のレコードにのみ記録する
        if err is not None:
            sub = getattr(subtest, "_subDescription", lambda: str(subtest))()
            if issubclass(err[0], test.failureException):
                status = "fail"
            else:
                status = "pending" if self._pending(err) else "error"
            self._set(test, status, (sub, _short(err), self._exc_info_to_string(err, test)))
            self.failures.append((subtest, "subtest"))      # wasSuccessful() 用

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._set(test, "skip", reason=reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._set(test, "xfail")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._set(test, "xpass")


STATUS_ORDER = ("pass", "fail", "error", "pending", "skip", "xfail", "xpass")


def _is_specgap(rec):
    return "SpecGap" in rec["cls"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="A1「判断待ち」テストランナー (unittest)")
    ap.add_argument("filters", nargs="*", help="ファイル名に含まれる文字列 (例: snapshot gui)。省略で全部")
    ap.add_argument("-v", "--verbose", action="store_true", help="1件ずつ結果を表示")
    ap.add_argument("--tb", action="store_true", help="失敗のトレースバックも表示")
    ap.add_argument("-f", "--failfast", action="store_true", help="最初の失敗で止める")
    ap.add_argument("--ignore-specgap", action="store_true",
                    help="SpecGap(仕様曖昧点の自然解釈テスト)の失敗を終了コードに含めない")
    ap.add_argument("--timeout", type=int, default=900, help="全体のウォッチドッグ秒数 (固まったら強制終了)")
    args = ap.parse_args(argv)

    faulthandler.dump_traceback_later(args.timeout, exit=True)

    # ---- ヘッダ ---------------------------------------------------------
    print("🧪 A1「判断待ち」テスト")
    try:
        target = _loader.target_path()
        mod = _loader.load()
        print(f"   対象    : {os.path.basename(target)}")
        print(f"   Python  : {sys.version.split()[0]}   DISPLAY={'あり' if os.environ.get('DISPLAY') else 'なし'}")
        if _loader.STUBBED_MODULES:
            print(f"   スタブ  : {', '.join(_loader.STUBBED_MODULES)} (この環境に無いため最小スタブで代替)")
        missing = _loader.missing_a1_names(mod)
        if missing:
            print(f"   ⏳ 未実装(対象ファイルに無いA1の名前) {len(missing)}件: {', '.join(missing)}")
        else:
            print("   ✅ A1の関数・定数・GUIメソッドは対象ファイルにすべて存在")
    except BaseException as e:                                  # noqa: BLE001
        print(f"   ❌ 対象ファイルの読み込みに失敗: {type(e).__name__}: {e}")
        return 2

    # ---- 収集 -----------------------------------------------------------
    loader = unittest.TestLoader()
    suite = loader.discover(TESTS_DIR, pattern="test_*.py", top_level_dir=TESTS_DIR)

    def flatten(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                yield from flatten(t)
            else:
                yield t

    tests = list(flatten(suite))
    if args.filters:
        tests = [t for t in tests if any(f in t.id().split(".")[0] for f in args.filters)]
    if not tests:
        print("   ❌ 実行するテストが見つかりません")
        return 2
    suite = unittest.TestSuite(tests)

    # ---- 実行 -----------------------------------------------------------
    result = A1Result(verbose=args.verbose, show_tb=args.tb)
    result.failfast = args.failfast
    t0 = time.time()
    print("   ▶ 実行中...")
    suite.run(result)
    elapsed = time.time() - t0

    # ---- 集計 -----------------------------------------------------------
    by_module = OrderedDict()
    for r in result.records.values():
        by_module.setdefault(r["module"], {k: 0 for k in STATUS_ORDER})
        by_module[r["module"]][r["status"] or "error"] += 1
    totals = {k: sum(m[k] for m in by_module.values()) for k in STATUS_ORDER}
    total = sum(totals.values())

    print()
    print("─" * 78)
    head = f"{'ファイル':<28}{'件数':>5}  ✅成功 ❌失敗 💥エラー ⏳未実装 ⏭スキップ 🧪想定内失敗 🎉想定外成功"
    print(head)
    for mod_name, c in by_module.items():
        n = sum(c.values())
        print(f"{mod_name:<28}{n:>5}  {c['pass']:>4}  {c['fail']:>4}  {c['error']:>5}  {c['pending']:>6}  "
              f"{c['skip']:>7}  {c['xfail']:>9}  {c['xpass']:>9}")
    print("─" * 78)
    print(f"合計 {total}件 ({elapsed:.1f}秒)")
    print(f"  ✅ 成功 {totals['pass']}   ❌ 失敗 {totals['fail']}   💥 エラー {totals['error']}   "
          f"⏳ 実装待ち {totals['pending']}   ⏭ スキップ {totals['skip']}   "
          f"🧪 想定内の失敗(expectedFailure) {totals['xfail']}   🎉 想定外の成功 {totals['xpass']}")

    # ---- 詳細 -----------------------------------------------------------
    bad = [r for r in result.records.values() if r["status"] in ("fail", "error", "pending")]
    real_bad = [r for r in bad if not _is_specgap(r)]
    gap_bad = [r for r in bad if _is_specgap(r)]

    def show(title, items, icon):
        if not items:
            return
        print()
        print(f"{title} ({len(items)}件)")
        for r in items:
            print(f"  {icon} {r['module']}.{r['cls']}.{r['name']}")
            if r["doc"] and not args.verbose:
                pass
            for sub, msg, full in r["details"][:3]:
                label = f"[{sub}] " if sub else ""
                print(f"       {label}{msg}")
                if args.tb:
                    print("       " + full.rstrip().replace("\n", "\n       "))
            if len(r["details"]) > 3:
                print(f"       … 他 {len(r['details']) - 3}件")

    show("❌ 失敗・エラー (仕様どおりでない/テストが落ちた)", real_bad, "❌")
    show("❓ 仕様確認が必要 (SpecGap: 仕様が曖昧な点を自然な解釈で書いたテストの失敗)", gap_bad, "❓")

    xfail = [r for r in result.records.values() if r["status"] == "xfail"]
    if xfail:
        print()
        print(f"🧪 想定内の失敗 = 既知の問題の記録 ({len(xfail)}件)")
        for r in xfail:
            print(f"  🧪 {r['module']}.{r['cls']}.{r['name']}")
            if r["doc"]:
                print(f"       {r['doc']}")

    xpass = [r for r in result.records.values() if r["status"] == "xpass"]
    if xpass:
        print()
        print(f"🎉 想定外の成功 ({len(xpass)}件) = 既知の問題が直った可能性。@unittest.expectedFailure を外してください")
        for r in xpass:
            print(f"  🎉 {r['module']}.{r['cls']}.{r['name']}")

    skips = [r for r in result.records.values() if r["status"] == "skip"]
    if skips:
        print()
        print(f"⏭ スキップ ({len(skips)}件)")
        reasons = OrderedDict()
        for r in skips:
            reasons.setdefault(r["reason"] or "(理由なし)", []).append(f"{r['module']}.{r['cls']}")
        for reason, who in reasons.items():
            uniq = sorted(set(who))
            print(f"  ⏭ {reason}")
            print(f"       対象: {', '.join(uniq[:6])}{' …' if len(uniq) > 6 else ''}")

    # ---- 終了判定 -------------------------------------------------------
    n_fail = len(real_bad) + (0 if args.ignore_specgap else len(gap_bad)) + len(xpass)
    print()
    if n_fail == 0:
        print("🟢 全テスト合格 (スキップ・想定内の失敗を除く)")
        code = 0
    else:
        print(f"🔴 要対応 {n_fail}件 (失敗/エラー/想定外の成功)")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
