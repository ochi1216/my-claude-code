# -*- coding: utf-8 -*-
"""A9「スタッフ俯瞰 Stage1 の軽量モデルを、設定で切り替えられるようにする」テスト (仕様書 A9_SPEC.md)。

仕様書だけを根拠に、A9 の実装 (_20261004_10.py の変更部分) を見ずに書いている
(入力の形・既存の呼び出し方は、変更前の _09 と既存テストに合わせた)。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの -> クラス名に SpecGap を含む

構成
  1. 定数 STAFF_STAGE1_DEFAULT_MODEL / DEFAULT_CONFIG には足さないこと
  2. MailSummarizer(...) を直接作ったときの lite_model_id (既定値)
  3. MailManagerGUI.__init__ が設定 gemini_lite_model を読むこと
     (無い・空・空白だけ・null・設定ファイルなし → 既定値・警告なし / 文字列 → 前後の空白を除いた値・警告なし /
      文字列でない (数値・リスト・true 等。仕様変更で追加) → 既定値＋警告「⚠️ 設定 gemini_lite_model が文字列ではないため、
      既定の gemini-2.5-flash-lite を使います」を1行)。
     本物の __init__ を、Outlook・ローカルサーバ・画面配置だけ差し替えて動かし、Outlook に初めて触れる時点
     (ウィンドウ配置のスレッドを作る直前) で止める。設定ファイルは書き換えないこと。
  4. summarize_staff_threads の Stage1 の AI 呼び出し (_run_genai_call_with_schema の第3引数) が lite_model_id に
     なること。本物の summarize_staff_threads を、AI 呼び出しだけ偽物にして動かす。空・None・属性なし → 既定値。
     Stage2 は第3引数なし (= 設定モデル)。プロジェクト俯瞰の Stage1・費用の見積りは変わらないこと。
  5. 範囲ガード (_09 と _10 をファイル名で指定して AST 比較。後のリビジョンが増えても変わらない)

変異テスト: 実装のコピーに誤りを1つ入れ、OTO_TARGET でその版を指してこのファイルだけを走らせる。
    OTO_TARGET=/path/to/壊した版.py xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a9_lite_model
(範囲ガードの章は常に tool フォルダの _09 / _10 を比べるので、変異版では変わらない)
GUI テストは tkinter とディスプレイが無ければ自動 skip (Linux は xvfb-run -a を付ける)。
"""
import ast
import contextlib
import copy
import difflib
import functools
import io
import os
import re
import threading
import unittest
from datetime import datetime
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui          # GUI テストの skip 判定 (tkinter・ディスプレイの有無) を借りる
from _loader import read_bytes, tempdir_cwd, write_json

tkmessagebox = a1gui.tkmessagebox


def oto():
    return _loader.load()


LITE = "gemini-2.5-flash-lite"
FLASH = "gemini-2.5-flash"
PRO = "gemini-2.5-pro"
NEW_LITE = "gemini-3.1-flash-lite"        # 後継とされる軽量モデル名 (ここでは任意の文字列として使うだけ)
NO_MODEL = "<第3引数なし>"                 # AI 呼び出しにモデルの指定が無かったことを表す印
# 仕様変更 (レビュー指摘): 文字列でない設定値のときにコンソールへ出す1行 (先頭は U+26A0 U+FE0F)
WARN_LINE = "\u26a0\ufe0f 設定 gemini_lite_model が文字列ではないため、既定の gemini-2.5-flash-lite を使います"


class InTempCwd(unittest.TestCase):
    """各テストを空の一時cwd で動かす (利用者の設定・解析キャッシュを拾わない/汚さない)。"""

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


# ============================================================
# 入力の合成・偽AI
# ============================================================
def _mail(cid, i, body):
    return {"conversation_id": cid, "entry_id": f"E-{cid}-{i}", "subject": f"件名{cid}",
            "conversation_topic": f"件名{cid}", "received": datetime(2026, 9, 20, 10, i),
            "sender_name": "Saji", "sender_email": "saji@example.com", "importance": 1, "unread": False,
            "routing": "to_me", "to_emails": [], "cc_emails": [], "body": body, "html_body": "", "categories": "",
            "flag_status": 0, "folder": "受信トレイ", "attachment_names": []}


