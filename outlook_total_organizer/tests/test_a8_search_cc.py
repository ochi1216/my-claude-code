# -*- coding: utf-8 -*-
"""A8 テスト: 検索タブで To:Me (または With:Me) と CC:Me を一緒にチェックすると、CC だけのスレッドが消えていた不具合の修正
(仕様書 A8_SPEC.md。A8 は _13 で入った。対象は既定で最新リビジョン)。

根拠は仕様書だけ (期待値は実装を見ずに決めた。後で実装と照合した)。
  1. MailManagerGUI._filter_threads_loose を、__new__ で作った GUI と偽の threads (本物の OutlookMailManager.group_by_thread で
     作る) で動かす。
     - To+CC・With+CC・To+With+CC: To/With に当たるスレッド「または」CC に自分がいるスレッドが残る。送信のみ・other は消える。
     - To 単独・With 単独では CC だけのスレッドは消える (従来どおり)。CC 単独・全部 OFF では何も消えない (従来どおり)。
     - cc_emails の各要素・user_smtp_address の大文字・前後の空白は無視して比べる (完全一致。部分一致ではない)。
     - user_smtp_address が空・空白・None なら CC では当たらない。cc_emails が無いメール (RSS 記事など) でも落ちない。
     - 他の条件 (未読・フラグ・分類・フォルダ) は従来どおり効く (CC に当たっても、他の条件で外れれば消える)。
  2. 直前版 (_12) との突き合わせ: 乱数で作った多数のスレッド・条件・自分のアドレスで、「CC と To/With を一緒にチェックした」
     ときだけ、_12 の結果に「他の条件を満たし、CC に自分がいるスレッド」が加わる。それ以外は _12 と完全に同じ。
  3. 画面の操作: 本物の「🔄 表示更新」(_refresh_display) と「🔍 通常検索」(_search → _run_search。厳密検索 OFF で絞り込みを
     通る / ON では通らない) を、検索タブの最小限の部品と偽の Outlook で動かし、一覧 (Treeview) に残るスレッドを確かめる。
  4. 範囲ガード (AST・ファイル名で _12 と _13 を指定): 変わった既存のメソッドは _filter_threads_loose だけで、その中でも
     「if check_cc and self.outlook.user_smtp_address:」の中身だけ。

1・2 は GUI (Tk) を使わない (絞り込みは self.threads と self.outlook.user_smtp_address しか使わない仕様のため。ほかの
属性に触れたら落ちる偽の Outlook を使う)。3 は tkinter とディスプレイが無ければ自動 skip
(Linux は xvfb-run -a /usr/bin/python3.12 tests/run_tests.py)。一時cwd の中で動かし、ファイルを作らない。
"""
import ast
import copy
import functools
import importlib.util
import os
import random
import re
import sys
import unittest
from datetime import datetime, timedelta

import _loader
import test_a1_gui_smoke as a1gui                  # GuiCase (一時cwd・messagebox の記録・待機・後始末)
import test_a7a_review_cost as a7a                 # AST の索引ヘルパ (_index_source / func_node)
from _loader import tempdir_cwd

tk, ttk = a1gui.tk, a1gui.ttk


def oto():
    return _loader.load()


OLD_REV = "outlook_total_organizer_20261004_12.py"
NEW_REV = "outlook_total_organizer_20261004_13.py"
FILTER = "MailManagerGUI._filter_threads_loose"
ME = "yuichi.ochi@example.com"
OTHER = "taro.sato@example.com"


@functools.lru_cache(maxsize=None)
def load_rev(filename):
    """ツールフォルダの指定リビジョンを別名で読み込む (突き合わせ用)。無ければ None。"""
    path = _loader.rev_path(filename)
    if not os.path.isfile(path):
        return None
    oto()                                                  # 先に最小スタブを入れておく
    name = "oto_a8_rev_" + re.sub(r"\W", "_", os.path.splitext(filename)[0])
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    with tempdir_cwd():
        spec.loader.exec_module(mod)
    return mod


# ============================================================
# 合成データ
# ============================================================
BASE_TIME = datetime(2026, 10, 1, 9, 0, 0)
_SEQ = [0]
_MISSING = object()


