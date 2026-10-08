# -*- coding: utf-8 -*-
"""tools/diagnose_search_folders_*.py の純粋関数・フェイクCOMテスト。"""
import glob
import importlib.util
import os
import sys
import unittest

sys.dont_write_bytecode = True

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(os.path.dirname(TESTS_DIR), "tools")


def _load_tool():
    paths = sorted(glob.glob(os.path.join(TOOLS_DIR, "diagnose_search_folders_*.py")))
    if not paths:
        raise FileNotFoundError("tools/diagnose_search_folders_*.py がありません")
    spec = importlib.util.spec_from_file_location("diag_search_folders_under_test", paths[-1])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


T = _load_tool()


class TestMask(unittest.TestCase):
    def test_email_masked(self):
        out = T.mask_filter("[SenderEmailAddress] = 'taro@example.com'")
        self.assertNotIn("taro@example.com", out)
        self.assertIn("<MAIL>", out)

    def test_name_literal_masked(self):
        out = T.mask_filter("\"urn:schemas:httpmail:displayto\" LIKE '%Ochi Taro%'")
        self.assertIn("<NAME>", out)
        self.assertNotIn("Ochi", out)
        self.assertIn("urn:schemas:httpmail:displayto", out)

    def test_japanese_name_masked(self):
        self.assertNotIn("越智", T.mask_filter("[To] = '越智 太郎'"))

    def test_safe_literals_kept(self):
        out = T.mask_filter("[UnRead] = 'True' AND [ReceivedTime] >= '2026-10-01 00:00'")
        self.assertEqual(out, "[UnRead] = 'True' AND [ReceivedTime] >= '2026-10-01 00:00'")

    def test_raw_mode(self):
        s = "[To] = 'Ochi'"
        self.assertEqual(T.mask_filter(s, enabled=False), s)

    def test_none(self):
        self.assertEqual(T.mask_filter(None), "")


class TestMaskFilterStrict(unittest.TestCase):
    def _no_leak(self, flt, *secrets):
        out = T.mask_filter(flt)
        for sec in secrets:
            self.assertNotIn(sec, out, flt)
        return out

    def test_mail_and_name(self):
        out = self._no_leak("[From]='a@b.co' AND [To]='Ochi Taro'", "a@b.co", "Ochi", "Taro")
        self.assertEqual(out, "[From]='<MAIL>' AND [To]='<NAME>'")

    def test_dasl(self):
        out = self._no_leak("\"urn:schemas:httpmail:fromemail\" = 'a@b.co' AND "
                            "\"urn:schemas:httpmail:displayto\" LIKE '%Ochi Taro%'", "a@b.co", "Ochi")
        self.assertIn('"urn:schemas:httpmail:fromemail"', out)
        self.assertIn("'<MAIL>'", out)

    def test_like_mail_wildcard(self):
        self.assertEqual(T.mask_filter("[To] LIKE '%a@b.co%'"), "[To] LIKE '%<MAIL>%'")

    def test_mail_plus_name_in_one_literal(self):
        self._no_leak("[To] LIKE '%Ochi a@b.co%'", "Ochi", "a@b.co")

    def test_broken_quotes(self):
        self._no_leak("[To]='Ochi", "Ochi")
        self._no_leak("[To]='Ochi Taro AND [Cc]='x@y.jp'", "Ochi", "x@y.jp")

    def test_escaped_quotes(self):
        self._no_leak("[To]='O''Neil Taro' AND [x]='a\\'b Taro'", "Neil", "Taro")

    def test_multiple_values(self):
        out = self._no_leak("[To]='A Bee' OR [To]='C Dee' OR [Cc]='e@f.jp'", "Bee", "Dee", "e@f.jp")
        self.assertEqual(out.count("<NAME>"), 2)

    def test_japanese_name_double_quote(self):
        self._no_leak('"urn:schemas:httpmail:displayto" LIKE \'%越智 太郎%\'', "越智")

    def test_mail_only_and_name_only(self):
        self.assertEqual(T.mask_filter("[From]='a@b.co'"), "[From]='<MAIL>'")
        self.assertEqual(T.mask_filter("[To]='Taro'"), "[To]='<NAME>'")

    def test_mail_outside_quotes(self):
        self._no_leak("[From]=a@b.co", "a@b.co")

    def test_unquoted_value(self):
        out = self._no_leak("[To] = Ochi Taro AND [UnRead] = True", "Ochi", "Taro")
        self.assertIn("[UnRead] = True", out)
        self._no_leak("[To] LIKE Ochi", "Ochi")

    def test_date_strict(self):
        self.assertEqual(T.mask_filter("[R]>='2026/1/1 10:00'"), "[R]>='2026/1/1 10:00'")
        self.assertEqual(T.mask_filter("[R]>='2026-01-01'"), "[R]>='2026-01-01'")
        self._no_leak("[R]>='2026/1/1 Taro'", "Taro")
        self._no_leak("[R]='12 Taro'", "Taro")

    def test_schema_strict(self):
        self._no_leak("[R]='urn:x Taro'", "Taro")
        self._no_leak("[R]='http://x Taro'", "Taro")
        self._no_leak("[R]='urn:schemas:httpmail:subject Taro'", "Taro")
        s = "\"http://schemas.microsoft.com/mapi/proptag/0x0037001F\" = 'x'"
        self.assertIn("http://schemas.microsoft.com/mapi/proptag/0x0037001F", T.mask_filter(s))

    def test_dasl_numeric_kept(self):
        s = '@SQL="urn:schemas:httpmail:read"=0'
        self.assertEqual(T.mask_filter(s), s)