def make_threads(n, prefix="c"):
    """group_by_thread の形 (topic / mails / latest_entry_id / latest_date) のスレッドを n 件。"""
    out = {}
    for k in range(n):
        cid = f"{prefix}{k}"
        mails = [_mail(cid, 0, f"{cid} の本文です。来週の打合せの件、確認をお願いします。")]
        out[cid] = {"topic": f"件名{cid}", "mails": mails, "latest_entry_id": mails[-1]["entry_id"],
                    "latest_date": mails[-1]["received"], "has_unread": False}
    return out


def staff_knowledge(name):
    return {"staffs": {name: {}}, "projects": {"00_Caracal": {}, "01_Wheeling": {}}}


class FakeAI:
    """MailSummarizer._run_genai_call_with_schema の代わり。呼び出しごとに (段, モデル指定) を記録する。
    段はスキーマで見分ける (Stage1 = properties に thread_id がある / Stage2 = それ以外)。
    モデル指定 = 第3引数 (位置引数、または override_model= のキーワード)。無ければ NO_MODEL。"""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, prompt, schema, *args, **kwargs):
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        stage = 1 if "thread_id" in props else 2
        if args:
            model = args[0]
        elif "override_model" in kwargs:
            model = kwargs["override_model"]
        else:
            model = NO_MODEL
        with self.lock:
            self.calls.append((stage, model))
        if stage == 1:
            m = re.search(r'thread_id は理由を問わず "(.*?)"', prompt)
            cid = m.group(1) if m else "?"
            return {"thread_id": cid, "topic": "t", "is_target": True, "summary": "要約", "category": "その他",
                    "project_scope": "横断業務", "action_type": "通知・共有", "importance": "中"}
        item = {"category": "その他", "project_scope": "横断業務", "action_type": "通知・共有", "text": "1文の要約。",
                "status_icon": "🔵", "source_thread_ids": []}
        return {"manager_actions": [dict(item)], "staff_status": [dict(item)], "stalled_monitor": [dict(item)],
                "updated_history": "新しい経緯", "ai_questions": []}

    def models(self, stage):
        return [m for st, m in self.calls if st == stage]


def real_summarizer(model=FLASH):
    """本物の MailSummarizer(api_key, model) を作り、AI 呼び出しだけ FakeAI に差し替える。"""
    s = oto().MailSummarizer("dummy-key", model)
    s._run_genai_call_with_schema = FakeAI()
    return s


# ============================================================
# 1. 定数
# ============================================================
class TestConstant(unittest.TestCase):
    def test_default_model_constant(self):
        """STAFF_STAGE1_DEFAULT_MODEL は "gemini-2.5-flash-lite" (従来の直書きと同じ値)。"""
        self.assertEqual(oto().STAFF_STAGE1_DEFAULT_MODEL, LITE)

    def test_default_config_gets_no_lite_key(self):
        """DEFAULT_CONFIG に gemini_lite_model は足さない (設定ファイルを書き換えないため)。設定モデルの既定値も従来どおり。"""
        cfg = oto().DEFAULT_CONFIG
        self.assertNotIn("gemini_lite_model", cfg)
        self.assertEqual(cfg.get("gemini_model"), FLASH)


# ============================================================
# 2. MailSummarizer(...) を直接作る
# ============================================================
class TestSummarizerDefault(InTempCwd):
    def test_direct_construction_has_the_default(self):
        """MailSummarizer(...) を直接作ると lite_model_id は既定値 (設定モデルが何でも)。model_id は渡したモデルのまま。"""
        for model in (FLASH, PRO, "gemini-3.5-flash", NEW_LITE):
            with self.subTest(model=model):
                s = oto().MailSummarizer("dummy-key", model)
                self.assertEqual(s.lite_model_id, LITE)
                self.assertEqual(s.model_id, model)


# ============================================================
# 3. MailManagerGUI.__init__ が設定を読む
# ============================================================
class _StopInit(BaseException):
    """MailManagerGUI.__init__ を途中で止めるための例外 (except Exception で握りつぶされないよう BaseException)。"""


class _FakeOutlook:
    """OutlookMailManager の代わり。__init__ が Outlook に初めて触れた時点 (既存コードでは、ウィンドウ配置の
    スレッドに渡す self.outlook.arrange_outlook_window を読む時点) で _StopInit を出し、__init__ をそこで止める
    (スレッド・画面の部品・COM には進ませない)。"""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise _StopInit(f"outlook.{name}")


BASE_CONFIG = {"gemini_api_key": "", "output_folder": "./mail_reports", "default_period_days": 7, "gemini_model": FLASH}