def mail(cid, routing="other", cc=(), to=(), unread=False, flag_status=0, categories="", folder="受信トレイ",
         sender="Sato, Taro"):
    """_item_to_dict と同じ形のメール1通。cc=None は cc_emails が None、cc=_MISSING は cc_emails キー自体が無い
    (RSS 記事などの形)。"""
    _SEQ[0] += 1
    n = _SEQ[0]
    d = {"subject": f"件名 {cid}", "sender_name": sender, "sender_email": "x@example.com",
         "received": BASE_TIME + timedelta(minutes=n), "body": "本文", "html_body": "", "inline_images": {},
         "attachment_names": [], "conversation_id": cid, "conversation_topic": f"件名 {cid}", "entry_id": f"E-{cid}-{n}",
         "importance": 1, "folder": folder, "has_attachments": False, "unread": unread, "categories": categories,
         "flag_status": flag_status, "routing": routing, "to_emails": list(to)}
    if cc is not _MISSING:
        d["cc_emails"] = None if cc is None else list(cc)
    return d


def group(mails, mod=None):
    """本物の OutlookMailManager.group_by_thread (self を使わない) でスレッドにまとめる。"""
    return (mod or oto()).OutlookMailManager.group_by_thread(None, mails)


def standard_mails(me=ME):
    """基本の6スレッド。
    to   : 自分だけが To (routing=to_me)          with : 自分と他人が To (routing=with_me)
    cc   : 自分は CC だけ (routing=other)           other: 自分は宛先に無い (routing=other)
    sent : 自分が送ったメールだけ (送信のみ。自分は宛先にも CC にも無い)
    mix  : 2通のうち2通目だけ CC に自分がいる"""
    return [
        mail("to", routing="to_me", to=[me]),
        mail("with", routing="with_me", to=[me, OTHER]),
        mail("cc", routing="other", to=[OTHER], cc=["boss@example.com", me]),
        mail("other", routing="other", to=[OTHER], cc=["boss@example.com"]),
        mail("sent", routing="other", to=[OTHER], cc=["boss@example.com"], sender="Ochi, Yuichi", folder="送信済みアイテム"),
        mail("mix", routing="other", to=[OTHER], cc=["boss@example.com"]),
        mail("mix", routing="other", to=[OTHER], cc=[me]),
    ]


ALL = {"to", "with", "cc", "other", "sent", "mix"}


class OutlookOnlyAddress:
    """Outlook の代わり。user_smtp_address だけを持つ。ほかの属性に触れたら AttributeError (絞り込みが COM に触れた疑い)。"""

    def __init__(self, addr):
        self.user_smtp_address = addr

    def __getattr__(self, name):
        raise AttributeError(f"OutlookOnlyAddress に {name} は無い (絞り込みが Outlook/COM に触れた疑い)")


def conds_of(to=False, with_=False, cc=False, **other):
    """「🔄表示更新」(_refresh_display) と同じキーの条件。他の条件は既定で無効。"""
    c = {"category": "", "unread_only": False, "flag_status": None, "to_me": to, "with_me": with_, "cc_me": cc,
         "folder_kw": ""}
    c.update(other)
    return c


def run_filter(threads, conds, addr=ME, mod=None):
    """__new__ で作った GUI で _filter_threads_loose(conds) を実行し、(残った cid の集合, GUI) を返す。入力は書き換えない。"""
    mod = mod or oto()
    gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
    gui.outlook = OutlookOnlyAddress(addr)
    gui.threads = copy.deepcopy(threads)
    gui._filter_threads_loose(copy.deepcopy(conds))
    return set(gui.threads), gui


def ref_cc_hit(thread, addr):
    """仕様の CC 判定 (独立した参照): 自分のアドレスを strip・小文字にした値が空でなく、どれかのメールの cc_emails
    (各要素を strip・小文字) に完全一致で含まれる。"""
    my = addr.strip().lower() if isinstance(addr, str) else ""
    if not my:
        return False
    for m in thread["mails"]:
        for e in (m.get("cc_emails") or []):
            if isinstance(e, str) and e.strip().lower() == my:
                return True
    return False


