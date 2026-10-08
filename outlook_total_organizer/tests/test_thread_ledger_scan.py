# -*- coding: utf-8 -*-
"""過去スレッド台帳 S1 (tools/thread_ledger_scan_*.py) のテスト。

app/ のモジュールではないので importlib で tools/ から読み込む。
純粋関数（正規化・照合・重複除去・スレッド化・候補判定・スコア・CSV・判定保持・再現率チェック・候補語）と、
COM部分（フェイクを注入）を確認する。ダミーデータの氏名・アドレス・番号はすべて架空。
"""
import contextlib
import csv
import glob
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.dont_write_bytecode = True

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(os.path.dirname(TESTS_DIR), "tools")


def _load_tool():
    paths = sorted(glob.glob(os.path.join(TOOLS_DIR, "thread_ledger_scan_*.py")))
    if not paths:
        raise FileNotFoundError("tools/thread_ledger_scan_*.py がありません")
    spec = importlib.util.spec_from_file_location("thread_ledger_scan_under_test", paths[-1])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


T = _load_tool()


def _rd(path, enc="utf-8"):
    with open(path, "r", encoding=enc) as fh:
        return fh.read()


def _rb(path):
    with open(path, "rb") as fh:
        return fh.read()


def _wr(path, text, enc="utf-8"):
    with open(path, "w", encoding=enc) as fh:
        fh.write(text)


def _rj(path):
    return json.loads(_rd(path))


def _wj(path, obj):
    _wr(path, json.dumps(obj, ensure_ascii=False))


def _rcsv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def _rdict(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))
SECRET = "SECRET-SUBJECT-ZZ9"
SECRET_ERR = "SECRET-ERR-MESSAGE-QQ7"


# ============================================================
# テーマ・データ作成ヘルパ
# ============================================================
def make_theme(**over):
    data = {
        "theme_version": "t1",
        "owner": {"name_aliases": ["Owner Taro"], "emails": ["owner@example.com"]},
        "anchors": [
            {"label": "PM", "name_aliases": ["Sato Pm", "佐藤"], "emails": ["pm@example.com"]},
            {"label": "Admin", "name_aliases": ["Suzuki Admin", "鈴木"], "emails": []},
        ],
        "related_parties": [
            {"label": "Sachi", "kind": "person", "name_aliases": ["Tanaka Partner"], "emails": [], "domains": []},
            {"label": "Courier", "kind": "org", "name_aliases": [], "emails": [], "domains": ["courier.example.com"]},
        ],
        "keywords": {
            "通関": {"weight": 3, "strong": ["通関", "customs clearance", "HS code"], "weak": ["hold", "保留"]},
            "トラブル語": {"weight": 2, "strong": [], "weak": ["delay", "urgent", "approval request"]},
        },
        "patterns": [
            {"category": "物流", "regex": r"#\s?\d{10}", "strong": True},
            {"category": "関税", "regex": r"\b\d{4}\.\d{2}\b", "strong": False},
        ],
        "score_weights": {"subject_multiplier": 2, "weak_multiplier": 0.5, "anchor_each": 3, "related_each": 2,
                          "reply_every": 5, "reply_points": 1, "reply_cap": 5},
        "period": {"from": "2024-01", "to": "2024-12"},
    }
    data.update(over)
    return T.normalize_theme(data, "unit")


def rec(eid, subj, t, sender="", to="", cc="", cid="", addr=""):
    return {"e": eid, "s": subj, "t": t, "n": sender, "a": addr, "to": to, "cc": cc, "c": cid}


def cache(store, sidx, folder, records, sid=None, scanned_at="2024-12-31T00:00:00"):
    return {"schema": 1, "store_index": sidx, "store_name": store, "store_id": sid or f"SID{sidx}",
            "folder_path": folder, "range": ["2024-01", "2024-12"], "complete": True, "records": records,
            "scanned_at": scanned_at, "counts": {"mail": len(records), "non_mail": 0, "errors": {}}}


def build(caches, theme=None, stage2=None, from_ym=(2024, 1), to_ym=(2024, 12)):
    theme = theme or make_theme()
    return T.evaluate_all(caches, theme, stage2 or {}, from_ym, to_ym), theme


def ev_of(res, i=0):
    return res["evals"][i]


def one_thread(records, theme=None, stage2=None):
    res, th = build([cache("S", 1, "\\Inbox", records)], theme, stage2)
    assert len(res["evals"]) == 1, len(res["evals"])
    return res, ev_of(res)


# ============================================================
# 期間・Restrict
# ============================================================
class TestPeriod(unittest.TestCase):
    def test_parse_ym(self):
        self.assertEqual(T.parse_ym("2023-07"), (2023, 7))
        self.assertEqual(T.parse_ym(" 2026/9 "), (2026, 9))
        for bad in ("2023", "2023-13", "2023-00", "x", None, ""):
            with self.assertRaises(ValueError):
                T.parse_ym(bad)

    def test_month_range_boundaries(self):
        self.assertEqual(len(T.month_range((2023, 7), (2026, 9))), 39)
        self.assertEqual(T.month_range((2024, 12), (2025, 1)), [(2024, 12), (2025, 1)])
        with self.assertRaises(ValueError):
            T.month_range((2025, 2), (2025, 1))

    def test_period_bounds_and_iso_filter(self):
        s, e = T.period_bounds((2023, 7), (2026, 9))
        self.assertEqual(s, datetime(2023, 7, 1))
        self.assertEqual(e, datetime(2026, 10, 1))
        self.assertEqual(T.period_bounds((2025, 12), (2025, 12))[1], datetime(2026, 1, 1))
        self.assertEqual(T.build_restrict_filter("ReceivedTime", s, e),
                         "[ReceivedTime] >= '2023-07-01 00:00' AND [ReceivedTime] < '2026-10-01 00:00'")

    def test_to_naive_dt(self):
        self.assertEqual(T.to_naive_dt(datetime(2024, 1, 2, 3, 4, 5)), datetime(2024, 1, 2, 3, 4, 5))
        self.assertIsNone(T.to_naive_dt(datetime(4501, 1, 1)))   # Outlookの「未設定」
        self.assertIsNone(T.to_naive_dt(None))
        self.assertIsNone(T.to_naive_dt(12345))


# ============================================================
# 正規化
# ============================================================
class TestNormalize(unittest.TestCase):
    def test_subject_prefix_chain(self):
        self.assertEqual(T.normalize_subject("RE: FW: Re: Fwd:  Hello World"), "hello world")
        self.assertEqual(T.normalize_subject("** internal only ** RE: FW: x"), "x")
        self.assertEqual(T.normalize_subject("FW: ** Internal Only ** Re: x"), "x")
        self.assertEqual(T.normalize_subject("AW: WG: 転送: 返信: [外部] x"), "x")
        self.assertEqual(T.normalize_subject("ＲＥ：　Ｈｅｌｌｏ　　Ｗｏｒｌｄ"), "hello world")

    def test_subject_keeps_bracket_tags_and_empty(self):
        self.assertEqual(T.normalize_subject("RE: [Export request]2024-01-01 10:00"), "[export request]2024-01-01 10:00")
        self.assertEqual(T.normalize_subject(""), "")
        self.assertEqual(T.normalize_subject(None), "")
        self.assertEqual(T.normalize_subject("RE: "), "")

    def test_subject_does_not_strip_inner_re(self):
        self.assertEqual(T.normalize_subject("Report re: status"), "report re: status")

    def test_name_matches_order_case_width(self):
        self.assertTrue(T.name_matches("Taro Sato", "SATO, Taro"))
        self.assertTrue(T.name_matches("Taro Sato", "ｔａｒｏ　ｓａｔｏ"))
        self.assertTrue(T.name_matches("Sato Taro", "Taro Sato (Dept)"))
        self.assertTrue(T.name_matches("Sato", "Sato, Hana"))
        self.assertTrue(T.name_matches("Sato", "Sato-san"))
        self.assertTrue(T.name_matches("Sato", "Mr. Sato"))
        self.assertTrue(T.name_matches("佐藤", "佐藤 太郎"))
        self.assertTrue(T.name_matches("佐藤", "太郎 佐藤さん"))
        self.assertTrue(T.name_matches("佐藤さん", "佐藤 美穂"))
        self.assertTrue(T.name_matches("佐藤", "Sato, 佐藤"))
        self.assertTrue(T.name_matches("太郎 佐藤", "佐藤, 太郎"))
        self.assertTrue(T.name_matches("佐藤太郎", "佐藤 太郎"))      # 連結が一致
        self.assertTrue(T.name_matches("佐藤 太郎", "佐藤太郎"))

    def test_name_matches_ascii_always_requires_word_end(self):
        self.assertFalse(T.name_matches("Jay", "Jaycee Smith"))
        self.assertTrue(T.name_matches("Jay", "Jay Smith"))
        self.assertFalse(T.name_matches("Chris", "Michristo"))                # 語頭境界
        self.assertFalse(T.name_matches("Chris", "Christopher Lee"))          # 4文字以上でも語末境界
        self.assertFalse(T.name_matches("Ono", "Onozuka Hana"))
        self.assertFalse(T.name_matches("Yuki", "Yukiko Tanaka"))
        self.assertFalse(T.name_matches("Sato", "Satomura Ken"))
        self.assertTrue(T.name_matches("Ono", "Ono Hana"))
        self.assertTrue(T.name_matches("Yuki", "Tanaka, Yuki"))
        self.assertFalse(T.name_matches("Taro Sato", "Taro Satomura"))

    def test_name_matches_japanese_surname_only_alias(self):
        # 姓だけの別名は、スペースの有無にかかわらずフルネームに一致する（表示名が全て非ASCIIで、残りが0〜4文字）
        self.assertTrue(T.name_matches("越智", "越智太郎"))
        self.assertTrue(T.name_matches("越智", "越智 太郎"))
        self.assertTrue(T.name_matches("木村", "木村美穂"))
        self.assertTrue(T.name_matches("木村", "木村 美穂"))
        self.assertTrue(T.name_matches("木村さん", "木村美穂"))
        self.assertTrue(T.name_matches("木村さん", "木村さん"))
        self.assertTrue(T.name_matches("田中", "田中 花子"))
        self.assertTrue(T.name_matches("田中さん", "田中"))
        self.assertTrue(T.name_matches("田中", "Tanaka, 田中さん"))

    def test_name_matches_japanese_other_surnames_do_not_match(self):
        self.assertFalse(T.name_matches("田中", "山田中"))          # 別名で始まらない
        self.assertFalse(T.name_matches("木村", "山木村"))
        self.assertFalse(T.name_matches("木村", "山木村太郎"))
        self.assertFalse(T.name_matches("佐藤", "田佐藤"))
        self.assertFalse(T.name_matches("木村", "木村ふじさわたろう"))   # 残りが5文字以上は姓+名とみなさない
        self.assertFalse(T.name_matches("木村", "木村Miho"))            # 非ASCIIだけの表示名に限る
        self.assertFalse(T.name_matches("田", "田中"))                  # 1文字の別名は完全トークン一致のみ

    def test_name_matches_known_risk_trailing_chars(self):
        # 既知のリスク（仕様）: 後ろに1〜4文字続く別姓は、姓+名と区別できず一致する
        self.assertTrue(T.name_matches("木村", "木村戸"))
        self.assertTrue(T.name_matches("田中", "田中村"))

    def test_name_matches_negative_basic(self):
        self.assertFalse(T.name_matches("", "Anyone"))
        self.assertFalse(T.name_matches("Taro Sato", ""))
        self.assertFalse(T.name_matches("Taro Sato", "Hanako Suzuki"))
        self.assertFalse(T.name_matches("田中", "佐藤"))

    def test_split_names_and_emails(self):
        self.assertEqual(T.split_names("A One; B Two <b@example.com>;;"), ["A One", "B Two"])
        self.assertEqual(T.split_names(""), [])
        self.assertEqual(T.extract_emails("X <A@Example.com>; y@b.co"), ["a@example.com", "y@b.co"])
        self.assertEqual(T.smtp_like("/O=EXCH/CN=ABC"), "")
        self.assertEqual(T.smtp_like("User@Example.com"), "user@example.com")
        self.assertTrue(T.domain_matches("mail.courier.example.com", "courier.example.com"))
        self.assertFalse(T.domain_matches("xcourier.example.com", "courier.example.com"))


# ============================================================
# テーマ・キーワード強弱
# ============================================================
class TestTheme(unittest.TestCase):
    def test_example_theme_loads_and_has_no_real_data(self):
        p = os.path.join(TOOLS_DIR, "thread_ledger_theme.example.json")
        th = T.load_theme(p)
        self.assertGreater(len(th["hit_table"]), 30)
        raw = _rd(p)
        import re
        for addr in re.findall(r"[\w.+-]+@[\w.-]+", raw):
            self.assertTrue(addr.endswith("example.com"), addr)

    def test_errors(self):
        with self.assertRaises(T.ThemeError):
            T.normalize_theme([], "x")
        with self.assertRaises(T.ThemeError):
            T.normalize_theme({"owner": {}, "anchors": [{"name_aliases": ["a"]}]}, "x")
        with self.assertRaises(T.ThemeError):
            T.normalize_theme({"owner": {"emails": ["a@b.c"]}, "anchors": []}, "x")
        with self.assertRaises(T.ThemeError):
            make_theme(patterns=[{"category": "c", "regex": "(", "strong": True}])
        with self.assertRaises(T.ThemeError):
            make_theme(period={"from": "bad"})
        with self.assertRaises(T.ThemeError):
            T.load_theme("/nonexistent/theme.json")

    def test_strong_wins_when_term_in_both(self):
        th = make_theme(keywords={"a": {"weight": 1, "weak": ["foo"]}, "b": {"weight": 1, "strong": ["foo"]}})
        self.assertTrue(th["hit_table"]["foo"]["strong"])

    def test_defaults_for_excludes(self):
        th = make_theme()
        self.assertIn("削除済みアイテム", th["exclude_folder_names"])
        self.assertIn("note-", th["exclude_folder_prefixes"])
        th2 = make_theme(exclude_folder_names=["X"])
        self.assertEqual(th2["exclude_folder_names"], ["X"])

    def test_dict_hash_changes_with_keywords(self):
        self.assertNotEqual(make_theme()["dict_hash"],
                            make_theme(keywords={"c": {"weight": 1, "strong": ["zzz"]}})["dict_hash"])

    def test_term_boundaries(self):
        tbl = make_theme()["hit_table"]
        self.assertIn("hold", T.scan_text_hits("please hold the shipment", tbl))
        self.assertNotIn("hold", T.scan_text_hits("the holder of the card", tbl))
        self.assertIn("delay", T.scan_text_hits("many delays happened", tbl))      # 複数形は許容
        self.assertNotIn("delay", T.scan_text_hits("delayed again", tbl))
        self.assertIn("通関", T.scan_text_hits("通関業者へ", tbl))                   # 日本語は部分一致
        self.assertIn("hs code", T.scan_text_hits("HS Code is wrong", tbl))
        self.assertEqual(T.scan_text_hits("", tbl), {})

    def test_pattern_hits(self):
        tbl = make_theme()["hit_table"]
        h = T.scan_text_hits("DHL #1234567890 ok", tbl)
        self.assertIn("pat:#\\s?\\d{10}", h)
        h2 = T.scan_text_hits("code 8541.10 listed", tbl)
        self.assertIn("pat:\\b\\d{4}\\.\\d{2}\\b", h2)
        self.assertEqual(T.scan_text_hits("#12345", tbl), {})