class GuiInitCase(InTempCwd):
    @classmethod
    def setUpClass(cls):
        reason = a1gui._gui_skip_reason()
        if reason:
            raise unittest.SkipTest(reason)

    def setUp(self):
        super().setUp()
        self.dialogs = []
        for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion",
                     "askyesnocancel", "askretrycancel"):
            p = mock.patch.object(tkmessagebox, name, lambda *a, _n=name, **k: self.dialogs.append(_n))
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _destroy(gui):
        root = getattr(gui, "root", None)
        if root is None:
            return
        try:
            for aid in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(aid)
        except Exception:                                   # noqa: BLE001
            pass
        try:
            root.destroy()
        except Exception:                                   # noqa: BLE001
            pass
        gui.root = None

    def init_gui(self, config):
        """config (dict) を設定ファイルに書き (None なら設定ファイルを作らない)、本物の MailManagerGUI.__init__ を動かす。
        戻り値: (gui, 止まった位置, 実行前の設定ファイルの中身)。"""
        mod = oto()
        if config is not None:
            write_json(mod.CONFIG_FILE, config)
        before = read_bytes(mod.CONFIG_FILE) if os.path.exists(mod.CONFIG_FILE) else None
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        self.addCleanup(self._destroy, gui)

        def stop_build(*a, **k):                            # 念のための止め (Outlook に触れずに画面を作り始めたら止める)
            raise _StopInit("_build_main_tabs")

        stubs = {"OutlookMailManager": _FakeOutlook, "start_local_server": lambda *a, **k: 8765,
                 "get_primary_work_area": lambda *a, **k: None, "get_physical_work_area": lambda *a, **k: None,
                 "fit_window_to_work_area": lambda *a, **k: None,
                 "set_gemini_direct_restored_callback": lambda *a, **k: None}
        stopped = None
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name, value in stubs.items():
                if hasattr(mod, name):
                    stack.enter_context(mock.patch.object(mod, name, value))
            stack.enter_context(mock.patch.object(mod.MailManagerGUI, "_build_main_tabs", stop_build))
            stack.enter_context(contextlib.redirect_stdout(out))      # コンソール出力 (警告の1行) を記録する
            stack.enter_context(contextlib.redirect_stderr(out))
            try:
                mod.MailManagerGUI.__init__(gui)
            except _StopInit as e:
                stopped = str(e)
        return gui, stopped, before, out.getvalue()

    def check(self, extra, expected, label, warn=False):
        """BASE_CONFIG + extra で起動し、self.summarizer.lite_model_id == expected。extra=None は設定ファイルなし。
        warn=True: 警告 WARN_LINE がちょうど1行出る / False: gemini_lite_model に触れる出力が1行も無い。"""
        mod = oto()
        cfg = None if extra is None else dict(BASE_CONFIG, **extra)
        gui, stopped, before, output = self.init_gui(cfg)
        try:
            s = getattr(gui, "summarizer", None)
            self.assertIsInstance(s, mod.MailSummarizer, f"{label}: self.summarizer が作られていない (止まった位置: {stopped})")
            self.assertEqual(s.lite_model_id, expected, f"{label}: 止まった位置 {stopped}")
            self.assertEqual(s.model_id, FLASH, f"{label}: 設定モデル (gemini_model) が変わった")
            lines = [ln.rstrip() for ln in output.splitlines() if "gemini_lite_model" in ln]
            self.assertEqual(lines, [WARN_LINE] if warn else [], f"{label}: 警告の出力が仕様どおりでない")
            after = read_bytes(mod.CONFIG_FILE) if os.path.exists(mod.CONFIG_FILE) else None
            self.assertEqual(after, before, f"{label}: 設定ファイルが書き換えられた/作られた")
            if extra is None or "gemini_lite_model" not in extra:
                self.assertNotIn("gemini_lite_model", gui.config, f"{label}: 読み込んだ設定に gemini_lite_model が足された")
            self.assertEqual(self.dialogs, [], f"{label}: 想定外のダイアログ")
            return s
        finally:
            self._destroy(gui)