class InTempCwd(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def kept(self, conds, mails=None, addr=ME):
        threads = group(mails if mails is not None else standard_mails())
        before = copy.deepcopy(threads)
        kept, gui = run_filter(threads, conds, addr)
        self.assertEqual(threads, before, "入力の threads が書き換えられた")
        for cid in kept:
            self.assertEqual(gui.threads[cid], before[cid], f"残ったスレッド {cid} の中身が変わった")
        return kept


# ============================================================
# 1. To/With/CC の組み合わせ
# ============================================================
class TestToWithCcCombinations(InTempCwd):
    def test_to_and_cc_keeps_cc_only_threads(self):
        """To:Me＋CC:Me: To に当たるスレッドと CC に自分がいるスレッド (cc・mix) が残り、with・other・送信のみは消える。"""
        self.assertEqual(self.kept(conds_of(to=True, cc=True)), {"to", "cc", "mix"})

    def test_with_and_cc_keeps_cc_only_threads(self):
        """With:Me＋CC:Me: With に当たるスレッドと CC に自分がいるスレッドが残り、to・other・送信のみは消える。"""
        self.assertEqual(self.kept(conds_of(with_=True, cc=True)), {"with", "cc", "mix"})

    def test_to_with_and_cc(self):
        """To＋With＋CC: to・with・cc・mix が残り、other・送信のみは消える。"""
        self.assertEqual(self.kept(conds_of(to=True, with_=True, cc=True)), {"to", "with", "cc", "mix"})

    def test_to_alone_still_drops_cc_only_threads(self):
        """To:Me 単独では CC だけのスレッドは消える (従来どおり)。"""
        self.assertEqual(self.kept(conds_of(to=True)), {"to"})

    def test_with_alone_and_to_with(self):
        """With:Me 単独・To＋With (CC なし) は従来どおり (CC だけのスレッドは消える)。"""
        self.assertEqual(self.kept(conds_of(with_=True)), {"with"})
        self.assertEqual(self.kept(conds_of(to=True, with_=True)), {"to", "with"})

    def test_cc_alone_removes_nothing(self):
        """CC:Me 単独では何も消えない (従来どおり。other・送信のみも残る)。"""
        self.assertEqual(self.kept(conds_of(cc=True)), ALL)

    def test_all_off_removes_nothing(self):
        """To/With/CC が全部 OFF なら何も変わらない。"""
        self.assertEqual(self.kept(conds_of()), ALL)

    def test_conds_without_routing_keys(self):
        """To/With/CC のキーが無い条件 (広告・RSS 検索の後の絞り込み {'folder_kw': ...}) は何も消さない。"""
        threads = group(standard_mails())
        kept, _gui = run_filter(threads, {"folder_kw": ""})
        self.assertEqual(kept, ALL)

    def test_cc_hit_in_any_mail_of_the_thread(self):
        """CC はスレッドのどのメールでも当たればよい (mix は2通目だけ CC に自分)。1通目だけでも同じ。"""
        mails = [mail("first", cc=[ME]), mail("first", cc=["boss@example.com"]), mail("none", cc=["boss@example.com"])]
        self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"first"})
        self.assertEqual(self.kept(conds_of(with_=True, cc=True), mails), {"first"})

    def test_to_hit_and_cc_hit_in_the_same_thread(self):
        """To にも CC にも当たるスレッドは残る (二重に数えたりしない)。"""
        mails = [mail("both", routing="to_me", cc=[ME]), mail("both", routing="other", cc=[ME])]
        self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"both"})