class TestKeywordSignal(unittest.TestCase):
    def setUp(self):
        self.tbl = make_theme()["hit_table"]

    def test_weak_one_not_enough(self):
        self.assertFalse(T.keyword_signal({"approval request"}, self.tbl)["ok"])
        self.assertFalse(T.keyword_signal({"hold"}, self.tbl)["ok"])

    def test_weak_two_distinct_enough(self):
        s = T.keyword_signal({"approval request", "hold"}, self.tbl)
        self.assertTrue(s["ok"])
        self.assertEqual(s["strong"], [])

    def test_strong_one_enough(self):
        self.assertTrue(T.keyword_signal({"通関"}, self.tbl)["ok"])

    def test_weak_pattern_counts_as_weak_and_strong_pattern_as_strong(self):
        self.assertFalse(T.keyword_signal({"pat:\\b\\d{4}\\.\\d{2}\\b"}, self.tbl)["ok"])
        self.assertTrue(T.keyword_signal({"pat:\\b\\d{4}\\.\\d{2}\\b", "hold"}, self.tbl)["ok"])
        self.assertTrue(T.keyword_signal({"pat:#\\s?\\d{10}"}, self.tbl)["ok"])

    def test_unknown_keys_ignored(self):
        self.assertFalse(T.keyword_signal({"nothing"}, self.tbl)["ok"])
        self.assertFalse(T.keyword_signal(set(), self.tbl)["ok"])


# ============================================================
# 重複除去・スレッド化
# ============================================================
class TestMergeAndThreads(unittest.TestCase):
    def test_cross_store_dedupe_records_all_sources_and_month_stats(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "RE: Topic", "2024-04-10T09:00:00", "Pm", "Owner Taro")])
        b = cache("PST", 2, "\\(ルート直下)", [rec("E9", "Topic", "2024-04-10T09:00:00", "Pm", "Owner Taro")])
        mails, st = T.merge_caches_to_mails([a, b], (2024, 1), (2024, 12))
        self.assertEqual(len(mails), 1)
        self.assertEqual(st["raw_total"], 2)
        self.assertEqual(st["unique_total"], 1)
        self.assertEqual(st["cross_store"], 1)
        self.assertEqual(st["dup_by_month"], {(2024, 4): 1})
        self.assertEqual({l["store"] for l in mails[0]["locs"]}, {"MB", "PST"})
        self.assertEqual(st["raw_by_store_month"][("MB", (2024, 4))], 1)

    def test_not_merged_when_seconds_or_sender_differ(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "Topic", "2024-04-10T09:00:00", "Pm"),
                                       rec("E2", "Topic", "2024-04-10T09:00:01", "Pm"),
                                       rec("E3", "Topic", "2024-04-10T09:00:00", "Other")])
        mails, st = T.merge_caches_to_mails([a], (2024, 1), (2024, 12))
        self.assertEqual(len(mails), 3)
        self.assertEqual(st["cross_store"], 0)

    def test_same_store_dup_counted_separately(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "Topic", "2024-04-10T09:00:00", "Pm")])
        b = cache("MB", 1, "\\Sub", [rec("E2", "Topic", "2024-04-10T09:00:00", "Pm")])
        mails, st = T.merge_caches_to_mails([a, b], (2024, 1), (2024, 12))
        self.assertEqual((len(mails), st["same_store"], st["cross_store"]), (2, 1, 0))   # 同一ストア内は別メール

    def test_period_filter_and_bad_time(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "A", "2023-12-31T23:59:59"), rec("E2", "B", "2024-01-01T00:00:00"),
                                       rec("E3", "C", "2024-12-31T23:59:59"), rec("E4", "D", "2025-01-01T00:00:00"),
                                       rec("E5", "E", "garbage")])
        mails, st = T.merge_caches_to_mails([a], (2024, 1), (2024, 12))
        self.assertEqual([m["subj"] for m in mails], ["B", "C"])
        self.assertEqual(st["no_time"], 1)

    def test_thread_by_conversation_id_then_subject(self):
        a = cache("MB", 1, "\\Inbox", [
            rec("E1", "Topic one", "2024-04-10T09:00:00", "A", cid="C1"),
            rec("E2", "Different subject", "2024-04-11T09:00:00", "B", cid="C1"),
            rec("E3", "RE: Longer shared subject", "2024-04-12T09:00:00", "A"),
            rec("E4", "FW: Longer shared subject", "2024-04-13T09:00:00", "B"),
            rec("E5", "Other", "2024-04-14T09:00:00", "A"),
        ])
        mails, _ = T.merge_caches_to_mails([a], (2024, 1), (2024, 12))
        threads = T.build_threads(mails)
        self.assertEqual(sorted(t["count"] for t in threads), [1, 2, 2])
        t1 = [t for t in threads if t["key"] == "c:C1"][0]
        self.assertEqual(t1["subject"], "Different subject")       # 最新の件名
        self.assertEqual(t1["first"], datetime(2024, 4, 10, 9))
        self.assertEqual(t1["last"], datetime(2024, 4, 11, 9))
        self.assertEqual(len({t["id"] for t in threads}), 3)

    def test_empty_subject_without_cid_not_lumped(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "", "2024-04-10T09:00:00", "A"),
                                       rec("E2", "RE:", "2024-04-11T09:00:00", "B")])
        mails, _ = T.merge_caches_to_mails([a], (2024, 1), (2024, 12))
        self.assertEqual(len(T.build_threads(mails)), 2)

    def test_select_caches_exclusions_and_latest(self):
        old = cache("MB", 1, "\\Inbox", [], scanned_at="2024-01-01T00:00:00")
        new = cache("MB", 1, "\\Inbox", [rec("E1", "x", "2024-04-10T09:00:00")], scanned_at="2024-02-01T00:00:00")
        deleted = cache("MB", 1, "\\削除済みアイテム\\sub", [rec("E2", "y", "2024-04-10T09:00:00")])
        news = cache("MB", 1, "\\Zenn-weekly", [rec("E3", "z", "2024-04-10T09:00:00")])
        other = cache("Other", 2, "\\Inbox", [rec("E4", "w", "2024-04-10T09:00:00")])
        th = make_theme()
        sel = T.select_caches([old, new, deleted, news, other], [], [], [], th["exclude_folder_names"],
                              th["exclude_folder_prefixes"])
        self.assertEqual(sorted((c["store_name"], c["folder_path"]) for c in sel),
                         [("MB", "\\Inbox"), ("Other", "\\Inbox")])
        self.assertEqual(len([c for c in sel if c["store_name"] == "MB"][0]["records"]), 1)
        sel2 = T.select_caches([new, other], ["other"], [], [], [], [])
        self.assertEqual([c["store_name"] for c in sel2], ["Other"])
        sel3 = T.select_caches([new, other], [], ["other"], [], [], [])
        self.assertEqual([c["store_name"] for c in sel3], ["MB"])

    def test_folder_excluded_and_store_selected(self):
        self.assertTrue(T.folder_excluded("Deleted Items", ["deleted items"], []))
        self.assertTrue(T.folder_excluded("ＮＯＴＥ-foo", [], ["note-"]))
        self.assertFalse(T.folder_excluded("Inbox", ["deleted items"], ["note-"]))
        self.assertFalse(T.folder_excluded("", ["x"], ["y"]))
        self.assertTrue(T.store_selected("User@Example.com", [], [], []))
        self.assertFalse(T.store_selected("User@Example.com", ["pst"], [], []))
        self.assertFalse(T.store_selected("2023_Q3", [], ["2023"], []))
        self.assertFalse(T.store_selected("Archive X", [], [], ["archive"]))