class TestGuiInitReadsTheSetting(GuiInitCase):
    """本物の MailManagerGUI.__init__ が設定 gemini_lite_model を self.summarizer.lite_model_id に入れる。"""

    def test_missing_empty_blank_or_null_setting_gives_the_default(self):
        """設定ファイルなし・キーなし・空・空白だけ (半角/タブ・改行/全角)・null → 既定の "gemini-2.5-flash-lite" (警告なし)。"""
        cases = (("設定ファイルなし", None), ("キーなし", {}), ("空文字", {"gemini_lite_model": ""}),
                 ("半角空白だけ", {"gemini_lite_model": "   "}), ("タブ・改行だけ", {"gemini_lite_model": "\t\r\n \n"}),
                 ("全角空白だけ", {"gemini_lite_model": "　　"}), ("null", {"gemini_lite_model": None}))
        for label, extra in cases:
            with self.subTest(case=label), tempdir_cwd():
                self.check(extra, LITE, label)

    def test_a_value_is_used_without_surrounding_whitespace(self):
        """文字列の値があれば、前後の空白を除いたその値 (警告なし)。"""
        cases = ((NEW_LITE, NEW_LITE), ("  " + NEW_LITE + "  ", NEW_LITE), ("\t" + NEW_LITE + "\r\n", NEW_LITE),
                 ("　" + NEW_LITE + "　", NEW_LITE), (FLASH, FLASH), (LITE, LITE))
        for value, expected in cases:
            with self.subTest(value=value), tempdir_cwd():
                self.check({"gemini_lite_model": value}, expected, repr(value))

    def test_a_non_string_value_gives_the_default_and_one_warning_line(self):
        """(仕様変更) 文字列でない値 (数値・リスト・true 等) → 既定値。コンソールに警告を1行
        「⚠️ 設定 gemini_lite_model が文字列ではないため、既定の gemini-2.5-flash-lite を使います」。"""
        for value in (123, 1.5, True, [NEW_LITE], {"model": NEW_LITE}):
            with self.subTest(value=value), tempdir_cwd():
                self.check({"gemini_lite_model": value}, LITE, repr(value), warn=True)

    def test_falsy_non_string_values_also_warn(self):
        """(仕様変更) 偽になる非文字列 (0・false・空リスト・空の辞書) も「文字列でない」ので既定値＋警告1行
        (警告なしで既定にするのは None (= 無い)・空・空白だけの文字列だけ)。"""
        for value in (0, False, [], {}):
            with self.subTest(value=value), tempdir_cwd():
                self.check({"gemini_lite_model": value}, LITE, repr(value), warn=True)

    def test_the_setting_reaches_stage1(self):
        """起動時に読んだ設定が、スタッフ俯瞰の Stage1 の呼び出しに届く (Stage2 は第3引数なし)。"""
        s = self.check({"gemini_lite_model": " " + NEW_LITE + " "}, NEW_LITE, "値あり")
        ai = s._run_genai_call_with_schema = FakeAI()
        s.summarize_staff_threads("Saji", make_threads(2), staff_knowledge("Saji"))
        self.assertEqual(ai.models(1), [NEW_LITE, NEW_LITE])
        self.assertEqual(ai.models(2), [NO_MODEL])

    def test_a_non_string_setting_never_reaches_stage1(self):
        """(仕様変更) 数値の設定は Stage1 に届かない (Stage1 は既定の "gemini-2.5-flash-lite"。"123" 等にならない)。"""
        s = self.check({"gemini_lite_model": 123}, LITE, "数値", warn=True)
        ai = s._run_genai_call_with_schema = FakeAI()
        s.summarize_staff_threads("Saji", make_threads(2), staff_knowledge("Saji"))
        self.assertEqual(ai.models(1), [LITE, LITE])