# ============================================================
# 2. アドレスの比べ方
# ============================================================
class TestAddressMatching(InTempCwd):
    def test_cc_emails_case_and_surrounding_spaces_are_ignored(self):
        """cc_emails の要素の大文字・前後の空白 (空白・タブ・改行) は無視して比べる。"""
        variants = ["YUICHI.OCHI@EXAMPLE.COM", "  yuichi.ochi@example.com  ", "\tYuichi.Ochi@Example.Com\n",
                    " Yuichi.OCHI@example.com"]
        for v in variants:
            with self.subTest(cc=v):
                mails = [mail("cc", cc=[OTHER, v]), mail("other", cc=[OTHER])]
                self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"cc"})

    def test_user_address_case_and_surrounding_spaces_are_ignored(self):
        """自分のアドレス (user_smtp_address) の大文字・前後の空白も無視して比べる (cc_emails 側も大文字・空白付きでも当たる)。"""
        for addr in ("YUICHI.OCHI@EXAMPLE.COM", "  yuichi.ochi@example.com ", "\nYuichi.Ochi@Example.com\t"):
            for cc in (ME, " YUICHI.ochi@example.COM "):
                with self.subTest(addr=addr, cc=cc):
                    mails = [mail("cc", cc=[cc]), mail("other", cc=[OTHER])]
                    self.assertEqual(self.kept(conds_of(with_=True, cc=True), mails, addr=addr), {"cc"})

    def test_only_exact_addresses_match(self):
        """完全一致だけ当たる (前後に文字が付いた別アドレス・一部だけ同じアドレス・表示名は当たらない)。"""
        for v in ("x" + ME, ME + ".au", ME[:-1], "yuichi.ochi", "Ochi, Yuichi", "yuichi.ochi@example.com>",
                  "<yuichi.ochi@example.com"):
            with self.subTest(cc=v):
                mails = [mail("near", cc=[v]), mail("to", routing="to_me")]
                self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"to"})

    def test_empty_or_blank_user_address_never_hits_by_cc(self):
        """自分のアドレスが空・空白だけ・None なら CC では当たらない (To+CC で CC だけのスレッドは消える。従来どおり)。
        cc_emails に空文字・空白だけの要素があっても当たらない。"""
        mails = [mail("cc", cc=[ME, "", "   "]), mail("blank", cc=["", "  "]), mail("to", routing="to_me")]
        for addr in ("", "   ", "\t\n", None):
            with self.subTest(addr=addr):
                self.assertEqual(self.kept(conds_of(to=True, cc=True), mails, addr=addr), {"to"})
                self.assertEqual(self.kept(conds_of(with_=True, cc=True), mails, addr=addr), set())
                self.assertEqual(self.kept(conds_of(cc=True), mails, addr=addr), {"cc", "blank", "to"},
                                 "CC 単独は従来どおり何も消さない")

    def test_blank_cc_entries_do_not_match_a_real_address(self):
        """空文字・空白だけの cc_emails の要素は、自分のアドレスに当たらない。"""
        mails = [mail("blank", cc=["", "   ", "\t"]), mail("to", routing="to_me")]
        self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"to"})

    def test_mail_without_cc_emails_key_does_not_break(self):
        """cc_emails キーが無いメール (RSS 記事など。「🔄表示更新」で通る) でも例外にならず、CC では当たらない。
        同じスレッドの別のメールの CC に自分がいれば当たる。"""
        mails = [mail("rss", cc=_MISSING), mail("mixed", cc=_MISSING), mail("mixed", cc=[ME]), mail("to", routing="to_me")]
        self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"mixed", "to"})
        self.assertEqual(self.kept(conds_of(cc=True), mails), {"rss", "mixed", "to"})

    def test_empty_cc_list(self):
        """cc_emails が空のリストなら CC では当たらない。"""
        mails = [mail("empty", cc=[]), mail("with", routing="with_me")]
        self.assertEqual(self.kept(conds_of(with_=True, cc=True), mails), {"with"})


class TestSpecGapUnusualCcValues(InTempCwd):
    """(SpecGap) cc_emails が None・要素に None や数値が混じる (_item_to_dict は作らない形)。仕様の「各要素を strip・小文字」を
    「文字列にしてから」と自然に解釈し、例外にならず、文字列の要素だけで判定されることを確かめる。"""

    def test_none_list_and_non_string_elements(self):
        """cc_emails=None は当たらない。要素に None・数値が混じっても例外にならず、自分のアドレスがあれば当たる。"""
        mails = [mail("none_list", cc=None), mail("mixed", cc=[None, 12345, ME]), mail("junk", cc=[None, 0, 1.5]),
                 mail("to", routing="to_me")]
        self.assertEqual(self.kept(conds_of(to=True, cc=True), mails), {"mixed", "to"})