class TestScopeMaskSeparate(unittest.TestCase):
    def test_store_and_folder_masked_separately(self):
        sm, fm = T.NameMasker(True, "Store", 2), T.NameMasker(True, "Folder", 3)
        sm.mask("existing")
        s = T.summarize_scope("'\\\\Mail A\\受信トレイ','\\\\Mail A\\送信済み'", sm.mask, fm.mask)
        self.assertIn("Store-02", s)
        self.assertIn("Folder-001", s)
        self.assertNotIn("受信トレイ", s)
        self.assertNotIn("Mail A", s)

    def test_folder_names_raw_when_unmasked(self):
        s = T.summarize_scope("'\\\\Mail A\\受信トレイ'", None, None)
        self.assertIn("受信トレイ", s)


class TestRestrictScan(unittest.TestCase):
    def test_skip_large(self):
        class F:
            def __init__(self, n):
                self.Items = _Items(n, restrict_n=3)
        total, capped, errs, skipped, scanned = T.restrict_scan([F(10), F(999999)], "x", 60, 1000)
        self.assertEqual((total, capped, skipped, scanned), (3, True, 1, 1))

    def test_unlimited(self):
        class F:
            Items = None
        f = F()
        f.Items = _Items(999999, restrict_n=4)
        self.assertEqual(T.restrict_scan([f], "x", 60, 0)[0], 4)

    def test_timeout_between_folders(self):
        class F:
            def __init__(self):
                self.Items = _Items(1, restrict_n=1)
        ticks = iter([0, 100, 200])
        total, capped, _e, _s, scanned = T.restrict_scan([F(), F()], "x", 50, 0, clock=lambda: next(ticks))
        self.assertTrue(capped)
        self.assertEqual(scanned, 0)


class TestSummary(unittest.TestCase):
    def test_empty(self):
        self.assertIn("空", T.summarize_filter(""))

    def test_dasl(self):
        s = T.summarize_filter('@SQL="urn:schemas:httpmail:read"=0 AND "urn:schemas:httpmail:displayto" LIKE \'%x%\'')
        self.assertIn("DASL", s)
        self.assertIn("read", s)
        self.assertIn("AND×1", s)
        self.assertNotIn("%x%", s)

    def test_restrict_unread(self):
        s = T.summarize_filter("[UnRead] = True")
        self.assertIn("Restrict", s)
        self.assertIn("未読条件あり", s)

    def test_scope_parse(self):
        sc = "'\\\\Mail A\\受信トレイ','\\\\Mail A\\送信済みアイテム'"
        self.assertEqual(len(T.parse_scope(sc)), 2)
        self.assertEqual(T.scope_store_names(sc), ["Mail A"])
        self.assertIn("2フォルダー / 1ストア", T.summarize_scope(sc))

    def test_scope_empty(self):
        self.assertEqual(T.parse_scope(""), [])
        self.assertIn("空", T.summarize_scope(""))

    def test_scope_mask(self):
        s = T.summarize_scope("'\\\\Mail A\\Inbox'", lambda x: "X", lambda x: "Y")
        self.assertNotIn("Mail A", s)

    def test_split_path(self):
        self.assertEqual(T.split_scope_path("\\\\S\\A\\B"), ["S", "A", "B"])