# ============================================================
# 4. Stage1 のモデル (本物の summarize_staff_threads を AI 呼び出しだけ偽物にして動かす)
# ============================================================
class TestStaffStage1Model(InTempCwd):
    def run_staff(self, s, name="Saji", n=3):
        ai = s._run_genai_call_with_schema
        res = s.summarize_staff_threads(name, make_threads(n), staff_knowledge(name))
        return ai, res

    def test_stage1_uses_lite_model_id_and_stage2_has_no_model(self):
        """lite_model_id を設定すると、Stage1 の全呼び出しの第3引数がその値。Stage2 は第3引数なし。"""
        s = real_summarizer()
        s.lite_model_id = NEW_LITE
        ai, res = self.run_staff(s, n=3)
        self.assertEqual(ai.models(1), [NEW_LITE] * 3)
        self.assertEqual(ai.models(2), [NO_MODEL])
        self.assertEqual(len(res.get("threads", [])), 3, "前提: Stage1 の結果がそろっていない")
        self.assertEqual(res["staff_status"][0]["text"], "1文の要約。", "前提: Stage2 の結果が使われていない")

    def test_default_instance_uses_the_default(self):
        """MailSummarizer(...) のまま (lite_model_id は既定値) なら、従来どおり "gemini-2.5-flash-lite"。"""
        ai, _ = self.run_staff(real_summarizer(), n=2)
        self.assertEqual(ai.models(1), [LITE] * 2)
        self.assertEqual(ai.models(2), [NO_MODEL])

    def test_empty_or_none_falls_back_to_the_default(self):
        """lite_model_id が空文字・None なら既定値。"""
        for i, value in enumerate(("", None)):
            with self.subTest(lite_model_id=value):
                s = real_summarizer()
                s.lite_model_id = value
                ai, _ = self.run_staff(s, name=f"Staff{i}", n=2)
                self.assertEqual(ai.models(1), [LITE] * 2)
                self.assertEqual(ai.models(2), [NO_MODEL])

    def test_missing_attribute_falls_back_to_the_default(self):
        """lite_model_id 属性が無い (__new__ で作った) インスタンスでも既定値 (例外にならない)。"""
        mod = oto()
        s = mod.MailSummarizer.__new__(mod.MailSummarizer)
        s.model_id = FLASH
        s.total_input_tokens = s.total_output_tokens = 0
        s._run_genai_call_with_schema = FakeAI()
        self.assertNotIn("lite_model_id", vars(s))
        ai, _ = self.run_staff(s, n=2)
        self.assertEqual(ai.models(1), [LITE] * 2)
        self.assertEqual(ai.models(2), [NO_MODEL])

    def test_the_value_is_read_at_each_run(self):
        """lite_model_id を書き換えると、次の実行からその値を使う (作った時点の値に固定しない)。"""
        s = real_summarizer()
        for i, value in enumerate((NEW_LITE, "gemini-9-lite", LITE)):
            with self.subTest(lite_model_id=value):
                s.lite_model_id = value
                s._run_genai_call_with_schema = FakeAI()
                ai, _ = self.run_staff(s, name=f"Run{i}", n=1)
                self.assertEqual(ai.models(1), [value])

    def test_settings_model_is_not_used_for_stage1(self):
        """設定モデル (model_id) が何でも、Stage1 は lite_model_id。Stage2 は第3引数なし (= 設定モデル)。"""
        s = real_summarizer(PRO)
        s.lite_model_id = NEW_LITE
        ai, _ = self.run_staff(s, n=2)
        self.assertEqual(ai.models(1), [NEW_LITE] * 2)
        self.assertEqual(ai.models(2), [NO_MODEL])

    def test_project_overview_calls_are_unchanged(self):
        """プロジェクト俯瞰 (summarize_project_threads) は変えない: Stage1 も Stage2 も第3引数なし (lite_model_id を使わない)。"""
        s = real_summarizer()
        s.lite_model_id = NEW_LITE
        ai = s._run_genai_call_with_schema
        s.summarize_project_threads("00_Caracal", make_threads(2), {"projects": {"00_Caracal": {}}})
        self.assertEqual(len(ai.models(1)), 2, "前提: Stage1 が2回呼ばれていない")
        self.assertEqual(set(ai.models(1)) | set(ai.models(2)), {NO_MODEL})


class TestEstimateIsUnchanged(InTempCwd):
    def test_overview_estimate_ignores_the_lite_setting(self):
        """費用の見積り (estimate_overview_cost) は従来どおり設定モデルの単価: gemini_lite_model を設定しても変わらない。"""
        mod = oto()
        per = {"Saji": make_threads(3)}
        know = staff_knowledge("Saji")
        write_json(mod.CONFIG_FILE, dict(BASE_CONFIG))
        base = mod.estimate_overview_cost("staff", per, know)
        write_json(mod.CONFIG_FILE, dict(BASE_CONFIG, gemini_lite_model=PRO))
        self.assertEqual(mod.estimate_overview_cost("staff", per, know), base)
        self.assertEqual(mod.estimate_overview_cost("staff", per, know, FLASH), base)


# ============================================================
# 5. 範囲ガード (_09 → _10 で変えてよいのは3つのメソッドと定数1つだけ)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_09.py"
NEW_REV = "outlook_total_organizer_20261004_10.py"
ALLOWED_TO_CHANGE = {"MailSummarizer.__init__", "MailManagerGUI.__init__", "MailSummarizer.summarize_staff_threads"}
NEW_CONSTANTS = {"STAFF_STAGE1_DEFAULT_MODEL"}
PLACEHOLDER = "__A9_STAGE1_MODEL__"