# ============================================================
# 3. 他の条件との組み合わせ
# ============================================================
class TestWithOtherConditions(InTempCwd):
    def mails(self):
        return [
            mail("cc_unread", cc=[ME], unread=True),
            mail("cc_read", cc=[ME]),
            mail("cc_flag", cc=[ME], flag_status=2),
            mail("cc_cat", cc=[ME], categories="顧客A, 社内"),
            mail("cc_fld", cc=[ME], folder="受信トレイ/案件X"),
            mail("to_read", routing="to_me"),
            mail("to_unread", routing="to_me", unread=True),
            mail("other_unread", cc=[OTHER], unread=True),
        ]

    def test_unread_only(self):
        """未読のみ: CC に当たっても既読のスレッドは消える。未読の CC スレッドは残る。"""
        self.assertEqual(self.kept(conds_of(to=True, cc=True, unread_only=True), self.mails()), {"cc_unread", "to_unread"})

    def test_flag_status(self):
        """フラグ: 'active' はフラグ付きだけ・'none' はフラグなしだけ (CC に当たっても外れれば消える)。"""
        m = self.mails()
        self.assertEqual(self.kept(conds_of(to=True, cc=True, flag_status="active"), m), {"cc_flag"})
        self.assertEqual(self.kept(conds_of(to=True, cc=True, flag_status="none"), m),
                         {"cc_unread", "cc_read", "cc_cat", "cc_fld", "to_read", "to_unread"})

    def test_category(self):
        """分類: 部分一致 (大文字小文字無視)・「(項目なし)」・「(すべて)」は従来どおり効く。"""
        m = self.mails()
        self.assertEqual(self.kept(conds_of(with_=True, cc=True, category="顧客"), m), {"cc_cat"})
        self.assertEqual(self.kept(conds_of(with_=True, cc=True, category="(項目なし)"), m),
                         {"cc_unread", "cc_read", "cc_flag", "cc_fld"})
        self.assertEqual(self.kept(conds_of(with_=True, cc=True, category="(すべて)"), m),
                         {"cc_unread", "cc_read", "cc_flag", "cc_cat", "cc_fld"})
        self.assertEqual(self.kept(conds_of(with_=True, cc=True, category="存在しない分類"), m), set())

    def test_folder_keyword(self):
        """フォルダ: キーワード (前後の空白・大文字は無視) を含むフォルダのスレッドだけ。"""
        m = self.mails()
        self.assertEqual(self.kept(conds_of(to=True, cc=True, folder_kw="  案件x "), m), {"cc_fld"})
        self.assertEqual(self.kept(conds_of(to=True, cc=True, folder_kw="受信"), m),
                         {"cc_unread", "cc_read", "cc_flag", "cc_cat", "cc_fld", "to_read", "to_unread"})

    def test_all_conditions_together(self):
        """未読・フラグ・分類・フォルダを全部指定: すべてを満たし、To/With か CC に当たるスレッドだけ。"""
        m = [mail("hit", cc=[ME], unread=True, flag_status=2, categories="顧客A", folder="受信トレイ/案件X"),
             mail("hit_to", routing="to_me", unread=True, flag_status=2, categories="顧客B", folder="受信トレイ/案件Y"),
             mail("no_cc", cc=[OTHER], unread=True, flag_status=2, categories="顧客A", folder="受信トレイ/案件X"),
             mail("read", cc=[ME], flag_status=2, categories="顧客A", folder="受信トレイ/案件X"),
             mail("noflag", cc=[ME], unread=True, categories="顧客A", folder="受信トレイ/案件X"),
             mail("nocat", cc=[ME], unread=True, flag_status=2, folder="受信トレイ/案件X"),
             mail("otherfld", cc=[ME], unread=True, flag_status=2, categories="顧客A", folder="アーカイブ")]
        c = conds_of(to=True, cc=True, unread_only=True, flag_status="active", category="顧客", folder_kw="案件")
        self.assertEqual(self.kept(c, m), {"hit", "hit_to"})


# ============================================================
# 4. 直前版 (_12) との突き合わせ (乱数)
# ============================================================
ADDR_VARIANTS = (ME, ME.upper(), f"  {ME} ", f"\t{ME.title()}\n", "", "   ", None, "someone.else@example.com")
CC_VARIANTS = ([], [ME], [ME.upper()], [f" {ME} "], [OTHER, f"{ME.title()}\t"], ["x" + ME], [ME + ".au"], [OTHER],
               ["", "  "], _MISSING)
FOLDERS = ("受信トレイ", "受信トレイ/案件X", "送信済みアイテム", "アーカイブ")
CATEGORIES = ("", "顧客A", "顧客B, 社内", "社内")


def random_threads(rng, mod):
    mails = []
    for i in range(rng.randint(1, 9)):
        cid = f"c{i}"
        for _ in range(rng.randint(1, 3)):
            cc = rng.choice(CC_VARIANTS)
            mails.append(mail(cid, routing=rng.choice(("to_me", "with_me", "other", "other", "other")),
                              cc=cc if cc is _MISSING else list(cc), unread=rng.random() < 0.4,
                              flag_status=rng.choice((0, 0, 2)), categories=rng.choice(CATEGORIES),
                              folder=rng.choice(FOLDERS)))
    return group(mails, mod)


def random_conds(rng):
    return conds_of(to=rng.random() < 0.5, with_=rng.random() < 0.5, cc=rng.random() < 0.6,
                    unread_only=rng.random() < 0.2, flag_status=rng.choice((None, None, None, "active", "none")),
                    category=rng.choice(("", "", "", "(すべて)", "(項目なし)", "顧客", "社内", "無い分類")),
                    folder_kw=rng.choice(("", "", "", "受信", "  案件 ", "送信", "アーカイブ")))