class TestLabels(unittest.TestCase):
    def test_connection_mode(self):
        self.assertIn("olOnline", T.connection_mode_label(800))
        self.assertIn("不明な値", T.connection_mode_label(12345))
        self.assertIn("不明", T.connection_mode_label(None))

    def test_store_kind(self):
        self.assertEqual(T.store_kind_label(False, "C:\\x\\2024_Q1.pst", "2024_Q1"), "PST")
        self.assertEqual(T.store_kind_label(False, "", "オンライン アーカイブ - a"), "アーカイブ")
        self.assertEqual(T.store_kind_label(True, "C:\\a.ost", "me"), "現行(既定)")

    def test_error_kind_no_message(self):
        class E(Exception):
            pass
        self.assertEqual(T.error_kind(E("secret subject")), "E")
        e = E(-2147221233, "secret")
        self.assertEqual(T.error_kind(e), "E(0x8004010F)")
        self.assertNotIn("secret", T.error_kind(e))

    def test_masker(self):
        m = T.NameMasker(True, "SF", 3)
        self.assertEqual(m.mask("a"), "SF-001")
        self.assertEqual(m.mask("b"), "SF-002")
        self.assertEqual(m.mask("a"), "SF-001")
        self.assertEqual(T.NameMasker(False, "SF").mask("a"), "a")

    def test_only_names(self):
        self.assertTrue(T.name_matches("未(CcMe)", []))
        self.assertTrue(T.name_matches("未(CcMe)", ["ccme"]))
        self.assertFalse(T.name_matches("未(ToMe)", ["ccme"]))
        self.assertEqual(T.parse_only_names(" a, b ,,"), ["a", "b"])


class TestHints(unittest.TestCase):
    def test_zero_but_restrict_positive(self):
        h = " ".join(T.diagnose_hints({"items_count": 0, "restrict_count": 12, "filter_empty": False,
                                       "scope_empty": False, "default_item_type": 0}))
        self.assertIn("評価が止まっている", h)

    def test_both_zero(self):
        h = " ".join(T.diagnose_hints({"items_count": 0, "restrict_count": 0}))
        self.assertIn("Restrictも0件", h)

    def test_empty_filter(self):
        h = " ".join(T.diagnose_hints({"items_count": 0, "filter_empty": True}))
        self.assertIn("条件(Filter)が空", h)

    def test_non_mail_type(self):
        h = " ".join(T.diagnose_hints({"items_count": 1, "default_item_type": 1}))
        self.assertIn("メール以外", h)

    def test_capped_suffix(self):
        h = " ".join(T.diagnose_hints({"items_count": 0, "restrict_count": 5, "restrict_capped": True}))
        self.assertIn("5件以上", h)

    def test_format_record_no_content_fields(self):
        rec = {"name": "SF-001", "store_label": "Store-01", "store_kind": "現行(既定)", "items_count": 0,
               "unread_count": 0, "default_item_type": 0, "is_synchronous": True, "search_subfolders": False,
               "filter_summary": "x", "filter_masked": "[To] = '<NAME>'", "scope_summary": "1フォルダー",
               "restrict_count": 3, "restrict_capped": False, "restrict_note": "1フォルダーを走査", "errors": []}
        text = "\n".join(T.format_record(rec, 1))
        self.assertIn("Items.Count=0", text)
        self.assertIn("Restrict再スキャン: 3", text)


class TestOutputPath(unittest.TestCase):
    def test_default_name(self):
        self.assertTrue(T.default_output_name().startswith("diagnose_search_folders_"))
        self.assertIn("mail_reports", T.resolve_output_path(""))