# ============================================================
# 候補判定
# ============================================================
class TestCandidate(unittest.TestCase):
    def test_all_three_conditions_via_related_party(self):
        _, e = one_thread([rec("E1", "Hello", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro; Tanaka Partner")])
        self.assertTrue(e["A"] and e["B"] and e["C_i"])
        self.assertFalse(e["C_ii"])
        self.assertTrue(e["candidate"])
        self.assertEqual(e["anchors"], ["PM"])
        self.assertEqual(e["related"], ["Sachi"])

    def test_candidate_via_strong_subject_keyword(self):
        _, e = one_thread([rec("E1", "RE: 通関の件", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")])
        self.assertTrue(e["candidate"])
        self.assertFalse(e["C_i"])
        self.assertTrue(e["C_ii"])

    def test_no_anchor_fails(self):
        _, e = one_thread([rec("E1", "通関", "2024-04-10T09:00:00", "Someone", "Owner Taro; Tanaka Partner")])
        self.assertFalse(e["A"])
        self.assertFalse(e["candidate"])
        self.assertEqual(T.failed_conditions(e), ["A"])

    def test_no_owner_fails(self):
        _, e = one_thread([rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Tanaka Partner")])
        self.assertFalse(e["B"])
        self.assertFalse(e["candidate"])
        self.assertEqual(T.failed_conditions(e), ["B"])

    def test_no_signal_fails(self):
        _, e = one_thread([rec("E1", "Lunch plan", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")])
        self.assertTrue(e["A"] and e["B"])
        self.assertFalse(e["C"])
        self.assertEqual(T.failed_conditions(e), ["C"])

    def test_weak_one_word_not_enough_but_two_is(self):
        _, e1 = one_thread([rec("E1", "[Approval request] Purchase lab parts", "2024-04-10T09:00:00",
                                "Sato Pm", "Owner Taro")])
        self.assertTrue(e1["A"] and e1["B"])
        self.assertFalse(e1["C_ii"])
        self.assertFalse(e1["candidate"])
        _, e2 = one_thread([rec("E1", "Approval request: urgent", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")])
        self.assertTrue(e2["C_ii"])
        self.assertTrue(e2["candidate"])

    def test_weak_one_but_related_party_rescues(self):
        _, e = one_thread([rec("E1", "[Approval request] Purchase", "2024-04-10T09:00:00", "Sato Pm",
                               "Owner Taro; Tanaka Partner")])
        self.assertFalse(e["C_ii"])
        self.assertTrue(e["candidate"])

    def test_union_over_thread_mails(self):
        # アンカーは1通目、越智は2通目、信号は3通目の件名 -> スレッド単位では全て満たす
        _, e = one_thread([
            rec("E1", "Topic", "2024-04-10T09:00:00", "Sato Pm", "X Other", cid="C1"),
            rec("E2", "Topic", "2024-04-11T09:00:00", "X Other", "Owner Taro", cid="C1"),
            rec("E3", "Topic customs clearance", "2024-04-12T09:00:00", "X Other", "Y", cid="C1"),
        ])
        self.assertTrue(e["candidate"])

    def test_weak_terms_across_subject_and_body_union(self):
        th = make_theme()
        recs = [rec("E1", "hold on", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        m = res["mails"][0]
        k = T.stage2_key(m["locs"][0]["sid"], m["locs"][0]["eid"])
        st2 = {k: {"s": "", "to": [], "cc": [], "att": [], "bh": th["dict_hash"], "hits": {"delay": 2}}}
        res2, _ = build([cache("S", 1, "\\Inbox", recs)], th, st2)
        self.assertFalse(ev_of(res)["candidate"])
        self.assertTrue(ev_of(res2)["candidate"])        # 件名の hold + 本文の delay = 異なる弱語2語

    def test_body_strong_from_stage2_and_stale_terms_ignored(self):
        th = make_theme()
        recs = [rec("E1", "Hello", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        m = res["mails"][0]
        k = T.stage2_key(m["locs"][0]["sid"], m["locs"][0]["eid"])
        st2 = {k: {"bh": th["dict_hash"], "hits": {"通関": 3, "removed-term": 9}}}
        res2, _ = build([cache("S", 1, "\\Inbox", recs)], th, st2)
        self.assertTrue(ev_of(res2)["candidate"])
        st3 = {k: {"bh": th["dict_hash"], "hits": {"removed-term": 9}}}
        res3, _ = build([cache("S", 1, "\\Inbox", recs)], th, st3)
        self.assertFalse(ev_of(res3)["candidate"])

    def test_address_only_match_via_stage2_and_domain(self):
        th = make_theme()
        # 表示名が別名と一致しない（'N. P.'）。SMTP で anchors(pm@example.com)・owner を拾う
        recs = [rec("E1", "通関", "2024-04-10T09:00:00", "N. P.", "O. P.")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        self.assertFalse(ev_of(res)["candidate"])
        m = res["mails"][0]
        k = T.stage2_key(m["locs"][0]["sid"], m["locs"][0]["eid"])
        st2 = {k: {"s": "pm@example.com", "to": [{"n": "O. P.", "a": "owner@example.com"}], "cc": [], "hits": {}}}
        res2, _ = build([cache("S", 1, "\\Inbox", recs)], th, st2)
        self.assertTrue(ev_of(res2)["candidate"])
        # ドメイン一致の関係者
        st3 = {k: {"s": "pm@example.com", "to": [{"n": "O. P.", "a": "owner@example.com"},
                                                  {"n": "Driver", "a": "x@sub.courier.example.com"}], "cc": []}}
        recs2 = [rec("E1", "Hello", "2024-04-10T09:00:00", "N. P.", "O. P.")]
        res3, _ = build([cache("S", 1, "\\Inbox", recs2)], th, st3)
        self.assertEqual(ev_of(res3)["related"], ["Courier"])
        self.assertTrue(ev_of(res3)["candidate"])

    def test_sender_smtp_in_stage1_used(self):
        recs = [rec("E1", "通関", "2024-04-10T09:00:00", "Zed", "Owner Taro", addr="pm@example.com")]
        _, e = one_thread(recs)
        self.assertTrue(e["candidate"])

    def test_exchange_x500_sender_not_used_as_address(self):
        recs = [rec("E1", "通関", "2024-04-10T09:00:00", "Zed", "Owner Taro", addr="/O=EXCH/CN=PM@EXAMPLE.COM")]
        _, e = one_thread(recs)
        self.assertFalse(e["A"])

    def test_summary_counts(self):
        recs = [
            rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro", cid="a"),   # 候補
            rec("E2", "通関", "2024-04-10T09:00:01", "Zed", "Owner Taro", cid="b"),        # Aのみ不成立
            rec("E3", "通関", "2024-04-10T09:00:02", "Sato Pm", "Zed", cid="c"),            # Bのみ不成立
            rec("E4", "Lunch", "2024-04-10T09:00:03", "Sato Pm", "Owner Taro", cid="d"),  # Cのみ不成立
            rec("E5", "Lunch", "2024-04-10T09:00:04", "Zed", "Zed", cid="e"),                # 全部不成立
        ]
        res, _ = build([cache("S", 1, "\\Inbox", recs)])
        s = T.summarize_conditions(res["evals"])
        self.assertEqual((s["total"], s["candidate"]), (5, 1))
        self.assertEqual((s["only_A_fails"], s["only_B_fails"], s["only_C_fails"]), (1, 1, 1))
        self.assertEqual((s["A"], s["B"], s["AB"]), (3, 3, 2))

    def test_select_stage2_targets_scope(self):
        recs = [
            rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro", cid="a"),
            rec("E4", "Lunch", "2024-04-10T09:00:03", "Sato Pm", "Owner Taro", cid="d"),
            rec("E2", "通関", "2024-04-10T09:00:01", "Zed", "Owner Taro", cid="b"),
        ]
        res, _ = build([cache("S", 1, "\\Inbox", recs)])
        n = lambda scope: len(T.select_stage2_targets(res["threads"], res["evals"], scope))
        self.assertEqual((n("candidate"), n("ab"), n("either")), (1, 2, 3))


# ============================================================
# スコア
# ============================================================
class TestScore(unittest.TestCase):
    def test_breakdown_text_and_subject_weighting(self):
        th = make_theme()
        recs = [rec(f"E{i}", "Re: customs clearance delay", f"2024-04-1{i}T09:00:00", "Sato Pm",
                    "Owner Taro; Tanaka Partner", cid="C") for i in range(5)]
        _, e = one_thread(recs, th)
        # アンカー1名+3, 関係者+2, 通関(1語) 3*2(件名)=6, トラブル語(1語) 2*2*0.5=2, 返信5通+1
        self.assertEqual(e["score"], 14.0)
        self.assertEqual(e["breakdown"], "アンカー+3, Sachi+2, 通関(1語)+6, トラブル語(1語)+2, 返信5通+1")

    def test_body_hit_lighter_than_subject_and_multiple_anchors(self):
        th = make_theme()
        recs = [rec("E1", "Hello", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro; Suzuki Admin")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        m = res["mails"][0]
        k = T.stage2_key(m["locs"][0]["sid"], m["locs"][0]["eid"])
        res2, _ = build([cache("S", 1, "\\Inbox", recs)], th, {k: {"bh": th["dict_hash"], "hits": {"通関": 1}}})
        e = ev_of(res2)
        self.assertEqual(e["breakdown"], "アンカー(2名)+6, 通関(1語)+3")
        self.assertEqual(e["score"], 9.0)

    def test_reply_cap_and_fmt(self):
        sw = make_theme()["score_weights"]
        s, b = T.compute_score([], [], set(), set(), {}, 100, sw)
        self.assertEqual((s, b), (5.0, "返信100通+5"))
        s2, _ = T.compute_score([], [], set(), set(), {}, 4, sw)
        self.assertEqual(s2, 0.0)
        self.assertEqual(T.fmt_num(2.0), "2")
        self.assertEqual(T.fmt_num(2.25), "2.2")

    def test_related_weight_override(self):
        th = make_theme(related_parties=[{"label": "Big", "name_aliases": ["Tanaka Partner"], "weight": 7}])
        _, e = one_thread([rec("E1", "Hello", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro; Tanaka Partner")], th)
        self.assertIn("Big+7", e["breakdown"])


# ============================================================
# CSV・判定
# ============================================================
class TestCsv(unittest.TestCase):
    def test_csv_safe(self):
        for ch in "=+-@":
            self.assertEqual(T.csv_safe(ch + "cmd"), "'" + ch + "cmd")
        self.assertEqual(T.csv_safe("\tabc"), "'\tabc")
        self.assertEqual(T.csv_safe("\rabc"), "'\rabc")
        self.assertEqual(T.csv_safe(" =1+1"), "' =1+1")
        self.assertEqual(T.csv_safe("normal"), "normal")
        self.assertEqual(T.csv_safe(""), "")
        self.assertEqual(T.csv_safe(None), "")
        self.assertEqual(T.csv_safe(12), "12")
        self.assertEqual(T.csv_safe("a=b"), "a=b")

    def test_write_csv_escapes_all_cells_and_utf8_sig(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            T.write_csv(p, ["=h", "b"], [["=SUM(A1)", "@x"], ["日本語", 3]])
            raw = _rb(p)
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            rows = _rcsv(p)
            self.assertEqual(rows[0], ["'=h", "b"])
            self.assertEqual(rows[1], ["'=SUM(A1)", "'@x"])
            self.assertEqual(rows[2], ["日本語", "3"])

    def test_ledger_rows_escape_mail_derived_strings_and_columns(self):
        th = make_theme()
        recs = [rec("E1", "=HYPERLINK(\"x\") 通関", "2024-04-10T09:00:00", "-Sato Pm", "@Owner Taro")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        # B は表示名の先頭記号を含んでも name_key が吸収するか確認（先頭 '@' は記号として残る）
        rows = T.build_ledger_rows(res["threads"], res["evals"], {}, th)
        for r in rows:
            self.assertEqual(len(r), len(T.LEDGER_COLUMNS))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.csv")
            T.write_csv(p, T.LEDGER_COLUMNS, rows)
            for line in _rcsv(p):
                for cell in line:
                    self.assertFalse(cell[:1] in ("=", "+", "@") or (cell[:1] == "-" and False), cell)

    def test_ledger_has_judgment_columns_and_version(self):
        th = make_theme()
        recs = [rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        tid = res["threads"][0]["id"]
        rows = T.build_ledger_rows(res["threads"], res["evals"], {tid: {"確認結果": "本物", "メモ": "m", "問題の種類": "通関"}}, th)
        d = dict(zip(T.LEDGER_COLUMNS, rows[0]))
        self.assertEqual((d["確認結果(本物/違う/保留)"], d["メモ"], d["問題の種類"], d["theme_version"]), ("本物", "m", "通関", "t1"))
        self.assertEqual(d["最新メールEntryID"], "E1")
        self.assertEqual(d["最新メールStoreID"], "SID1")
        self.assertIn("A:○(PM)", d["条件A/B/C内訳"])

    def test_non_candidates_not_in_ledger(self):
        th = make_theme()
        recs = [rec("E1", "Lunch", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        self.assertEqual(T.build_ledger_rows(res["threads"], res["evals"], {}, th), [])

    def test_ledger_sorted_by_score(self):
        th = make_theme()
        recs = [rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro", cid="a"),
                rec("E2", "通関 customs clearance", "2024-04-11T09:00:00", "Sato Pm", "Owner Taro; Tanaka Partner", cid="b")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        rows = T.build_ledger_rows(res["threads"], res["evals"], {}, th)
        self.assertGreater(float(rows[0][10]), float(rows[1][10]))


class TestJudgments(unittest.TestCase):
    def test_existing_never_overwritten_new_rows_added(self):
        existing = {"t1": {"確認結果": "本物", "メモ": "keep", "問題の種類": "通関"}, "old": {"確認結果": "違う"}}
        merged, added = T.merge_judgments(existing, ["t1", "t2"])
        self.assertEqual(added, 1)
        self.assertEqual(merged["t1"], existing["t1"])
        self.assertEqual(merged["t2"], {"確認結果": "", "メモ": "", "問題の種類": ""})
        self.assertIn("old", merged)                       # 候補から外れた行も消さない
        self.assertEqual(merged["old"]["確認結果"], "違う")
        self.assertEqual(merged["old"]["メモ"], "")        # 欠けたキーは空で補うだけ
        self.assertIsNot(merged["t1"], existing["t1"])

    def test_none_existing(self):
        merged, added = T.merge_judgments(None, ["a"])
        self.assertEqual((len(merged), added), (1, 1))


# ============================================================
# カバレッジ・新メンバー・候補語
# ============================================================
class TestReports(unittest.TestCase):
    def test_coverage_flags_and_counts(self):
        th = make_theme()
        a = cache("MB", 1, "\\Inbox", [rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro"),
                                       rec("E2", "Lunch", "2024-04-11T09:00:00", "Zed", "Zed")])
        b = cache("PST", 2, "\\(ルート直下)", [rec("E9", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")])
        res, _ = build([a, b], th)
        rows = T.build_coverage_rows(res["stats"], res["mails"], res["threads"], res["evals"], {}, th,
                                     [(2024, 3), (2024, 4)], ["MB", "PST"])
        d = {(r[0], r[1]): r for r in rows}
        self.assertEqual(d[("MB", "2024-04")][2:6], [2, 2, 1, 1])
        self.assertEqual(d[("PST", "2024-04")][2:6], [1, 0, 0, 1])      # 重複除去後は代表(MB)側に数える
        self.assertEqual(d[("(全ストア)", "2024-04")][2:6], [3, 2, 1, 1])
        self.assertIn("未取得の恐れ", d[("MB", "2024-03")][6])
        self.assertIn("取得元ゼロ・要確認", d[("(全ストア)", "2024-03")][6])
        self.assertIn("未取得の恐れ", d[("(全ストア)", "2024-03")][6])
        self.assertEqual(d[("MB", "2024-04")][6], "")

    def test_suggest_participants_excludes_known_and_ranks(self):
        th = make_theme()
        recs = [
            rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro; New Person", cid="a"),
            rec("E2", "通関", "2024-04-11T09:00:00", "Sato Pm", "Owner Taro; New Person; Rare One", cid="b"),
            rec("E3", "Lunch", "2024-04-12T09:00:00", "Sato Pm", "Owner Taro; Not Candidate", cid="c"),
        ]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        rows = T.suggest_participants(res["threads"], res["evals"], th, {})
        names = [r[0] for r in rows]
        self.assertEqual(names[0], "New Person")
        self.assertEqual(rows[0][2], 2)
        self.assertIn("Rare One", names)
        for known in ("Sato Pm", "Owner Taro", "Not Candidate"):
            self.assertNotIn(known, names)

    def test_rank_candidate_terms_down_weights_common_words(self):
        fg = [{"customs", "meeting"}, {"customs", "meeting"}, {"customs", "report"}]
        bg = fg + [{"meeting"}] * 50 + [{"other"}] * 10
        rows = T.rank_candidate_terms(fg, bg, known_terms=["customs"])
        terms = [r[0] for r in rows]
        self.assertEqual(terms[0], "customs")
        self.assertEqual(rows[0][7], "はい")
        self.assertNotIn("report", terms)               # fg 1件のみ(min_fg=2未満)
        if "meeting" in terms:
            self.assertLess(terms.index("customs"), terms.index("meeting"))
        self.assertEqual(T.rank_candidate_terms([], bg), [])
        self.assertEqual(T.rank_candidate_terms(fg, []), [])

    def test_tokenize_for_terms(self):
        w = T.tokenize_for_terms("Re: パラメータシート提出 and customs-entry 2024 XY")
        self.assertIn("パラメータシート", w)
        self.assertIn("提出", w)
        self.assertIn("customs-entry", w)
        self.assertNotIn("and", w)
        self.assertNotIn("2024", w)
        self.assertNotIn("xy", w)

    def test_candidate_term_docs_only_related_in_fg(self):
        th = make_theme()
        recs = [rec("E1", "foobar baz", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro; Tanaka Partner", cid="a"),
                rec("E2", "通関 qux", "2024-04-10T09:00:01", "Sato Pm", "Owner Taro", cid="b")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        fg, bg = T.candidate_term_docs(res["threads"], res["evals"], th, {})
        self.assertEqual((len(fg), len(bg)), (1, 2))


# ============================================================
# 正解件名チェック
# ============================================================
class TestCheckSubjects(unittest.TestCase):
    def setUp(self):
        th = make_theme()
        recs = [
            rec("E1", "** internal only ** RE: [Export request]2024-04-01 10:00", "2024-04-10T09:00:00",
                "Sato Pm", "Owner Taro; Tanaka Partner", cid="a"),
            rec("E2", "FW: Weekly lunch plan arrangement", "2024-04-11T09:00:00", "Sato Pm", "Owner Taro", cid="b"),
            rec("E3", "customs clearance for other", "2024-04-12T09:00:00", "Zed", "Owner Taro", cid="c"),
        ]
        self.res, _ = build([cache("S", 1, "\\Inbox", recs)], th)

    def test_found_candidate_exact_with_prefix_stripped(self):
        r = T.classify_check_subjects(["RE: [Export request]2024-04-01 10:00"], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r["status"], "found")
        m = r["matches"][0]
        self.assertEqual((m["kind"], m["A"], m["B"], m["C"], m["candidate"]), ("完全一致", True, True, True, True))
        self.assertEqual(m["total"], 3)
        self.assertGreaterEqual(m["rank"], 1)

    def test_found_but_not_candidate_reports_failed_conditions(self):
        r = T.classify_check_subjects(["Weekly lunch plan arrangement"], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r["status"], "found_not_candidate")
        self.assertEqual(r["matches"][0]["failed"], ["C"])
        r2 = T.classify_check_subjects(["customs clearance for other"], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r2["matches"][0]["failed"], ["A"])

    def test_partial_match(self):
        r = T.classify_check_subjects(["Export request"], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r["status"], "found")
        self.assertEqual(r["matches"][0]["kind"], "部分一致")

    def test_short_query_no_partial_and_missing(self):
        r = T.classify_check_subjects(["lunch"], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r["status"], "missing")
        r2 = T.classify_check_subjects(["totally unknown subject here"], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r2["status"], "missing")
        r3 = T.classify_check_subjects([""], self.res["threads"], self.res["evals"])[0]
        self.assertEqual(r3["status"], "missing")

    def test_rank_is_by_score(self):
        ranks = {}
        for q in ("[Export request]2024-04-01 10:00", "customs clearance for other", "Weekly lunch plan arrangement"):
            ranks[q] = T.classify_check_subjects([q], self.res["threads"], self.res["evals"])[0]["matches"][0]["rank"]
        self.assertEqual(ranks["Weekly lunch plan arrangement"], 3)
        self.assertLess(ranks["[Export request]2024-04-01 10:00"], 3)

    def test_format_lines_and_load_file(self):
        rs = T.classify_check_subjects(["Weekly lunch plan arrangement", "unknown unknown unknown"],
                                       self.res["threads"], self.res["evals"])
        text = "\n".join(T.format_check_result(1, 2, rs[0]) + T.format_check_result(2, 2, rs[1]))
        self.assertIn("あるが候補外", text)
        self.assertIn("キャッシュに無い", text)
        self.assertIn("順位", text)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.txt")
            _wr(p, "# comment\n\nSubject A\n  Subject B  \n#x\n")
            self.assertEqual(T.load_calibration_subjects(p), ["Subject A", "Subject B"])
        ex = os.path.join(TOOLS_DIR, "calibration_subjects.example.txt")
        self.assertGreaterEqual(len(T.load_calibration_subjects(ex)), 3)


# ============================================================
# キャッシュ方針
# ============================================================
class TestCachePolicy(unittest.TestCase):
    def test_decide_cache_action(self):
        f, t = (2024, 1), (2024, 12)
        done = {"complete": True, "range": ["2023-07", "2026-09"]}
        self.assertEqual(T.decide_cache_action(done, f, t, False), "skip")
        self.assertEqual(T.decide_cache_action(done, f, t, True), "fresh")
        self.assertEqual(T.decide_cache_action(None, f, t, False), "fresh")
        self.assertEqual(T.decide_cache_action({"complete": True, "range": ["2024-03", "2024-12"]}, f, t, False), "fresh")
        self.assertEqual(T.decide_cache_action({"complete": True, "range": ["2024-01", "2024-11"]}, f, t, False), "fresh")
        cp = {"complete": False, "range": ["2024-01", "2024-12"], "last_received": "2024-05-01T00:00:00"}
        self.assertEqual(T.decide_cache_action(cp, f, t, False), "resume")
        self.assertEqual(T.decide_cache_action(cp, (2024, 2), t, False), "fresh")
        self.assertEqual(T.decide_cache_action({"complete": False, "range": ["2024-01", "2024-12"]}, f, t, False), "fresh")
        self.assertEqual(T.decide_cache_action({"range": "bad"}, f, t, False), "fresh")

    def test_folder_cache_path_stable_and_distinct(self):
        p = T.make_paths("/x/data", "/x/out")
        a = T.folder_cache_path(p, 1, "S", "\\Inbox")
        self.assertEqual(a, T.folder_cache_path(p, 1, "S", "\\Inbox"))
        self.assertNotEqual(a, T.folder_cache_path(p, 1, "S", "\\Other"))
        self.assertTrue(os.path.basename(a).startswith("01_"))

    def test_load_all_caches_skips_broken(self):
        with tempfile.TemporaryDirectory() as d:
            T.write_json_atomic(os.path.join(d, "a.json"), cache("S", 1, "\\Inbox", []))
            _wr(os.path.join(d, "b.json"), "{broken")
            T.write_json_atomic(os.path.join(d, "c.json"), {"schema": 99, "records": []})
            self.assertEqual(len(T.load_all_caches(d)), 1)


# ============================================================
# COM フェイク
# ============================================================
FORBIDDEN = {"Delete", "Move", "Save", "SaveAs", "Copy", "MarkAsTask", "UnRead", "Categories", "AddStore",
             "RemoveStore", "FlagStatus", "Send"}
ACCESSED = []         # 禁止属性にアクセスされた記録
STAGE2_ONLY = {"Body", "Recipients", "Attachments", "PropertyAccessor"}
LIGHT_ACCESSED = []   # 第1段で読んではいけない属性にアクセスされた記録


class FakeComError(Exception):
    pass


class FakeItem:
    def __init__(self, fields, raises=None, stage1=True, display_log=None):
        object.__setattr__(self, "_f", fields)
        object.__setattr__(self, "_r", raises or {})
        object.__setattr__(self, "_stage1", stage1)
        object.__setattr__(self, "_display_log", display_log)

    def __setattr__(self, name, value):
        ACCESSED.append(f"set:{name}")
        raise AttributeError(name)

    def Display(self):
        if self._display_log is not None:
            self._display_log.append(self._f.get("EntryID"))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in FORBIDDEN:
            ACCESSED.append(name)
            raise AttributeError(name)
        if self._stage1 and name in STAGE2_ONLY:
            LIGHT_ACCESSED.append(name)
        if name in self._r:
            raise self._r[name]
        if name in self._f:
            return self._f[name]
        raise AttributeError(name)


def mk_item(eid, subj, t, sender="", to="", cc="", cid="", cls=43, addr="", sent=None, raises=None, **extra):
    f = {"Class": cls, "EntryID": eid, "Subject": subj, "ReceivedTime": t, "SenderName": sender,
         "SenderEmailAddress": addr, "To": to, "CC": cc, "ConversationID": cid}
    if sent is not None:
        f["SentOn"] = sent
    f.update(extra)
    return FakeItem(f, raises)


class FakeRestricted:
    def __init__(self, items, field):
        self.items = list(items)
        self.field = field
        self.i = 0
        self.next_raises = None

    def Sort(self, prop):
        key = prop.strip("[]")
        self.items.sort(key=lambda it: getattr(it, key))

    @property
    def Count(self):
        return len(self.items)

    def Item(self, i):
        if getattr(self, "item_raises", None) is not None:
            raise self.item_raises
        if i < 1 or i > len(self.items):
            raise IndexError(i)
        return self.items[i - 1]

    def GetFirst(self):
        self.i = 0
        return self.items[0] if self.items else None

    def GetNext(self):
        if self.next_raises is not None and self.i + 1 == self.next_raises[0]:
            raise self.next_raises[1]
        self.i += 1
        return self.items[self.i] if self.i < len(self.items) else None


class FakeItems:
    def __init__(self, items, filters, items_raise=None, next_raises=None, fail_or=False, item_raises=None):
        self.items = items
        self.filters = filters
        self.items_raise = items_raise
        self.next_raises = next_raises
        self.fail_or = fail_or
        self.item_raises = item_raises

    @property
    def Count(self):
        return len(self.items)

    def Restrict(self, flt):
        import re
        self.filters.append(flt)
        if self.items_raise is not None:
            raise self.items_raise
        if self.fail_or and " OR " in flt:
            raise FakeComError(SECRET_ERR)
        clauses = re.findall(r"\[(\w+)\] >= '([^']+)' AND \[\w+\] < '([^']+)'", flt)
        assert clauses, flt
        out = []
        for it in self.items:
            for field, s, e in clauses:
                s_dt, e_dt = datetime.strptime(s, "%Y-%m-%d %H:%M"), datetime.strptime(e, "%Y-%m-%d %H:%M")
                try:
                    v = getattr(it, field)
                except Exception:
                    continue
                if isinstance(v, datetime) and s_dt <= v < e_dt:
                    out.append(it)
                    break
        field = clauses[0][0]
        r = FakeRestricted(out, field)
        r.next_raises = self.next_raises
        r.item_raises = self.item_raises
        return r


class FakeFolders:
    def __init__(self, folders):
        self.folders = folders

    @property
    def Count(self):
        return len(self.folders)

    def Item(self, i):
        return self.folders[i - 1]


_FID = [0]


class FakeFolder:
    def __init__(self, name, items=None, subfolders=None, item_type=0, items_raise=None, next_raises=None,
                 fail_or=False, item_raises=None):
        self.Name = name
        _FID[0] += 1
        self.EntryID = f"FID{_FID[0]}"
        self.DefaultItemType = item_type
        self.filters = []
        self._items = FakeItems(items or [], self.filters, items_raise, next_raises, fail_or, item_raises)
        self.Folders = FakeFolders(subfolders or [])

    @property
    def Items(self):
        return self._items


class FakeStore:
    def __init__(self, name, root, sid=None, path=""):
        self.DisplayName = name
        self.StoreID = sid if sid is not None else "SID-" + name
        self.FilePath = path
        self._root = root

    def GetRootFolder(self):
        return self._root


class FakeStores:
    def __init__(self, stores):
        self.stores = stores

    @property
    def Count(self):
        return len(self.stores)

    def Item(self, i):
        return self.stores[i - 1]


PROXIES = []     # GetFolderFromID が返したフォルダ（弱参照）。走査後に全て解放されていること


class FolderProxy:
    """GetFolderFromID が返すフォルダ。本物のフェイクに委譲する（解放確認のため弱参照できる別オブジェクト）。"""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    def __getattr__(self, name):
        return getattr(self._real, name)


class FakeNamespace:
    def __init__(self, stores, by_id=None):
        self.Stores = FakeStores(stores)
        self.by_id = by_id or {}
        self.folder_fetches = []
        self.store_lookups = []
        self.store_lookup_fails = False

    def GetStoreFromID(self, sid):
        self.store_lookups.append(sid)
        if self.store_lookup_fails:
            raise FakeComError(SECRET_ERR)
        for st in self.Stores.stores:
            if st.StoreID == sid:
                return st
        raise FakeComError(SECRET_ERR)

    def GetFolderFromID(self, eid, sid=None):
        import weakref

        def walk(f):
            yield f
            for sub in f.Folders.folders:
                yield from walk(sub)
        for st in self.Stores.stores:
            for f in walk(st._root):
                if f.EntryID == eid and (sid is None or sid == st.StoreID):
                    self.folder_fetches.append((eid, sid))
                    px = FolderProxy(f)
                    PROXIES.append(weakref.ref(px))
                    return px
        raise FakeComError(SECRET_ERR)

    def GetItemFromID(self, eid, sid):
        if (eid, sid) not in self.by_id:
            raise FakeComError(SECRET_ERR)
        v = self.by_id[(eid, sid)]
        if isinstance(v, BaseException):
            raise v
        return v


class FakeOutlook:
    def __init__(self, ns):
        self.ns = ns

    def GetNamespace(self, name):
        return self.ns


class FakeClient:
    def __init__(self, ns):
        self.ns = ns

    def Dispatch(self, name):
        return FakeOutlook(self.ns)


class FakePythonCom:
    def __init__(self):
        self.init = 0
        self.uninit = 0

    def CoInitialize(self):
        self.init += 1

    def CoUninitialize(self):
        self.uninit += 1


def fake_com(ns):
    pc = FakePythonCom()
    return (FakeClient(ns), pc), pc


def dt(m, d, h=9, mi=0, s=0):
    return datetime(2024, m, d, h, mi, s)


def run_main(argv, com=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = T.main(argv, com=com)
    return code, buf.getvalue()


class ComTestBase(unittest.TestCase):
    def setUp(self):
        ACCESSED.clear()
        LIGHT_ACCESSED.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmp.name, "data")
        self.out = os.path.join(self.tmp.name, "out")
        self.theme_path = os.path.join(self.tmp.name, "theme.json")
        self.theme_data = {
            "theme_version": "t1",
            "owner": {"name_aliases": ["Owner Taro"], "emails": ["owner@example.com"]},
            "anchors": [{"label": "PM", "name_aliases": ["Sato Pm"], "emails": ["pm@example.com"]}],
            "related_parties": [{"label": "Sachi", "name_aliases": ["Tanaka Partner"]}],
            "keywords": {"通関": {"weight": 3, "strong": ["通関"], "weak": ["hold"]}},
            "period": {"from": "2024-01", "to": "2024-12"},
        }
        _wj(self.theme_path, self.theme_data)
        self.old_cp = T.CHECKPOINT_EVERY

    def tearDown(self):
        T.CHECKPOINT_EVERY = self.old_cp
        self.tmp.cleanup()

    def argv(self, *extra):
        return ["--theme", self.theme_path, "--data-dir", self.data, "--output-dir", self.out, *extra]

    def paths(self):
        return T.make_paths(self.data, self.out)

    def caches(self):
        return T.load_all_caches(self.paths()["scan_cache"])

    def standard_namespace(self):
        inbox = FakeFolder("Inbox", [
            mk_item("E1", f"{SECRET} 通関", dt(4, 10), "Sato Pm", "Owner Taro", cid="C1", addr="pm@example.com"),
            mk_item("E2", "RE: " + SECRET + " 通関", dt(4, 11), "Owner Taro", "Sato Pm", cid="C1"),
            mk_item("E3", "Lunch", dt(5, 1), "Zed", "Owner Taro"),
            mk_item("E4", "meeting request", dt(5, 2), "Zed", "Owner Taro", cls=53),   # 会議出席依頼 -> メール以外
            mk_item("E5", "out of period", datetime(2023, 11, 1, 9), "Zed", "Owner Taro"),
        ], subfolders=[
            FakeFolder("削除済みアイテム", [mk_item("D1", "deleted", dt(4, 12), "Zed", "Owner Taro")]),
            FakeFolder("Calendar", [mk_item("K1", "cal", dt(4, 12))], item_type=1),
        ])
        mb = FakeStore("user@example.com", inbox_root(inbox))
        pst_root = FakeFolder("root", [
            mk_item("P1", f"{SECRET} 通関", dt(4, 10), "Sato Pm", "Owner Taro", cid="C9"),     # E1 と重複
            mk_item("P2", "PST only 通関", dt(4, 20), "Sato Pm", "Owner Taro", cid="C2"),
        ])
        pst = FakeStore("2024_Q2", pst_root, path="C:\\x\\2024_Q2.pst")
        return FakeNamespace([mb, pst])


def inbox_root(inbox):
    root = FakeFolder("root", [], subfolders=[inbox])
    return root


# ============================================================
# 第1段スキャン（COM）
# ============================================================
class TestScanCom(ComTestBase):
    def test_scan_end_to_end_cache_and_privacy(self):
        ns = self.standard_namespace()
        com, pc = fake_com(ns)
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET, out)
        self.assertEqual((pc.init, pc.uninit), (1, 1))            # 走査1回のみCOMを使う（評価はCOM不要）
        self.assertEqual(LIGHT_ACCESSED, [])                     # Body等は第1段で読まない
        self.assertEqual(ACCESSED, [])                           # 変更系は一切呼ばない
        caches = self.caches()
        by_path = {(c["store_name"], c["folder_path"]): c for c in caches}
        self.assertIn(("user@example.com", "\\Inbox"), by_path)
        self.assertIn(("2024_Q2", "\\(ルート直下)"), by_path)
        self.assertNotIn(("user@example.com", "\\削除済みアイテム"), by_path)          # 除外フォルダは走査しない
        self.assertNotIn(("user@example.com", "\\Calendar"), by_path)                   # メール以外のフォルダ
        inbox = by_path[("user@example.com", "\\Inbox")]
        self.assertEqual(sorted(r["e"] for r in inbox["records"]), ["E1", "E2", "E3"])  # 期間外は取らない・クラス53は除く
        self.assertEqual(inbox["counts"]["non_mail"], 1)
        self.assertTrue(inbox["complete"])
        self.assertEqual(inbox["store_id"], "SID-user@example.com")
        r1 = [r for r in inbox["records"] if r["e"] == "E1"][0]
        self.assertEqual((r1["n"], r1["to"], r1["c"], r1["a"]), ("Sato Pm", "Owner Taro", "C1", "pm@example.com"))
        self.assertEqual(r1["t"], "2024-04-10T09:00:00")
        for k in r1:
            self.assertIn(k, {"e", "s", "t", "n", "a", "to", "cc", "c"})                # 本文は含めない
        # フィルタはISO・期間全体で1回
        flt = ns.Stores.Item(1).GetRootFolder().Folders.Item(1).filters
        self.assertEqual(flt, ["([ReceivedTime] >= '2024-01-01 00:00' AND [ReceivedTime] < '2025-01-01 00:00') OR ([SentOn] >= '2024-01-01 00:00' AND [SentOn] < '2025-01-01 00:00')"])

    def test_console_has_no_mail_addresses_of_stores(self):
        com, _ = fake_com(self.standard_namespace())
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertNotIn("user@example.com", out)
        self.assertIn("<MAIL>", out)

    def test_outputs_after_scan_dedupe_and_csv(self):
        com, _ = fake_com(self.standard_namespace())
        code, out = run_main(self.argv("--no-stage2", "--suggest", "--suggest-terms"), com)
        self.assertEqual(code, 0)
        self.assertIn("ストア間の重複 1件", out)
        files = os.listdir(self.out)
        for prefix in ("thread_ledger_theme_", "coverage_", "suggest_participants_", "candidate_terms_"):
            self.assertTrue(any(f.startswith(prefix) and f.endswith(".csv") for f in files), prefix)
        led = [f for f in files if f.startswith("thread_ledger_theme_")][0]
        rows = _rdict(os.path.join(self.out, led))
        self.assertEqual(len(rows), 2)        # C1(E1/E2/P1重複) と C2
        self.assertEqual(sorted(r["メール数"] for r in rows), ["1", "2"])
        multi = [r for r in rows if r["メール数"] == "2"][0]
        self.assertIn("user@example.com", multi["取得元(ストア/フォルダ)"])
        self.assertIn("2024_Q2", multi["取得元(ストア/フォルダ)"])   # 重複の取得元も全て記録
        self.assertTrue(os.path.exists(os.path.join(self.data, "judgments_theme.json")))
        self.assertNotIn(SECRET, "".join(_rd(os.path.join(self.out, f), "utf-8-sig")
                                         for f in files if f.endswith(".log")))

    def test_second_run_skips_completed_and_rescan_refetches(self):
        com, _ = fake_com(self.standard_namespace())
        run_main(self.argv("--no-stage2"), com)
        ns2 = self.standard_namespace()
        com2, _ = fake_com(ns2)
        code, out = run_main(self.argv("--no-stage2"), com2)
        self.assertIn("完了済みスキップ 2", out)
        self.assertEqual(ns2.Stores.Item(1).GetRootFolder().Folders.Item(1).filters, [])
        ns3 = self.standard_namespace()
        com3, _ = fake_com(ns3)
        run_main(self.argv("--no-stage2", "--rescan"), com3)
        self.assertEqual(len(ns3.Stores.Item(1).GetRootFolder().Folders.Item(1).filters), 1)

    def test_one_folder_exception_continues_and_error_kind_only(self):
        bad = FakeFolder("Bad", [mk_item("B1", SECRET, dt(4, 1), "Zed", "Owner Taro")],
                         items_raise=FakeComError(SECRET_ERR))
        good = FakeFolder("Good", [mk_item("G1", "ok", dt(4, 2), "Zed", "Owner Taro")])
        root = FakeFolder("root", [], subfolders=[bad, good])
        com, _ = fake_com(FakeNamespace([FakeStore("MB", root)]))
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertEqual(code, 0)
        self.assertIn("FakeComError", out)
        self.assertNotIn(SECRET_ERR, out)
        self.assertNotIn(SECRET, out)
        paths = {c["folder_path"] for c in self.caches()}
        self.assertIn("\\Good", paths)
        self.assertNotIn("\\Bad", paths)

    def test_item_field_exceptions_are_swallowed_per_field(self):
        it = mk_item("X1", SECRET, dt(4, 1), "Zed", "Owner Taro",
                     raises={"Subject": FakeComError(SECRET_ERR), "ConversationID": FakeComError(SECRET_ERR)})
        it2 = mk_item("X2", "t", dt(4, 2), raises={"EntryID": FakeComError(SECRET_ERR)})
        it3 = mk_item("X3", "t", dt(4, 3), raises={"Class": FakeComError(SECRET_ERR)})
        it4 = mk_item("X4", "ok", dt(4, 4), "Zed", "Owner Taro")
        root = FakeFolder("root", [it, it2, it3, it4])
        com, _ = fake_com(FakeNamespace([FakeStore("MB", root)]))
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET_ERR, out)
        c = self.caches()[0]
        self.assertEqual(sorted(r["e"] for r in c["records"]), ["X1", "X4"])
        x1 = [r for r in c["records"] if r["e"] == "X1"][0]
        self.assertEqual((x1["s"], x1["c"]), ("", ""))
        self.assertIn("Subject:FakeComError", c["counts"]["errors"])

    def sent_item(self):
        # ReceivedTime が未設定（4501年）の送信済みアイテム
        return FakeItem({"Class": 43, "EntryID": "S1", "Subject": "s", "ReceivedTime": datetime(4501, 1, 1),
                         "SentOn": dt(4, 5), "SenderName": "Owner Taro", "To": "Sato Pm",
                         "SenderEmailAddress": "", "CC": "", "ConversationID": ""})

    def test_or_restrict_catches_sent_and_received_together(self):
        sent = FakeFolder("Mixed", [self.sent_item(), mk_item("R1", "r", dt(4, 6), "Zed", "Owner Taro")])
        com, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", [], subfolders=[sent]))]))
        run_main(self.argv("--no-stage2"), com)
        c = self.caches()[0]
        self.assertEqual(c["date_field"], "or")
        self.assertEqual(sorted(r["e"] for r in c["records"]), ["R1", "S1"])
        self.assertEqual({r["e"]: r["t"] for r in c["records"]}["S1"], "2024-04-05T09:00:00")
        self.assertIn(" OR ", sent.filters[0])

    def test_or_restrict_failure_falls_back_to_receivedtime_then_senton(self):
        sent = FakeFolder("Sent", [self.sent_item()], fail_or=True)
        com, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", [], subfolders=[sent]))]))
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertEqual(code, 0)
        c = self.caches()[0]
        self.assertEqual(c["date_field"], "SentOn")
        self.assertEqual(c["records"][0]["t"], "2024-04-05T09:00:00")
        self.assertEqual([f.split()[0] for f in sent.filters], ["([ReceivedTime]", "[ReceivedTime]", "[SentOn]"])
        self.assertNotIn(SECRET_ERR, out)
        # 受信側のフォルダは ReceivedTime で取れる（SentOn まで行かない）
        inbox = FakeFolder("In", [mk_item("R1", "r", dt(4, 6), "Zed", "Owner Taro")], fail_or=True)
        com2, _ = fake_com(FakeNamespace([FakeStore("MB2", FakeFolder("root", [], subfolders=[inbox]), sid="S2")]))
        run_main(self.argv("--no-stage2", "--stores", "MB2"), com2)
        self.assertEqual(len(inbox.filters), 2)

    def test_resume_in_fallback_mode_restricts_from_last_received(self):
        T.CHECKPOINT_EVERY = 100
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 8)]
        items[4] = mk_item("M5", "s5", dt(4, 5), "Zed", "Owner Taro", raises={"Subject": KeyboardInterrupt()})
        f1 = FakeFolder("F", items, fail_or=True)
        com, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", [], subfolders=[f1]))]))
        self.assertEqual(run_main(self.argv("--no-stage2"), com)[0], 130)
        items2 = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 8)]
        f2 = FakeFolder("F", items2, fail_or=True)
        com2, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", [], subfolders=[f2]))]))
        self.assertEqual(run_main(self.argv("--no-stage2"), com2)[0], 0)
        self.assertEqual(f2.filters, ["[ReceivedTime] >= '2024-04-04 09:00' AND [ReceivedTime] < '2025-01-01 00:00'"])
        c = self.caches()[0]
        self.assertEqual(sorted(r["e"] for r in c["records"]), [f"M{i}" for i in range(1, 8)])

    def test_keyboard_interrupt_saves_partial_and_resume_has_no_duplicates(self):
        T.CHECKPOINT_EVERY = 2
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 8)]
        items[4] = mk_item("M5", "s5", dt(4, 5), "Zed", "Owner Taro", raises={"Subject": KeyboardInterrupt()})
        root = FakeFolder("root", items)
        com, pc = fake_com(FakeNamespace([FakeStore("MB", root)]))
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertEqual(code, 130)
        self.assertEqual(pc.uninit, 1)
        c = self.caches()[0]
        self.assertFalse(c["complete"])
        self.assertEqual(sorted(r["e"] for r in c["records"]), ["M1", "M2", "M3", "M4"])
        self.assertEqual(c["last_received"], "2024-04-04T09:00:00")
        self.assertIn("Ctrl+C", out)
        # 再開: OR方式は期間全体を取り直し、取得済みEntryIDを早期に飛ばして重複除去する
        items2 = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 8)]
        root2 = FakeFolder("root", items2)
        com2, _ = fake_com(FakeNamespace([FakeStore("MB", root2)]))
        code2, out2 = run_main(self.argv("--no-stage2"), com2)
        self.assertEqual(code2, 0)
        self.assertEqual(root2.filters, ["([ReceivedTime] >= '2024-01-01 00:00' AND [ReceivedTime] < '2025-01-01 00:00') OR ([SentOn] >= '2024-01-01 00:00' AND [SentOn] < '2025-01-01 00:00')"])
        c2 = self.caches()[0]
        self.assertTrue(c2["complete"])
        eids = [r["e"] for r in c2["records"]]
        self.assertEqual(sorted(eids), [f"M{i}" for i in range(1, 8)])
        self.assertEqual(len(eids), len(set(eids)))

    def test_checkpoint_saved_every_n_items(self):
        T.CHECKPOINT_EVERY = 3
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 9)]
        saved = []
        orig = T.write_json_atomic

        def spy(path, obj):
            if "scan_cache" in path:
                saved.append((obj["complete"], len(obj["records"])))
            return orig(path, obj)
        T.write_json_atomic = spy
        try:
            com, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", items))]))
            run_main(self.argv("--no-stage2"), com)
        finally:
            T.write_json_atomic = orig
        self.assertEqual(saved, [(False, 3), (False, 6), (True, 8)])

    def test_getnext_failure_skips_bad_item_and_goes_on(self):
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 5)]
        f = FakeFolder("F", items, next_raises=(2, FakeComError(SECRET_ERR)))
        com, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", [], subfolders=[f]))]))
        code, out = run_main(self.argv("--no-stage2"), com)
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET_ERR, out)
        c = self.caches()[0]
        self.assertTrue(c["complete"])                 # 失敗した1件を飛ばして最後まで読む（再実行でも同じ所で止まらない）
        self.assertEqual(sorted(r["e"] for r in c["records"]), ["M1", "M2", "M4"])
        self.assertIn("GetNext:FakeComError", c["counts"]["errors"])

    def test_many_unreadable_items_stop_the_folder_as_incomplete(self):
        items = [mk_item(f"M{i}", f"s{i}", dt(4, 1) , "Zed", "Owner Taro") for i in range(1, 4)]
        st = T.new_scan_state()
        restricted_items = FakeItems(items, [])

        class Bad(FakeRestricted):
            def Item(self, i):
                raise FakeComError(SECRET_ERR)

            def GetNext(self):
                raise FakeComError(SECRET_ERR)

        class F:
            class Items:
                @staticmethod
                def Restrict(flt):
                    return Bad(items, "x")
        old = T.MAX_ITEM_SKIP
        T.MAX_ITEM_SKIP = 1
        try:
            T.scan_folder_items(F, datetime(2024, 1, 1), datetime(2025, 1, 1), st, total_hint=3)
        finally:
            T.MAX_ITEM_SKIP = old
        self.assertFalse(st["complete"])
        self.assertEqual([r["e"] for r in st["records"]], ["M1"])

    def test_stores_and_skip_stores_filters(self):
        ns = self.standard_namespace()
        com, _ = fake_com(ns)
        run_main(self.argv("--no-stage2", "--stores", "2024_q2"), com)
        self.assertEqual({c["store_name"] for c in self.caches()}, {"2024_Q2"})

    def test_no_com_available(self):
        orig = T.import_com
        T.import_com = lambda: (None, None)
        try:
            code, out = run_main(self.argv("--no-stage2"))
        finally:
            T.import_com = orig
        self.assertEqual(code, 2)
        self.assertIn("win32com", out)

    def test_outlook_connection_failure(self):
        class BadClient:
            def Dispatch(self, n):
                raise FakeComError(SECRET_ERR)
        pc = FakePythonCom()
        code, out = run_main(self.argv("--no-stage2"), (BadClient(), pc))
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET_ERR, out)
        self.assertEqual(pc.uninit, 1)


# ============================================================
# 第2段・評価のみ・open
# ============================================================
class TestStage2AndModes(ComTestBase):
    def scan_first(self):
        com, _ = fake_com(self.standard_namespace())
        run_main(self.argv("--no-stage2"), com)

    def stage2_ns(self, **kw):
        sid_mb, sid_pst = "SID-user@example.com", "SID-2024_Q2"
        body = "please see customs and 通関 and hold " + SECRET
        full = lambda eid, s_addr, recips, **r: FakeItem(
            {"Class": 43, "EntryID": eid, "SenderEmailAddress": s_addr, "SenderEmailType": "SMTP",
             "PropertyAccessor": FakePA({T.PR_SENDER_SMTP: s_addr, T.PR_INTERNET_MESSAGE_ID: "<id@x>"}),
             "Recipients": FakeRecipients(recips), "Attachments": FakeAtts(["a.pdf", "b.xlsx"]),
             "Body": body}, raises=r, stage1=False)
        by_id = {
            ("E1", sid_mb): full("E1", "pm@example.com", [("Owner Taro", "owner@example.com", 1), ("Tanaka Partner", "", 2)], **kw),
            ("E2", sid_mb): full("E2", "owner@example.com", [("Sato Pm", "pm@example.com", 1)]),
            ("P2", sid_pst): full("P2", "pm@example.com", [("Owner Taro", "owner@example.com", 1)]),
        }
        return FakeNamespace([], by_id)

    def test_stage2_fills_cache_without_body_text_and_reevaluates(self):
        self.scan_first()
        ns = self.stage2_ns()
        com, pc = fake_com(ns)
        code, out = run_main(self.argv("--evaluate-only"), None)      # 評価のみ（COMなし）
        self.assertEqual(code, 0)
        code, out = run_main(self.argv(), com)  # 走査はスキップ → 第2段
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET, out)
        self.assertNotIn("pm@example.com", out)
        self.assertEqual(ACCESSED, [])
        raw = _rd(self.paths()["stage2_cache"])
        self.assertNotIn(SECRET, raw)                                  # 本文は保存しない
        st2 = _rj(self.paths()["stage2_cache"])
        self.assertEqual(len(st2), 3)
        k = T.stage2_key("SID-user@example.com", "E1")
        r = st2[k]
        self.assertEqual(r["s"], "pm@example.com")
        self.assertEqual(r["to"], [{"n": "Owner Taro", "a": "owner@example.com"}])
        self.assertEqual(r["cc"][0]["n"], "Tanaka Partner")
        self.assertEqual(r["att"], ["a.pdf", "b.xlsx"])
        self.assertEqual(r["imid"], "<id@x>")
        self.assertEqual(r["hits"], {"通関": 1, "hold": 1})
        self.assertEqual(r["bh"], T.load_theme(self.theme_path)["dict_hash"])

    def test_stage2_no_body_skips_body_and_second_run_reuses(self):
        self.scan_first()
        ns = self.stage2_ns()
        com, _ = fake_com(ns)
        run_main(self.argv("--no-body"), com)
        st2 = _rj(self.paths()["stage2_cache"])
        self.assertTrue(all(v["hits"] == {} and v["bh"] is None for v in st2.values()))
        # --no-body の再実行は取得済みをスキップ。本文ありで再実行すると取り直す
        ns2 = self.stage2_ns()
        ns2.by_id[("E1", "SID-user@example.com")] = FakeComError("must not be opened")
        com2, _ = fake_com(ns2)
        code, out = run_main(self.argv("--no-body"), com2)
        self.assertEqual(code, 0)
        self.assertIn("取得済みスキップ 3", out)
        ns3 = self.stage2_ns()
        com3, _ = fake_com(ns3)
        run_main(self.argv(), com3)
        st3 = _rj(self.paths()["stage2_cache"])
        self.assertEqual(st3[T.stage2_key("SID-user@example.com", "E1")]["hits"], {"通関": 1, "hold": 1})

    def test_stage2_item_errors_swallowed_and_kinds_only(self):
        self.scan_first()
        ns = self.stage2_ns(Body=FakeComError(SECRET_ERR), Attachments=FakeComError(SECRET_ERR),
                            Recipients=FakeComError(SECRET_ERR))
        ns.by_id[("E2", "SID-user@example.com")] = FakeComError(SECRET_ERR)     # 開けないメール
        com, _ = fake_com(ns)
        code, out = run_main(self.argv(), com)
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET_ERR, out)
        self.assertIn("FakeComError", out)
        self.assertIn("開けず 1通", out)
        st2 = _rj(self.paths()["stage2_cache"])
        self.assertEqual(len(st2), 2)

    def test_stage2_keyboard_interrupt_saves(self):
        self.scan_first()
        ns = self.stage2_ns()
        ns.by_id[("E2", "SID-user@example.com")] = KeyboardInterrupt()
        com, pc = fake_com(ns)
        code, out = run_main(self.argv(), com)
        self.assertEqual(code, 130)
        st2 = _rj(self.paths()["stage2_cache"])
        self.assertGreaterEqual(len(st2), 1)
        self.assertEqual(pc.uninit, 2)   # 走査(スキップ)と第2段で各1回

    def test_no_stage2_does_not_open_items_but_uses_existing_cache(self):
        self.scan_first()
        com, _ = fake_com(self.stage2_ns())
        run_main(self.argv(), com)
        ns = self.stage2_ns()
        ns.by_id.clear()            # 開こうとすれば FakeComError になる
        com2, pc2 = fake_com(ns)
        code, out = run_main(self.argv("--no-stage2"), com2)
        self.assertEqual(code, 0)
        self.assertIn("既存の第2段キャッシュ", out)
        self.assertNotIn("第2段: 対象メール", out)
        self.assertNotIn("FakeComError", out)

    def test_evaluate_only_never_touches_com(self):
        self.scan_first()
        orig = T.import_com
        T.import_com = lambda: (_ for _ in ()).throw(AssertionError("COMを使ってはいけない"))
        try:
            code, out = run_main(self.argv("--evaluate-only"))
        finally:
            T.import_com = orig
        self.assertEqual(code, 0)
        self.assertIn("候補スレッド", out)

    def test_evaluate_only_without_cache(self):
        code, out = run_main(self.argv("--evaluate-only"))
        self.assertEqual(code, 2)
        self.assertIn("走査キャッシュがありません", out)

    def test_judgments_preserved_across_reevaluation(self):
        self.scan_first()
        run_main(self.argv("--evaluate-only"))
        jp = os.path.join(self.data, "judgments_theme.json")
        j = _rj(jp)
        tid = sorted(j)[0]
        j[tid]["確認結果"] = "本物"
        j[tid]["メモ"] = "手編集"
        _wj(jp, j)
        run_main(self.argv("--evaluate-only"))
        run_main(self.argv("--evaluate-only", "--rescan"))
        j2 = _rj(jp)
        self.assertEqual(j2[tid]["確認結果"], "本物")
        self.assertEqual(j2[tid]["メモ"], "手編集")
        newest = sorted(f for f in os.listdir(self.out) if f.startswith("thread_ledger_theme_"))[-1]
        rows = _rdict(os.path.join(self.out, newest))
        self.assertEqual([r["確認結果(本物/違う/保留)"] for r in rows if r["thread_id"] == tid], ["本物"])

    def test_theme_edit_changes_evaluation_without_rescan(self):
        self.scan_first()
        run_main(self.argv("--evaluate-only"))
        self.theme_data["owner"] = {"name_aliases": ["Nobody Here"]}
        _wj(self.theme_path, self.theme_data)
        code, out = run_main(self.argv("--evaluate-only"))
        self.assertIn("候補スレッド(A∧B∧C): 0件", out)

    def test_check_subjects_command_prints_subjects_only_on_console_and_no_scan(self):
        self.scan_first()
        cal = os.path.join(self.tmp.name, "cal.txt")
        _wr(cal, f"# c\nRE: {SECRET} 通関\nnot in cache subject xyz\nLunch\n")
        orig = T.import_com
        T.import_com = lambda: (_ for _ in ()).throw(AssertionError("COM禁止"))
        try:
            code, out = run_main(self.argv("--check-subjects", cal))
        finally:
            T.import_com = orig
        self.assertEqual(code, 0)
        self.assertIn(SECRET, out)                       # この出力だけは件名を表示
        self.assertIn("キャッシュに無い", out)
        self.assertIn("あるが候補外", out)
        self.assertIn("順位", out)
        log = sorted(f for f in os.listdir(self.out) if f.endswith(".log"))[-1]
        logtext = _rd(os.path.join(self.out, log), "utf-8-sig")
        self.assertNotIn(SECRET, logtext)                # ログには件名を残さない
        self.assertIn("再現率チェック", logtext)

    def test_open_uses_ledger_and_only_displays(self):
        self.scan_first()
        run_main(self.argv("--evaluate-only"))
        led = sorted(f for f in os.listdir(self.out) if f.startswith("thread_ledger_theme_"))[-1]
        rows = _rdict(os.path.join(self.out, led))
        row = rows[0]
        shown = []
        item = FakeItem({"EntryID": row["最新メールEntryID"]}, display_log=shown)
        ns = FakeNamespace([], {(row["最新メールEntryID"], row["最新メールStoreID"]): item})
        com, pc = fake_com(ns)
        code, out = run_main(["--open", row["thread_id"], "--data-dir", self.data, "--output-dir", self.out], com)
        self.assertEqual(code, 0)
        self.assertEqual(shown, [row["最新メールEntryID"]])
        self.assertEqual(ACCESSED, [])
        self.assertEqual(pc.uninit, 1)

    def test_open_unknown_thread_and_fallback_to_cache(self):
        self.scan_first()
        com, _ = fake_com(FakeNamespace([], {}))
        code, out = run_main(["--open", "zzzzzzzzzzzz", "--data-dir", self.data, "--output-dir", self.out], com)
        self.assertEqual(code, 2)
        # 台帳CSVが無くてもキャッシュから引ける
        mails, _s = T.merge_caches_to_mails(self.caches(), (2024, 1), (2024, 12))
        t = T.build_threads(mails)[0]
        eid, sid = t["mails"][-1]["locs"][0]["eid"], t["mails"][-1]["locs"][0]["sid"]
        self.assertEqual(T.find_thread_in_cache(self.paths(), t["id"], (2024, 1), (2024, 12)), (eid, sid))

    def test_missing_theme_guides_to_example(self):
        code, out = run_main(["--data-dir", self.data, "--output-dir", self.out, "--evaluate-only"])
        self.assertEqual(code, 2)
        self.assertIn("thread_ledger_theme.example.json", out)

    def test_invalid_period_arg(self):
        code, out = run_main(self.argv("--from", "2025-01", "--to", "2024-01", "--evaluate-only"))
        self.assertEqual(code, 2)

    def test_coverage_csv_flags_empty_months(self):
        self.scan_first()
        run_main(self.argv("--evaluate-only"))
        cov = sorted(f for f in os.listdir(self.out) if f.startswith("coverage_"))[-1]
        rows = _rdict(os.path.join(self.out, cov))
        allrows = {r["年月"]: r for r in rows if r["ストア"] == "(全ストア)"}
        self.assertIn("未取得の恐れ", allrows["2024-02"]["備考"])
        self.assertEqual(allrows["2024-04"]["備考"], "")


class FakePA:
    def __init__(self, props):
        self.props = props

    def GetProperty(self, url):
        if url not in self.props:
            raise FakeComError(SECRET_ERR)
        return self.props[url]


class FakeRecipient:
    def __init__(self, name, addr, typ):
        self.Name = name
        self.Type = typ
        self.Address = addr
        self.PropertyAccessor = FakePA({T.PR_RECIP_SMTP: addr} if addr else {})


class FakeRecipients:
    def __init__(self, recips):
        self.r = [FakeRecipient(*x) for x in recips]

    @property
    def Count(self):
        return len(self.r)

    def Item(self, i):
        return self.r[i - 1]


class FakeAttachment:
    def __init__(self, name):
        self.FileName = name


class FakeAtts:
    def __init__(self, names):
        self.a = [FakeAttachment(n) for n in names]

    @property
    def Count(self):
        return len(self.a)

    def Item(self, i):
        return self.a[i - 1]


class TestReadStage2Item(unittest.TestCase):
    def test_fallback_chain_for_sender_and_recipient_smtp(self):
        class Entry:
            def GetExchangeUser(self):
                class U:
                    PrimarySmtpAddress = "Ex.User@Example.com"
                return U()

        class RecipEx:
            Name = "Ex Person"
            Type = 1
            Address = "/O=EXCH/CN=X"
            AddressEntry = Entry()
            PropertyAccessor = FakePA({})

        class Recs:
            Count = 1

            def Item(self, i):
                return RecipEx()

        item = FakeItem({"SenderEmailAddress": "/O=EXCH/CN=Y", "SenderEmailType": "EX", "Sender": Entry(),
                         "PropertyAccessor": FakePA({}), "Recipients": Recs(), "Attachments": FakeAtts([]),
                         "Body": "x"}, stage1=False)
        errs = {}
        r = T.read_stage2_item(item, make_theme(), False, errs)
        self.assertEqual(r["s"], "ex.user@example.com")
        self.assertEqual(r["to"], [{"n": "Ex Person", "a": "ex.user@example.com"}])
        self.assertTrue(all(SECRET_ERR not in k for k in errs))
        self.assertIn("送信者SMTP(PA):FakeComError", errs)

    def test_bcc_ignored(self):
        item = FakeItem({"SenderEmailAddress": "a@example.com", "PropertyAccessor": FakePA({}),
                         "Recipients": FakeRecipients([("X", "x@example.com", 3), ("Y", "y@example.com", 1)]),
                         "Attachments": FakeAtts([]), "Body": ""}, stage1=False)
        r = T.read_stage2_item(item, make_theme(), True, {})
        self.assertEqual([x["n"] for x in r["to"]], ["Y"])
        self.assertEqual(r["cc"], [])
        self.assertEqual(r["s"], "a@example.com")


class TestReporterAndMisc(unittest.TestCase):
    def test_error_kind_never_includes_message(self):
        self.assertEqual(T.error_kind(FakeComError(SECRET_ERR)), "FakeComError")
        self.assertEqual(T.error_kind(FakeComError(-2147221233, SECRET_ERR)), "FakeComError(0x8004010F)")

    def test_format_duration(self):
        self.assertEqual(T.format_duration(0.5), "0.500秒")
        self.assertEqual(T.format_duration(65), "1分05秒")
        self.assertEqual(T.format_duration(3720), "1時間02分")
        self.assertEqual(T.format_duration(None), "-")

    def test_reporter_console_not_in_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.log")
            rep = T.Reporter(p)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rep.log("logged")
                rep.console("consoleonly")
            rep.close()
            self.assertIn("consoleonly", buf.getvalue())
            self.assertEqual(_rd(p, "utf-8-sig").strip(), "logged")

    def test_reporter_unwritable_path_does_not_crash(self):
        rep = T.Reporter("/proc/nonexistent_dir/x.log")
        with contextlib.redirect_stdout(io.StringIO()):
            rep.log("x")
        rep.close()

    def test_mask_emails(self):
        self.assertEqual(T.mask_emails("a@b.com / 2024_Q2"), "<MAIL> / 2024_Q2")


# ============================================================
# レビュー指摘への対応（M1〜M8・任意改善・安全性）
# ============================================================
class TestStoreIdentity(unittest.TestCase):
    """M1: 同名ストアのキャッシュが消えない（識別はStoreID+FilePath）"""

    def two_caches(self):
        a = cache("PST", 1, "\\(ルート直下)", [rec("A1", "通関 alpha topic", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro", cid="X1")],
                  sid="SID-A")
        b = cache("PST", 2, "\\(ルート直下)", [rec("B1", "通関 beta topic", "2024-04-11T09:00:00", "Sato Pm", "Owner Taro", cid="X2")],
                  sid="SID-B")
        return a, b

    def test_both_survive_with_unique_labels(self):
        a, b = self.two_caches()
        sel = T.select_caches([a, b], [], [], [], [], [])
        self.assertEqual(sorted(c["store_label"] for c in sel), ["PST", "PST #2"])
        res, _ = build([a, b])
        self.assertEqual(len(res["mails"]), 2)
        self.assertEqual(res["stats"]["raw_by_store_month"][("PST", (2024, 4))], 1)
        self.assertEqual(res["stats"]["raw_by_store_month"][("PST #2", (2024, 4))], 1)
        self.assertEqual({m["locs"][0]["store"] for m in res["mails"]}, {"PST", "PST #2"})

    def test_same_name_same_path_not_merged_as_dup_and_filter_by_label(self):
        a, b = self.two_caches()
        b["records"][0].update({"s": a["records"][0]["s"], "t": a["records"][0]["t"], "e": "B1"})
        res, _ = build([a, b])
        self.assertEqual(res["stats"]["cross_store"], 1)      # 別ストアなので統合（重複）
        self.assertEqual(len(res["mails"]), 1)
        self.assertEqual({l["store"] for l in res["mails"][0]["locs"]}, {"PST", "PST #2"})
        sel = T.select_caches([a, b], ["#2"], [], [], [], [])
        self.assertEqual([c["store_label"] for c in sel], ["PST #2"])
        sel = T.select_caches([a, b], [], ["#2"], [], [], [])
        self.assertEqual([c["store_label"] for c in sel], ["PST"])

    def test_filepath_distinguishes_when_store_id_same(self):
        a, b = self.two_caches()
        a["store_id"] = b["store_id"] = "SAME"
        a["file_path"], b["file_path"] = "C:\\a.pst", "C:\\b.pst"
        self.assertEqual(len(T.select_caches([a, b], [], [], [], [], [])), 2)

    def test_assign_labels_order_and_third(self):
        lab = T.assign_store_labels([("i3", "X", 3), ("i1", "X", 1), ("i2", "Y", 2), ("i4", "X", 4)])
        self.assertEqual(lab, {"i1": "X", "i3": "X #2", "i2": "Y", "i4": "X #3"})


class TestDedupeKeepsDistinctMails(unittest.TestCase):
    """M3: 同一ストア内でEntryIDが異なるメールは別メール。統合時のTo/CCは和集合"""

    def test_same_second_subject_sender_different_to_same_store_kept_separate(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "Topic long subject", "2024-04-10T09:00:00", "Sato", "Alice One"),
                                       rec("E2", "Topic long subject", "2024-04-10T09:00:00", "Sato", "Bob Two")])
        mails, st = T.merge_caches_to_mails([a], (2024, 1), (2024, 12))
        self.assertEqual(len(mails), 2)
        self.assertEqual(st["same_store"], 1)
        self.assertEqual(sorted(m["to"] for m in mails), ["Alice One", "Bob Two"])

    def test_cross_store_merge_unions_to_and_cc(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "Topic long subject", "2024-04-10T09:00:00", "Sato", "Alice One; Bob Two", "Cc One")])
        b = cache("PST", 2, "\\(ルート直下)", [rec("P1", "RE: Topic long subject", "2024-04-10T09:00:00", "Sato", "Bob Two; Carol Three", "Cc Two")])
        mails, st = T.merge_caches_to_mails([a, b], (2024, 1), (2024, 12))
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["to"], "Alice One; Bob Two; Carol Three")
        self.assertEqual(mails[0]["cc"], "Cc One; Cc Two")
        self.assertEqual(st["cross_store"], 1)

    def test_union_names_fullwidth_and_empty(self):
        self.assertEqual(T.union_names("A One", "ａ　ｏｎｅ; B Two"), "A One; B Two")
        self.assertEqual(T.union_names("", "X"), "X")
        self.assertEqual(T.union_names("", ""), "")


class TestJudgmentsFile(unittest.TestCase):
    """M2: 判定JSONの破損で全消去しない"""

    def test_load_judgments_status(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "j.json")
            self.assertEqual(T.load_judgments(p), ({}, "new"))
            _wr(p, "")
            self.assertEqual(T.load_judgments(p)[1], "broken")
            _wr(p, "   \n")
            self.assertEqual(T.load_judgments(p)[1], "broken")
            _wr(p, "{broken")
            self.assertEqual(T.load_judgments(p)[1], "broken")
            _wr(p, "[1, 2]")
            self.assertEqual(T.load_judgments(p)[1], "broken")
            _wr(p, '{"a": {"メモ": "x"}}')
            self.assertEqual(T.load_judgments(p), ({"a": {"メモ": "x"}}, "ok"))

    def test_backup_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "j.json")
            _wr(p, "{broken")
            bak = T.backup_file(p)
            self.assertTrue(".bak_" in bak and _rd(bak) == "{broken")
            self.assertEqual(_rd(p), "{broken")                      # 元は触らない
            self.assertIsNone(T.backup_file(os.path.join(d, "nothing.json")))

    def test_partially_invalid_entries_are_kept_untouched(self):
        existing = {"t1": "oops", "t2": {"確認結果": "本物"}, "t3": None, "t4": [1]}
        merged, added = T.merge_judgments(existing, ["t1", "t2", "new"])
        self.assertEqual(merged["t1"], "oops")
        self.assertIsNone(merged["t3"])
        self.assertEqual(merged["t4"], [1])
        self.assertEqual(merged["t2"]["確認結果"], "本物")
        self.assertEqual(added, 1)
        th = make_theme()
        recs = [rec("E1", "通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        tid = res["threads"][0]["id"]
        rows = T.build_ledger_rows(res["threads"], res["evals"], {tid: "oops"}, th)    # 形が不正でも落ちない
        self.assertEqual(rows[0][T.LEDGER_COLUMNS.index("確認結果(本物/違う/保留)")], "")


class TestSafetyAndOptions(ComTestBase):
    def scan_first(self):
        com, _ = fake_com(self.standard_namespace())
        run_main(self.argv("--no-stage2"), com)

    def test_broken_and_empty_judgments_not_overwritten(self):
        self.scan_first()
        run_main(self.argv("--evaluate-only"))
        jp = os.path.join(self.data, "judgments_theme.json")
        for content in ("{broken", ""):
            _wr(jp, content)
            code, out = run_main(self.argv("--evaluate-only"))
            self.assertEqual(code, 0)
            self.assertEqual(_rd(jp), content)                                   # 上書きしない
            self.assertIn("判定ファイルを読めません", out)
            self.assertTrue(any(".bak_" in f for f in os.listdir(self.data)))
            self.assertTrue(any(f.startswith("thread_ledger_theme_") for f in os.listdir(self.out)))

    def test_stage2_guard_blocks_large_run_and_yes_overrides(self):
        self.scan_first()
        ns = Stage2Helper.namespace()
        com, pc = fake_com(ns)
        code, out = run_main(self.argv("--stage2-max", "1"), com)
        self.assertEqual(code, 3)
        self.assertIn("--stage2-max", out)
        self.assertIn("--yes", out)
        self.assertIn("--stage2-scope candidate", out)
        self.assertIn("概算", out)
        self.assertEqual(ns.opened, [])
        self.assertFalse(os.path.exists(self.paths()["stage2_cache"]))
        self.assertTrue(any(f.startswith("thread_ledger_theme_") for f in os.listdir(self.out)))   # 第1段の結果は出力する
        code, out = run_main(self.argv("--stage2-max", "1", "--yes"), fake_com(Stage2Helper.namespace())[0])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.paths()["stage2_cache"]))

    def test_stage2_candidate_scope_is_smaller_and_allowed_under_limit(self):
        self.scan_first()
        ns = Stage2Helper.namespace()
        code, out = run_main(self.argv("--stage2-max", "5", "--stage2-scope", "candidate"), fake_com(ns)[0])
        self.assertEqual(code, 0)
        self.assertEqual(len(ns.opened), 3)        # 候補スレッド(C1: E1,E2 / C2: P2)の3通

    def test_stage2_saved_in_big_batches_only(self):
        self.assertEqual(T.STAGE2_SAVE_EVERY, 1000)
        self.scan_first()
        saved = []
        orig = T.write_json_atomic
        T.write_json_atomic = lambda path, obj: (saved.append(path) if "stage2" in path else None, orig(path, obj))[1]
        try:
            run_main(self.argv(), fake_com(Stage2Helper.namespace())[0])
        finally:
            T.write_json_atomic = orig
        self.assertEqual(len(saved), 1)            # 3通なので終了時の1回だけ

    def test_stage2_error_records_are_flagged_and_refetched(self):
        self.scan_first()
        ns = Stage2Helper.namespace(Body=FakeComError(SECRET_ERR))
        run_main(self.argv(), fake_com(ns)[0])
        st2 = _rj(self.paths()["stage2_cache"])
        self.assertTrue(st2[T.stage2_key("SID-user@example.com", "E1")]["retry"])
        self.assertFalse(st2[T.stage2_key("SID-user@example.com", "E2")]["retry"])
        ns2 = Stage2Helper.namespace()
        run_main(self.argv(), fake_com(ns2)[0])
        self.assertEqual(ns2.opened, [("E1", "SID-user@example.com")])         # エラーだった1通だけ取り直す
        st3 = _rj(self.paths()["stage2_cache"])
        self.assertFalse(st3[T.stage2_key("SID-user@example.com", "E1")]["retry"])

    def test_stale_dictionary_hits_ignored_and_warned(self):
        self.scan_first()
        run_main(self.argv(), fake_com(Stage2Helper.namespace())[0])
        self.theme_data["keywords"] = {"通関": {"weight": 3, "strong": ["通関"], "weak": ["hold", "extra"]}}
        _wj(self.theme_path, self.theme_data)
        code, out = run_main(self.argv("--evaluate-only"))
        self.assertEqual(code, 0)
        self.assertIn("辞書が変わる前に本文照合した第2段レコードが 3通", out)

    def test_folders_are_fetched_by_id_and_com_refs_released(self):
        import gc
        PROXIES.clear()
        ns = self.standard_namespace()
        com, pc = fake_com(ns)
        run_main(self.argv("--no-stage2"), com)
        self.assertEqual(len(ns.folder_fetches), 2)               # Inbox と PST の(ルート直下)
        gc.collect()
        self.assertTrue(PROXIES and all(r() is None for r in PROXIES))
        task_like = T.enumerate_mail_folders(ns.Stores.Item(1).GetRootFolder(), "SID", [], [], {}, {})
        self.assertTrue(task_like and all("com" not in f and f["eid"] and f["sid"] == "SID" for f in task_like))

    def test_cache_replaced_via_part_file_when_range_changes(self):
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 6)]
        com, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", list(items)))]))
        run_main(self.argv("--no-stage2"), com)
        old = self.caches()[0]
        self.assertEqual(old["range"], ["2024-01", "2024-12"])
        # 期間を広げて再取得 -> Ctrl+C で中断しても、完了済みの旧キャッシュは壊れない
        bad = list(items)
        bad[3] = mk_item("M4", "s4", dt(4, 4), "Zed", "Owner Taro", raises={"Subject": KeyboardInterrupt()})
        com2, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", bad))]))
        self.assertEqual(run_main(self.argv("--no-stage2", "--from", "2023-01"), com2)[0], 130)
        cur = self.caches()[0]
        self.assertEqual((cur["range"], cur["complete"], len(cur["records"])), (["2024-01", "2024-12"], True, 5))
        parts = [f for f in os.listdir(self.paths()["scan_cache"]) if f.endswith(".part")]
        self.assertEqual(len(parts), 1)
        com3, _ = fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", list(items)))]))
        self.assertEqual(run_main(self.argv("--no-stage2", "--from", "2023-01"), com3)[0], 0)
        new = self.caches()[0]
        self.assertEqual((new["range"], new["complete"]), (["2023-01", "2024-12"], True))
        self.assertEqual([f for f in os.listdir(self.paths()["scan_cache"]) if f.endswith(".part")], [])

    def test_mask_names_hides_store_and_folder_names_in_console_and_log_but_not_csv(self):
        com, _ = fake_com(self.standard_namespace())
        code, out = run_main(self.argv("--no-stage2", "--mask-names"), com)
        self.assertEqual(code, 0)
        self.assertIn("Store-01", out)
        self.assertIn("Folder-001", out)
        for secret in ("2024_Q2", "Inbox", "ルート直下", "user@example.com"):
            self.assertNotIn(secret, out)
        log = sorted(f for f in os.listdir(self.out) if f.endswith(".log"))[-1]
        logtext = _rd(os.path.join(self.out, log), "utf-8-sig")
        for secret in ("2024_Q2", "Inbox", "user@example.com"):
            self.assertNotIn(secret, logtext)
        led = sorted(f for f in os.listdir(self.out) if f.startswith("thread_ledger_theme_"))[-1]
        csv_text = _rd(os.path.join(self.out, led), "utf-8-sig")
        self.assertTrue("2024_Q2" in csv_text or "user@example.com" in csv_text)           # CSVには元の名前
        T.configure_masking(False)

    def test_same_display_name_pst_stores_end_to_end(self):
        r1 = FakeFolder("root", [mk_item("A1", "通関 alpha subject", dt(4, 10), "Sato Pm", "Owner Taro", cid="X1")])
        r2 = FakeFolder("root", [mk_item("B1", "通関 beta subject", dt(4, 11), "Sato Pm", "Owner Taro", cid="X2")])
        ns = FakeNamespace([FakeStore("PST", r1, sid="SID-A", path="C:\\a.pst"),
                            FakeStore("PST", r2, sid="SID-B", path="C:\\b.pst")])
        code, out = run_main(self.argv("--no-stage2"), fake_com(ns)[0])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.caches()), 2)
        self.assertIn("PST #2", out)
        led = sorted(f for f in os.listdir(self.out) if f.startswith("thread_ledger_theme_"))[-1]
        rows = _rdict(os.path.join(self.out, led))
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("PST #2" in r["取得元(ストア/フォルダ)"] for r in rows))
        run_main(self.argv("--evaluate-only", "--stores", "#2"))
        led2 = sorted(f for f in os.listdir(self.out) if f.startswith("thread_ledger_theme_"))[-1]
        self.assertEqual(len(_rdict(os.path.join(self.out, led2))), 1)

    def test_cli_alias_and_defaults(self):
        a = T.parse_args(["--candidate-terms"])
        self.assertTrue(a.suggest_terms)
        self.assertEqual((a.stage2_max, a.yes, a.mask_names), (5000, False, False))
        self.assertTrue(T.parse_args(["--suggest-terms"]).suggest_terms)


class Stage2Helper:
    """第2段のフェイク名前空間（開いたメールを記録する）"""

    @staticmethod
    def namespace(**kw):
        sid_mb, sid_pst = "SID-user@example.com", "SID-2024_Q2"
        body = "please see 通関 and hold"

        def full(eid, s_addr, recips, **r):
            return FakeItem({"Class": 43, "EntryID": eid, "SenderEmailAddress": s_addr, "SenderEmailType": "SMTP",
                             "PropertyAccessor": FakePA({T.PR_SENDER_SMTP: s_addr, T.PR_INTERNET_MESSAGE_ID: "<id@x>"}),
                             "Recipients": FakeRecipients(recips), "Attachments": FakeAtts(["a.pdf"]),
                             "Body": body}, raises=r, stage1=False)
        by_id = {
            ("E1", sid_mb): full("E1", "pm@example.com", [("Owner Taro", "owner@example.com", 1)], **kw),
            ("E2", sid_mb): full("E2", "owner@example.com", [("Sato Pm", "pm@example.com", 1)]),
            ("P2", sid_pst): full("P2", "pm@example.com", [("Owner Taro", "owner@example.com", 1)]),
        }

        class Recording(FakeNamespace):
            opened = None

            def GetItemFromID(self, eid, sid):
                self.opened.append((eid, sid))
                return FakeNamespace.GetItemFromID(self, eid, sid)
        ns = Recording([], by_id)
        ns.opened = []
        return ns


class TestOptionalImprovements(unittest.TestCase):
    def test_classify_exact_preferred_and_partial_skips_generic(self):
        th = make_theme()
        recs = [
            rec("E1", "Weekly lunch plan arrangement", "2024-04-10T09:00:00", "Zed", "Zed", cid="a"),               # 候補外(完全一致)
            rec("E2", "Weekly lunch plan arrangement and more", "2024-04-11T09:00:00", "Sato Pm", "Owner Taro; Tanaka Partner", cid="b"),  # 候補(部分一致側)
        ]
        res, _ = build([cache("S", 1, "\\Inbox", recs)], th)
        r = T.classify_check_subjects(["Weekly lunch plan arrangement"], res["threads"], res["evals"])[0]
        self.assertEqual(r["status"], "found_not_candidate")     # 完全一致が候補外なら、部分一致の候補があっても found にしない
        self.assertEqual([m["kind"] for m in r["matches"]], ["完全一致"])
        r2 = T.classify_check_subjects(["lunch"], res["threads"], res["evals"])[0]
        self.assertEqual(r2["status"], "missing")                # 短い汎用件名は部分一致しない
        r3 = T.classify_check_subjects(["Weekly lunch plan arrangement and"], res["threads"], res["evals"])[0]
        self.assertEqual(r3["status"], "found")                  # 十分に長ければ部分一致する
        self.assertEqual(r3["matches"][0]["kind"], "部分一致")

    def test_generic_subjects_not_used_for_thread_grouping(self):
        a = cache("MB", 1, "\\Inbox", [rec("E1", "FYI", "2024-04-10T09:00:00", "A"), rec("E2", "RE: FYI", "2024-04-11T09:00:00", "B"),
                                       rec("E3", "お疲れ様です", "2024-04-12T09:00:00", "A"), rec("E4", "short", "2024-04-13T09:00:00", "A"),
                                       rec("E5", "Quarterly review meeting", "2024-04-14T09:00:00", "A"),
                                       rec("E6", "RE: Quarterly review meeting", "2024-04-15T09:00:00", "B")])
        mails, _ = T.merge_caches_to_mails([a], (2024, 1), (2024, 12))
        threads = T.build_threads(mails)
        self.assertEqual(sorted(t["count"] for t in threads), [1, 1, 1, 1, 2])
        self.assertTrue(T.is_generic_subject("short"))
        self.assertTrue(T.is_generic_subject("meeting"))
        self.assertFalse(T.is_generic_subject("quarterly review meeting"))

    def test_name_matches_is_memoized(self):
        T.name_matches.cache_clear()
        T.name_matches("Zed Alias", "Zed Alias Person")
        T.name_matches("Zed Alias", "Zed Alias Person")
        self.assertGreaterEqual(T.name_matches.cache_info().hits, 1)

    def test_store_zero_months(self):
        stats = {"raw_by_store_month": {("A", (2024, 1)): 3, ("A", (2024, 3)): 1}}
        z = T.store_zero_months(stats, [(2024, 1), (2024, 2), (2024, 3)], ["A", "B"])
        self.assertEqual(z["A"], [(2024, 2)])
        self.assertEqual(len(z["B"]), 3)

    def test_resume_does_not_double_count_errors(self):
        cache_ = {"records": [{"e": "E1", "t": "2024-04-01T09:00:00"}], "last_received": "2024-04-01T09:00:00",
                  "counts": {"non_mail": 2, "errors": {"Subject:X": 2}}, "date_field": "or"}
        st = T.new_scan_state(cache_)
        self.assertEqual(st["errors"], {})
        T.add_error(st["errors"], "Subject:X")
        task = {"sidx": 1, "store_name": "S", "store_id": "I", "folder_path": "\\F"}
        p1 = T.make_cache_payload(task, st, (2024, 1), (2024, 12), False)
        p2 = T.make_cache_payload(task, st, (2024, 1), (2024, 12), False)      # 保存を繰り返しても増えない
        self.assertEqual(p1["counts"]["errors"], {"Subject:X": 3})
        self.assertEqual(p2["counts"]["errors"], {"Subject:X": 3})

    def test_known_items_skipped_without_reading_other_fields(self):
        item = mk_item("K1", SECRET, dt(4, 1), "Zed", "Owner Taro", raises={"Subject": FakeComError(SECRET_ERR)})
        errs = {}
        self.assertEqual(T.read_light_item(item, errs, {"K1"}), ("dup", None))
        self.assertEqual(errs, {})

    def test_pattern_safety_and_length_caps(self):
        with self.assertRaises(T.ThemeError):
            make_theme(patterns=[{"category": "c", "regex": "(a+)+$", "strong": True}])
        with self.assertRaises(T.ThemeError):
            make_theme(patterns=[{"category": "c", "regex": "a" * 300, "strong": True}])
        make_theme(patterns=[{"category": "c", "regex": r"\b\d{4}\.\d{2}(\.\d{2,4})?\b", "strong": False}])   # 通常の式は可
        tbl = make_theme()["hit_table"]
        self.assertEqual(T.scan_text_hits("x" * (T.MAX_BODY_CHARS + 10) + " 通関", tbl), {})            # 本文の上限
        th = make_theme()
        recs = [rec("E1", "x" * 400 + " 通関", "2024-04-10T09:00:00", "Sato Pm", "Owner Taro")]
        _, e = one_thread(recs, th)
        self.assertFalse(e["C_ii"])                                                                      # 件名は300字まで

    def test_write_json_atomic_fsync(self):
        calls = []
        orig = os.fsync
        os.fsync = lambda fd: calls.append(fd)
        try:
            with tempfile.TemporaryDirectory() as d:
                T.write_json_atomic(os.path.join(d, "a.json"), {"x": 1})
                self.assertEqual(_rj(os.path.join(d, "a.json")), {"x": 1})
        finally:
            os.fsync = orig
        self.assertEqual(len(calls), 1)

    def test_no_real_surnames_in_repo_files(self):
        import re
        words = ["中" + "井", "梶" + "川", "佐" + "治", "Na" + "kai", "Kaji" + "kawa", "Sa" + "ji", "nexp" + "eria",
                 "dhl" + r"\.com", "trade" + "win"]
        pat = re.compile("|".join(words), re.IGNORECASE)
        targets = [os.path.join(TOOLS_DIR, f) for f in ("thread_ledger_scan_20261009_01.py",
                   "thread_ledger_theme.example.json", "calibration_subjects.example.txt")] + [os.path.abspath(__file__)]
        for t in targets:
            self.assertIsNone(pat.search(_rd(t)), t)



class TestReReviewFixes(ComTestBase):
    def test_call_by_id_omits_empty_store_id(self):
        calls = []
        T.call_by_id(lambda *a: calls.append(a), "E", "")
        T.call_by_id(lambda *a: calls.append(a), "E", None)
        T.call_by_id(lambda *a: calls.append(a), "E", "S")
        self.assertEqual(calls, [("E",), ("E",), ("E", "S")])

    def test_scan_with_empty_store_id_calls_without_second_argument(self):
        root = FakeFolder("root", [mk_item("A1", "通関 x subject", dt(4, 10), "Sato Pm", "Owner Taro")])
        inbox = FakeFolder("Inbox", [mk_item("A2", "通関 y subject", dt(4, 11), "Sato Pm", "Owner Taro")])
        root.Folders.folders.append(inbox)
        ns = FakeNamespace([FakeStore("MB", root, sid="")])
        code, out = run_main(self.argv("--no-stage2"), fake_com(ns)[0])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.caches()), 2)
        self.assertTrue(all(sid is None for _e, sid in ns.folder_fetches))     # 第2引数は省略された

    def root_ns(self, lookup_fails=False):
        root = FakeFolder("root", [mk_item("A1", "通関 x subject", dt(4, 10), "Sato Pm", "Owner Taro")])
        root.EntryID = ""                       # PSTのルートでEntryIDが空
        ns = FakeNamespace([FakeStore("PST", root, sid="SID-PST", path="C:\\a.pst")])
        ns.store_lookup_fails = lookup_fails
        return ns

    def test_root_without_entry_id_uses_get_store_from_id(self):
        ns = self.root_ns()
        code, out = run_main(self.argv("--no-stage2"), fake_com(ns)[0])
        self.assertEqual(code, 0)
        self.assertEqual(ns.store_lookups, ["SID-PST"])
        self.assertEqual(len(self.caches()), 1)
        self.assertEqual(self.caches()[0]["records"][0]["e"], "A1")
        self.assertNotIn("EntryIDなし", out)

    def test_root_without_entry_id_falls_back_to_enumeration_store_ref(self):
        ns = self.root_ns(lookup_fails=True)
        code, out = run_main(self.argv("--no-stage2"), fake_com(ns)[0])
        self.assertEqual(code, 0)
        self.assertEqual(ns.store_lookups, ["SID-PST"])
        self.assertEqual(self.caches()[0]["records"][0]["e"], "A1")
        self.assertNotIn(SECRET_ERR, out)

    def test_non_root_folder_without_entry_id_is_skipped_with_error_kind(self):
        sub = FakeFolder("Sub", [mk_item("A1", "x", dt(4, 10), "Zed", "Owner Taro")])
        sub.EntryID = ""
        ns = FakeNamespace([FakeStore("MB", FakeFolder("root", [], subfolders=[sub]))])
        code, out = run_main(self.argv("--no-stage2"), fake_com(ns)[0])
        self.assertEqual(code, 2)                 # 取得できたキャッシュが無いので評価は中止
        self.assertIn("フォルダEntryIDなし", out)
        self.assertEqual(self.caches(), [])

    def test_stage2_final_save_happens_even_if_periodic_save_fails(self):
        com, _ = fake_com(self.standard_namespace())
        run_main(self.argv("--no-stage2"), com)
        old_every, orig = T.STAGE2_SAVE_EVERY, T.write_json_atomic
        calls = []

        def flaky(path, obj):
            if "stage2" in path:
                calls.append(path)
                if len(calls) == 1:
                    raise OSError(SECRET_ERR)
            return orig(path, obj)
        T.STAGE2_SAVE_EVERY, T.write_json_atomic = 1, flaky
        try:
            code, out = run_main(self.argv(), fake_com(Stage2Helper.namespace())[0])
        finally:
            T.STAGE2_SAVE_EVERY, T.write_json_atomic = old_every, orig
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET_ERR, out)
        self.assertIn("途中保存に失敗", out)
        self.assertEqual(len(_rj(self.paths()["stage2_cache"])), 3)          # 最終保存で全件が残る

    def test_incomplete_rescan_does_not_replace_old_complete_cache(self):
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 4)]
        run_main(self.argv("--no-stage2"), fake_com(FakeNamespace([FakeStore("MB", FakeFolder("root", list(items)))]))[0])
        before = self.caches()[0]
        self.assertTrue(before["complete"])
        old = T.MAX_ITEM_SKIP
        T.MAX_ITEM_SKIP = 1
        try:
            f = FakeFolder("root", list(items), next_raises=(1, FakeComError(SECRET_ERR)),
                           item_raises=FakeComError(SECRET_ERR))
            code, out = run_main(self.argv("--no-stage2", "--from", "2023-01"),
                                 fake_com(FakeNamespace([FakeStore("MB", f)]))[0])
        finally:
            T.MAX_ITEM_SKIP = old
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET_ERR, out)
        cur = self.caches()[0]
        self.assertEqual((cur["range"], cur["complete"], len(cur["records"])), (["2024-01", "2024-12"], True, 3))
        parts = [x for x in os.listdir(self.paths()["scan_cache"]) if x.endswith(".part")]
        self.assertEqual(len(parts), 1)
        part = _rj(os.path.join(self.paths()["scan_cache"], parts[0]))
        self.assertFalse(part["complete"])
        self.assertEqual(part["range"], ["2023-01", "2024-12"])

    def test_count_failure_does_not_mark_folder_complete(self):
        items = [mk_item(f"M{i}", f"s{i}", dt(4, i), "Zed", "Owner Taro") for i in range(1, 4)]

        class NoCount(FakeRestricted):
            @property
            def Count(self):
                raise FakeComError(SECRET_ERR)

            def GetNext(self):
                raise FakeComError(SECRET_ERR)

        class F:
            class Items:
                @staticmethod
                def Restrict(flt):
                    return NoCount(items, "x")
        st = T.new_scan_state()
        T.scan_folder_items(F, datetime(2024, 1, 1), datetime(2025, 1, 1), st, total_hint=3)
        self.assertFalse(st["complete"])
        self.assertIn("Count:FakeComError", st["errors"])
        self.assertEqual([r["e"] for r in st["records"]], ["M1"])

    def test_usage_mentions_trial_run(self):
        doc = T.__doc__
        self.assertIn("1か月", doc)
        self.assertIn("--stores", doc)

    def test_example_theme_comment_explains_aliases(self):
        txt = _rd(os.path.join(TOOLS_DIR, "thread_ledger_theme.example.json"))
        self.assertIn("別々の別名として両方書く", txt)



if __name__ == "__main__":
    unittest.main()