class TestMatchesBaselineExceptCc(InTempCwd):
    @classmethod
    def setUpClass(cls):
        cls.old = load_rev(OLD_REV)
        if cls.old is None:
            raise unittest.SkipTest(f"{OLD_REV} が無い")

    def test_random_cases_against_12(self):
        """乱数 (固定シード) の 1500 ケース: CC と To/With を一緒にチェックしたときだけ、_12 の結果に「他の条件を満たし、
        CC に自分がいるスレッド」が加わる。それ以外は _12 と同じ。"""
        rng = random.Random(20261005)
        grew = same = 0
        for case in range(1500):
            threads = random_threads(rng, oto())
            conds = random_conds(rng)
            addr = rng.choice(ADDR_VARIANTS)
            old_kept, _ = run_filter(threads, conds, addr, self.old)
            new_kept, _ = run_filter(threads, conds, addr)
            if conds["cc_me"] and (conds["to_me"] or conds["with_me"]):
                others = dict(conds, to_me=False, with_me=False, cc_me=False)
                passing, _ = run_filter(threads, others, addr, self.old)
                expected = old_kept | {cid for cid in passing if ref_cc_hit(threads[cid], addr)}
            else:
                expected = old_kept
            with self.subTest(case=case, conds=conds, addr=addr):
                self.assertEqual(new_kept, expected)
            if new_kept != old_kept:
                grew += 1
            else:
                same += 1
        self.assertGreater(grew, 60, "前提: CC だけのスレッドが残るケースが十分にある")
        self.assertGreater(same, 1000, "前提: 従来どおりのケースも十分にある")

    def test_standard_set_against_12(self):
        """基本の6スレッド × To/With/CC の全8通り: CC と To/With を一緒にチェックしたときだけ cc・mix が加わり、ほかは _12 と同じ。"""
        threads = group(standard_mails())
        for to in (False, True):
            for with_ in (False, True):
                for cc in (False, True):
                    c = conds_of(to=to, with_=with_, cc=cc)
                    old_kept, _ = run_filter(threads, c, ME, self.old)
                    new_kept, _ = run_filter(threads, c, ME)
                    extra = {"cc", "mix"} if cc and (to or with_) else set()
                    with self.subTest(to=to, with_=with_, cc=cc):
                        self.assertEqual(new_kept, old_kept | extra)
                        self.assertEqual(old_kept & extra, set(), "前提: _12 では CC だけのスレッドが消えていた")


# ============================================================
# 5. 画面の操作 (「🔄 表示更新」・「🔍 通常検索」)
# ============================================================
class SearchOutlook(a1gui.StubOutlook):
    """検索タブが呼ぶ Outlook のメソッドだけを持つ偽物 (ほかの属性に触れたら AttributeError)。検索は条件を記録して、
    渡されたメールをそのまま返す (厳密検索の絞り込みはしない)。group_by_thread は本物。"""

    def __init__(self, addr, mails):
        super().__init__("Ochi, Yuichi", addr)
        self.mails = mails
        self.searches = []

    def check_and_update_outlook_restart_state(self):
        return False

    def search_mails_fast(self, conditions, logic="AND", *args, **kwargs):
        self.searches.append(dict(conditions))
        return copy.deepcopy(self.mails)

    def group_by_thread(self, mails):
        return group(mails)


TREE_COLUMNS = ("sel", "cat", "top", "cnt", "who", "date", "fld", "flg")


