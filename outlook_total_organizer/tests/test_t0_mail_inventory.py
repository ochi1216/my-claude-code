# -*- coding: utf-8 -*-
"""T0 事前診断スクリプト (tools/diagnose_mail_inventory_*.py) の純粋関数テスト。

app/ のモジュールではないので、importlib で tools/ から直接読み込む。
COM (win32com / pythoncom) は import しない設計なので、スタブ無しで読み込める。
"""
import contextlib
import glob
import importlib.util
import io
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime

sys.dont_write_bytecode = True

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(os.path.dirname(TESTS_DIR), "tools")


def _load_tool():
    paths = sorted(glob.glob(os.path.join(TOOLS_DIR, "diagnose_mail_inventory_*.py")))
    if not paths:
        raise FileNotFoundError("tools/diagnose_mail_inventory_*.py がありません")
    spec = importlib.util.spec_from_file_location("diag_mail_inventory_under_test", paths[-1])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


T = _load_tool()


class TestMonths(unittest.TestCase):
    def test_parse_ym_ok(self):
        self.assertEqual(T.parse_ym("2023-10"), (2023, 10))
        self.assertEqual(T.parse_ym("2026/9"), (2026, 9))
        self.assertEqual(T.parse_ym(" 2026-09 "), (2026, 9))

    def test_parse_ym_bad(self):
        for bad in ("2023", "2023-13", "2023-00", "abc", "", "23-10", None, "2023-10-01"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    T.parse_ym(bad)

    def test_month_range_default_is_36(self):
        r = T.month_range(T.parse_ym("2023-10"), T.parse_ym("2026-09"))
        self.assertEqual(len(r), 36)
        self.assertEqual(r[0], (2023, 10))
        self.assertEqual(r[-1], (2026, 9))
        self.assertIn((2024, 1), r)
        self.assertEqual(r.index((2023, 12)) + 1, r.index((2024, 1)))

    def test_month_range_single_and_reverse(self):
        self.assertEqual(T.month_range((2025, 5), (2025, 5)), [(2025, 5)])
        with self.assertRaises(ValueError):
            T.month_range((2025, 6), (2025, 5))

    def test_month_bounds_december_and_leap(self):
        self.assertEqual(T.month_bounds(2025, 12), (datetime(2025, 12, 1), datetime(2026, 1, 1)))
        self.assertEqual(T.month_bounds(2024, 2), (datetime(2024, 2, 1), datetime(2024, 3, 1)))

    def test_overlap_bounds(self):
        s, e = T.overlap_bounds(2025, 1, 1)
        self.assertEqual(s, datetime(2024, 12, 31))
        self.assertEqual(e, datetime(2025, 2, 2))


class TestFilters(unittest.TestCase):
    def test_build_range_filter(self):
        f = T.build_range_filter("ReceivedTime", datetime(2026, 9, 1), datetime(2026, 10, 1), "US_24h")
        self.assertEqual(f, "[ReceivedTime] >= '09/01/2026 00:00' AND [ReceivedTime] < '10/01/2026 00:00'")

    def test_variants_cover_all_formats(self):
        v = T.build_month_filter_variants("ReceivedTime", 2026, 9)
        self.assertEqual([n for n, _ in v], [n for n, _ in T.DATE_FORMATS])
        d = dict(v)
        self.assertIn("'2026-09-01 00:00'", d["ISO_24h"])
        self.assertIn("'01/09/2026 00:00'", d["DMY_24h"])
        self.assertIn("'2026/10/01 00:00'", d["YMD_slash_24h"])
        self.assertIn("'09/01/2026'", d["US_date"])
        self.assertIn("[ReceivedTime] <", d["US_24h"])

    def test_variants_overlap(self):
        d = dict(T.build_month_filter_variants("SentOn", 2026, 9, overlap_days=1))
        self.assertIn("'08/31/2026 00:00'", d["US_24h"])
        self.assertIn("'10/02/2026 00:00'", d["US_24h"])
        self.assertIn("[SentOn]", d["US_24h"])

    def test_dasl_filters(self):
        d = T.build_dasl_filters("ReceivedTime", 2026, 9, "invoice")
        self.assertIn("LIKE '%invoice%'", d["like"])
        self.assertIn("ci_phrasematch 'invoice'", d["phrase"])
        self.assertTrue(d["like"].startswith("@SQL="))
        self.assertIn("urn:schemas:httpmail:datereceived", d["baseline"])
        self.assertIn("'2026-09-01 00:00:00'", d["baseline"])
        self.assertNotIn("LIKE", d["baseline"])
        d2 = T.build_dasl_filters("SentOn", 2026, 9, "x")
        self.assertIn("urn:schemas:httpmail:date\"", d2["baseline"])

    def test_sanitize_probe_word(self):
        self.assertEqual(T.sanitize_probe_word("inv'oice%"), "invoice")
        self.assertEqual(T.sanitize_probe_word(' "請求書" '), "請求書")
        for bad in ("", "'%'", None):
            with self.assertRaises(ValueError):
                T.sanitize_probe_word(bad)


class TestMask(unittest.TestCase):
    def test_windows_user(self):
        self.assertEqual(T.mask_user_path(r"C:\Users\ochi\Documents\Outlook\a.pst"),
                         r"C:\Users\<USER>\Documents\Outlook\a.pst")

    def test_forward_slash_and_unix(self):
        self.assertEqual(T.mask_user_path("C:/Users/Taro Yamada/x.pst"), "C:/Users/<USER>/x.pst")
        self.assertEqual(T.mask_user_path("/home/bob/x.pst"), "/home/<USER>/x.pst")

    def test_onedrive_org(self):
        out = T.mask_user_path(r"C:\Users\u1\OneDrive - ACME Corp\Docs\a.pst")
        self.assertNotIn("u1", out)
        self.assertNotIn("ACME", out)
        self.assertIn("<ORG>", out)

    def test_extra_names_whole_segment_only(self):
        out = T.mask_user_path(r"D:\mail\ochi\a.pst", ["ochi"])
        self.assertEqual(out, r"D:\mail\<USER>\a.pst")
        self.assertEqual(T.mask_user_path(r"D:\mail\ochiai\a.pst", ["ochi"]), r"D:\mail\ochiai\a.pst")

    def test_email_masked(self):
        self.assertEqual(T.mask_emails("ochi@example.co.jp - Online Archive"), "<MAIL> - Online Archive")
        self.assertNotIn("@", T.mask_user_path(r"C:\x\a@b.com.pst"))

    def test_empty(self):
        self.assertEqual(T.mask_user_path(""), "")
        self.assertEqual(T.mask_user_path(None), "")


class TestStoreJudgement(unittest.TestCase):
    def test_archive_by_type(self):
        self.assertTrue(T.is_archive_store(False, 3, "foo"))

    def test_archive_by_name(self):
        self.assertTrue(T.is_archive_store(False, 0, "オンライン アーカイブ - ochi"))
        self.assertTrue(T.is_archive_store(False, None, "Online Archive - x"))
        self.assertTrue(T.is_archive_store(False, None, "In-Place Archive - x"))

    def test_default_never_archive(self):
        self.assertFalse(T.is_archive_store(True, 3, "オンライン アーカイブ"))

    def test_not_archive(self):
        self.assertFalse(T.is_archive_store(False, 0, "メールボックス"))
        self.assertFalse(T.is_archive_store(False, "abc", "PST 2023"))

    def test_labels(self):
        self.assertEqual(T.store_kind_label(False, 3, "x", ""), "アーカイブ要確認")
        self.assertEqual(T.store_kind_label(False, 3, "Online Archive - x", ""), "アーカイブ")
        self.assertEqual(T.store_kind_label(False, 2, "2023_Q3", r"C:\a\x.pst"), "PST")
        self.assertEqual(T.store_kind_label(True, 0, "me", r"C:\a\x.ost"), "現行(既定)")
        self.assertEqual(T.store_kind_label(False, 0, "other", ""), "その他")

    def test_folder_classification(self):
        self.assertEqual(T.classify_folder_name("削除済みアイテム"), "削除済み")
        self.assertEqual(T.classify_folder_name("Junk Email"), "迷惑メール")
        self.assertEqual(T.classify_folder_name("迷惑メール"), "迷惑メール")
        self.assertIsNotNone(T.classify_folder_name("検索フォルダー"))
        self.assertIsNone(T.classify_folder_name("受信トレイ"))
        self.assertIsNone(T.classify_folder_name(""))


class TestWarnings(unittest.TestCase):
    MONTHS = T.month_range((2025, 1), (2025, 6))

    def test_leading_zero(self):
        self.assertEqual(T.leading_zero_months([0, 0, 3, 0]), 2)
        self.assertEqual(T.leading_zero_months([1, 0]), 0)
        self.assertEqual(T.leading_zero_months([0, 0]), 2)
        self.assertEqual(T.leading_zero_months([]), 0)

    def test_no_warning(self):
        self.assertIsNone(T.build_zero_warning("S", self.MONTHS, [5, 4, 3, 2, 1, 0]))

    def test_old_months_zero(self):
        w = T.build_zero_warning("S", self.MONTHS, [0, 0, 0, 2, 3, 4])
        self.assertIn("キャッシュ期間外・保持ポリシーの可能性", w)
        self.assertIn("2025-01", w)
        self.assertIn("2025-03", w)
        self.assertIn("3か月", w)
        self.assertIn("2025-04", w)

    def test_all_zero(self):
        w = T.build_zero_warning("S", self.MONTHS, [0] * 6)
        self.assertIn("全期間", w)
        self.assertIn("2025-06", w)

    def test_mismatch_length(self):
        self.assertIsNone(T.build_zero_warning("S", self.MONTHS, [0, 0]))


class TestDecisions(unittest.TestCase):
    def _res(self, **kw):
        base = {n: (10, 5) for n, _ in T.DATE_FORMATS}
        base.update(kw)
        return list(base.items())

    def test_compare_all_agree(self):
        r = T.compare_date_formats(self._res())
        self.assertEqual(r["adopted"], "ISO_24h")
        self.assertFalse(r["review"])
        self.assertEqual(r["statuses"]["US_24h"], "一致")
        self.assertEqual(r["statuses"]["ISO_24h"], "基準")

    def test_compare_difference_needs_review_and_not_adopted(self):
        r = T.compare_date_formats(self._res(DMY_24h=(8, 2)))
        self.assertEqual(r["adopted"], "ISO_24h")
        self.assertTrue(r["review"])
        self.assertIn("要確認", r["statuses"]["DMY_24h"])
        self.assertTrue(any("ロケール依存" in n and "DMY_24h" in n for n in r["notes"]))

    def test_compare_correlated_formats_do_not_outvote_base(self):
        # US系3書式が同じ値で多数派でも、ISO基準と違えば採用せず要確認にする(多数決をしない)
        r = T.compare_date_formats(self._res(ISO_24h=(10, 5), US_24h=(7, 3), US_12h=(7, 3), US_date=(7, 3),
                                              DMY_24h=None, YMD_slash_24h=(10, 5)))
        self.assertEqual(r["adopted"], "ISO_24h")
        self.assertTrue(r["review"])
        for n in ("US_24h", "US_12h", "US_date"):
            self.assertIn("要確認", r["statuses"][n])

    def test_compare_base_alone_matches_nobody(self):
        r = T.compare_date_formats(self._res(ISO_24h=(10, 5), YMD_slash_24h=(9, 4), US_24h=(7, 3),
                                              US_12h=(7, 3), US_date=(7, 3), DMY_24h=(1, 1)))
        self.assertTrue(r["review"])
        self.assertTrue(any("一致する書式が他にありません" in n for n in r["notes"]))

    def test_compare_fallback_to_ymd_slash(self):
        r = T.compare_date_formats(self._res(ISO_24h=None))
        self.assertEqual(r["adopted"], "YMD_slash_24h")

    def test_compare_all_zero_is_not_confirmed(self):
        zero = {n: (0, 0) for n, _ in T.DATE_FORMATS}
        r = T.compare_date_formats(list(zero.items()))
        self.assertTrue(r["review"])
        self.assertTrue(any("判別できません" in n for n in r["notes"]))
        self.assertFalse(any("全窓で一致" in n for n in r["notes"]))

    def test_compare_only_ymd_slash_zero_match(self):
        res = self._res(**{n: None for n, _ in T.DATE_FORMATS if n not in ("ISO_24h", "YMD_slash_24h")})
        res = [(n, (0, 0) if n in ("ISO_24h", "YMD_slash_24h") else v) for n, v in res]
        r = T.compare_date_formats(res)
        self.assertTrue(r["review"])
        self.assertTrue(any("判別できません" in n for n in r["notes"]))

    def test_compare_no_base(self):
        r = T.compare_date_formats(self._res(ISO_24h=None, YMD_slash_24h=None))
        self.assertIsNone(r["adopted"])
        self.assertTrue(r["review"])

    def test_probe_windows_include_day13_plus(self):
        months = T.month_range((2023, 10), (2026, 9))
        wins = T.build_probe_windows(months)
        self.assertEqual(wins[0][1], datetime(2023, 10, 1))
        self.assertEqual(wins[0][2], datetime(2026, 10, 1))
        self.assertGreaterEqual(len(wins), 4)
        for _l, s, e in wins[1:]:
            self.assertEqual((s.day, e.day), (13, 28))
            self.assertEqual((s.year, s.month), (e.year, e.month))
        self.assertEqual(len(T.build_probe_windows([(2025, 5)])), 2)

    def test_latest_nonzero_and_select(self):
        self.assertEqual(T.latest_nonzero_index([1, 0, 3, 0, 0]), 2)
        self.assertIsNone(T.latest_nonzero_index([0, 0]))
        self.assertEqual(T.select_test_folders([("a", 5), ("b", 0), ("c", 9), ("d", 1)], 2), ["c", "a"])
        self.assertEqual(T.select_test_folders([("a", 0)], 3), [])

    def test_archive_verdict(self):
        self.assertTrue(T.archive_verdict(False, 3, "x").startswith("要確認"))
        self.assertIn("表示名のみ", T.archive_verdict(False, 0, "Online Archive - a"))
        self.assertIn("とも一致", T.archive_verdict(False, 3, "Online Archive - a"))
        self.assertEqual(T.archive_verdict(False, 0, "mailbox"), "")
        self.assertEqual(T.archive_verdict(True, 3, "Online Archive"), "")

    def test_name_masker_and_display_mask(self):
        m = T.NameMasker(True, "Folder")
        self.assertEqual(m.mask("A"), "Folder-001")
        self.assertEqual(m.mask("B"), "Folder-002")
        self.assertEqual(m.mask("A"), "Folder-001")
        self.assertEqual(T.NameMasker(False, "Folder").mask("A"), "A")
        self.assertEqual(T.mask_display_name("ochi - taro@x.com", ["ochi"]), "<USER> - <MAIL>")

    def test_resolve_output_path(self):
        p = T.resolve_output_path("", datetime(2026, 10, 8, 1, 2, 3))
        self.assertTrue(p.replace("\\", "/").endswith("outlook_total_organizer/mail_reports/diagnose_mail_inventory_20261008_010203.txt"))
        self.assertEqual(T.resolve_output_path("/x/y.txt"), "/x/y.txt")

    def test_judge_match(self):
        v, d = T.judge_index_result({"count": 5, "error": None}, {"count": 5, "error": None},
                                    {"count": 99, "error": None})
        self.assertEqual(v, "一致")
        self.assertIn("5", d)

    def test_judge_mismatch(self):
        v, _ = T.judge_index_result({"count": 5, "error": None}, {"count": 3, "error": None})
        self.assertEqual(v, "不一致")

    def test_judge_error(self):
        v, d = T.judge_index_result({"count": 5, "error": None}, {"count": None, "error": "com_error(0x80040201)"})
        self.assertEqual(v, "エラー")
        self.assertIn("ci_phrasematch", d)

    def test_judge_baseline_error(self):
        v, d = T.judge_index_result({"count": 1, "error": None}, {"count": 1, "error": None},
                                    {"count": None, "error": "com_error"})
        self.assertEqual(v, "エラー")
        self.assertIn("DASL日付", d)


class TestErrorKind(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(T.error_kind(ValueError("件名: 極秘 見積")), "ValueError")

    def test_hresult_without_message(self):
        class com_error(Exception):
            pass
        e = com_error(-2147352567, "件名を含む説明", None, None)
        k = T.error_kind(e)
        self.assertEqual(k, "com_error(0x80020009)")
        self.assertNotIn("件名", k)


class TestFormatting(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(T.format_duration(0.1234), "0.123秒")
        self.assertEqual(T.format_duration(12.34), "12.3秒")
        self.assertEqual(T.format_duration(185), "3分05秒")
        self.assertEqual(T.format_duration(None), "-")

    def test_month_table(self):
        months = [(2025, 1), (2025, 2)]
        txt = T.format_month_table(months, [10, 0], [12, 1])
        self.assertIn("2025-01", txt)
        self.assertIn("+2", txt)
        self.assertIn("+1", txt)
        self.assertIn("合計", txt)
        self.assertEqual(len(txt.splitlines()), 4)

    def test_folder_line(self):
        months = [(2025, 1), (2025, 2), (2025, 3)]
        line = T.format_folder_line(r"\受信トレイ", 50, months, [0, 7, 0])
        self.assertIn("2025-02=7", line)
        self.assertNotIn("2025-01=", line)
        self.assertIn("0件月=2", line)
        self.assertIn("期間内0件", T.format_folder_line("x", 0, months, [0, 0, 0]))

    def test_output_name(self):
        self.assertEqual(T.default_output_name(datetime(2026, 10, 8, 9, 5, 3)),
                         "diagnose_mail_inventory_20261008_090503.txt")

    def test_summarize_errors(self):
        out = T.summarize_errors([("a", "X"), ("b", "Y"), ("c", "X")])
        self.assertEqual(out, ["X: 2件", "Y: 1件"])


class TestReadOnlyAndNoCom(unittest.TestCase):
    """読み取り専用・COM遅延importの静的ガード。"""

    @classmethod
    def setUpClass(cls):
        with open(T.__file__, encoding="utf-8") as f:
            cls.src = f.read()

    def test_no_top_level_com_import(self):
        for line in self.src.splitlines():
            if line.startswith("import win32com") or line.startswith("import pythoncom") \
                    or line.startswith("from win32com"):
                self.fail(f"トップレベルでCOMをimportしている: {line}")

    def test_no_mutating_calls(self):
        for banned in (".Delete(", ".Move(", ".Save(", ".AddStore", ".RemoveStore", ".MarkAsRead",
                       ".Copy(", ".UnRead =", ".UnRead=", ".Send("):
            self.assertNotIn(banned, self.src, f"書き込み系の呼び出しが含まれる: {banned}")

    def test_no_content_output(self):
        for banned in ("SenderEmailAddress", "SenderName", ".Body", ".HTMLBody", ".To ", ".Recipients"):
            self.assertNotIn(banned, self.src, f"出力禁止の項目に触れている: {banned}")


# ============================================================
# COM部分のフェイク（Outlook無しで run_inventory を通す）
# ============================================================
SECRET_SUBJECT = "SECRET-SUBJECT-XYZ"
SECRET_ERRMSG = "SECRET-ERRMSG-QRS"
SECRET_ADDR = "secret.person@example.com"
_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M")


class FakeComError(Exception):
    pass


def _parse_dates(flt):
    """フィルタ中の 'xxx' をすべて datetime にする（未対応書式は FakeComError）。"""
    out = []
    for lit in re.findall(r"'([^']*)'", flt):
        if "%" in lit:
            continue
        for f in _DT_FORMATS:
            try:
                out.append(datetime.strptime(lit, f))
                break
            except ValueError:
                continue
        else:
            if re.fullmatch(r"[\d/: -]+", lit):
                raise FakeComError(-2147352567, SECRET_ERRMSG, None, None)
    return out


class FakeItem:
    @property
    def Subject(self):
        return SECRET_SUBJECT


class FakeTable:
    def __init__(self, n):
        self.n = n
        self.pos = 0
        self.Columns = self

    def RemoveAll(self):
        pass

    def Add(self, name):
        pass

    @property
    def EndOfTable(self):
        return self.pos >= self.n

    def GetNextRow(self):
        self.pos += 1
        return self

    def Item(self, i):
        return SECRET_SUBJECT


class FakeRestricted:
    def __init__(self, n):
        self.Count = n
        self._i = 0

    def GetFirst(self):
        self._i = 0
        return self.GetNext()

    def GetNext(self):
        if self._i >= self.Count:
            return None
        self._i += 1
        return FakeItem()


class FakeItems:
    def __init__(self, folder):
        self.f = folder

    @property
    def Count(self):
        return len(self.f.dates)

    def Restrict(self, flt):
        self.f.restrict_calls += 1
        if self.f.interrupt_on and self.f.restrict_calls >= self.f.interrupt_on:
            raise KeyboardInterrupt()
        if self.f.fail:
            raise FakeComError(-2147221233, SECRET_ERRMSG, None, None)
        if "ci_phrasematch" in flt:
            raise FakeComError(-2147352567, SECRET_ERRMSG, None, None)
        d = _parse_dates(flt)
        if len(d) != 2:
            raise FakeComError(-1, SECRET_ERRMSG, None, None)
        return FakeRestricted(sum(1 for x in self.f.dates if d[0] <= x < d[1]))


class FakeFolder:
    def __init__(self, name, dates=(), item_type=0, children=(), fail=False, interrupt_on=0):
        self.Name = name
        self.dates = list(dates)
        self.DefaultItemType = item_type
        self._children = list(children)
        self.fail = fail
        self.interrupt_on = interrupt_on
        self.restrict_calls = 0
        self.Folders = self

    @property
    def Count(self):
        return len(self._children)

    def Item(self, i):
        return self._children[i - 1]

    @property
    def Items(self):
        return FakeItems(self)

    def GetTable(self, flt):
        return FakeTable(len([1 for x in self.dates]))


class FakeStore:
    def __init__(self, name, root, sid, exch=0, path=""):
        self.DisplayName = name
        self.StoreID = sid
        self.ExchangeStoreType = exch
        self.FilePath = path
        self._root = root

    def GetRootFolder(self):
        return self._root


class FakeNamespace:
    def __init__(self, stores):
        self._stores = stores
        self.Stores = self

    @property
    def Count(self):
        return len(self._stores)

    def Item(self, i):
        return self._stores[i - 1]

    def GetDefaultFolder(self, n):
        class _F:
            pass
        f = _F()
        f.Store = self._stores[0]
        return f


def make_com(stores):
    ns = FakeNamespace(stores)

    class _Outlook:
        def GetNamespace(self, _n):
            return ns

    class _Client:
        @staticmethod
        def Dispatch(_n):
            return _Outlook()

    class _Py:
        inits = 0
        uninits = 0

        @classmethod
        def CoInitialize(cls):
            cls.inits += 1

        @classmethod
        def CoUninitialize(cls):
            cls.uninits += 1

    return (_Client, _Py)


def dts(y, m, days):
    return [datetime(y, m, d, 10, 0) for d in days]


def run_fake(stores, extra_args=(), tmp=None):
    tmp = tmp or tempfile.mkdtemp(prefix="t0_")
    out = os.path.join(tmp, "out.txt")
    args = T.parse_args(["--from", "2026-01", "--to", "2026-09", "--output", out, *extra_args])
    rep = T.Reporter(out)
    buf = io.StringIO()
    com = make_com(stores)
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            code = T.run_inventory(args, rep, com=com)
        finally:
            rep.close()
    with open(out, encoding="utf-8-sig") as f:
        text = f.read()
    return code, buf.getvalue(), text, com[1]


class TestFakeCom(unittest.TestCase):
    def _basic_stores(self):
        inbox = FakeFolder("受信トレイ", dts(2026, 9, [1, 5, 14, 20]) + dts(2026, 3, [2, 15, 31]))
        sub = FakeFolder("プロジェクト", dts(2026, 8, [13, 14]))
        cal = FakeFolder("予定表", dts(2026, 9, [1]), item_type=1)
        deleted = FakeFolder("削除済みアイテム", dts(2026, 9, [3]))
        root = FakeFolder("root", children=[inbox, FakeFolder("親", children=[sub]), cal, deleted])
        return [FakeStore(f"{SECRET_ADDR}", root, "S1"), ]

    def test_no_secret_in_output_and_readonly(self):
        stores = self._basic_stores()
        code, console, text, py = run_fake(stores, ["--probe-word", "invoice"])
        self.assertEqual(code, 0)
        for secret in (SECRET_SUBJECT, SECRET_ERRMSG, SECRET_ADDR):
            self.assertNotIn(secret, console)
            self.assertNotIn(secret, text)
        self.assertIn("<MAIL>", text)
        self.assertEqual(console.count("\n") >= text.count("\n") - 1, True)
        self.assertEqual((py.inits, py.uninits), (1, 1))

    def test_counts_and_exclusion(self):
        code, _c, text, _p = run_fake(self._basic_stores())
        self.assertIn("2026-09", text)
        self.assertIn("除外候補: 削除済み", text)
        self.assertNotIn("予定表", text)   # 予定表(DefaultItemType!=0)は列挙されない
        self.assertIn("採用書式: ISO_24h", text)
        self.assertIn("ストア別 月別件数", text)
        self.assertIn("ExchangeStoreType(実機の生の値)=0", text)

    def test_folder_exception_continues(self):
        bad = FakeFolder("壊れ", dts(2026, 9, [1, 2]), fail=True)
        good = FakeFolder("正常", dts(2026, 9, [1, 2, 3]))
        root = FakeFolder("root", children=[bad, good])
        code, _c, text, _p = run_fake([FakeStore("S", root, "S1")])
        self.assertEqual(code, 0)
        self.assertIn("正常", text)
        self.assertIn("FakeComError", text)
        self.assertNotIn(SECRET_ERRMSG, text)
        self.assertIn("✅ 診断完了", text)

    def test_keyboard_interrupt_saves_partial(self):
        f1 = FakeFolder("一番目", dts(2026, 9, [1, 2, 3]))
        # 日付書式の試験(約25回)を過ぎてから月別件数の途中で中断させる
        f2 = FakeFolder("二番目", dts(2026, 8, [1, 2]) + dts(2026, 9, [1]), interrupt_on=30)
        root = FakeFolder("root", children=[f1, f2])
        code, console, text, _p = run_fake([FakeStore("S", root, "S1")])
        self.assertEqual(code, 0)
        self.assertIn("Ctrl+C", text)
        self.assertIn("ストア別 月別件数（途中まで）", text)
        self.assertIn("診断は途中までです", text)
        self.assertIn("Ctrl+C", console)

    def test_test_selection_is_per_store(self):
        a = FakeStore("Aストア", FakeFolder("r", children=[
            FakeFolder("a1", dts(2026, 9, [1, 2, 3])), FakeFolder("a2", dts(2026, 9, [1])),
            FakeFolder("a3", dts(2026, 9, [4, 5]))]), "A")
        b = FakeStore("Bストア", FakeFolder("r", children=[FakeFolder("b1", dts(2026, 5, [1, 2]))]), "B")
        c = FakeStore("Cストア", FakeFolder("r", children=[FakeFolder("c1", [])]), "C")
        code, _c, text, _p = run_fake([a, b, c], ["--max-test-folders", "2"])
        self.assertIn("試験月 2026-09 / 対象 2フォルダ", text)       # A: 上位2のみ
        self.assertIn("試験月 2026-05 / 対象 1フォルダ", text)       # B: 自分の最新月
        self.assertRegex(text, r"試験対象なし: Cストア")            # C: 総括に明示
        self.assertIn("試験対象: Aストア: 試験月 2026-09 / 2フォルダ", text)

    def test_probe_folders_skip_zero_range_folders(self):
        # 総件数は多いが期間外(2020年)だけのフォルダは、書式の試験フォルダに選ばれない
        old = FakeFolder("古いだけ", [datetime(2020, 1, 5, 9, 0)] * 50)
        cur = FakeFolder("現役", dts(2026, 9, [14, 15]))
        root = FakeFolder("root", children=[old, cur])
        code, _c, text, _p = run_fake([FakeStore("S", root, "S1")])
        self.assertIn("試験フォルダ 1個", text)
        self.assertNotIn("判別できません", text)

    def test_all_zero_range_flags_review(self):
        old = FakeFolder("古いだけ", [datetime(2020, 1, 5, 9, 0)] * 5)
        code, _c, text, _p = run_fake([FakeStore("S", FakeFolder("root", children=[old]), "S1")])
        self.assertIn("判別できません", text)
        self.assertIn("日付書式は要確認", text)

    def test_incomplete_folder_excluded_from_sum(self):
        # 月別の途中でエラーになるフォルダ: 全期間は数えられるが、月別の途中(2回目以降)で失敗する
        class Flaky(FakeFolder):
            pass
        flaky = Flaky("途中で壊れる", dts(2026, 9, [1, 2, 3]))
        orig = FakeItems.Restrict
        good = FakeFolder("正常", dts(2026, 9, [1]))
        root = FakeFolder("root", children=[flaky, good])
        calls = {"n": 0}

        def patched(self, flt):
            if self.f is flaky:
                calls["n"] += 1
                if calls["n"] > 30:     # 書式試験・全期間の後、月別の途中から失敗
                    raise FakeComError(-2147221233, SECRET_ERRMSG, None, None)
            return orig(self, flt)
        FakeItems.Restrict = patched
        try:
            code, _c, text, _p = run_fake([FakeStore("S", root, "S1")])
        finally:
            FakeItems.Restrict = orig
        self.assertIn("不完全フォルダ 1個", text)
        self.assertNotIn(SECRET_ERRMSG, text)

    def test_com_refs_released(self):
        stores = [FakeStore("S", FakeFolder("root", children=[FakeFolder("a", dts(2026, 9, [1]))]), "S1")]
        holder = {}
        orig = T._inventory_core

        def spy(args, rep, client, st):
            holder["stores"] = st
            return orig(args, rep, client, st)
        T._inventory_core = spy
        try:
            code, _c, _t, py = run_fake(stores)
        finally:
            T._inventory_core = orig
        self.assertEqual(holder["stores"], [])          # 全ストア記録が解放済み
        self.assertEqual((py.inits, py.uninits), (1, 1))

    def test_root_direct_mail_is_counted(self):
        root = FakeFolder("root", dts(2026, 9, [14, 15, 16]), children=[])
        root.Folders = root
        code, _c, text, _p = run_fake([FakeStore("PST2024", root, "P1", exch=0, path="C:\\x\\a.pst")])
        self.assertEqual(code, 0)
        self.assertIn("(ルート直下)  [3件]", text)
        self.assertRegex(text, r"\\\(ルート直下\) \| 総3件 \| 月別: 2026-09=3")
        self.assertNotIn(SECRET_SUBJECT, text)

    def test_root_zero_not_listed(self):
        root = FakeFolder("root", [], children=[FakeFolder("受信トレイ", dts(2026, 9, [1]))])
        code, _c, text, _p = run_fake([FakeStore("現行", root, "S1")])
        self.assertEqual(code, 0)
        self.assertNotIn("(ルート直下)  [", text)
        self.assertIn("メールフォルダ 1個", text)

    def test_root_items_exception_continues(self):
        class BadRoot(FakeFolder):
            @property
            def Items(self):
                raise FakeComError(-1, SECRET_ERRMSG, None, None)
        root = BadRoot("root", children=[FakeFolder("受信トレイ", dts(2026, 9, [1]))])
        code, _c, text, _p = run_fake([FakeStore("S", root, "S1")])
        self.assertEqual(code, 0)
        self.assertIn("受信トレイ", text)
        self.assertNotIn(SECRET_ERRMSG, text)

    def test_root_label_masked_with_mask_names(self):
        root = FakeFolder("root", dts(2026, 9, [14]), children=[])
        root.Folders = root
        code, _c, text, _p = run_fake([FakeStore("S", root, "S1")], ["--mask-names"])
        self.assertNotIn("ルート直下)  [", text)
        self.assertIn("Folder-001", text)

    def test_mask_names(self):
        code, _c, text, _p = run_fake(self._basic_stores(), ["--mask-names"])
        self.assertNotIn("受信トレイ", text)
        self.assertNotIn("プロジェクト", text)
        self.assertIn("Folder-001", text)
        self.assertIn("Store-01", text)

    def test_output_fallback_to_temp(self):
        bad = os.path.join(tempfile.mkdtemp(prefix="t0_"), "file_as_dir.txt")
        with open(bad, "w") as f:
            f.write("x")
        out = os.path.join(bad, "sub", "o.txt")   # ファイルの下にフォルダは作れない
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rep = T.Reporter(out)
            rep.log("hello")
            rep.close()
        self.assertTrue(rep.fallback_path)
        self.assertTrue(rep.fallback_path.startswith(tempfile.gettempdir()))
        with open(rep.fallback_path, encoding="utf-8-sig") as f:
            self.assertIn("hello", f.read())
        self.assertIn(os.path.basename(rep.fallback_path), buf.getvalue())
        os.remove(rep.fallback_path)

    def test_incremental_flush(self):
        tmp = tempfile.mkdtemp(prefix="t0_")
        out = os.path.join(tmp, "o.txt")
        rep = T.Reporter(out)
        with contextlib.redirect_stdout(io.StringIO()):
            rep.log("line1")
        with open(out, encoding="utf-8-sig") as f:      # close前でも読める
            self.assertIn("line1", f.read())
        rep.close()


if __name__ == "__main__":
    unittest.main()