# ---- フェイクCOM ----
class _Coll:
    def __init__(self, items):
        self._items = list(items)
        self.Count = len(self._items)

    def Item(self, i):
        return self._items[i - 1]


class _Restricted:
    def __init__(self, n):
        self.Count = n


class _Items:
    def __init__(self, n, restrict_n=0):
        self.Count = n
        self._r = restrict_n

    def Restrict(self, flt):
        return _Restricted(self._r)


class _Search:
    def __init__(self, flt, scope):
        self.Filter, self.Scope = flt, scope
        self.IsSynchronous, self.SearchSubFolders, self.Tag = False, False, "t"


class _Folder:
    def __init__(self, name, items=None, search=None, subs=()):
        self.Name = name
        self.Items = items or _Items(0)
        self.Search = search
        self.Folders = _Coll(subs)
        self.DefaultItemType = 0
        self.UnReadItemCount = 0


class _Store:
    def __init__(self, name, sfs, path=""):
        self.DisplayName, self.FilePath = name, path
        self._sfs = sfs
        self.IsCachedExchange = False
        self.IsInstantSearchEnabled = True

    def GetSearchFolders(self):
        return _Coll(self._sfs)


class _NS:
    def __init__(self, stores, roots):
        self.Stores = _Coll(stores)
        self.Folders = _Coll(roots)
        self.ExchangeConnectionMode = 800
        self._stores = stores

    def GetDefaultFolder(self, n):
        class F:
            pass
        f = F()
        f.Store = self._stores[0]
        return f


class _App:
    Version = "16.0"

    def __init__(self, ns):
        self._ns = ns

    def GetNamespace(self, _):
        return self._ns


class _Client:
    def __init__(self, app):
        self._app = app

    def Dispatch(self, _):
        return self._app


class _Py:
    def CoInitialize(self):
        pass

    def CoUninitialize(self):
        pass


class _Rep:
    def __init__(self):
        self.lines = []

    def log(self, t=""):
        self.lines.append(t)


class TestFakeRun(unittest.TestCase):
    def _run(self, extra=()):
        inbox = _Folder("受信トレイ", _Items(100, restrict_n=7))
        root = _Folder("Mail A", subs=[inbox])
        sf = _Folder("未(CcMe)", _Items(0),
                     _Search("[UnRead] = True AND [CC] = 'Ochi Taro'", "'\\\\Mail A\\受信トレイ'"))
        store = _Store("Mail A", [sf])
        ns = _NS([store], [root])
        args = T.parse_args(list(extra))
        rep = _Rep()
        code = T.run_diagnosis(args, rep, com=(_Client(_App(ns)), _Py()))
        return code, "\n".join(rep.lines)

    def test_basic(self):
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("未(CcMe)", out)
        self.assertIn("Items.Count=0", out)
        self.assertNotIn("Ochi", out)
        self.assertNotIn("Restrict再スキャン", out)

    def test_verify_restrict(self):
        code, out = self._run(["--verify-restrict"])
        self.assertEqual(code, 0)
        self.assertIn("Restrict再スキャン: 7", out)
        self.assertIn("評価が止まっている", out)

    def test_mask_names(self):
        _code, out = self._run(["--mask-names"])
        self.assertNotIn("未(CcMe)", out)
        self.assertIn("SF-001", out)

    def test_no_com(self):
        rep = _Rep()
        orig = T.import_com
        T.import_com = lambda: (None, None)
        try:
            self.assertEqual(T.run_diagnosis(T.parse_args([]), rep), 2)
        finally:
            T.import_com = orig


class TestReadOnly(unittest.TestCase):
    def test_no_mutating_calls_in_source(self):
        path = sorted(glob.glob(os.path.join(TOOLS_DIR, "diagnose_search_folders_*.py")))[-1]
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        code_lines = [l for l in src.splitlines() if not l.lstrip().startswith(("#", '"""'))]
        body = "\n".join(code_lines)
        for bad in (".Delete(", ".Move(", ".Save(", ".AddStore(", ".Send(", ".AddSearchFolder(", ".MarkAsRead(", ".Display("):
            self.assertNotIn(bad, body, bad)


if __name__ == "__main__":
    unittest.main()