class SearchTabCase(a1gui.GuiCase):
    """検索タブの最小限の部品 (To/With/CC・分類・フォルダ・フラグ・未読・厳密検索・一覧・ボタン) を持つ GUI を作る。"""

    def build(self, mails, addr=ME, to=False, with_=False, cc=False, strict=False):
        gui = self.make_gui(select_action=False, build_panel=False, smtp=addr)
        root = gui.root
        gui.v_all_me = tk.BooleanVar(master=root, value=False)
        gui.v_to_me = tk.BooleanVar(master=root, value=to)
        gui.v_with_me = tk.BooleanVar(master=root, value=with_)
        gui.v_cc_me = tk.BooleanVar(master=root, value=cc)
        gui.v_cat = tk.StringVar(master=root, value="(すべて)")
        gui.v_flag = tk.StringVar(master=root, value="(指定なし)")
        gui.v_unread = tk.BooleanVar(master=root, value=False)
        gui.v_strict = tk.BooleanVar(master=root, value=strict)
        gui.v_prd = tk.StringVar(master=root, value="1週間")
        gui.e_fld = ttk.Combobox(root)
        gui.e_sub, gui.e_snd, gui.e_kwd = ttk.Entry(root), ttk.Entry(root), ttk.Entry(root)
        gui.tree = ttk.Treeview(root, columns=TREE_COLUMNS, show="headings")
        for name in ("btn_gen", "btn_excl", "btn_read", "btn_mark_unread", "btn_promo", "btn_remove_flag"):
            setattr(gui, name, ttk.Button(root, text=name))
        gui.btn_refresh = ttk.Button(root, text="🔄 表示更新", command=gui._refresh_display)
        gui.btn_search = ttk.Button(root, text="🔍 通常検索", command=gui._search)
        gui.selected = set()
        gui.threads = {}
        gui.outlook = self.stub_outlook = SearchOutlook(addr, mails)
        root.update()
        return gui

    def shown(self):
        return set(self.gui.tree.get_children())

    def status(self):
        return str(self.gui.lbl_stat.cget("text"))


class TestRefreshDisplayButton(SearchTabCase):
    def refresh(self, mails, addr=ME, selected=(), **flags):
        gui = self.build(mails, addr, **flags)
        gui.threads = group(mails)
        gui.selected = set(selected)
        gui.btn_refresh.invoke()
        self.settle(0.05)
        return gui

    def test_to_and_cc_keeps_cc_only_threads_in_the_list(self):
        """「🔄 表示更新」To:Me＋CC:Me: 一覧に to・cc・mix が残り、with・other・送信のみは消える。消えたスレッドは選択に残らない。
        (選択の復元は既存の _update が選択を全部外すため働かない。A8 の範囲外なので、ここでは確かめない)"""
        gui = self.refresh(standard_mails(), selected={"cc", "other"}, to=True, cc=True)
        self.assertEqual(set(gui.threads), {"to", "cc", "mix"})
        self.assertEqual(self.shown(), {"to", "cc", "mix"})
        self.assertLessEqual(gui.selected, {"to", "cc", "mix"})
        self.assertEqual(self.status(), "リフレッシュ完了: 3件")

    def test_combinations_on_the_button(self):
        """「🔄 表示更新」の To/With/CC の組み合わせ: With+CC は with・cc・mix / To 単独は to (CC だけは消える) / CC 単独は全部。"""
        cases = ((dict(with_=True, cc=True), {"with", "cc", "mix"}), (dict(to=True), {"to"}),
                 (dict(to=True, with_=True), {"to", "with"}), (dict(cc=True), ALL), ({}, ALL),
                 (dict(to=True, with_=True, cc=True), {"to", "with", "cc", "mix"}))
        for flags, want in cases:
            with self.subTest(**flags):
                if self.gui is not None:
                    self._teardown_gui()
                    self.gui = None
                self.refresh(standard_mails(), **flags)
                self.assertEqual(self.shown(), want)

    def test_blank_address_and_case_and_missing_cc_on_the_button(self):
        """「🔄 表示更新」: 自分のアドレスが空白なら CC では残らない / 大文字・空白付きでも当たる / cc_emails の無いメールでも落ちない。"""
        mails = [mail("cc", cc=[" YUICHI.OCHI@EXAMPLE.COM "]), mail("rss", cc=_MISSING), mail("to", routing="to_me")]
        for addr, want in (("  ", {"to"}), ("Yuichi.Ochi@Example.com ", {"cc", "to"})):
            with self.subTest(addr=addr):
                if self.gui is not None:
                    self._teardown_gui()
                    self.gui = None
                self.refresh(mails, addr, to=True, cc=True)
                self.assertEqual(self.shown(), want)