@functools.lru_cache(maxsize=None)
def _source(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@functools.lru_cache(maxsize=None)
def _parse(path):
    return ast.parse(_source(path))


def method_node(path, cls_name, meth):
    for node in _parse(path).body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == meth:
                    return sub
    raise AssertionError(f"{cls_name}.{meth} が {os.path.basename(path)} に無い")


def _is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _index_source(path):
    """関数/メソッド・定数・import・その他のトップレベル文・クラスの骨格を AST ダンプ (行番号・コメント・空白は無視) で索引化する。"""
    dump = ast.dump
    funcs, consts, imports, others, shells = {}, {}, set(), [], {}

    def add_consts(prefix, node):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                consts[prefix + t.id] = dump(node)

    for node in _parse(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = dump(node)
        elif isinstance(node, ast.ClassDef):
            rest = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[f"{node.name}.{sub.name}"] = dump(sub)
                elif not _is_docstring(sub):
                    rest.append(dump(sub))
                    if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                        add_consts(f"{node.name}.", sub)
            header = ([dump(x) for x in node.bases], [dump(x) for x in node.keywords],
                      [dump(x) for x in node.decorator_list])
            shells[node.name] = (header, rest)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            add_consts("", node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.add(dump(node))
        elif not _is_docstring(node):
            others.append(dump(node))
    return funcs, consts, imports, others, shells


def _stmt_lists(fn):
    """fn の中のすべての文のリスト (body / orelse / finalbody。except 節の body を含む)。"""
    for node in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            lst = getattr(node, field, None)
            if isinstance(lst, list) and lst and isinstance(lst[0], ast.stmt):
                yield lst


def _assigns_to(stmt, dotted):
    return (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and ast.unparse(stmt.targets[0]) == dotted)


def short_diff(a, b, limit=30):
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "old", "new", lineterm="", n=1))
    return "\n".join(lines[:limit])


class TestScopeGuardA9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = os.path.join(_loader.TOOL_DIR, OLD_REV)
        cls.target = os.path.join(_loader.TOOL_DIR, NEW_REV)
        if not (os.path.isfile(cls.baseline) and os.path.isfile(cls.target)):
            raise unittest.SkipTest("A9 のリビジョン対 (20261004_09 / 20261004_10) が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_is_removed(self):
        """既存の関数/メソッドは消えていない。"""
        self.assertEqual(sorted(n for n in self.old[0] if n not in self.new[0]), [])

    def test_only_the_three_methods_changed(self):
        """変わった既存の関数は MailSummarizer.__init__・MailManagerGUI.__init__・MailSummarizer.summarize_staff_threads だけ
        (3つとも実際に変わっている)。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = {n for n, s in old_f.items() if n in new_f and new_f[n] != s}
        self.assertEqual(sorted(changed - ALLOWED_TO_CHANGE), [], "許可されていない既存関数/メソッドの変更")
        self.assertEqual(sorted(ALLOWED_TO_CHANGE - changed), [], "A9 で変わるはずのメソッドが変わっていない")

    def test_no_function_or_method_is_added(self):
        """関数/メソッドは追加されていない。"""
        self.assertEqual(sorted(n for n in self.new[0] if n not in self.old[0]), [])

    def test_only_the_constant_is_added_at_module_level(self):
        """追加の名前は定数 STAFF_STAGE1_DEFAULT_MODEL だけ (モジュール直下・値は "gemini-2.5-flash-lite")。"""
        added = {n for n in self.new[1] if n not in self.old[1]}
        self.assertEqual(added, NEW_CONSTANTS)
        node = [n for n in _parse(self.target).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "STAFF_STAGE1_DEFAULT_MODEL" for t in n.targets)]
        self.assertEqual(len(node), 1)
        self.assertEqual(ast.literal_eval(node[0].value), LITE)

    def test_existing_constants_imports_and_other_statements_are_unchanged(self):
        """既存の定数 (単価表・DEFAULT_CONFIG を含む)・import・その他のトップレベル文・クラスの骨格は変わらない。"""
        old_c, new_c = self.old[1], self.new[1]
        self.assertEqual(sorted(n for n in old_c if n not in new_c), [], "既存の定数が消えている")
        self.assertEqual(sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s), [], "既存の定数が変わっている")
        self.assertEqual(self.old[2], self.new[2], "import が変わっている")
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        self.assertEqual(self.old[4], self.new[4], "クラスの骨格 (継承・クラス直下の文) が変わっている")

    def test_summarizer_init_only_adds_the_default_line(self):
        """MailSummarizer.__init__ の変更は self.lite_model_id = STAFF_STAGE1_DEFAULT_MODEL の1行の追加だけ。"""
        old = ast.unparse(method_node(self.baseline, "MailSummarizer", "__init__")).splitlines()
        new = ast.unparse(method_node(self.target, "MailSummarizer", "__init__")).splitlines()
        ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        changes = [(tag, old[i1:i2], new[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]
        self.assertEqual([c for c in changes if c[0] != "insert"], [], "追加以外の変更 (削除・置換) がある")
        self.assertEqual([ln.strip() for _, _, added in changes for ln in added],
                         ["self.lite_model_id = STAFF_STAGE1_DEFAULT_MODEL"])

    def test_gui_init_only_adds_the_setting_block_right_after_the_summarizer(self):
        """MailManagerGUI.__init__ の変更は、self.summarizer = MailSummarizer(...) の直後に足した数文 (設定 gemini_lite_model を
        読む・文字列でなければ警告・self.summarizer.lite_model_id に入れる) だけ。ほかの self の属性や設定 (self.config) には
        代入しない・設定ファイルを保存しない。"""
        old_fn = method_node(self.baseline, "MailManagerGUI", "__init__")
        new_fn = copy.deepcopy(method_node(self.target, "MailManagerGUI", "__init__"))

        def summarizer_stmt(fn):
            hits = [(lst, i) for lst in _stmt_lists(fn) for i, st in enumerate(lst)
                    if _assigns_to(st, "self.summarizer") and isinstance(st.value, ast.Call)
                    and ast.unparse(st.value.func) == "MailSummarizer"]
            self.assertEqual(len(hits), 1, "self.summarizer = MailSummarizer(...) が1つでない")
            return hits[0]

        old_lst, oi = summarizer_stmt(old_fn)
        self.assertLess(oi + 1, len(old_lst), "比較元 (_09) で、MailSummarizer(...) の後に文が無い")
        next_old = ast.dump(old_lst[oi + 1])
        lst, i = summarizer_stmt(new_fn)
        ends = [j for j in range(i + 1, len(lst)) if ast.dump(lst[j]) == next_old]
        self.assertTrue(ends, "比較元で直後にあった文 (self.reporter = ... など) が見つからない")
        block = lst[i + 1:ends[0]]
        self.assertTrue(block, "MailSummarizer(...) の直後に追加の文が無い")
        block_text = "\n".join(ast.unparse(st) for st in block)
        sets = [n for st in block for n in ast.walk(st) if _assigns_to(n, "self.summarizer.lite_model_id")]
        self.assertEqual(len(sets), 1, "追加の文の中で self.summarizer.lite_model_id への代入が1つでない\n" + block_text)
        for part in ("gemini_lite_model", "STAFF_STAGE1_DEFAULT_MODEL"):
            self.assertIn(part, block_text)
        for st in block:
            for n in ast.walk(st):
                targets = (n.targets if isinstance(n, ast.Assign) else [n.target]
                           if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else [])
                for t in targets:
                    ok = isinstance(t, ast.Name) or ast.unparse(t) == "self.summarizer.lite_model_id"
                    self.assertTrue(ok, f"追加の文が想定外の場所に代入している: {ast.unparse(t)}")
        self.assertNotIn("save_config", block_text, "追加の文が設定ファイルを保存している")
        del lst[i + 1:ends[0]]
        self.assertEqual(ast.dump(new_fn), ast.dump(old_fn),
                         "直後の追加以外にも変更がある\n" + short_diff(ast.unparse(old_fn), ast.unparse(new_fn)))

    def test_staff_stage1_only_replaces_the_hardcoded_model(self):
        """summarize_staff_threads の変更は、Stage1 の呼び出しの直書き "gemini-2.5-flash-lite" を
        (getattr(self, "lite_model_id", "") or STAFF_STAGE1_DEFAULT_MODEL) に置き換えた1か所だけ。"""
        old_fn = copy.deepcopy(method_node(self.baseline, "MailSummarizer", "summarize_staff_threads"))
        new_fn = copy.deepcopy(method_node(self.target, "MailSummarizer", "summarize_staff_threads"))
        old_hits = [(call, k) for call in ast.walk(old_fn) if isinstance(call, ast.Call)
                    for k, a in enumerate(call.args) if isinstance(a, ast.Constant) and a.value == LITE]
        self.assertEqual(len(old_hits), 1, "比較元 (_09) の直書きが1か所でない")
        new_hits = [(call, k) for call in ast.walk(new_fn) if isinstance(call, ast.Call)
                    for k, a in enumerate(call.args)
                    if not isinstance(a, ast.Constant) and "lite_model_id" in ast.unparse(a)]
        self.assertEqual(len(new_hits), 1, "lite_model_id を渡す呼び出しが1か所でない")
        (oc, ok), (nc, nk) = old_hits[0], new_hits[0]
        self.assertEqual(ok, nk, "モデルを渡す引数の位置が変わった")
        expr = nc.args[nk]
        text = ast.unparse(expr)
        self.assertIn("getattr(self, 'lite_model_id'", text)
        self.assertIn("STAFF_STAGE1_DEFAULT_MODEL", text)
        self.assertFalse([n for n in ast.walk(expr) if isinstance(n, ast.Constant) and n.value == LITE], "直書きが残っている")
        oc.args[ok] = ast.Name(id=PLACEHOLDER, ctx=ast.Load())
        nc.args[nk] = ast.Name(id=PLACEHOLDER, ctx=ast.Load())
        self.assertEqual(ast.dump(new_fn), ast.dump(old_fn),
                         "モデル指定の1か所以外にも変更がある\n" + short_diff(ast.unparse(old_fn), ast.unparse(new_fn)))

    def test_no_hardcoded_lite_model_outside_the_constant_and_the_price_table(self):
        """文字列 "gemini-2.5-flash-lite" の直書きは、定数 STAFF_STAGE1_DEFAULT_MODEL と単価表 (とコメント) 以外に無い。
        (docstring はコメント扱い。f-string の一部やメッセージ文も直書きとして数える)"""
        tree = _parse(self.target)
        allowed, kinds = set(), []
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if "STAFF_STAGE1_DEFAULT_MODEL" in names and isinstance(node.value, ast.Constant):
                allowed.add(id(node.value))
                kinds.append("定数")
            if "GEMINI_PRICES_USD_PER_1M" in names and isinstance(node.value, ast.Dict):
                for k in node.value.keys:
                    if isinstance(k, ast.Constant) and k.value == LITE:
                        allowed.add(id(k))
                        kinds.append("単価表")
        self.assertEqual(sorted(kinds), ["単価表", "定数"], "定数・単価表の中に見当たらない")
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.body and _is_docstring(n.body[0])}
        bad = [f"{n.lineno}行目: {n.value[:60]!r}" for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and LITE in n.value
               and id(n) not in allowed and id(n) not in docstrings]
        self.assertEqual(bad, [])

    def test_comments_mention_the_setting(self):
        """コメント: 定数の近く (3行以内) と Stage1 の呼び出しの直前のコメントが、設定 gemini_lite_model に触れている。"""
        lines = _source(self.target).splitlines()
        const = [n for n in _parse(self.target).body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "STAFF_STAGE1_DEFAULT_MODEL" for t in n.targets)][0]
        near = lines[max(0, const.lineno - 4):const.end_lineno]
        self.assertTrue(any("#" in ln and "gemini_lite_model" in ln for ln in near),
                        "定数の近くのコメントに gemini_lite_model が無い:\n" + "\n".join(near))
        fn = method_node(self.target, "MailSummarizer", "summarize_staff_threads")
        call = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                and any(not isinstance(a, ast.Constant) and "lite_model_id" in ast.unparse(a) for a in c.args)][0]
        stmt_line = max(n.lineno for n in ast.walk(fn) if isinstance(n, ast.stmt) and n is not fn
                        and n.lineno <= call.lineno <= n.end_lineno)          # 呼び出しを含む、いちばん内側の文
        block, k = [], stmt_line - 2
        while k >= 0 and (not lines[k].strip() or lines[k].lstrip().startswith("#")):
            if lines[k].strip():
                block.append(lines[k])
            k -= 1
        self.assertTrue(any("gemini_lite_model" in ln for ln in block),
                        "Stage1 の呼び出しの直前のコメントに gemini_lite_model が無い:\n" + "\n".join(reversed(block)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