class TestSearchButton(SearchTabCase):
    def search(self, mails, **flags):
        gui = self.build(mails, **flags)
        before = set(self.worker_threads())
        gui.btn_search.invoke()
        started = [t for t in self.worker_threads() if t not in before]
        self.assertEqual(len(started), 1, "検索のワーカーが起動していない")
        self.assertTrue(self.pump(lambda: not started[0].is_alive(), timeout=20), "検索が終わらない")
        self.settle(0.1)
        return gui

    def test_normal_search_keeps_cc_only_threads(self):
        """「🔍 通常検索」(厳密検索 OFF) で To:Me＋CC:Me: 絞り込みを通り、一覧に to・cc・mix が残る。検索の条件は従来どおり。"""
        gui = self.search(standard_mails(), to=True, cc=True)
        self.assertEqual(set(gui.threads), {"to", "cc", "mix"})
        self.assertEqual(self.shown(), {"to", "cc", "mix"})
        c = self.stub_outlook.searches[0]
        self.assertEqual((c["to_me"], c["with_me"], c["cc_me"], c["strict_mode"]), (True, False, True, False))
        self.assertEqual(self.status(), "完了: 3件")

    def test_strict_search_does_not_use_the_loose_filter(self):
        """厳密検索 ON では、後の絞り込みは通らない (従来どおり。検索結果がそのまま一覧に出る)。"""
        gui = self.search(standard_mails(), to=True, cc=True, strict=True)
        self.assertEqual(set(gui.threads), ALL)
        self.assertTrue(self.stub_outlook.searches[0]["strict_mode"])


# ============================================================
# 6. 範囲ガード (AST・_12 → _13)
# ============================================================
def _cc_if_nodes(fn):
    """関数の中の「if check_cc and self.outlook.user_smtp_address:」の If ノード。"""
    want = ast.dump(ast.parse("check_cc and self.outlook.user_smtp_address", mode="eval").body)
    return [n for n in ast.walk(fn) if isinstance(n, ast.If) and ast.dump(n.test) == want]


class TestScopeGuardA8(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest(f"A8 のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = a7a._index_source(cls.baseline)
        cls.new = a7a._index_source(cls.target)

    def test_only_filter_threads_loose_changed(self):
        """変わった既存の関数・メソッドは MailManagerGUI._filter_threads_loose だけ (実際に変わっている)。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = sorted(n for n, s in old_f.items() if n in new_f and new_f[n] != s)
        self.assertEqual(changed, [FILTER])

    def test_nothing_added_or_removed(self):
        """関数・メソッド・定数の追加/削除なし。定数・import・その他のトップレベル文・クラスの骨格は不変。"""
        self.assertEqual(sorted(set(self.old[0]) ^ set(self.new[0])), [])
        self.assertEqual(sorted(set(self.old[1]) ^ set(self.new[1])), [])
        self.assertEqual(sorted(n for n, s in self.old[1].items() if self.new[1].get(n) != s), [])
        self.assertEqual(self.old[2], self.new[2])
        self.assertEqual(self.old[3], self.new[3])
        self.assertEqual(self.old[4], self.new[4])

    def test_only_the_body_of_the_cc_branch_changed(self):
        """_filter_threads_loose の中で変わったのは「if check_cc and self.outlook.user_smtp_address:」の中身だけ
        (旧は pass)。条件そのもの・削除の条件「if (check_to or check_with) and not hit」・ほかの判定は同じ。"""
        old_fn, new_fn = a7a.func_node(self.baseline, FILTER), a7a.func_node(self.target, FILTER)
        old_if, new_if = _cc_if_nodes(old_fn), _cc_if_nodes(new_fn)
        self.assertEqual((len(old_if), len(new_if)), (1, 1), "CC の判定の if がちょうど1つずつ")
        self.assertEqual([type(s).__name__ for s in old_if[0].body], ["Pass"], "前提: 旧は pass")
        self.assertNotEqual([type(s).__name__ for s in new_if[0].body], ["Pass"], "CC の判定が実装されていない")
        self.assertEqual(new_if[0].orelse, [])
        new_if[0].body = [ast.Pass()]
        self.assertEqual(ast.dump(new_fn), ast.dump(old_fn), "CC の判定の中身以外も変わっている")
        removal = ast.dump(ast.parse("(check_to or check_with) and not hit", mode="eval").body)
        self.assertTrue(any(isinstance(n, ast.If) and ast.dump(n.test) == removal for n in ast.walk(new_fn)),
                        "削除の条件 if (check_to or check_with) and not hit が無い")

    def test_cc_branch_reads_only_the_user_address_and_cc_emails(self):
        """CC の判定の中で読むのは self.outlook.user_smtp_address と、メールの cc_emails だけ (COM・ほかの属性を呼ばない)。"""
        new_if = _cc_if_nodes(a7a.func_node(self.target, FILTER))[0]
        attrs = {n.attr for b in new_if.body for n in ast.walk(b) if isinstance(n, ast.Attribute)}
        self.assertLessEqual(attrs - {"user_smtp_address", "outlook", "strip", "lower", "casefold", "get"}, set(), attrs)
        consts = {n.value for b in new_if.body for n in ast.walk(b) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertIn("cc_emails", consts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
