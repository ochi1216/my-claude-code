# -*- coding: utf-8 -*-
"""A6b テスト: 毎日タブ「📋 アクション」の「📥 自分待ち・🔥 催促」パネル (仕様書 A6B_SPEC.md + A6B_SPEC_DELTA_fix1.md)。

根拠は仕様書だけ。期待値は _09 の新規部分の実装を読まずに決めた (比較の基準として、_08 の既存コード
= _reformat_cockpit_v2 の _still_open・既存の読込関数・A1 の判断待ちパネルだけを読んだ)。
  - 仕様に明記された挙動                              -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの -> クラス名に SpecGap を含む (docstring に解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

構成
  1. 純関数 build_cockpit_v2_my_court_snapshot: missing / error / ok、4区分だけ・保存順・確認済み・action_keys・
     PJ上書き・重複・行の中身・generated_at と「古い」・件数・status_text の文言・入力不変・例外なし・書き込みなし。
  2. _reformat_cockpit_v2 の _still_open と同じ判定: 同じファイルから、v2 の「フォーマットのみ再生成」に渡る queue を
     4区分に絞ったものと、パネルの行 (と PJ) の集合が一致する (手で選んだ組合せ + 乱数で作った150通り)。
  3. GUI (xvfb): 本番と同じ順 (_build_main_tabs → _ui_action_tab → ステータス行) で組み、配置・一覧・状態表示・詳細・
     Outlookで開く (ダブルクリック/右クリック)・再読込 (ボタン/タブ切替/定期)・起動時の頑健さ・タブ見出し (A1) 不変。
  4. 範囲ガード (AST): _08 → _09 をファイル名で指定して比較 (後のリビジョンでも落ちないように)。
     変更は _ui_action_tab の1行と、(fix1) 判断待ちの _action_decision_set_progress / _action_decision_undo の最後の1行だけ。
     追加は仕様の名前だけ、v2 の実行/再生成・A1 のその他は不変。
  (fix1) アクションタブは pack_propagate(False) (上位タブの必要な高さを上げない・画面下のステータス行を潰さない)、
     パネルと一覧の枠は fill=BOTH/expand、行に days_now (= days_elapsed + max(age_days, 0)) で「経過」は int(days_now) 日、
     読めないときの文言の末尾に「。「🎯 v2」を実行し直すと直ります」、判断待ちの完了/無視/元に戻すの成功後にこのパネルも読み直す、
     パネルを作っていない画面では _refresh_action_my_court_view は何もしない。

方針: 一時cwd の中だけで動かす。Outlook(COM)・AI・ネットワーク・実ブラウザには触れない。GUI は A1/A6 のハーネス
(test_a1_gui_smoke.GuiCase / test_a6_tabs.TabsCase) を使う。後始末で保留中の after を取り消してから root を破棄する
("invalid command name ..._action_my_court_tick" を出さない)。定期の再読込 (after 900 / 120秒) は、確認する
テスト以外では「記録だけして予約しない」(結果が時間に左右されないように)。
Linux では  xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a6b  で実行できる。
"""
import ast
import builtins
import contextlib
import copy
import inspect
import os
import random
import re
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui            # GuiCase (一時cwd・messagebox の記録・待機・後始末)・スタブ
import test_a6_tabs as a6tabs                # TabsCase (本番の _build_main_tabs で組む)・AST の索引
from _loader import snapshot_files, tempdir_cwd, write_bytes, write_json, write_text

tk, ttk = a1gui.tk, a1gui.ttk
walk = a1gui.walk


def oto():
    return _loader.load()


# 範囲ガードの比較対象 (ファイル名で固定する)
OLD_REV = "outlook_total_organizer_20261004_08.py"
NEW_REV = "outlook_total_organizer_20261004_09.py"

# ---- 仕様の文言・値 --------------------------------------------------------
CATS4 = ("reminded", "silent", "spiking", "waiting")
PANEL_TEXT = "📥 自分待ち・🔥 催促（統括コックピットv2の前回結果・毎週更新）"
LOADING_TEXT = "読み込み中..."
MISSING_TEXT = ("統括コックピットv2の結果がまだありません"
                "（「📅 毎週(俯瞰)」→「🚀 統括コックピット」→「🎯 v2」を実行すると、ここに出ます）")
ERROR_TAIL = "。「🎯 v2」を実行し直すと直ります"                  # (fix1)
ERROR_RE = re.compile(r"^⚠ 統括コックピットv2の前回結果を読めませんでした（([A-Za-z_][A-Za-z0-9_.]*)）"
                      + re.escape(ERROR_TAIL) + "$")
STALE_LINE = "\n⚠ 7日以上前の結果です。「🎯 v2」で更新してください"
NO_ID_TEXT = "このスレッドにはOutlookで開くためのIDがありません。"
OPEN_LABEL = "📧 Outlookで開く"
RELOAD_TEXT = "🔄 再読込"
ROW_KEYS = ("key", "category_key", "category_label", "project", "topic", "real_topic", "entry_id",
            "latest_date_display", "days_elapsed", "reasons_text", "days_now")          # days_now は fix1
SNAP_KEYS = ("state", "rows", "count", "reminded", "generated_at", "age_days", "stale", "status_text")

# 実際の今日 (2026年) から離した「現在」。実装が now 引数ではなく datetime.now() を使っていれば結果がずれて分かる
NOW = datetime(2031, 3, 15, 12, 0, 0)
GEN = "2031-03-15 09:30"                     # NOW の2.5時間前 (= 今日)
GEN_WHEN = "03/15 09:30（今日）"

ABSENT = object()          # v2_item / v2_saved で「そのキーを作らない」
READ = object()            # build() で「None を渡して既存の読込関数/ファイルから読ませる」


def error_text(type_name):
    return f"⚠ 統括コックピットv2の前回結果を読めませんでした（{type_name}）{ERROR_TAIL}"


def ok_text(count, reminded, when, stale=False):
    """仕様の ok の文言。when は「MM/DD HH:MM（今日|N日前）」または「日時不明」。"""
    head = ("📥 ボールが自分にある案件はありません" if count == 0
            else f"📥 ボールが自分にある案件 {count}件（うち🔥催促されている {reminded}件）")
    return f"{head}｜v2の前回結果: {when}" + (STALE_LINE if stale else "")


def detail_text(reasons_text, real_topic):
    return f"根拠: {reasons_text or '—'} ／ 件名: {real_topic}"


# ---- 合成データ -------------------------------------------------------------
def labels():
    return oto().COCKPIT_V2_CATEGORY_LABELS


def v2_item(cid, cat="waiting", **kw):
    """v2 が cockpit_v2_last_result.json の queue に保存する1件 (generate_cockpit_v2_data の形)。"""
    it = {"project": "PJ-A", "other_projects": [], "conversation_id": cid, "topic": f"AI件名{cid}",
          "real_topic": f"実件名{cid}", "latest_entry_id": f"ENTRY-{cid}", "latest_date_display": "03/10 09:15",
          "category_key": cat,
          "category_label": labels().get(cat, f"?{cat}") if isinstance(cat, str) else "?",
          "days_elapsed": 4.5, "reasons": ["⏰ 4日間 動きなし", "👥 2人が待っている"], "is_flagged": False,
          "mail_count": 3, "action_keys": [f"{cid}::0"]}
    it.update(kw)
    return {k: v for k, v in it.items() if v is not ABSENT}


def v2_saved(items, generated_at=GEN):
    cd = {"projects": {}, "queue": items}
    if generated_at is not ABSENT:
        cd["generated_at"] = generated_at
    return {"cockpit_data": cd, "total_input": 100, "total_output": 50}


def build(saved=READ, ack=None, st=None, ov=None, now=None):
    """build_cockpit_v2_my_court_snapshot を仕様の引数名で呼ぶ。
    saved は省略/READ でファイルを読ませる。ack/st/ov は省略で {} (ファイルを読ませない)、READ で None を渡す。"""
    def arg(v):
        return None if v is READ else ({} if v is None else v)
    return oto().build_cockpit_v2_my_court_snapshot(
        NOW if now is None else now, saved=None if saved is READ else saved,
        acknowledged=arg(ack), action_statuses=arg(st), project_overrides=arg(ov))


def keys_of(snap):
    return [r["key"] for r in snap["rows"]]


def last_result_path():
    return oto().COCKPIT_V2_LAST_RESULT_FILE


# ---- Tk の値の正規化 --------------------------------------------------------
def _ints(v):
    """pady / padding などを int のタプルに ((8, 0) / "8 0" / 8 / Tcl_Obj のどれでも)。"""
    if isinstance(v, (tuple, list)):
        out = []
        for x in v:
            out.extend(_ints(x))
        return tuple(out)
    return tuple(int(float(t)) for t in re.findall(r"-?\d+(?:\.\d+)?", str(v)))


def _num(v):
    found = re.findall(r"-?\d+(?:\.\d+)?", str(v))
    return float(found[0]) if found else 0.0


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _words(v):
    if isinstance(v, (tuple, list)):
        return [str(x) for x in v]
    return str(v).split()


def _days_cell_ok(cell, days):
    """「経過」の表示が「N日」の形で、N が days_elapsed (整数部 or そのまま) に合っているか。"""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)日", cell)
    return bool(m) and float(m.group(1)) in {float(int(days)), float(days), round(float(days), 1)}


# ============================================================
# 1. 純関数 build_cockpit_v2_my_court_snapshot
# ============================================================
class PureCase(unittest.TestCase):
    """一時cwd の中で動かす (json/ を相対パスで読むため)。"""

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def assert_shape(self, s):
        self.assertIsInstance(s, dict)
        for k in SNAP_KEYS:
            self.assertIn(k, s, f"戻り値に {k} が無い: {sorted(s)}")
        self.assertIn(s["state"], ("ok", "missing", "error"))
        self.assertIsInstance(s["rows"], list)
        self.assertEqual(s["count"], len(s["rows"]), "count は len(rows)")
        self.assertEqual(s["reminded"], sum(1 for r in s["rows"] if r.get("category_key") == "reminded"))
        self.assertIsInstance(s["status_text"], str)

    def assert_error(self, s, type_name=None, rows_empty=True):
        self.assert_shape(s)
        self.assertEqual(s["state"], "error", s.get("status_text"))
        m = ERROR_RE.match(s["status_text"])
        self.assertTrue(m, f"error の文言が仕様と違う: {s['status_text']!r}")
        if type_name:
            self.assertEqual(m.group(1), type_name)
        self.assertTrue(s.get("error"), "error のときは error (型名とメッセージ) が入る")
        self.assertIn(m.group(1), str(s["error"]), "error に型名が入っていない")
        if rows_empty:
            self.assertEqual((s["rows"], s["count"], s["reminded"]), ([], 0, 0))
            self.assertFalse(s["stale"])
        return m.group(1)


class TestConstantsAndSignature(unittest.TestCase):
    def test_my_court_categories(self):
        """COCKPIT_V2_MY_COURT_CATEGORIES = ("reminded", "silent", "spiking", "waiting") (tuple)。"""
        v = oto().COCKPIT_V2_MY_COURT_CATEGORIES
        self.assertIsInstance(v, tuple)
        self.assertEqual(v, CATS4)

    def test_my_court_categories_are_the_v2_categories_except_them_stalled(self):
        """(整合) v2 の5区分から「🧊 相手が止まっている」を除いた4つ。"""
        self.assertEqual(set(oto().COCKPIT_V2_MY_COURT_CATEGORIES),
                         set(oto().COCKPIT_V2_CATEGORY_ORDER) - {"them_stalled"})

    def test_stale_days(self):
        """COCKPIT_V2_STALE_DAYS = 7。"""
        self.assertEqual(oto().COCKPIT_V2_STALE_DAYS, 7)

    def test_function_signature(self):
        """build_cockpit_v2_my_court_snapshot(now, saved=None, acknowledged=None, action_statuses=None,
        project_overrides=None)。"""
        params = list(inspect.signature(oto().build_cockpit_v2_my_court_snapshot).parameters.values())
        self.assertEqual([p.name for p in params],
                         ["now", "saved", "acknowledged", "action_statuses", "project_overrides"])
        self.assertIs(params[0].default, inspect.Parameter.empty)
        self.assertEqual([p.default for p in params[1:]], [None] * 4)


class TestStates(PureCase):
    """state: missing (ファイルが無い) / error (読めない・JSONでない・dictでない・cockpit_data が dict でない) / ok。"""

    def test_missing_file(self):
        """ファイルが無い → missing。行なし・日時なし・古くない・文言は仕様どおり。"""
        s = build()
        self.assert_shape(s)
        self.assertEqual(s["state"], "missing")
        self.assertEqual((s["rows"], s["count"], s["reminded"]), ([], 0, 0))
        self.assertEqual(s["generated_at"], "")
        self.assertIsNone(s["age_days"])
        self.assertFalse(s["stale"])
        self.assertEqual(s["status_text"], MISSING_TEXT)
        self.assertFalse(s.get("error"), "error は error のときだけ")

    def test_missing_file_while_the_other_three_are_read(self):
        """他の3つも読ませた (None を渡した) 場合も missing。"""
        s = build(ack=READ, st=READ, ov=READ)
        self.assertEqual((s["state"], s["status_text"]), ("missing", MISSING_TEXT))

    def test_broken_json_is_error_with_the_type_name(self):
        """壊れたJSON → error。文言は「⚠ …読めませんでした（JSONDecodeError）」、error に型名。"""
        write_text(last_result_path(), '{"cockpit_data": {"queue": [')
        s = build()
        self.assert_error(s, "JSONDecodeError")
        self.assertEqual(s["status_text"], error_text("JSONDecodeError"))

    def test_empty_file_is_error(self):
        """空のファイル → error (JSONDecodeError)。"""
        write_text(last_result_path(), "")
        self.assert_error(build(), "JSONDecodeError")

    def test_undecodable_bytes_are_error(self):
        """UTF-8 として読めないバイト列 → error。"""
        write_bytes(last_result_path(), b'\xff\xfe\x80{"cockpit_data": {}}')
        self.assert_error(build())

    def test_json_that_is_not_a_dict_is_error(self):
        """JSON だが dict でない (list / 文字列 / 数 / null / true) → error。"""
        for content in ([1, 2], ["cockpit_data"], "text", 5, None, True):
            with self.subTest(content=content):
                write_json(last_result_path(), content)
                self.assert_error(build())

    def test_cockpit_data_missing_or_not_a_dict_is_error(self):
        """cockpit_data が無い / dict でない → error (ファイルから読んだ場合も、saved を渡した場合も)。"""
        for saved in ({}, {"cockpit_data": None}, {"cockpit_data": []}, {"cockpit_data": "x"},
                      {"cockpit_data": 5}, {"queue": [v2_item("A")]}):
            with self.subTest(saved=saved, via="file"):
                write_json(last_result_path(), saved)
                self.assert_error(build())
            with self.subTest(saved=saved, via="argument"):
                self.assert_error(build(saved=copy.deepcopy(saved)))

    def test_queue_that_is_not_a_list_gives_an_empty_ok(self):
        """queue が無い / list でない → 空の一覧で ok。"""
        for q in (ABSENT, None, {}, {"0": v2_item("A")}, "abc", 5):
            with self.subTest(queue=q if q is not ABSENT else "(キーなし)"):
                saved = v2_saved([])
                if q is ABSENT:
                    del saved["cockpit_data"]["queue"]
                else:
                    saved["cockpit_data"]["queue"] = q
                s = build(saved=saved)
                self.assert_shape(s)
                self.assertEqual((s["state"], s["rows"]), ("ok", []))
                self.assertEqual(s["status_text"], ok_text(0, 0, GEN_WHEN))

    def test_ok_has_all_keys_and_no_error_value(self):
        """ok の戻り値には仕様のキーがすべてあり、error は入らない (error のときだけ)。"""
        s = build(saved=v2_saved([v2_item("A")]))
        self.assert_shape(s)
        self.assertEqual(s["state"], "ok")
        self.assertFalse(s.get("error"))

    def test_ok_from_the_file(self):
        """saved=None ならファイルを読む: 2件 (うち催促1件) が一覧になる。"""
        write_json(last_result_path(), v2_saved([v2_item("A", "reminded"), v2_item("B")]))
        s = build()
        self.assertEqual((s["state"], keys_of(s)), ("ok", ["A", "B"]))
        self.assertEqual(s["status_text"], ok_text(2, 1, GEN_WHEN))


class TestLoadersAndArguments(PureCase):
    """acknowledged / action_statuses / project_overrides が None なら既存の読込関数で読む (例外なら error)。
    dict でない値は空の dict として扱う。"""

    def items(self):
        return [v2_item("A", "reminded"), v2_item("B", "silent", action_keys=["B::0", "B::1"]),
                v2_item("C", "spiking", project="PJ-C"), v2_item("D")]

    @contextlib.contextmanager
    def loaders(self, ack=None, st=None, ov=None, raise_for=None):
        """3つの読込関数を記録用に差し替える。値は deepcopy して返す。raise_for の関数は RuntimeError を出す。"""
        mod = oto()
        calls = {"ack": 0, "st": 0, "ov": 0}

        def mk(name, value):
            def f(*a, **k):
                calls[name] += 1
                if raise_for == name:
                    raise RuntimeError(f"boom-{name}")
                return copy.deepcopy(value)
            return f
        with mock.patch.object(mod, "load_cockpit_v2_acknowledged", mk("ack", {} if ack is None else ack)), \
                mock.patch.object(mod, "load_action_status", mk("st", {} if st is None else st)), \
                mock.patch.object(mod, "load_cockpit_v2_project_overrides", mk("ov", {} if ov is None else ov)):
            yield calls

    def test_none_arguments_are_read_with_the_existing_loaders(self):
        """None を渡すと load_cockpit_v2_acknowledged / load_action_status / load_cockpit_v2_project_overrides を
        1回ずつ呼び、その中身で判定する。"""
        with self.loaders(ack={"A": {"mail_count": 3}},
                          st={"B::0": {"progress": "done"}, "B::1": {"progress": "ignored"}},
                          ov={"C": "PJ-OV"}) as calls:
            s = build(saved=v2_saved(self.items()), ack=READ, st=READ, ov=READ)
        self.assertEqual(calls, {"ack": 1, "st": 1, "ov": 1})
        self.assertEqual(keys_of(s), ["C", "D"])
        self.assertEqual(s["rows"][0]["project"], "PJ-OV")

    def test_given_arguments_are_used_and_the_loaders_are_not_called(self):
        """dict を渡したら読込関数は呼ばず、渡した値で判定する (ファイルの値は使わない)。"""
        with self.loaders(ack={"A": {"mail_count": 3}}, st={"B::0": {"progress": "done"}},
                          ov={"C": "PJ-FILE"}) as calls:
            s = build(saved=v2_saved(self.items()), ack={}, st={}, ov={})
            self.assertEqual(keys_of(s), ["A", "B", "C", "D"])
            s = build(saved=v2_saved(self.items()), ack={"D": {"mail_count": 3}}, st={}, ov={"A": "PJ-ARG"})
            self.assertEqual(keys_of(s), ["A", "B", "C"])
            self.assertEqual(s["rows"][0]["project"], "PJ-ARG")
        self.assertEqual(calls, {"ack": 0, "st": 0, "ov": 0})

    def test_none_arguments_read_the_real_files(self):
        """(読込関数そのまま) json/ の3つのファイルの中身が判定に効く。"""
        mod = oto()
        write_json(mod.COCKPIT_V2_ACKNOWLEDGED_FILE, {"A": {"mail_count": 3, "acknowledged_at": "x"}})
        write_json(mod.ACTION_STATUS_FILE, {"B::0": {"progress": "done"}, "B::1": {"progress": "done"}})
        write_json(mod.COCKPIT_V2_PROJECT_OVERRIDE_FILE, {"D": "PJ-D2"})
        s = build(saved=v2_saved(self.items()), ack=READ, st=READ, ov=READ)
        self.assertEqual(keys_of(s), ["C", "D"])
        self.assertEqual([r["project"] for r in s["rows"]], ["PJ-C", "PJ-D2"])

    def test_given_saved_is_used_instead_of_the_file(self):
        """saved を渡したらファイルは読まない (ファイルが壊れていても ok)。"""
        write_json(last_result_path(), v2_saved([v2_item("X")]))
        self.assertEqual(keys_of(build(saved=v2_saved([v2_item("Y")]))), ["Y"])
        write_text(last_result_path(), "{broken")
        s = build(saved=v2_saved([v2_item("Y")]))
        self.assertEqual((s["state"], keys_of(s)), ("ok", ["Y"]))

    def test_loader_exception_is_error(self):
        """読込関数が例外を出したら state "error" (例外は外に出さない)。文言は型名、error に型名とメッセージ。"""
        for name, arg in (("ack", "ack"), ("st", "st"), ("ov", "ov")):
            with self.subTest(loader=name):
                with self.loaders(raise_for=name):
                    s = build(saved=v2_saved(self.items()), **{arg: READ})
                self.assert_error(s, "RuntimeError", rows_empty=False)
                self.assertEqual(s["status_text"], error_text("RuntimeError"))
                self.assertIn(f"boom-{name}", str(s["error"]), "error にメッセージが入っていない")

    def test_loader_returning_a_non_dict_is_treated_as_empty(self):
        """読込関数が dict 以外を返したら空の dict として扱う (全部表示・PJ はそのまま)。"""
        for bad in ([], ["A", "B::0", "C"], "A", 5, None, True):
            with self.subTest(value=bad):
                mod = oto()
                with mock.patch.object(mod, "load_cockpit_v2_acknowledged", lambda b=bad: copy.deepcopy(b)), \
                        mock.patch.object(mod, "load_action_status", lambda b=bad: copy.deepcopy(b)), \
                        mock.patch.object(mod, "load_cockpit_v2_project_overrides", lambda b=bad: copy.deepcopy(b)):
                    s = build(saved=v2_saved(self.items()), ack=READ, st=READ, ov=READ)
                self.assertEqual((s["state"], keys_of(s)), ("ok", ["A", "B", "C", "D"]))
                self.assertEqual([r["project"] for r in s["rows"]], ["PJ-A", "PJ-A", "PJ-C", "PJ-A"])

    def test_non_dict_arguments_are_treated_as_empty(self):
        """dict でない引数 (list / 文字列 / 数 / True) も空の dict として扱う。"""
        for bad in ([], ["A"], "A", 5, True):
            with self.subTest(value=bad):
                s = build(saved=v2_saved(self.items()), ack=bad, st=bad, ov=bad)
                self.assertEqual((s["state"], keys_of(s)), ("ok", ["A", "B", "C", "D"]))

    def test_broken_or_non_dict_side_files_are_treated_as_empty(self):
        """3つのファイルが壊れている / dict でない → 既存の読込関数の結果 ({} / list) を空として扱い ok。"""
        mod = oto()
        write_text(mod.COCKPIT_V2_ACKNOWLEDGED_FILE, "{broken")
        write_json(mod.ACTION_STATUS_FILE, [1, 2])
        write_json(mod.COCKPIT_V2_PROJECT_OVERRIDE_FILE, "PJ-X")
        s = build(saved=v2_saved(self.items()), ack=READ, st=READ, ov=READ)
        self.assertEqual((s["state"], keys_of(s)), ("ok", ["A", "B", "C", "D"]))


class TestFilterAndOrder(PureCase):
    """4区分だけ・them_stalled は出さない・保存順のまま・dict でない item は飛ばす・重複は最初の1件。"""

    def test_only_the_four_my_court_categories_are_listed(self):
        """reminded / silent / spiking / waiting だけが出る (them_stalled は出ない)。"""
        items = [v2_item("R", "reminded"), v2_item("T", "them_stalled"), v2_item("S", "silent"),
                 v2_item("P", "spiking"), v2_item("W", "waiting")]
        s = build(saved=v2_saved(items))
        self.assertEqual(keys_of(s), ["R", "S", "P", "W"])
        self.assertEqual([r["category_key"] for r in s["rows"]], list(CATS4))

    def test_them_stalled_only_gives_no_rows(self):
        """相手待ち (them_stalled) だけなら0件 (「…案件はありません」)。"""
        s = build(saved=v2_saved([v2_item("T1", "them_stalled"), v2_item("T2", "them_stalled")]))
        self.assertEqual((s["state"], s["rows"], s["count"]), ("ok", [], 0))
        self.assertEqual(s["status_text"], ok_text(0, 0, GEN_WHEN))

    def test_unknown_or_missing_category_is_not_listed(self):
        """category_key が4区分に無いもの (未知・空・None・キーなし・大文字違い・空白付き・ラベル文字列) は出ない。"""
        items = [v2_item("U1", "unknown"), v2_item("U2", ""), v2_item("U3", None), v2_item("U4", ABSENT),
                 v2_item("U5", "Waiting"), v2_item("U6", " waiting"), v2_item("U7", "🔥 催促されている"),
                 v2_item("OK", "waiting")]
        self.assertEqual(keys_of(build(saved=v2_saved(items))), ["OK"])

    def test_saved_order_is_kept(self):
        """並べ替えない: 区分順・経過日数順に並んでいない保存順でも、そのままの順。"""
        items = [v2_item("W9", "waiting", days_elapsed=9.0), v2_item("R1", "reminded", days_elapsed=1.0),
                 v2_item("P30", "spiking", days_elapsed=30.0), v2_item("S2", "silent", days_elapsed=2.0),
                 v2_item("W0", "waiting", days_elapsed=0.5), v2_item("R50", "reminded", days_elapsed=50.0)]
        self.assertEqual(keys_of(build(saved=v2_saved(items))), ["W9", "R1", "P30", "S2", "W0", "R50"])

    def test_non_dict_items_are_skipped(self):
        """queue の中の dict でない要素は飛ばす (他は出る)。"""
        items = [None, 1, "W", ["W"], 2.5, True, v2_item("A"), {"0": 1}, v2_item("B", "reminded")]
        s = build(saved=v2_saved(items))
        self.assertEqual((s["state"], keys_of(s)), ("ok", ["A", "B"]))

    def test_duplicate_conversation_id_keeps_only_the_first(self):
        """同じ conversation_id が2回出たら最初の1件だけ (位置も最初の場所。件数・催促数も1件として数える)。"""
        items = [v2_item("D", "reminded", topic="最初の件名", project="PJ-1"), v2_item("E"),
                 v2_item("D", "waiting", topic="2件目の件名", project="PJ-2")]
        s = build(saved=v2_saved(items))
        self.assertEqual(keys_of(s), ["D", "E"])
        d = s["rows"][0]
        self.assertEqual((d["topic"], d["project"], d["category_key"]), ("最初の件名", "PJ-1", "reminded"))
        self.assertEqual((s["count"], s["reminded"]), (2, 1))

    def test_a_row_without_conversation_id_gets_a_row_key(self):
        """conversation_id が無い行の key は「row{i}」(他の行と重ならない)。"""
        nocid = v2_item("X", topic="IDなし")
        del nocid["conversation_id"]
        s = build(saved=v2_saved([v2_item("A"), nocid, v2_item("B")]))
        self.assertEqual(len(s["rows"]), 3)
        k = s["rows"][1]["key"]
        self.assertTrue(isinstance(k, str) and re.match(r"^row\d+", k), f"key={k!r}")
        self.assertEqual(len(set(keys_of(s))), 3)


class TestAcknowledged(PureCase):
    """確認済み: acknowledged[cid] が dict で mail_count が同じなら除外 (違えば表示)。"""

    def run_one(self, ack_value, **item_kw):
        items = [v2_item("A", "reminded", **item_kw), v2_item("B")]
        ack = {} if ack_value is ABSENT else {"A": ack_value}
        return keys_of(build(saved=v2_saved(items), ack=ack))

    def test_same_mail_count_is_excluded(self):
        """mail_count が同じ → 除外。"""
        self.assertEqual(self.run_one({"mail_count": 3, "acknowledged_at": "2031-03-10T10:00:00"}), ["B"])

    def test_different_mail_count_is_listed(self):
        """mail_count が違う (新着があった) → 表示。"""
        self.assertEqual(self.run_one({"mail_count": 2}), ["A", "B"])
        self.assertEqual(self.run_one({"mail_count": 4}), ["A", "B"])

    def test_mail_count_is_compared_with_equality(self):
        """「同じ」は == で比べる (文字列の "3" は 3 と違う)。"""
        self.assertEqual(self.run_one({"mail_count": "3"}), ["A", "B"])

    def test_ack_without_mail_count_lists_an_item_that_has_one(self):
        """確認済みに mail_count が無く、item には有る → 違う → 表示。"""
        self.assertEqual(self.run_one({"acknowledged_at": "2031-03-10T10:00:00"}), ["A", "B"])

    def test_ack_and_item_both_without_mail_count_is_excluded(self):
        """確認済み (dict・mail_count なし) と item (mail_count なし): どちらも None で同じ → 除外 (_still_open と同じ)。"""
        self.assertEqual(self.run_one({"acknowledged_at": "x"}, mail_count=ABSENT), ["B"])

    def test_non_dict_ack_value_is_ignored(self):
        """acknowledged[cid] が dict でない → 確認済みとして扱わない (表示)。例外も出さない。"""
        for v in ("x", 5, [3], True, None, 3):
            with self.subTest(ack=v):
                self.assertEqual(self.run_one(v), ["A", "B"])

    def test_ack_of_another_conversation_does_not_matter(self):
        """他の conversation_id の確認済みは関係ない。"""
        self.assertEqual(keys_of(build(saved=v2_saved([v2_item("A")]), ack={"Z": {"mail_count": 3}})), ["A"])


class TestActionKeys(PureCase):
    """action_keys が空でない list で、全部の progress が done / ignored なら除外 (それ以外は表示)。"""

    def listed(self, action_keys, st):
        items = [v2_item("A", "waiting", action_keys=action_keys), v2_item("B")]
        return "A" in keys_of(build(saved=v2_saved(items), st=st))

    def test_all_done_or_ignored_is_excluded(self):
        """全部 done / 全部 ignored / done と ignored の混在 → 除外。"""
        done, ign = {"progress": "done"}, {"progress": "ignored"}
        for keys, st in ((["k1"], {"k1": done}), (["k1", "k2"], {"k1": done, "k2": done}),
                         (["k1"], {"k1": ign}), (["k1", "k2"], {"k1": done, "k2": ign})):
            with self.subTest(keys=keys, st=st):
                self.assertFalse(self.listed(keys, st))

    def test_partly_open_is_listed(self):
        """一部だけ done / 一部の状態が無い / progress が無い / 未着手・進行中 → 表示。"""
        done = {"progress": "done"}
        for keys, st in ((["k1", "k2"], {"k1": done, "k2": {"progress": "in_progress"}}),
                         (["k1", "k2"], {"k1": done}),
                         (["k1", "k2"], {"k1": done, "k2": {"priority": "high"}}),
                         (["k1"], {"k1": {"progress": "not_started"}}),
                         (["k1"], {"k1": {"progress": "Done"}})):
            with self.subTest(keys=keys, st=st):
                self.assertTrue(self.listed(keys, st))

    def test_empty_none_or_missing_action_keys_are_listed(self):
        """action_keys が空 list / None / キーなし → 表示 (状態ファイルに何があっても)。"""
        st = {"A::0": {"progress": "done"}}
        for keys in ([], None, ABSENT):
            with self.subTest(keys="(キーなし)" if keys is ABSENT else keys):
                self.assertTrue(self.listed(keys, st))

    def test_a_non_dict_status_counts_as_open(self):
        """action_statuses[k] が dict でない ("done" という文字列など) → {} とみなす (表示)。例外も出さない。"""
        for bad in ("done", ["done"], 5, None):
            with self.subTest(status=bad):
                self.assertTrue(self.listed(["k1"], {"k1": bad}))
                self.assertFalse(self.listed(["k1", "k2"], {"k1": {"progress": "done"}, "k2": {"progress": "ignored"}}))


class TestProjectOverride(PureCase):
    """project_overrides に conversation_id があれば、その値を PJ にする (入力は書き換えない)。"""

    def test_override_replaces_the_project_of_that_row_only(self):
        items = [v2_item("A", project="PJ-A"), v2_item("B", project="PJ-B"), v2_item("C", "reminded", project="PJ-C")]
        saved = v2_saved(items)
        s = build(saved=saved, ov={"B": "PJ-新", "C": "", "Z": "PJ-Z"})
        self.assertEqual([r["project"] for r in s["rows"]], ["PJ-A", "PJ-新", ""])
        self.assertEqual([it["project"] for it in saved["cockpit_data"]["queue"]], ["PJ-A", "PJ-B", "PJ-C"])

    def test_override_is_matched_by_conversation_id_not_by_topic(self):
        items = [v2_item("A", topic="件名B"), v2_item("B", topic="件名A")]
        s = build(saved=v2_saved(items), ov={"A": "PJ-X"})
        self.assertEqual([(r["key"], r["project"]) for r in s["rows"]], [("A", "PJ-X"), ("B", "PJ-A")])


class TestRowFields(PureCase):
    """行 (rows の要素) の中身。"""

    def one_row(self, **kw):
        s = build(saved=v2_saved([v2_item("A", "reminded", **kw)]))
        self.assertEqual(len(s["rows"]), 1, s)
        return s["rows"][0]

    def test_row_has_the_spec_keys(self):
        r = self.one_row()
        self.assertIsInstance(r, dict)
        for k in ROW_KEYS:
            self.assertIn(k, r, f"行に {k} が無い: {sorted(r)}")

    def test_fields_come_from_the_saved_item(self):
        """key=conversation_id, category_key/label, project, topic, real_topic, entry_id=latest_entry_id,
        latest_date_display, days_elapsed, reasons_text=reasons を「・」で連結。"""
        r = self.one_row(project="PJ-Q", topic="AI要約", real_topic="RE: 実件名", latest_entry_id="EID-1",
                         latest_date_display="03/09 18:42", days_elapsed=5.7, category_label="🔥 催促されている",
                         reasons=["🔥 2回催促されている", "⏰ 5日間 動きなし", "🚩 フラグ"])
        expected = {"key": "A", "category_key": "reminded", "category_label": "🔥 催促されている", "project": "PJ-Q",
                    "topic": "AI要約", "real_topic": "RE: 実件名", "entry_id": "EID-1",
                    "latest_date_display": "03/09 18:42", "days_elapsed": 5.7,
                    "reasons_text": "🔥 2回催促されている・⏰ 5日間 動きなし・🚩 フラグ"}
        self.assertEqual({k: r[k] for k in ROW_KEYS if k != "days_now"}, expected)
        self.assertAlmostEqual(r["days_now"], 5.7 + 0.1, places=6)          # (fix1) 生成から0.1日

    def test_category_label_falls_back_to_the_label_table(self):
        """category_label が無ければ COCKPIT_V2_CATEGORY_LABELS から。有ればそのまま。"""
        for cat in CATS4:
            with self.subTest(cat=cat):
                s = build(saved=v2_saved([v2_item("A", cat, category_label=ABSENT)]))
                self.assertEqual(s["rows"][0]["category_label"], labels()[cat])
        self.assertEqual(self.one_row(category_label="独自ラベル")["category_label"], "独自ラベル")

    def test_real_topic_falls_back_to_the_topic(self):
        """real_topic が無ければ topic。"""
        self.assertEqual(self.one_row(real_topic=ABSENT, topic="AIの件名")["real_topic"], "AIの件名")

    def test_missing_latest_entry_id_gives_an_empty_entry_id(self):
        """latest_entry_id が無い → entry_id は空 (Outlook で開けない行)。"""
        self.assertFalse(self.one_row(latest_entry_id=ABSENT)["entry_id"])

    def test_reasons_text(self):
        """reasons が list なら「・」で連結 ([] は "")。list でなければ ""。"""
        self.assertEqual(self.one_row(reasons=["a"])["reasons_text"], "a")
        self.assertEqual(self.one_row(reasons=[])["reasons_text"], "")
        for bad in ("⏰ 4日間 動きなし", None, ABSENT, {"a": 1}, 5):
            with self.subTest(reasons=bad):
                self.assertEqual(self.one_row(reasons=bad)["reasons_text"], "")

    def test_days_elapsed_that_is_not_a_number_is_zero(self):
        """days_elapsed が数値でなければ 0 (数値ならそのまま)。"""
        for bad in ("3.5", None, ABSENT, [], {}, "x"):
            with self.subTest(days=bad):
                self.assertEqual(self.one_row(days_elapsed=bad)["days_elapsed"], 0)
        for good in (0, 4, 2.5, 30.1):
            with self.subTest(days=good):
                self.assertEqual(self.one_row(days_elapsed=good)["days_elapsed"], good)


class TestDaysNow(PureCase):
    """(fix1) 各行の days_now = days_elapsed + max(age_days, 0) (age_days が None なら +0)。
    days_elapsed は v2 の時点の値のまま残す。"""

    def row(self, gen, **kw):
        s = build(saved=v2_saved([v2_item("A", **kw)], generated_at=gen))
        self.assertEqual(len(s["rows"]), 1, s)
        return s, s["rows"][0]

    def test_days_now_adds_the_age_of_the_result(self):
        for gen, age, _, _ in AGE_CASES:
            with self.subTest(generated_at=gen):
                s, r = self.row(gen, days_elapsed=4.5)
                self.assertAlmostEqual(r["days_now"], 4.5 + age, places=6)
                self.assertAlmostEqual(r["days_now"], 4.5 + s["age_days"], places=6)
                self.assertEqual(r["days_elapsed"], 4.5, "days_elapsed は v2 の時点の値のまま")

    def test_unknown_generated_at_adds_nothing(self):
        for gen in ("bad", "", ABSENT, None):
            with self.subTest(generated_at="(キーなし)" if gen is ABSENT else gen):
                s, r = self.row(gen, days_elapsed=4.5)
                self.assertIsNone(s["age_days"])
                self.assertAlmostEqual(r["days_now"], 4.5, places=6)

    def test_a_future_generated_at_adds_nothing(self):
        """生成日時が now より後 (age_days が負) → max(age_days, 0) で +0。"""
        s, r = self.row("2031-03-16 08:00", days_elapsed=4.5)
        self.assertAlmostEqual(r["days_now"], 4.5, places=6)

    def test_invalid_days_elapsed_counts_as_zero(self):
        """days_elapsed が数値でなければ 0 として足す (days_now = 経過日数だけ)。"""
        for bad in ("5", None, ABSENT):
            with self.subTest(days=bad):
                s, r = self.row("2031-03-12 10:00", days_elapsed=bad)
                self.assertEqual(r["days_elapsed"], 0)
                self.assertAlmostEqual(r["days_now"], 3.1, places=6)

    def test_days_now_with_the_now_argument(self):
        """37日後の now なら days_now も37日ぶん増える。"""
        s = build(saved=v2_saved([v2_item("A", days_elapsed=2)], generated_at="2031-03-08 12:00"),
                  now=datetime(2031, 4, 14, 12, 0))
        self.assertAlmostEqual(s["rows"][0]["days_now"], 39.0, places=6)


# (generated_at, age_days, 括弧の中, stale)  NOW = 2031-03-15 12:00
AGE_CASES = (
    ("2031-03-15 12:00", 0.0, "今日", False),
    ("2031-03-15 09:30", 0.1, "今日", False),
    ("2031-03-14 16:48", 0.8, "今日", False),
    ("2031-03-14 12:00", 1.0, "1日前", False),
    ("2031-03-13 07:12", 2.2, "2日前", False),
    ("2031-03-12 10:00", 3.1, "3日前", False),       # 3日2時間 = 3.083 → 3.1
    ("2031-03-11 14:00", 3.9, "3日前", False),       # 3日22時間 = 3.917 → 3.9 → int で 3
    ("2031-03-09 00:00", 6.5, "6日前", False),
    ("2031-03-08 14:24", 6.9, "6日前", False),
    ("2031-03-08 12:00", 7.0, "7日前", True),        # ちょうど7日 → 古い
    ("2031-03-07 12:00", 8.0, "8日前", True),
    ("2031-03-01 04:48", 14.3, "14日前", True),
)


class TestGeneratedAtAndStale(PureCase):
    """generated_at ("%Y-%m-%d %H:%M") → age_days (小数1桁) / stale (7日以上) / 「今日」「N日前」「日時不明」。"""

    def test_age_today_days_ago_and_stale(self):
        for gen, age, when, stale in AGE_CASES:
            with self.subTest(generated_at=gen):
                s = build(saved=v2_saved([v2_item("A", "reminded")], generated_at=gen))
                self.assertEqual(s["state"], "ok")
                self.assertEqual(s["generated_at"], gen)
                self.assertIsInstance(s["age_days"], (int, float))
                self.assertAlmostEqual(s["age_days"], age, places=6)
                self.assertIs(s["stale"], stale)
                mmdd = datetime.strptime(gen, "%Y-%m-%d %H:%M").strftime("%m/%d %H:%M")
                self.assertEqual(s["status_text"], ok_text(1, 1, f"{mmdd}（{when}）", stale))

    def test_exactly_seven_days_is_stale(self):
        """7日ちょうど (age_days == 7.0) で「古い」になり、文言の末尾に案内が付く。"""
        s = build(saved=v2_saved([v2_item("A")], generated_at="2031-03-08 12:00"))
        self.assertIs(s["stale"], True)
        self.assertTrue(s["status_text"].endswith(STALE_LINE), s["status_text"])

    def test_unknown_generated_at(self):
        """解釈できない generated_at → age_days None・古くない・「｜v2の前回結果: 日時不明」。"""
        for gen in ("", "bad", "2031/03/15 09:30", "15-03-2031 09:30", "2031-13-45 09:30", "2031-02-30 10:00",
                    None, 12345, ["2031-03-15 09:30"], ABSENT):
            with self.subTest(generated_at="(キーなし)" if gen is ABSENT else gen):
                s = build(saved=v2_saved([v2_item("A", "reminded"), v2_item("B")], generated_at=gen))
                self.assertEqual(s["state"], "ok")
                self.assertIsNone(s["age_days"])
                self.assertFalse(s["stale"])
                self.assertEqual(s["status_text"], ok_text(2, 1, "日時不明"))

    def test_generated_at_is_returned_as_the_saved_string(self):
        """generated_at は保存されている文字列のまま。無ければ ""。"""
        self.assertEqual(build(saved=v2_saved([], generated_at="2031-03-12 10:00"))["generated_at"], "2031-03-12 10:00")
        self.assertEqual(build(saved=v2_saved([], generated_at=ABSENT))["generated_at"], "")

    def test_the_now_argument_is_used(self):
        """経過は引数 now から計算する (同じ生成日時でも now が37日後なら「37日前」)。"""
        saved = v2_saved([v2_item("A")], generated_at="2031-03-08 12:00")
        s = build(saved=saved, now=datetime(2031, 4, 14, 12, 0))
        self.assertAlmostEqual(s["age_days"], 37.0, places=6)
        self.assertEqual(s["status_text"], ok_text(1, 0, "03/08 12:00（37日前）", stale=True))


class TestCountsAndStatusText(PureCase):
    """count / reminded と status_text の文言 (仕様の文字列どおり)。"""

    def test_count_and_reminded(self):
        """count = 表示する行数、reminded = そのうち reminded の数 (除外した行は数えない)。"""
        items = [v2_item("R1", "reminded"), v2_item("R2", "reminded"), v2_item("S", "silent"),
                 v2_item("P", "spiking"), v2_item("W", "waiting"), v2_item("T", "them_stalled"),
                 v2_item("R3", "reminded", mail_count=5), v2_item("R4", "reminded", action_keys=["R4::0"])]
        s = build(saved=v2_saved(items), ack={"R3": {"mail_count": 5}}, st={"R4::0": {"progress": "done"}})
        self.assertEqual((s["count"], s["reminded"]), (5, 2))
        self.assertEqual(s["status_text"], ok_text(5, 2, GEN_WHEN))

    def test_status_text_literals(self):
        """仕様の文言どおり (全角の括弧・｜・空白の位置まで)。"""
        rows3 = [v2_item("A", "reminded"), v2_item("B", "silent"), v2_item("C", "waiting")]
        cases = (
            (rows3, "2031-03-12 10:00",
             "📥 ボールが自分にある案件 3件（うち🔥催促されている 1件）｜v2の前回結果: 03/12 10:00（3日前）"),
            ([v2_item("A")], "2031-03-15 09:30",
             "📥 ボールが自分にある案件 1件（うち🔥催促されている 0件）｜v2の前回結果: 03/15 09:30（今日）"),
            (rows3, "2031-03-01 04:48",
             "📥 ボールが自分にある案件 3件（うち🔥催促されている 1件）｜v2の前回結果: 03/01 04:48（14日前）"
             "\n⚠ 7日以上前の結果です。「🎯 v2」で更新してください"),
            ([], "2031-03-15 09:30", "📥 ボールが自分にある案件はありません｜v2の前回結果: 03/15 09:30（今日）"),
            ([v2_item("T", "them_stalled")], "2031-03-01 04:48",
             "📥 ボールが自分にある案件はありません｜v2の前回結果: 03/01 04:48（14日前）"
             "\n⚠ 7日以上前の結果です。「🎯 v2」で更新してください"),
            (rows3, "?", "📥 ボールが自分にある案件 3件（うち🔥催促されている 1件）｜v2の前回結果: 日時不明"),
            ([], ABSENT, "📥 ボールが自分にある案件はありません｜v2の前回結果: 日時不明"),
        )
        for items, gen, text in cases:
            with self.subTest(text=text):
                self.assertEqual(build(saved=v2_saved(items, generated_at=gen))["status_text"], text)

    def test_missing_and_error_literals(self):
        """missing / error の文言。"""
        self.assertEqual(
            build()["status_text"],
            "統括コックピットv2の結果がまだありません（「📅 毎週(俯瞰)」→「🚀 統括コックピット」→「🎯 v2」を実行すると、ここに出ます）")
        write_text(last_result_path(), "{")
        self.assertEqual(build()["status_text"],
                         "⚠ 統括コックピットv2の前回結果を読めませんでした（JSONDecodeError）。「🎯 v2」を実行し直すと直ります")


GARBAGE_ITEMS = [
    None, 1, "x", [], [1, 2], 2.5, True, {}, {"category_key": "waiting"},
    {"category_key": ["waiting"]}, {"category_key": {"k": 1}}, {"category_key": 5},
    {"category_key": "waiting", "conversation_id": ["unhashable"]},
    {"category_key": "reminded", "conversation_id": {"a": 1}},
    {"category_key": "silent", "conversation_id": 123},
    {"category_key": "spiking", "conversation_id": None},
    {"category_key": "waiting", "conversation_id": "W1", "action_keys": [["x"], {"y": 1}, None, 5]},
    {"category_key": "waiting", "conversation_id": "W2", "action_keys": "abc"},
    {"category_key": "waiting", "conversation_id": "W3", "action_keys": {"k": 1}},
    {"category_key": "waiting", "conversation_id": "W4", "action_keys": 5},
    {"category_key": "waiting", "conversation_id": "W5", "mail_count": [1], "days_elapsed": "x",
     "reasons": [1, None, "a", ["b"], {"c": 1}]},
    {"category_key": "reminded", "conversation_id": "W6", "days_elapsed": float("nan")},
    {"category_key": "reminded", "conversation_id": "W7", "days_elapsed": float("inf"), "reasons": "abc"},
    {"category_key": "spiking", "conversation_id": "W8", "topic": None, "real_topic": None, "project": None,
     "latest_entry_id": None, "latest_date_display": None, "category_label": None, "reasons": None,
     "mail_count": None},
    {"category_key": "silent", "conversation_id": "W9", "topic": 5, "real_topic": ["x"], "project": {"p": 1},
     "category_label": 3, "latest_entry_id": 7, "latest_date_display": ["d"]},
    {"category_key": "waiting", "conversation_id": "W1"},
]
GARBAGE_ACK = {"W1": "str", "W2": 5, "W3": [1], "W4": {"mail_count": [1]}, "123": {"mail_count": 1},
               "W9": {"mail_count": {"x": 1}}}
GARBAGE_ST = {"x": "done", "abc": 5, "k": [1], "a": {"progress": ["done"]}, "b": {"progress": None}}
GARBAGE_OV = {"W5": None, "W6": ["list"], "W7": {"d": 1}, "W8": 5}


class TestPurity(PureCase):
    """入力を書き換えない・例外を出さない・ファイルに書かない・Outlook/AI に触れない。"""

    def test_inputs_are_not_modified(self):
        """saved / acknowledged / action_statuses / project_overrides は呼ぶ前と同じ (PJ上書きも入力には書かない)。"""
        nocid = v2_item("N")
        del nocid["conversation_id"]
        items = [v2_item("A", "reminded"), v2_item("B", "them_stalled"), v2_item("C", action_keys=["C::0"]),
                 v2_item("D", reasons="x", days_elapsed="5", category_label=ABSENT, real_topic=ABSENT),
                 v2_item("A", "waiting"), None, nocid]
        saved = v2_saved(items)
        ack = {"A": {"mail_count": 99}, "C": "x"}
        st = {"C::0": {"progress": "done"}}
        ov = {"A": "PJ-OV", "D": "PJ-D", "N": "PJ-N"}
        before = copy.deepcopy((saved, ack, st, ov))
        s = build(saved=saved, ack=ack, st=st, ov=ov)
        self.assertEqual((saved, ack, st, ov), before)
        for r in s["rows"]:                    # 戻り値の行を書き換えても入力は変わらない (入力の dict をそのまま使っていない)
            r["project"] = r["topic"] = "CHANGED"
        self.assertEqual((saved, ack, st, ov), before)

    def test_garbage_never_raises(self):
        """JSON で作れる変な値 (dict でない item・ハッシュできない ID・変な型の各欄・NaN/Infinity) でも例外を出さない。"""
        cases = {
            "引数": dict(saved=v2_saved(copy.deepcopy(GARBAGE_ITEMS)), ack=GARBAGE_ACK, st=GARBAGE_ST, ov=GARBAGE_OV),
            "生成日時が変": dict(saved=v2_saved([v2_item("A")], generated_at={"x": 1})),
            "cockpit_data の中が変": dict(saved={"cockpit_data": {"queue": [v2_item("A")], "generated_at": [1, 2]},
                                                 "total_input": "x"}),
        }
        for label, kw in cases.items():
            with self.subTest(case=label):
                self.assert_shape(build(**kw))
        with self.subTest(case="ファイル"):
            mod = oto()
            write_json(last_result_path(), v2_saved(GARBAGE_ITEMS))
            write_json(mod.COCKPIT_V2_ACKNOWLEDGED_FILE, GARBAGE_ACK)
            write_json(mod.ACTION_STATUS_FILE, GARBAGE_ST)
            write_json(mod.COCKPIT_V2_PROJECT_OVERRIDE_FILE, GARBAGE_OV)
            self.assert_shape(build(ack=READ, st=READ, ov=READ))

    def test_reading_writes_no_files(self):
        """読むだけ: 4つのファイルの中身・更新時刻は変わらず、書き込みモードで開かない。新しいファイルも作らない。"""
        mod = oto()
        write_json(mod.COCKPIT_V2_LAST_RESULT_FILE, v2_saved([v2_item("A"), v2_item("B", "reminded")]))
        write_json(mod.COCKPIT_V2_ACKNOWLEDGED_FILE, {"A": {"mail_count": 3}})
        write_json(mod.ACTION_STATUS_FILE, {"B::0": {"progress": "in_progress"}})
        write_json(mod.COCKPIT_V2_PROJECT_OVERRIDE_FILE, {"B": "PJ-OV"})
        before = snapshot_files(".")
        opened = []
        real_open = builtins.open

        def spy(file, mode="r", *a, **k):
            opened.append((str(file), str(mode)))
            return real_open(file, mode, *a, **k)
        with mock.patch.object(builtins, "open", spy):
            s = build(ack=READ, st=READ, ov=READ)
        self.assertEqual((keys_of(s), s["rows"][0]["project"]), (["B"], "PJ-OV"))
        self.assertEqual([o for o in opened if set(o[1]) & set("wax+")], [], "書き込みモードで開いた")
        self.assertEqual(snapshot_files("."), before)

    def test_missing_and_error_write_no_files(self):
        """ファイルが無いとき・壊れているときも何も書かない (無いファイルを作らない)。"""
        build(ack=READ, st=READ, ov=READ)
        self.assertEqual(snapshot_files("."), {})
        write_text(last_result_path(), "{broken")
        before = snapshot_files(".")
        build(ack=READ, st=READ, ov=READ)
        self.assertEqual(snapshot_files("."), before)

    def test_does_not_touch_outlook_ai_or_network(self):
        """COM・AI・ネットワークの名前に触れたら失敗する偽物に替えても ok で動く。"""
        mod = oto()
        with contextlib.ExitStack() as stack:
            for n in ("win32com", "pythoncom", "requests", "_CommonGeminiClient"):
                stack.enter_context(mock.patch.object(mod, n, a1gui._Boom(n), create=True))
            s = build(saved=v2_saved([v2_item("A")]), ack=READ, st=READ, ov=READ)
        self.assertEqual((s["state"], keys_of(s)), ("ok", ["A"]))


class TestSpecGapPure(PureCase):
    """仕様が明記していない点を、自然な解釈で書いたもの。"""

    def test_a_directory_in_place_of_the_file_is_error(self):
        # 仕様「無い→ missing。読めない/JSONでない/dictでない→ error」。同じ名前のフォルダがある場合は「読めない」と解釈する
        os.makedirs(last_result_path())
        self.assert_error(build())

    def test_loader_error_returns_no_rows(self):
        # 仕様は error のときの rows を書いていない。読めなかったのだから空 (count 0) と解釈する
        with mock.patch.object(oto(), "load_action_status", mock.Mock(side_effect=RuntimeError("x"))):
            s = build(saved=v2_saved([v2_item("A"), v2_item("B", "reminded")]), st=READ)
        self.assert_error(s, "RuntimeError", rows_empty=True)

    def test_error_key_is_absent_unless_error(self):
        # 仕様「"error": 型名とメッセージ(error のときだけ)」→ ok / missing ではキー自体が無い、と解釈する
        self.assertNotIn("error", build(saved=v2_saved([v2_item("A")])))
        self.assertNotIn("error", build())

    def test_saved_argument_that_is_not_a_dict_is_error(self):
        # 仕様の「dictでない→ error」はファイルの話。渡された saved が dict でない場合も同じく error と解釈する
        for saved in ([], ["x"], "x", 5, True):
            with self.subTest(saved=saved):
                self.assert_error(build(saved=saved))

    def test_row_keys_are_unique_even_against_row_like_conversation_ids(self):
        # 仕様「無ければ f"row{i}" で一意に」→ 実在の ID が "row1" などでも重ならない、と解釈する
        nocid = v2_item("X", topic="IDなし")
        del nocid["conversation_id"]
        items = [v2_item("row0"), v2_item("row1"), nocid, v2_item("row2"), v2_item("row3")]
        s = build(saved=v2_saved(items))
        self.assertEqual(len(s["rows"]), 5)
        self.assertEqual(len(set(keys_of(s))), 5, f"key が重なった: {keys_of(s)}")

    def test_two_rows_without_conversation_id_are_both_listed(self):
        # ID の無い行同士は「同じ conversation_id」ではない (それぞれ別の row{i}) と解釈する
        a, b = v2_item("X1", topic="IDなし1"), v2_item("X2", topic="IDなし2", conversation_id=None)
        del a["conversation_id"]
        s = build(saved=v2_saved([a, b]))
        self.assertEqual([r["topic"] for r in s["rows"]], ["IDなし1", "IDなし2"])
        self.assertEqual(len(set(keys_of(s))), 2)

    def test_empty_conversation_id_gets_a_row_key(self):
        # 空文字の conversation_id も「無い」扱い (Treeview の iid "" は根の項目と重なるため) と解釈する
        s = build(saved=v2_saved([v2_item("", topic="空ID"), v2_item("A")]))
        self.assertEqual(len(s["rows"]), 2)
        self.assertTrue(all(isinstance(k, str) and k for k in keys_of(s)), keys_of(s))

    def test_reasons_join_only_the_strings(self):
        # 仕様「reasons の文字列を「・」で連結」→ 文字列でない要素は入れない、と解釈する
        s = build(saved=v2_saved([v2_item("A", reasons=["a", 1, None, "b", ["c"]])]))
        self.assertEqual(s["rows"][0]["reasons_text"], "a・b")

    def test_future_generated_at_counts_as_today(self):
        # 生成日時が now より後 (時計のずれ) → 1日未満なので「今日」・古くない、と解釈する
        s = build(saved=v2_saved([v2_item("A")], generated_at="2031-03-16 08:00"))
        self.assertFalse(s["stale"])
        self.assertEqual(s["status_text"], ok_text(1, 0, "03/16 08:00（今日）"))


# ============================================================
# 2. _reformat_cockpit_v2 の _still_open と同じ判定
# ============================================================
class _FakeRoot:
    def __init__(self):
        self.calls = []

    def after(self, ms, func=None, *args):
        self.calls.append((ms, func))
        return f"fake#{len(self.calls)}"


class _FakeButton:
    def __init__(self):
        self.configs = []

    def config(self, *a, **k):
        self.configs.append(k)
    configure = config


class _CaptureReporter:
    def __init__(self):
        self.calls = []

    def generate_cockpit_v2_report(self, cockpit_data, total_input, total_output, reformat_mode=False, **kw):
        self.calls.append({"data": copy.deepcopy(cockpit_data), "reformat_mode": reformat_mode})
        return None                                # None → webbrowser.open しない


def random_case(rng):
    """乱数で queue / 確認済み / 状態 / PJ上書き を作る (_still_open が例外を出さない範囲の値だけ)。"""
    cats = ["reminded", "them_stalled", "silent", "spiking", "waiting", "unknown_cat"]
    items, ack, st, ov = [], {}, {}, {}
    for i in range(rng.randint(0, 12)):
        cid = f"C{i}"
        kw = {"project": rng.choice(["P1", "P2", ""])}
        mc = rng.choice(["absent", None, 1, 2, 3])
        kw["mail_count"] = ABSENT if mc == "absent" else mc
        ak = rng.choice(["absent", "none", "empty", "list", "list", "list"])
        if ak == "absent":
            kw["action_keys"] = ABSENT
        elif ak == "none":
            kw["action_keys"] = None
        elif ak == "empty":
            kw["action_keys"] = []
        else:
            keys = [f"{cid}::{j}" for j in range(rng.randint(1, 3))]
            kw["action_keys"] = keys
            for k in keys:
                s = rng.choice(["absent", "done", "ignored", "in_progress", "not_started", "noprog", "done", "ignored"])
                if s == "noprog":
                    st[k] = {"priority": "high"}
                elif s != "absent":
                    st[k] = {"progress": s, "updated_at": "2031-03-01T00:00:00"}
        it = v2_item(cid, rng.choice(cats), **kw)
        choices = ["absent", "absent", "same", "diff", "nomc"]
        if it.get("mail_count") is not None:
            choices.append("emptydict")            # 空の dict は、item に件数があるときだけ (無いときは仕様の文と _still_open で食い違う)
        a = rng.choice(choices)
        if a == "same":
            ack[cid] = {"mail_count": it.get("mail_count"), "acknowledged_at": "2031-03-10T10:00:00"}
        elif a == "diff":
            ack[cid] = {"mail_count": (it.get("mail_count") or 0) + 5}
        elif a == "nomc":
            ack[cid] = {"acknowledged_at": "2031-03-10T10:00:00"}
        elif a == "emptydict":
            ack[cid] = {}
        if rng.random() < 0.3:
            ov[cid] = f"OV{i}"
        items.append(it)
    if rng.random() < 0.3:
        ov["ZZ-none"] = "OV-none"

    def maybe_absent(d):
        return ABSENT if rng.random() < 0.15 else d
    return items, maybe_absent(ack), maybe_absent(st), maybe_absent(ov)


class StillOpenCase(PureCase):
    """同じ4つのファイルから、(a) 本物の _reformat_cockpit_v2 が HTML 生成に渡す queue と、
    (b) build_cockpit_v2_my_court_snapshot(datetime.now()) の行 を作って比べる。"""

    FILES = ("COCKPIT_V2_LAST_RESULT_FILE", "COCKPIT_V2_ACKNOWLEDGED_FILE", "ACTION_STATUS_FILE",
             "COCKPIT_V2_PROJECT_OVERRIDE_FILE")

    def put_files(self, items, ack, st, ov):
        mod = oto()
        gen = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        for const, value in zip(self.FILES, (v2_saved(items, gen), ack, st, ov)):
            path = getattr(mod, const)
            if value is ABSENT:
                if os.path.exists(path):
                    os.remove(path)
            else:
                write_json(path, value)

    def reformat_queue(self):
        mod = oto()
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        gui.root = _FakeRoot()
        gui.btn_reformat_cockpit_v2 = _FakeButton()
        gui._set_status = lambda *a, **k: None
        gui.reporter = _CaptureReporter()
        before = set(threading.enumerate())
        with contextlib.ExitStack() as stack:
            mb = a1gui.tkmessagebox
            if mb is not None:
                for n in ("showerror", "showinfo", "showwarning"):
                    stack.enter_context(mock.patch.object(mb, n, lambda *a, **k: None))
            gui._reformat_cockpit_v2()
            for t in threading.enumerate():
                if t not in before:
                    t.join(10)
        self.assertEqual(len(gui.reporter.calls), 1,
                         f"(比較の基準) _reformat_cockpit_v2 が再生成まで進まない: after={gui.root.calls}")
        return gui.reporter.calls[0]["data"].get("queue", [])

    def panel_rows(self):
        s = oto().build_cockpit_v2_my_court_snapshot(datetime.now())
        self.assertEqual(s["state"], "ok", s.get("status_text"))
        return s["rows"]

    def assert_same(self, items, ack=ABSENT, st=ABSENT, ov=ABSENT, label=""):
        self.put_files(items, ack, st, ov)
        queue = self.reformat_queue()
        expected = [(it.get("conversation_id"), it.get("project")) for it in queue
                    if it.get("category_key") in CATS4]
        got = [(r["key"], r["project"]) for r in self.panel_rows()]
        self.assertEqual(sorted(got, key=repr), sorted(expected, key=repr),
                         f"{label} パネル={got} / v2の再生成(4区分)={expected}")
        return got, expected


class TestSameJudgementAsReformatV2(StillOpenCase):
    def test_handpicked_combinations(self):
        """確認済み (同じ/違う/件数なし)・action_keys (全部済/一部/不明/progress なし/空/None/なし)・PJ上書き・区分の組合せ。"""
        items = [
            v2_item("R-open", "reminded"),
            v2_item("T-open", "them_stalled"),
            v2_item("R-ack-same", "reminded", mail_count=4),
            v2_item("S-ack-diff", "silent", mail_count=4),
            v2_item("P-ack-nomc", "spiking", mail_count=ABSENT),
            v2_item("W-ack-nomc-has", "waiting", mail_count=2),
            v2_item("W-done", "waiting", action_keys=["d1", "d2"]),
            v2_item("W-ign", "waiting", action_keys=["i1"]),
            v2_item("W-mixed-closed", "waiting", action_keys=["d1", "i1"]),
            v2_item("W-partial", "waiting", action_keys=["d1", "p1"]),
            v2_item("W-unknown-key", "waiting", action_keys=["d1", "nokey"]),
            v2_item("W-noprog", "waiting", action_keys=["np"]),
            v2_item("W-empty-keys", "waiting", action_keys=[]),
            v2_item("W-none-keys", "waiting", action_keys=None),
            v2_item("W-no-keys", "waiting", action_keys=ABSENT),
            v2_item("S-ov", "silent", project="PJ-old"),
            v2_item("T-ov", "them_stalled", project="PJ-old"),
            v2_item("X-cat", "unknown_cat"),
            v2_item("R-ack-done", "reminded", mail_count=1, action_keys=["d1"]),
        ]
        ack = {"R-ack-same": {"mail_count": 4, "acknowledged_at": "2031-03-10T10:00:00"},
               "S-ack-diff": {"mail_count": 3}, "P-ack-nomc": {"acknowledged_at": "x"},
               "W-ack-nomc-has": {"acknowledged_at": "x"}, "R-ack-done": {"mail_count": 2}}
        st = {"d1": {"progress": "done"}, "d2": {"progress": "done"}, "i1": {"progress": "ignored"},
              "p1": {"progress": "in_progress"}, "np": {"priority": "high"}}
        ov = {"S-ov": "PJ-new", "T-ov": "PJ-new", "nonexistent": "PJ-x"}
        got, expected = self.assert_same(items, ack, st, ov)
        self.assertEqual([k for k, _ in expected],
                         ["R-open", "S-ack-diff", "W-ack-nomc-has", "W-partial", "W-unknown-key", "W-noprog",
                          "W-empty-keys", "W-none-keys", "W-no-keys", "S-ov"],
                         "(比較の基準の確認) _reformat_cockpit_v2 の結果が想定と違う")
        self.assertIn(("S-ov", "PJ-new"), got)

    def test_without_the_three_side_files(self):
        """確認済み・状態・PJ上書きのファイルが無いときも一致 (全部まだ開いている)。"""
        self.assert_same([v2_item("A", "reminded"), v2_item("B", "them_stalled"), v2_item("C")])

    def test_random_combinations(self):
        """乱数で作った150通り (固定の seed) で一致。"""
        rng = random.Random(20261004)
        for case in range(150):
            items, ack, st, ov = random_case(rng)
            with self.subTest(case=case):
                self.assert_same(items, ack, st, ov, label=f"case {case}:")


class TestSpecGapSameJudgementAsReformatV2(StillOpenCase):
    def test_empty_ack_dict_and_an_item_without_mail_count(self):
        # 仕様の文「ack が dict で、ack.get("mail_count") == item.get("mail_count") なら除外」をそのまま読むと、
        # ack = {} と mail_count の無い item は (None == None で) 除外になる。一方 _still_open は `if ack and …` なので
        # 空の dict は確認済みとみなさない (表示)。仕様の見出し「_still_open と同じ」を優先して、_still_open と一致すること
        items = [v2_item("E1", "waiting", mail_count=ABSENT), v2_item("E2", "reminded", mail_count=None)]
        got, expected = self.assert_same(items, {"E1": {}, "E2": {}}, {}, {})
        self.assertEqual(len(expected), 2, "(比較の基準の確認) _still_open は空の dict を確認済みとみなさない")


# ============================================================
# 3. GUI (xvfb)
# ============================================================
def mrow(cid, cat="waiting", **kw):
    """パネルに渡す行 (仕様の行の形)。"""
    r = {"key": cid, "category_key": cat, "category_label": labels().get(cat, cat), "project": f"PJ-{cid}",
         "topic": f"AI件名{cid}", "real_topic": f"実件名{cid}", "entry_id": f"ENTRY-{cid}",
         "latest_date_display": "03/10 09:15", "days_elapsed": 3, "days_now": 3.1,
         "reasons_text": f"根拠{cid}-1・根拠{cid}-2"}
    r.update(kw)
    return r


def msnap(rows, state="ok", status_text=None, **kw):
    """パネルに渡すスナップショット (仕様の戻り値の形)。"""
    rows = list(rows)
    s = {"state": state, "rows": rows, "count": len(rows),
         "reminded": sum(1 for r in rows if r.get("category_key") == "reminded"),
         "generated_at": "2031-03-15 09:30", "age_days": 0.1, "stale": False,
         "status_text": status_text if status_text is not None else f"状態{state}{len(rows)}"}
    if state == "error":
        s["error"] = "RuntimeError: テスト"
    s.update(kw)
    return s


class MyCourtCase(a6tabs.TabsCase):
    """本番と同じ順 (_build_main_tabs → _ui_action_tab → ステータス行) で組み立てる。
    record_after=True なら root.after を記録し、500ms 以上の予約 (900ms の初回・120秒の定期) は実際には予約しない。"""

    def setUp(self):
        super().setUp()
        self.after_calls = []
        self.popups = []

    def build(self, record_after=True, select_action=True, update=True, prebind=None, no_ai=False,
              geometry="1100x900+0+0"):
        mod = oto()
        gui = self.new_gui(geometry)
        if record_after:
            real_after = gui.root.after
            calls = self.after_calls

            def rec(ms, func=None, *args):
                calls.append((ms, func))
                if isinstance(ms, (int, float)) and ms >= 500:
                    return f"after#fake{len(calls)}"
                return real_after(ms, func, *args)
            gui.root.after = rec
        gui._build_main_tabs()
        if prebind is not None:
            gui.notebook.bind("<<NotebookTabChanged>>", prebind)
        gui.project_knowledge = {"staffs": {}, "projects": {}}
        gui.outlook = self.stub_outlook = a1gui.StubOutlook()
        gui.summarizer = a1gui._Boom("summarizer") if no_ai else a1gui.StubSummarizer()
        gui.reporter = a1gui._Boom("reporter") if no_ai else a1gui.StubReporter()
        gui.config = dict(mod.DEFAULT_CONFIG)
        gui.threads = {}
        gui.selected = set()
        if select_action:
            gui.notebook.select(gui.tab_action)
            if update:
                gui.root.update()                 # タブ切替のイベントを、パネルのバインドより前に流す
        gui._ui_action_tab()                      # ← 検査対象 (A1 の判断待ちパネル + このパネル)
        gui.lbl_stat = ttk.Label(gui.root, text="Ready", relief="sunken", padding=2)   # 本番でも _ui_action_tab の後
        gui.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)
        if update:
            gui.root.update()
        return gui

    # ---- 探索 ---------------------------------------------------------
    def my_panel(self):
        found = [w for w in walk(self.gui.tab_action)
                 if isinstance(w, (ttk.LabelFrame, tk.LabelFrame)) and str(w.cget("text")) == PANEL_TEXT]
        self.assertEqual(len(found), 1, f"LabelFrame「{PANEL_TEXT}」が {len(found)} 個ある")
        return found[0]

    def a1_panel(self):
        found = [w for w in walk(self.gui.tab_action)
                 if isinstance(w, (ttk.LabelFrame, tk.LabelFrame)) and "判断待ち" in str(w.cget("text"))]
        self.assertEqual(len(found), 1, f"判断待ちパネルが {len(found)} 個ある")
        return found[0]

    def my_tree(self):
        found = [w for w in walk(self.my_panel()) if isinstance(w, ttk.Treeview)]
        self.assertEqual(len(found), 1, f"パネルの Treeview が {len(found)} 個ある")
        return found[0]

    def my_buttons(self, text):
        return [w for w in walk(self.my_panel())
                if isinstance(w, (ttk.Button, tk.Button)) and str(w.cget("text")) == text]

    def label_with_var(self, var):
        name = str(var)
        found = [w for w in walk(self.my_panel())
                 if isinstance(w, (ttk.Label, tk.Label)) and str(w.cget("textvariable")) == name]
        self.assertEqual(len(found), 1, f"{name} を表示するラベルが {len(found)} 個ある")
        return found[0]

    def rows(self):
        tree = self.my_tree()
        return [tuple(str(v) for v in tree.item(i, "values")) for i in tree.get_children()]

    def topics(self):
        return [r[2] for r in self.rows()]

    def iid_of(self, topic):
        tree = self.my_tree()
        found = [i for i in tree.get_children() if str(tree.item(i, "values")[2]) == topic]
        self.assertEqual(len(found), 1, f"件名 {topic!r} の行が {len(found)} 個ある: {self.rows()}")
        return found[0]

    def selected_topics(self):
        tree = self.my_tree()
        return [str(tree.item(i, "values")[2]) for i in tree.selection()]

    def status(self):
        return self.gui._action_my_court_status_var.get()

    def detail(self):
        return self.gui._action_my_court_detail_var.get()

    # ---- 操作 ---------------------------------------------------------
    def apply_my(self, snap):
        self.gui._apply_action_my_court_view(snap)
        self.gui.root.update()

    def select_topic(self, topic):
        self.my_tree().selection_set(self.iid_of(topic))
        self.settle(0.1)

    def _row_point(self, topic):
        tree = self.my_tree()
        iid = self.iid_of(topic)
        tree.see(iid)
        self.gui.root.update()
        bbox = tree.bbox(iid)
        self.assertTrue(bbox, "行が表示されていない")
        x, y, w, h = bbox
        return tree, x + min(max(w - 1, 1), 12), y + h // 2

    def double_click(self, topic):
        tree, cx, cy = self._row_point(topic)
        for _ in range(2):                         # <Double-1> は event_generate できないので2回クリック
            tree.event_generate("<ButtonPress-1>", x=cx, y=cy)
            tree.event_generate("<ButtonRelease-1>", x=cx, y=cy)
        self.gui.root.update()

    def right_click(self, topic):
        tree, cx, cy = self._row_point(topic)
        rx, ry = tree.winfo_rootx() + cx, tree.winfo_rooty() + cy
        tree.event_generate("<ButtonPress-3>", x=cx, y=cy, rootx=rx, rooty=ry)
        tree.event_generate("<ButtonRelease-3>", x=cx, y=cy, rootx=rx, rooty=ry)
        self.gui.root.update()

    def patch_popup(self):
        """右クリックメニューを実際には出さず (grab を避ける)、出そうとしたメニューを記録する。"""
        def rec(menu, *a, **k):
            self.popups.append(menu)
        for name in ("tk_popup", "post"):
            p = mock.patch.object(tk.Menu, name, rec)
            p.start()
            self.addCleanup(p.stop)

    def invoke_menu(self, menu, fragment):
        end = menu.index("end")
        found = []
        for i in range(0 if end is None else end + 1):
            try:
                lab = str(menu.entrycget(i, "label"))
            except tk.TclError:
                continue
            found.append(lab)
            if fragment in lab:
                menu.invoke(i)
                self.gui.root.update()
                return lab
        self.fail(f"メニューに「{fragment}」が無い: {found}")

    def patch_builder(self, fn):
        p = mock.patch.object(oto(), "build_cockpit_v2_my_court_snapshot", fn)
        p.start()
        self.addCleanup(p.stop)

    def counting_builder(self):
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return msnap([], status_text=f"N{len(calls)}")
        self.patch_builder(fake)
        return calls

    def wait_explorer(self, n=1):
        return self.pump(lambda: len(self.stub_outlook.explorer_calls) >= n, timeout=5)

    def cancel_afters(self):
        root = self.gui.root
        for aid in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(aid)


class TestPanelPlacement(MyCourtCase):
    """置き場所: アクションタブ・判断待ちパネルの下 (同じ親の最後)・fill X・expand しない。"""

    def test_the_action_tab_has_the_panel_with_the_spec_text(self):
        """アクションタブに LabelFrame「📥 自分待ち・🔥 催促（統括コックピットv2の前回結果・毎週更新）」が1つ。"""
        self.build()
        self.assertIsInstance(self.my_panel(), ttk.LabelFrame)

    def test_panel_padding_is_8(self):
        self.build()
        self.assertEqual(set(_ints(self.my_panel().cget("padding"))), {8})

    def test_panel_is_packed_fill_both_expand_pady_8_0(self):
        """(fix1) pack(fill=tk.BOTH, expand=True, pady=(8, 0))。"""
        self.build()
        info = self.my_panel().pack_info()
        self.assertEqual(str(info["fill"]), "both")
        self.assertTrue(_truthy(info["expand"]), "expand する")
        self.assertEqual(_ints(info["pady"]), (8, 0))
        self.assertEqual(str(info["side"]), "top")

    def test_the_list_frame_fills_and_expands(self):
        """(fix1) 一覧の枠も fill=BOTH, expand=True。"""
        self.build()
        tree, panel = self.my_tree(), self.my_panel()
        frame = tree if str(tree.master) == str(panel) else tree.master
        while str(frame.master) != str(panel):
            frame = frame.master
        info = frame.pack_info()
        self.assertEqual((str(info["fill"]), _truthy(info["expand"])), ("both", True), f"{frame}: {info}")

    def test_with_spare_height_both_panels_and_the_list_grow(self):
        """(fix1) 余白があるときは、判断待ちと分け合って広がる (一覧も伸びる)。"""
        gui = self.build(geometry="1100x1000+0+0")
        mine, a1, tree = self.my_panel(), self.a1_panel(), self.my_tree()
        main = mine.master
        if main.winfo_height() < main.winfo_reqheight() + 60:
            self.skipTest(f"余白が作れない (高さ {main.winfo_height()} / 必要 {main.winfo_reqheight()})")
        self.assertGreater(mine.winfo_height(), mine.winfo_reqheight() + 10, "このパネルが広がらない")
        self.assertGreater(a1.winfo_height(), a1.winfo_reqheight() + 10, "判断待ちパネルが広がらない")
        self.assertGreater(tree.winfo_height(), tree.winfo_reqheight() + 10, "一覧が伸びない")

    def test_the_action_tab_does_not_propagate_its_size(self):
        """(fix1) self.tab_action.pack_propagate(False) (パネルを足してもアクションタブの必要な高さを上げない)。"""
        gui = self.build()
        self.assertFalse(_truthy(gui.tab_action.pack_propagate()))

    # ---- (fix1) 上位タブ全体の必要な高さ・画面下のステータス行 ----------------
    def full_gui(self, with_panel=True):
        """6つの _ui_*_tab をすべて組んだ本番の構成 (ステータス行は最後)。with_panel=False は、このパネルを作らない
        (= _08 の _ui_action_tab と同じ構成)。定期の再読込の予約は取り消しておく。"""
        mod = oto()
        ctx = (contextlib.nullcontext() if with_panel else
               mock.patch.object(mod.MailManagerGUI, "_ui_action_my_court_panel", lambda self, parent: None))
        with ctx:
            gui = self.make_main(ui=a6tabs.UI_ORDER)
        gui.root.update_idletasks()
        self.cancel_afters()
        return gui

    def required_heights(self):
        """(パネルなし=_08 と同じ構成, パネルあり) の上位Notebook の必要な高さ。Tk を2つ同時に生かさない。"""
        old = self.full_gui(with_panel=False)
        old_h = old.notebook.winfo_reqheight()
        self.cancel_afters()
        old.root.destroy()
        self.gui = None
        new = self.full_gui(with_panel=True)
        return old_h, new.notebook.winfo_reqheight()

    def test_the_top_notebook_needs_the_same_height_as_before(self):
        """(fix1) 6つのタブを組んだときの上位Notebook の必要な高さは、このパネルが無い構成 (_08) と同じ。"""
        old_h, new_h = self.required_heights()
        self.assertGreater(old_h, 100, "(前提) 必要な高さが測れる")
        self.assertLessEqual(new_h, old_h + 2, f"パネルで必要な高さが増えた: {old_h} → {new_h}")
        self.assertGreaterEqual(new_h, old_h - 2, f"必要な高さが変わった: {old_h} → {new_h}")

    def test_the_status_line_at_the_bottom_is_not_squeezed(self):
        """(fix1) 窓の高さが「パネルが無い構成の必要な高さ + ステータス行」あれば、画面下のステータス行は潰れない
        (このパネルの分の高さは要求しない)。どのタブを開いていても同じ。"""
        old_h, _ = self.required_heights()
        gui = self.gui
        lbl = gui.lbl_stat
        height = old_h + lbl.winfo_reqheight() + 10 + 30          # 10 = 上位Notebook の pady (上下5)、30 = 余裕
        gui.root.geometry(f"1100x{height}+0+0")
        for page in (gui.tab_search, gui.tab_action, gui.nb_weekly, gui.tab_review):
            with self.subTest(tab=gui.notebook.tab(page, "text")):
                gui.notebook.select(page)
                self.drain()
                gui.root.update_idletasks()
                if abs(gui.root.winfo_height() - height) > 4:
                    self.skipTest(f"窓の高さを {height}px にできない (実際 {gui.root.winfo_height()}px)")
                self.assertGreaterEqual(lbl.winfo_height(), lbl.winfo_reqheight(), "ステータス行が潰れている")
                self.assertLessEqual(lbl.winfo_y() + lbl.winfo_height(), gui.root.winfo_height())

    def test_panel_shares_the_frame_of_the_decision_panel_and_is_packed_last(self):
        """判断待ちパネルと同じ親 (_ui_action_tab の main) で、判断待ちの次・最後に置かれる。"""
        self.build()
        mine, a1 = self.my_panel(), self.a1_panel()
        self.assertEqual(mine.winfo_parent(), a1.winfo_parent())
        slaves = [str(s) for s in mine.master.pack_slaves()]
        self.assertLess(slaves.index(str(a1)), slaves.index(str(mine)))
        self.assertEqual(slaves[-1], str(mine))

    def test_panel_is_shown_below_the_decision_panel(self):
        """画面上も判断待ちパネルの下に見える。"""
        self.build()
        mine, a1 = self.my_panel(), self.a1_panel()
        self.assertTrue(mine.winfo_viewable())
        self.assertGreaterEqual(mine.winfo_rooty(), a1.winfo_rooty() + a1.winfo_height() - 1)

    def test_decision_panel_keeps_its_layout(self):
        """判断待ちパネル (A1) の配置は変わらない (fill both・expand・pady (10, 0))。"""
        self.build()
        info = self.a1_panel().pack_info()
        self.assertEqual((str(info["fill"]), _truthy(info["expand"]), _ints(info["pady"])), ("both", True, (10, 0)))

    def test_in_a_low_window_this_panel_shrinks_before_the_decision_panel(self):
        """窓が低いときは、後から置いたこのパネルが先に縮む (判断待ちパネルは必要な高さを保つ)。"""
        gui = self.build(geometry="1100x1000+0+0")
        root, mine, a1 = gui.root, self.my_panel(), self.a1_panel()
        main = mine.master
        root.update()
        root.update_idletasks()
        if main.winfo_height() < main.winfo_reqheight():
            self.skipTest("前提: 最初の高さで全部が収まらない")
        overhead = root.winfo_height() - main.winfo_height()
        need_mine = mine.winfo_reqheight() + sum(_ints(mine.pack_info()["pady"]))
        target = main.winfo_reqheight() - need_mine // 2
        root.geometry(f"1100x{target + overhead}+0+0")
        root.update()
        root.update_idletasks()
        root.update()
        if abs(main.winfo_height() - target) > 4:
            self.skipTest(f"高さを {target}px にできない (実際 {main.winfo_height()}px)")
        self.assertGreaterEqual(a1.winfo_height(), a1.winfo_reqheight() - 2, "判断待ちパネルが先に縮んだ")
        self.assertLess(mine.winfo_height(), mine.winfo_reqheight() - 10, "このパネルが縮んでいない")


class TestTreeAndWidgets(MyCourtCase):
    """一覧 (Treeview) ・スクロールバー・状態表示・詳細・再読込ボタン。"""

    def test_tree_attribute_is_the_treeview_of_the_panel(self):
        gui = self.build()
        self.assertIsInstance(gui.tree_action_my_court, ttk.Treeview)
        self.assertEqual(str(gui.tree_action_my_court), str(self.my_tree()))

    def test_columns_and_headings(self):
        """列 ("cat", "proj", "topic", "days", "date")・見出し「区分」「PJ」「件名」「経過」「最終」。"""
        self.build()
        tree = self.my_tree()
        self.assertEqual(tuple(str(c) for c in tree["columns"]), ("cat", "proj", "topic", "days", "date"))
        self.assertEqual([str(tree.heading(c, "text")) for c in ("cat", "proj", "topic", "days", "date")],
                         ["区分", "PJ", "件名", "経過", "最終"])

    def test_show_selectmode_height(self):
        """show="headings"・selectmode="browse"・height=5。"""
        self.build()
        tree = self.my_tree()
        self.assertEqual(_words(tree.cget("show")), ["headings"])
        self.assertEqual(str(tree.cget("selectmode")), "browse")
        self.assertEqual(int(str(tree.cget("height"))), 5)

    def test_column_widths_anchors_and_the_stretching_topic(self):
        """区分130・PJ90・件名 stretch (minwidth 160)・経過50 中央・最終80 中央 (配置で幅が変わる前の設定値)。"""
        self.build(update=False)
        tree = self.my_tree()
        self.assertEqual({c: int(_num(tree.column(c, "width"))) for c in ("cat", "proj", "days", "date")},
                         {"cat": 130, "proj": 90, "days": 50, "date": 80})
        self.assertTrue(_truthy(tree.column("topic", "stretch")))
        self.assertEqual(int(_num(tree.column("topic", "minwidth"))), 160)
        self.assertEqual((str(tree.column("days", "anchor")), str(tree.column("date", "anchor"))), ("center", "center"))

    def test_vertical_scrollbar_is_connected_to_the_tree(self):
        """縦スクロールバーがあり、一覧と連動する。"""
        self.build()
        tree = self.my_tree()
        bars = [w for w in walk(self.my_panel())
                if isinstance(w, (ttk.Scrollbar, tk.Scrollbar)) and str(w.cget("orient")) == "vertical"]
        self.assertEqual(len(bars), 1, "縦スクロールバーが無い")
        self.assertTrue(str(bars[0].cget("command")).strip(), "スクロールバーの command が無い")
        self.assertTrue(str(tree.cget("yscrollcommand")).strip(), "Treeview の yscrollcommand が無い")
        self.apply_my(msnap([mrow(f"C{i:02d}") for i in range(30)]))
        first = tuple(bars[0].get())
        tree.yview_moveto(1.0)
        self.gui.root.update()
        self.assertNotEqual(tuple(bars[0].get()), first, "一覧をスクロールしてもスクロールバーが動かない")

    def test_reload_button_exists_once_and_rereads(self):
        """「🔄 再読込」がパネルに1つあり、押すと読み直す。"""
        self.build()
        btns = self.my_buttons(RELOAD_TEXT)
        self.assertEqual(len(btns), 1, f"パネルの「{RELOAD_TEXT}」が {len(btns)} 個")
        calls = []
        self.patch_builder(lambda *a, **k: (calls.append(1), msnap([mrow("A")], status_text="RELOADED"))[1])
        btns[0].invoke()
        self.assertTrue(self.pump(lambda: self.status() == "RELOADED", timeout=5), self.status())
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.topics(), ["AI件名A"])

    def test_status_label_starts_with_loading_and_is_gray_and_left_aligned(self):
        """状態表示 _action_my_court_status_var: 初期値「読み込み中...」、ttk.Label・灰色・左寄せ。"""
        gui = self.build()
        self.assertEqual(self.status(), LOADING_TEXT)
        lbl = self.label_with_var(gui._action_my_court_status_var)
        self.assertIsInstance(lbl, ttk.Label)
        self.assertEqual(str(lbl.cget("foreground")), "gray")
        self.assertLessEqual(lbl.winfo_x(), 12, "状態表示が左寄せになっていない")

    def test_status_label_wraps_with_the_panel_width(self):
        """状態表示の折り返し幅は、パネルの幅に合わせて変わる。"""
        gui = self.build()
        lbl = self.label_with_var(gui._action_my_court_status_var)
        panel = self.my_panel()

        def measure(width):
            gui.root.geometry(f"{width}x900+0+0")
            for _ in range(3):
                gui.root.update()
                gui.root.update_idletasks()
            return panel.winfo_width(), _num(lbl.cget("wraplength"))
        p1, w1 = measure(1200)
        p2, w2 = measure(850)
        if p1 - p2 < 150:
            self.skipTest(f"窓の幅を変えられない (パネル {p1}px → {p2}px)")
        self.assertGreater(w1, 0, "折り返し幅が設定されていない")
        self.assertGreater(w2, 0)
        self.assertLess(w2, w1, "パネルが狭くなっても折り返し幅が変わらない")
        self.assertLessEqual(w1, p1)
        self.assertLessEqual(w2, p2)

    def test_detail_is_empty_before_selection(self):
        """詳細 _action_my_court_detail_var: 未選択なら空。"""
        self.build()
        self.assertEqual(self.detail(), "")
        self.apply_my(msnap([mrow("A"), mrow("B")]))
        self.assertEqual(self.detail(), "")


class TestApplyView(MyCourtCase):
    """_apply_action_my_court_view: 状態表示を更新し、一覧を描き直す (state が ok 以外なら空)。"""

    def test_rows_show_category_project_topic_days_and_date(self):
        """各行: 区分=category_label・PJ=project・件名=topic・経過=「int(days_now)日」(fix1)・最終=latest_date_display。"""
        self.build()
        rows = [mrow("A", "reminded", project="PJ-X", topic="件名A", days_elapsed=12, days_now=12.4,
                     latest_date_display="02/28 17:05"),
                mrow("B", "silent", project="", topic="件名B", days_elapsed=0, days_now=0, latest_date_display="03/14 08:00"),
                mrow("C", "waiting", category_label="📥 自分待ち(独自)", project="PJ-Z", topic="件名C", days_elapsed=4.5,
                     days_now=7.6, latest_date_display="")]
        self.apply_my(msnap(rows))
        got = self.rows()
        self.assertEqual(len(got), 3)
        for r, g in zip(rows, got):
            with self.subTest(row=r["key"]):
                self.assertEqual((g[0], g[1], g[2], g[4]),
                                 (r["category_label"], r["project"], r["topic"], r["latest_date_display"]))
        self.assertEqual([g[3] for g in got], ["12日", "0日", "7日"])

    def test_days_column_uses_days_now_not_days_elapsed(self):
        """(fix1) 「経過」は今日までの日数 int(days_now)。v2 の時点の days_elapsed ではない。"""
        self.build()
        self.apply_my(msnap([mrow("A", days_elapsed=3, days_now=9.95), mrow("B", days_elapsed=20.2, days_now=20.2),
                             mrow("C", days_elapsed=0.4, days_now=1.0)]))
        self.assertEqual([r[3] for r in self.rows()], ["9日", "20日", "1日"])

    def test_rows_keep_the_snapshot_order(self):
        self.build()
        self.apply_my(msnap([mrow("C"), mrow("A", "reminded"), mrow("B", "spiking")]))
        self.assertEqual(self.topics(), ["AI件名C", "AI件名A", "AI件名B"])

    def test_status_text_is_shown(self):
        self.build()
        text = "📥 ボールが自分にある案件 1件（うち🔥催促されている 0件）｜v2の前回結果: 03/15 09:30（今日）" + STALE_LINE
        self.apply_my(msnap([mrow("A")], status_text=text))
        self.assertEqual(self.status(), text)

    def test_non_ok_states_leave_the_list_empty(self):
        """missing / error では一覧が空 (rows が入っていても出さない)・状態表示はその文言。"""
        self.build()
        self.apply_my(msnap([mrow("A"), mrow("B")]))
        self.assertEqual(len(self.rows()), 2)
        self.apply_my(msnap([], state="missing", status_text=MISSING_TEXT))
        self.assertEqual((self.rows(), self.status()), ([], MISSING_TEXT))
        self.apply_my(msnap([mrow("A")]))
        self.apply_my(msnap([mrow("E")], state="error", status_text=error_text("RuntimeError")))
        self.assertEqual(self.rows(), [], "state が ok 以外なら一覧は空")
        self.assertEqual(self.status(), error_text("RuntimeError"))

    def test_apply_is_repeatable_and_replaces_rows(self):
        self.build()
        snap = msnap([mrow("A"), mrow("B")])
        for _ in range(10):
            self.apply_my(snap)
        self.assertEqual(self.topics(), ["AI件名A", "AI件名B"])
        self.apply_my(msnap([mrow("D"), mrow("B")]))
        self.assertEqual(self.topics(), ["AI件名D", "AI件名B"])

    def test_special_characters_are_shown_as_is(self):
        """件名・PJ・key に Tcl の特殊文字があっても、そのまま表示できる。"""
        self.build()
        nasty = 'a {b} \\ "c" $d [e] ; 件名 {unbalanced'
        self.apply_my(msnap([mrow("A", key=nasty, topic=nasty, project="O'Brien {x}"), mrow("B")]))
        self.assertEqual(self.rows()[0][1:3], ("O'Brien {x}", nasty))
        self.assertEqual(len(self.rows()), 2)


class TestSelectionAndDetail(MyCourtCase):
    """選択で詳細「根拠: {reasons_text or '—'} ／ 件名: {real_topic}」。描き直しても残っている行は選択し直す。"""

    def test_selecting_a_row_shows_its_reasons_and_real_topic(self):
        self.build()
        self.apply_my(msnap([mrow("A", reasons_text="⏰ 4日間 動きなし・👥 2人が待っている", real_topic="RE: 実件名A"),
                             mrow("B")]))
        self.select_topic("AI件名A")
        self.assertEqual(self.detail(), detail_text("⏰ 4日間 動きなし・👥 2人が待っている", "RE: 実件名A"))
        self.assertEqual(self.detail(), "根拠: ⏰ 4日間 動きなし・👥 2人が待っている ／ 件名: RE: 実件名A")

    def test_a_row_without_reasons_shows_a_dash(self):
        self.build()
        self.apply_my(msnap([mrow("A", reasons_text="")]))
        self.select_topic("AI件名A")
        self.assertEqual(self.detail(), "根拠: — ／ 件名: 実件名A")

    def test_selection_is_kept_when_the_row_remains(self):
        self.build()
        self.apply_my(msnap([mrow("A"), mrow("B"), mrow("C")]))
        self.select_topic("AI件名B")
        self.apply_my(msnap([mrow("C"), mrow("B", project="PJ-変更"), mrow("D")]))
        self.settle(0.1)
        self.assertEqual(self.selected_topics(), ["AI件名B"])

    def test_selection_and_detail_are_cleared_when_the_row_vanishes(self):
        self.build()
        self.apply_my(msnap([mrow("A"), mrow("B")]))
        self.select_topic("AI件名B")
        self.assertTrue(self.detail())
        self.apply_my(msnap([mrow("A"), mrow("C")]))
        self.settle(0.1)
        self.assertEqual(self.selected_topics(), [])
        self.assertEqual(self.detail(), "")

    def test_a_non_ok_state_clears_the_detail(self):
        self.build()
        self.apply_my(msnap([mrow("A")]))
        self.select_topic("AI件名A")
        self.apply_my(msnap([], state="missing", status_text=MISSING_TEXT))
        self.settle(0.1)
        self.assertEqual(self.detail(), "")


class TestOpenInOutlook(MyCourtCase):
    """ダブルクリック・右クリック「📧 Outlookで開く」: show_thread_in_explorer(real_topic or topic, entry_id) を
    ワーカースレッドで呼ぶ。entry_id が空なら showinfo「このスレッドにはOutlookで開くためのIDがありません。…」。"""

    def setup_rows(self, rows):
        self.build()
        self.apply_my(msnap(rows))

    def test_double_click_opens_the_thread_in_a_worker_thread(self):
        self.setup_rows([mrow("A", real_topic="RE: 実件名X", topic="AI件名X", entry_id="ENTRY-X")])
        self.double_click("AI件名X")
        self.assertTrue(self.wait_explorer(), "ダブルクリックで show_thread_in_explorer が呼ばれない")
        calls = self.stub_outlook.explorer_calls
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["topic"], calls[0]["entry_id"]), ("RE: 実件名X", "ENTRY-X"))
        self.assertFalse(calls[0]["in_main_thread"], "COM を触る関数をメインスレッドで呼んでいる")
        self.assertTrue(calls[0]["daemon"], "daemon=True のスレッドで呼ぶ")

    def test_empty_real_topic_falls_back_to_the_topic(self):
        self.setup_rows([mrow("A", real_topic="", topic="AI件名だけ", entry_id="E-1")])
        self.double_click("AI件名だけ")
        self.assertTrue(self.wait_explorer())
        self.assertEqual(self.stub_outlook.explorer_calls[0]["topic"], "AI件名だけ")

    def test_each_row_uses_its_own_ids(self):
        self.setup_rows([mrow("A", entry_id="E-A"), mrow("B", entry_id="E-B")])
        self.double_click("AI件名B")
        self.assertTrue(self.wait_explorer())
        c = self.stub_outlook.explorer_calls[0]
        self.assertEqual((c["topic"], c["entry_id"]), ("実件名B", "E-B"))

    def test_empty_entry_id_shows_the_message_and_does_not_open(self):
        for eid in ("", None):
            with self.subTest(entry_id=eid):
                if self.gui is None:
                    self.build()
                self.dialogs.clear()
                self.apply_my(msnap([mrow("A", entry_id=eid)]))
                self.double_click("AI件名A")
                self.settle(0.4)
                self.assertEqual(self.stub_outlook.explorer_calls, [], "entry_id が空なのに Outlook を呼んだ")
                self.assertIn(NO_ID_TEXT, self.dialog_text(("showinfo",)), f"showinfo が出ない: {self.dialogs}")

    def test_double_click_on_an_empty_area_does_nothing(self):
        self.setup_rows([mrow("A")])
        tree = self.my_tree()
        x, y = 5, max(tree.winfo_height() - 3, 5)
        for _ in range(2):
            tree.event_generate("<ButtonPress-1>", x=x, y=y)
            tree.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.settle(0.4)
        self.assertEqual(self.stub_outlook.explorer_calls, [])
        self.assertEqual(self.dialogs, [])

    def test_context_menu_open_in_outlook(self):
        """右クリックでメニューが出て、「📧 Outlookで開く」でその行を (ワーカースレッドで) 開く。"""
        self.patch_popup()
        self.setup_rows([mrow("A", entry_id="E-A"), mrow("B", entry_id="E-B", real_topic="RE: B")])
        self.select_topic("AI件名B")
        self.right_click("AI件名B")
        self.assertEqual(len(self.popups), 1, "右クリックでメニューが出ない")
        self.assertEqual(self.invoke_menu(self.popups[0], "Outlookで開く"), OPEN_LABEL)
        self.assertTrue(self.wait_explorer(), "メニューから開けない")
        c = self.stub_outlook.explorer_calls
        self.assertEqual([(x["topic"], x["entry_id"]) for x in c], [("RE: B", "E-B")])
        self.assertFalse(c[0]["in_main_thread"])

    def test_context_menu_with_an_empty_entry_id_shows_the_message(self):
        self.patch_popup()
        self.setup_rows([mrow("A", entry_id="")])
        self.select_topic("AI件名A")
        self.right_click("AI件名A")
        self.assertEqual(len(self.popups), 1)
        self.invoke_menu(self.popups[0], "Outlookで開く")
        self.settle(0.3)
        self.assertEqual(self.stub_outlook.explorer_calls, [])
        self.assertIn(NO_ID_TEXT, self.dialog_text(("showinfo",)))


class TestRefresh(MyCourtCase):
    """_refresh_action_my_court_view: ワーカーで build_cockpit_v2_my_court_snapshot(datetime.now()) → after(0) で反映。
    実行中の再要求は、終了後にもう1回だけ読み直す。例外は出さない。"""

    def test_builder_runs_in_a_worker_and_the_view_is_applied_in_the_main_thread(self):
        gui = self.build()
        seen, applied = [], []
        snap = msnap([mrow("A")], status_text="WORKER")

        def fake(*a, **k):
            seen.append({"main": threading.current_thread() is threading.main_thread(), "args": a, "kwargs": k})
            return snap
        orig = gui._apply_action_my_court_view

        def spy(s):
            applied.append((threading.current_thread() is threading.main_thread(), s))
            return orig(s)
        gui._apply_action_my_court_view = spy
        self.patch_builder(fake)
        t0 = datetime.now()
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status() == "WORKER", timeout=5), self.status())
        t1 = datetime.now()
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0]["main"], "集計をメインスレッドで実行している (画面が固まる)")
        self.assertEqual((len(seen[0]["args"]), seen[0]["kwargs"]), (1, {}), "build_…(datetime.now()) だけで呼ぶ")
        now_arg = seen[0]["args"][0]
        self.assertIsInstance(now_arg, datetime)
        self.assertTrue(t0 - timedelta(seconds=2) <= now_arg <= t1 + timedelta(seconds=2), now_arg)
        self.assertTrue(applied and all(m for m, _ in applied), "反映をメインスレッド以外で行っている")
        self.assertEqual(applied[-1][1], snap)
        self.assertEqual(self.topics(), ["AI件名A"])

    def test_a_request_during_a_run_rereads_exactly_once_afterwards(self):
        """実行中に何回再要求しても多重には動かず、終わった後にもう1回だけ読み直す (最後の結果が出る)。"""
        gui = self.build()
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        calls = []

        def builder(*a, **k):
            calls.append(1)
            n = len(calls)
            if n == 1:
                started.set()
                gate.wait(10)
            return msnap([mrow(f"R{n}")], status_text=f"RUN{n}")
        self.patch_builder(builder)
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(started.is_set, timeout=5), "ワーカーが始まらない")
        for _ in range(3):
            gui._refresh_action_my_court_view()
        self.settle(0.3)
        self.assertEqual(len(calls), 1, "実行中に多重起動した")
        gate.set()
        self.assertTrue(self.pump(lambda: self.status() == "RUN2", timeout=5), f"読み直しが無い: {self.status()!r}")
        self.settle(0.4)
        self.assertEqual(len(calls), 2, "読み直しは1回だけ")
        self.assertEqual(self.topics(), ["AI件名R2"])

    def test_can_refresh_again_after_completion(self):
        gui = self.build()
        calls = []
        self.patch_builder(lambda *a, **k: (calls.append(1), msnap([], status_text=f"N{len(calls)}"))[1])
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status() == "N1", timeout=5))
        self.settle(0.1)
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status() == "N2", timeout=5), "完了後の2回目が動かない")

    def test_a_builder_exception_does_not_escape(self):
        """集計関数が (想定外に) 例外を出しても、ワーカー・Tk のコールバックから例外が漏れない (後始末で確認)。"""
        gui = self.build()

        def boom(*a, **k):
            raise RuntimeError("想定外の例外")
        self.patch_builder(boom)
        gui._refresh_action_my_court_view()
        self.settle(0.5)

    def test_end_to_end_with_real_files(self):
        """実ファイル: them_stalled・確認済み・全部完了は出ず、PJ上書きが効き、状態表示は件数と「N日前」。何も書かない。"""
        mod = oto()
        gen_dt = datetime.now() - timedelta(days=2, hours=3)
        items = [v2_item("A", "reminded", topic="件名A", project="PJ-A"),
                 v2_item("B", "them_stalled", topic="件名B"),
                 v2_item("C", "waiting", topic="件名C", mail_count=4),
                 v2_item("D", "silent", topic="件名D"),
                 v2_item("E", "spiking", topic="件名E", project="PJ-E"),
                 v2_item("F", "waiting", topic="件名F", real_topic=ABSENT, latest_entry_id="")]
        write_json(mod.COCKPIT_V2_LAST_RESULT_FILE, v2_saved(items, gen_dt.strftime("%Y-%m-%d %H:%M")))
        write_json(mod.COCKPIT_V2_ACKNOWLEDGED_FILE, {"C": {"mail_count": 4, "acknowledged_at": "x"}})
        write_json(mod.ACTION_STATUS_FILE, {"D::0": {"progress": "done"}})
        write_json(mod.COCKPIT_V2_PROJECT_OVERRIDE_FILE, {"E": "PJ-OV"})
        gui = self.build()
        before = snapshot_files(".")
        gui._refresh_action_my_court_view()
        expected = ok_text(3, 1, f"{gen_dt:%m/%d %H:%M}（2日前）")
        self.assertTrue(self.pump(lambda: self.status() == expected, timeout=8), f"{self.status()!r} != {expected!r}")
        self.assertEqual(self.topics(), ["件名A", "件名E", "件名F"])
        self.assertEqual([r[1] for r in self.rows()], ["PJ-A", "PJ-OV", "PJ-A"])
        self.assertEqual([r[3] for r in self.rows()], ["6日"] * 3, "経過 = int(4.5 + 約2.1)")      # (fix1) days_now
        self.assertEqual(snapshot_files("."), before, "ファイルに書き込んだ")
        self.double_click("件名A")
        self.assertTrue(self.wait_explorer())
        self.assertEqual((self.stub_outlook.explorer_calls[0]["topic"], self.stub_outlook.explorer_calls[0]["entry_id"]),
                         ("実件名A", "ENTRY-A"))
        self.double_click("件名F")
        self.settle(0.3)
        self.assertEqual(len(self.stub_outlook.explorer_calls), 1)
        self.assertIn(NO_ID_TEXT, self.dialog_text(("showinfo",)))


class TestTriggers(MyCourtCase):
    """再読込のきっかけ: (1) パネルを作った後 after(900, tick)  (2) tick は再読込して ACTION_DECISION_REFRESH_MS 後に
    自分を予約し直す  (3) アクションタブが選ばれたら再読込 (A1 のバインドを壊さない)。"""

    def test_the_first_reload_is_scheduled_900ms_after_building(self):
        gui = self.build()
        first = [(ms, f) for ms, f in self.after_calls if ms == 900]
        self.assertEqual(len(first), 1, f"after の呼び出し: {[ms for ms, _ in self.after_calls]}")
        self.assertEqual(first[0][1], gui._action_my_court_tick)
        self.assertEqual(self.status(), LOADING_TEXT, "パネルを作った時点ではまだ読まない (900ms 後)")

    def test_tick_reloads_and_schedules_itself_again(self):
        gui = self.build()
        calls = []
        self.patch_builder(lambda *a, **k: (calls.append(1), msnap([mrow("A")], status_text=f"TICK{len(calls)}"))[1])
        n0 = len(self.after_calls)
        gui._action_my_court_tick()
        self.assertTrue(self.pump(lambda: self.status() == "TICK1", timeout=5), self.status())
        again = [(ms, f) for ms, f in self.after_calls[n0:] if ms == oto().ACTION_DECISION_REFRESH_MS]
        self.assertEqual(len(again), 1, f"after の呼び出し: {[ms for ms, _ in self.after_calls[n0:]]}")
        self.assertEqual(again[0][1], gui._action_my_court_tick)
        self.assertEqual(oto().ACTION_DECISION_REFRESH_MS, 120000, "(前提) A1 と同じ間隔")

    def test_the_scheduled_tick_keeps_repeating(self):
        gui = self.build()
        calls = []
        self.patch_builder(lambda *a, **k: (calls.append(1), msnap([], status_text=f"TICK{len(calls)}"))[1])
        first = [f for ms, f in self.after_calls if ms == 900]
        self.assertTrue(first)
        first[0]()                                  # 900ms 後の初回を実行
        self.assertTrue(self.pump(lambda: self.status() == "TICK1", timeout=5))
        nxt = [f for ms, f in self.after_calls if ms == oto().ACTION_DECISION_REFRESH_MS]
        self.assertTrue(nxt)
        nxt[-1]()                                   # 120秒後の分を実行
        self.assertTrue(self.pump(lambda: self.status() == "TICK2", timeout=5))
        self.assertEqual(len([f for ms, f in self.after_calls if ms == oto().ACTION_DECISION_REFRESH_MS]), 2)

    def test_the_first_tick_really_runs_after_startup(self):
        """(実際の after) 起動して約0.9秒後に読み込み、ファイルが無ければ missing の文言になる。"""
        self.build(record_after=False)
        self.assertEqual(self.status(), LOADING_TEXT)
        self.assertTrue(self.pump(lambda: self.status() == MISSING_TEXT, timeout=5), self.status())

    def test_selecting_the_action_tab_reloads_once(self):
        gui = self.build(select_action=False)
        calls = self.counting_builder()
        self.drain()
        self.assertEqual(calls, [], "起動直後 (検索タブ) に読み込んだ")
        gui.notebook.select(gui.tab_action)
        self.drain()
        self.assertTrue(self.pump(lambda: len(calls) >= 1, timeout=5), "アクションタブを選んでも読み直さない")
        self.settle(0.3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.status(), "N1")

    def test_other_tabs_do_not_reload(self):
        """毎週(俯瞰)・入れ子の3タブ・振り返り・検索を選んでも読み直さない。"""
        gui = self.build(select_action=False)
        calls = self.counting_builder()
        for nb, page in ((gui.notebook, gui.nb_weekly), (gui.nb_weekly, gui.tab_staff), (gui.nb_weekly, gui.tab_cockpit),
                         (gui.notebook, gui.tab_review), (gui.notebook, gui.tab_search)):
            nb.select(page)
            self.drain()
        self.settle(0.3)
        self.assertEqual(calls, [])

    def test_coming_back_to_the_action_tab_reloads_again(self):
        gui = self.build(select_action=False)
        calls = self.counting_builder()
        for page in (gui.tab_action, gui.nb_weekly, gui.tab_action, gui.tab_review, gui.tab_action):
            gui.notebook.select(page)
            self.drain()
        self.assertTrue(self.pump(lambda: len(calls) >= 3, timeout=5), f"{len(calls)}回")
        self.settle(0.3)
        self.assertEqual(len(calls), 3)

    def test_the_decision_panel_still_reloads_on_the_tab_change(self):
        """A1 のタブ切替の再読込も動く (このパネルのバインドで上書きしていない)。"""
        gui = self.build(select_action=False)
        a1 = []
        gui._refresh_action_decision_view = lambda: a1.append(1)
        calls = self.counting_builder()
        gui.notebook.select(gui.tab_action)
        self.drain()
        self.assertTrue(self.pump(lambda: calls, timeout=5))
        self.assertEqual(len(a1), 1, "A1 の再読込 (タブ切替のバインド) が壊れた")

    def test_existing_tab_change_bindings_are_kept(self):
        fired = []
        gui = self.build(select_action=False, prebind=lambda e: fired.append(1))
        gui._refresh_action_decision_view = lambda: None
        calls = self.counting_builder()
        fired.clear()
        gui.notebook.select(gui.tab_action)
        self.drain()
        self.assertTrue(self.pump(lambda: calls, timeout=5))
        self.assertTrue(fired, "既存の <<NotebookTabChanged>> のバインドが上書きされた (add=\"+\" でない)")


class TestStartupRobustness(MyCourtCase):
    """ファイルが無い / 壊れていても起動は止まらない (初回の自動読込で文言が出る)。Outlook・AI・書き込みなし。"""

    def startup(self):
        return self.build(record_after=False, select_action=False)

    def test_missing_file(self):
        self.startup()
        self.assertTrue(self.pump(lambda: self.status() == MISSING_TEXT, timeout=5), self.status())
        self.assertEqual(self.rows(), [])

    def test_broken_file(self):
        write_text(oto().COCKPIT_V2_LAST_RESULT_FILE, "{broken json")
        self.startup()
        self.assertTrue(self.pump(lambda: self.status() == error_text("JSONDecodeError"), timeout=5), self.status())
        self.assertEqual(self.rows(), [])

    def test_file_that_is_not_a_dict(self):
        write_json(oto().COCKPIT_V2_LAST_RESULT_FILE, [1, 2, 3])
        self.startup()
        self.assertTrue(self.pump(lambda: bool(ERROR_RE.match(self.status())), timeout=5), self.status())
        self.assertEqual(self.rows(), [])

    def test_broken_side_files_do_not_stop_the_list(self):
        mod = oto()
        write_json(mod.COCKPIT_V2_LAST_RESULT_FILE,
                   v2_saved([v2_item("A", "reminded"), v2_item("B")], datetime.now().strftime("%Y-%m-%d %H:%M")))
        write_text(mod.COCKPIT_V2_ACKNOWLEDGED_FILE, "{")
        write_text(mod.ACTION_STATUS_FILE, "[[[")
        write_text(mod.COCKPIT_V2_PROJECT_OVERRIDE_FILE, "{")
        self.startup()
        self.assertTrue(self.pump(lambda: self.status().startswith("📥 ボールが自分にある案件 2件"), timeout=5),
                        self.status())
        self.assertEqual(len(self.rows()), 2)

    def test_startup_touches_no_outlook_ai_or_files(self):
        """起動〜初回の読込で、Outlook (COM)・AI・ネットワークに触れず、ファイルも書かない。"""
        mod = oto()
        write_json(mod.COCKPIT_V2_LAST_RESULT_FILE, v2_saved([v2_item("A")], datetime.now().strftime("%Y-%m-%d %H:%M")))
        before = snapshot_files(".")
        for n in ("win32com", "pythoncom", "requests", "_CommonGeminiClient"):
            p = mock.patch.object(mod, n, a1gui._Boom(n), create=True)
            p.start()
            self.addCleanup(p.stop)
        self.build(record_after=False, select_action=False, no_ai=True)
        self.assertTrue(self.pump(lambda: self.status().startswith("📥 ボールが自分にある案件 1件"), timeout=5),
                        self.status())
        self.assertEqual(snapshot_files("."), before)
        self.assertEqual(self.stub_outlook.explorer_calls, [])


class TestTabHeading(MyCourtCase):
    """タブの見出し (A1 の判断待ちの件数) と、選ばれているタブは変えない。"""

    def test_the_panel_never_changes_the_tab_heading(self):
        gui = self.build()
        base = gui.notebook.tab(gui.tab_action, "text")
        self.assertEqual(base, "📋 アクション")
        for snap in (msnap([mrow("A", "reminded")]), msnap([], state="missing", status_text=MISSING_TEXT),
                     msnap([], state="error", status_text=error_text("X"))):
            self.apply_my(snap)
            self.assertEqual(gui.notebook.tab(gui.tab_action, "text"), base)
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status() == MISSING_TEXT, timeout=5))
        self.assertEqual(gui.notebook.tab(gui.tab_action, "text"), base)

    def test_the_decision_count_heading_and_list_survive_the_panel(self):
        gui = self.build()
        heading = "📋 アクション (判断待ち2・解析1時間前)"
        gui._apply_action_decision_view(a1gui.make_snapshot([a1gui.make_row("A"), a1gui.make_row("B")], heading=heading))
        gui.root.update()
        self.assertEqual(gui.notebook.tab(gui.tab_action, "text"), heading)
        write_json(oto().COCKPIT_V2_LAST_RESULT_FILE,
                   v2_saved([v2_item("Z", "reminded")], datetime.now().strftime("%Y-%m-%d %H:%M")))
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status().startswith("📥 ボールが自分にある案件 1件"), timeout=5))
        self.apply_my(msnap([mrow("Y")]))
        self.assertEqual(gui.notebook.tab(gui.tab_action, "text"), heading)
        self.assertEqual(len(gui.tree_action_decision.get_children()), 2, "判断待ちの一覧が変わった")

    def test_the_panel_does_not_change_the_selected_tab(self):
        gui = self.build(select_action=False)
        calls = []
        orig = gui.notebook.select

        def spy(*a, **k):
            if a or k:
                calls.append((a, k))
            return orig(*a, **k)
        gui.notebook.select = spy
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status() == MISSING_TEXT, timeout=5))
        self.apply_my(msnap([mrow("A")]))
        gui._action_my_court_tick()
        self.settle(0.3)
        self.assertEqual(calls, [], "notebook.select(タブ指定) が呼ばれた")
        self.assertEqual(gui.notebook.index("current"), 0)


class TestReloadAfterDecisionOperations(MyCourtCase):
    """(fix1) 判断待ちの「✅ 完了にする」「🙈 無視する」「↩ 元に戻す」が成功したら、このパネルも (1回) 読み直す。
    失敗・何もしなかったときは読み直さない。"""

    def setup_both(self):
        self.seed_files()                         # A1 の合成データ (A, B, C の判断待ち。B は進行中)
        self.build()
        self.load_real(3)
        calls = self.counting_builder()
        self.settle(0.2)
        self.assertEqual(calls, [], "(前提) まだ読み直していない")
        return calls

    def wait_one_more(self, calls, n0):
        self.assertTrue(self.pump(lambda: len(calls) > n0, timeout=5), "このパネルが読み直されない")
        self.settle(0.3)
        self.assertEqual(len(calls) - n0, 1, "読み直しは1回")

    def test_complete_rereads_this_panel(self):
        calls = self.setup_both()
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.wait_one_more(calls, 0)
        self.assertTrue(self.pump(lambda: self.row_ids() == [self.key("B"), self.key("C")], timeout=8),
                        f"判断待ちの一覧が更新されない: {self.row_ids()}")

    def test_ignore_rereads_this_panel(self):
        calls = self.setup_both()
        self.select(self.key("C"))
        self.button("無視する").invoke()
        self.wait_one_more(calls, 0)

    def test_undo_rereads_this_panel(self):
        calls = self.setup_both()
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.wait_one_more(calls, 0)
        self.assertTrue(self.pump(lambda: len(self.row_ids()) == 2, timeout=8))
        self.button("元に戻す").invoke()
        self.wait_one_more(calls, 1)
        self.assertTrue(self.pump(lambda: len(self.row_ids()) == 3, timeout=8))

    def test_a_failed_write_does_not_reread(self):
        calls = self.setup_both()
        self.select(self.key("A"))
        with mock.patch.object(oto(), "set_action_progress", mock.Mock(side_effect=OSError("書けない"))):
            self.button("完了にする").invoke()
            self.settle(0.4)
        self.assertEqual(calls, [], "書込みに失敗したのに読み直した")
        self.assertIn("書けない", self.dialog_text(("showerror",)))

    def test_a_failed_undo_does_not_reread(self):
        calls = self.setup_both()
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.wait_one_more(calls, 0)
        with mock.patch.object(oto(), "set_action_progress", mock.Mock(side_effect=OSError("戻せない"))):
            self.button("元に戻す").invoke()
            self.settle(0.4)
        self.assertEqual(len(calls), 1, "元に戻すに失敗したのに読み直した")

    def test_no_selection_does_not_reread(self):
        calls = self.setup_both()
        self.my_tree()                            # (前提) このパネルがある
        self.gui._action_decision_set_progress("done")
        self.settle(0.4)
        self.assertEqual(calls, [])
        self.assertTrue(self.dialog_text(("showinfo",)), "未選択の案内が出ない")


class TestRefreshWithoutThePanel(a1gui.GuiCase):
    """(fix1) このパネルを作っていない画面 (判断待ちパネルだけを組んだ A1 の画面) では、_refresh_action_my_court_view は
    何もしない。判断待ちの操作 (完了・元に戻す) もそのまま動く。"""

    def test_refresh_does_nothing_without_the_panel(self):
        gui = self.make_gui(select_action=True)
        calls = []
        p = mock.patch.object(oto(), "build_cockpit_v2_my_court_snapshot", lambda *a, **k: calls.append(1))
        p.start()
        self.addCleanup(p.stop)
        before = set(threading.enumerate())
        gui._refresh_action_my_court_view()
        self.settle(0.3)
        self.assertEqual(calls, [])
        self.assertEqual([t for t in threading.enumerate() if t not in before and t.is_alive()], [])

    def test_decision_operations_still_work_without_the_panel(self):
        self.setup_loaded()
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.row_ids() == [self.key("B"), self.key("C")], timeout=8))
        self.button("元に戻す").invoke()
        self.assertTrue(self.pump(lambda: len(self.row_ids()) == 3, timeout=8))


class TestRefreshWithoutAnyWidget(unittest.TestCase):
    def test_refresh_on_a_bare_object_does_nothing(self):
        """(fix1) 画面を何も作っていないオブジェクトでも例外にならず、読込も始めない。"""
        mod = oto()
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        calls = []
        with mock.patch.object(mod, "build_cockpit_v2_my_court_snapshot", lambda *a, **k: calls.append(1)):
            before = set(threading.enumerate())
            gui._refresh_action_my_court_view()
            time.sleep(0.3)
        self.assertEqual(calls, [], "パネルが無いのに読込を始めた")
        self.assertEqual([t for t in threading.enumerate() if t not in before and t.is_alive()], [])


class TestSpecGapGui(MyCourtCase):
    """GUI で仕様が明記していない点を、自然な解釈で書いたもの。"""

    def test_only_the_topic_column_stretches(self):
        # 仕様で stretch と書かれているのは「件名」だけ → 他の4列は幅固定 (stretch しない) と解釈する
        self.build(update=False)
        tree = self.my_tree()
        self.assertEqual({c: _truthy(tree.column(c, "stretch")) for c in ("cat", "proj", "topic", "days", "date")},
                         {"cat": False, "proj": False, "topic": True, "days": False, "date": False})

    def test_detail_follows_the_new_data_of_the_kept_row(self):
        # 選択し直した行の詳細は、新しい内容で表示し直す (A1 と同じ) と解釈する
        self.build()
        self.apply_my(msnap([mrow("A"), mrow("B", reasons_text="古い根拠")]))
        self.select_topic("AI件名B")
        self.assertIn("古い根拠", self.detail())
        self.apply_my(msnap([mrow("B", reasons_text="新しい根拠"), mrow("A")]))
        self.settle(0.1)
        self.assertEqual(self.selected_topics(), ["AI件名B"])
        self.assertEqual(self.detail(), detail_text("新しい根拠", "実件名B"))

    def test_right_click_on_an_unselected_row_selects_and_opens_that_row(self):
        # 「A1 と同じ方式」: 右クリックした行を選んでからメニューを出す (メニューの「開く」はその行) と解釈する
        self.patch_popup()
        self.build()
        self.apply_my(msnap([mrow("A", entry_id="E-A"), mrow("B", entry_id="E-B")]))
        self.select_topic("AI件名A")
        self.right_click("AI件名B")
        self.assertEqual(self.selected_topics(), ["AI件名B"])
        self.assertEqual(len(self.popups), 1)
        self.invoke_menu(self.popups[0], "Outlookで開く")
        self.assertTrue(self.wait_explorer())
        self.assertEqual(self.stub_outlook.explorer_calls[0]["entry_id"], "E-B")

    def test_after_a_builder_exception_the_next_reload_runs_at_once(self):
        # 集計が例外でも「実行中」が残らず、次の再読込がすぐ動く (60秒待たない) と解釈する
        gui = self.build()
        state = {"n": 0}

        def builder(*a, **k):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("1回目だけ失敗")
            return msnap([mrow("A")], status_text="RECOVERED")
        self.patch_builder(builder)
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: state["n"] >= 1, timeout=5))
        self.settle(0.3)
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(lambda: self.status() == "RECOVERED", timeout=5), "例外の後、再読込が止まった")

    def test_a_run_stuck_for_more_than_60_seconds_does_not_block_forever(self):
        # 仕様「60秒を超えて戻らないときは新たに始めてよい」(任意)。時計 (time.monotonic / time.time) を61秒進めると
        # 新しい読込が始まる、と解釈する (A1 と同じ)。datetime で測る実装だとこのテストでは確かめられない
        gui = self.build()
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        calls = []

        def builder(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                started.set()
                gate.wait(10)
            return msnap([mrow("W")], status_text=f"WD{len(calls)}")
        self.patch_builder(builder)
        offset = [0.0]
        real_mono, real_time = time.monotonic, time.time
        with mock.patch.object(time, "monotonic", lambda: real_mono() + offset[0]), \
                mock.patch.object(time, "time", lambda: real_time() + offset[0]):
            gui._refresh_action_my_court_view()
            self.assertTrue(self.pump(started.is_set, timeout=5))
            offset[0] = 61.0
            gui._refresh_action_my_court_view()
            ok = self.pump(lambda: len(calls) >= 2, timeout=3)
            gate.set()
            self.pump(lambda: not self.worker_threads(), timeout=5)
        self.assertTrue(ok, "61秒たっても新しい読込が始まらない (永久に止まる)")

    def test_a_worker_finishing_after_the_window_closed_raises_nothing(self):
        # 「例外は出さない（ウィンドウを閉じている最中の TclError は無視）」。閉じた後に戻ってきたワーカーの root.after は
        # TclError か RuntimeError("main thread is not in main loop") になる (Tk の作り)。どちらも外に出さない、と解釈する
        gui = self.build()
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)

        def slow(*a, **k):
            started.set()
            gate.wait(10)
            return msnap([mrow("Z")])
        self.patch_builder(slow)
        gui._refresh_action_my_court_view()
        self.assertTrue(self.pump(started.is_set, timeout=5))
        workers = self.worker_threads()
        self.cancel_afters()
        gui.root.destroy()
        self.gui = None                             # 破棄済みの root を後始末で触らない
        gate.set()
        for t in workers:
            t.join(8)
        self.assertFalse([t for t in workers if t.is_alive()], "ワーカーが終わらない")
        self.assertEqual(self.thread_errors, [], "閉じた後に戻ってきたワーカーが例外を出した")

    def test_apply_after_the_window_closed_raises_nothing(self):
        # 閉じている最中の TclError は無視 (A1 の反映と同じ) と解釈する
        gui = self.build()
        self.cancel_afters()
        gui.root.destroy()
        self.gui = None
        gui._apply_action_my_court_view(msnap([mrow("A")]))

    def test_tick_reschedules_even_if_the_reload_raises(self):
        # 再読込が例外でも定期の予約は続く (A1 の tick と同じ) と解釈する
        gui = self.build()

        def boom():
            raise RuntimeError("reload failed")
        gui._refresh_action_my_court_view = boom
        n0 = len(self.after_calls)
        try:
            gui._action_my_court_tick()
        except RuntimeError:
            pass
        self.assertIn(oto().ACTION_DECISION_REFRESH_MS, [ms for ms, _ in self.after_calls[n0:]])


# ============================================================
# 4. 範囲ガード (AST): _08 → _09
# ============================================================
GUI_CLS = "MailManagerGUI"
CHANGED = "MailManagerGUI._ui_action_tab"
SET_PROGRESS = "MailManagerGUI._action_decision_set_progress"
UNDO = "MailManagerGUI._action_decision_undo"
# 変えてよい既存メソッド: {名前: (旧版の最後の文, 足してよい1行)}  (fix1 で判断待ちの2つが増えた)
ALLOWED_TO_CHANGE = {
    CHANGED: ("self._ui_action_decision_panel(main)", "self._ui_action_my_court_panel(main)"),
    SET_PROGRESS: ("self._refresh_action_decision_view()", "self._refresh_action_my_court_view()"),
    UNDO: ("self._refresh_action_decision_view()", "self._refresh_action_my_court_view()"),
}
NEW_FUNC = "build_cockpit_v2_my_court_snapshot"
NEW_CONSTS = ["COCKPIT_V2_MY_COURT_CATEGORIES", "COCKPIT_V2_STALE_DAYS"]
REQUIRED_METHODS = [f"{GUI_CLS}.{n}" for n in ("_ui_action_my_court_panel", "_refresh_action_my_court_view",
                                                 "_apply_action_my_court_view", "_action_my_court_tick")]
HANDLER_PREFIX = f"{GUI_CLS}._action_my_court_"
A1_GUI_METHODS = ("_ui_action_decision_panel", "_action_decision_tick", "_on_action_decision_tab_changed",
                  "_refresh_action_decision_view", "_choose_action_tab_heading", "_apply_action_decision_view",
                  "_render_action_decision_rows", "_on_action_decision_select", "_on_action_decision_double_click",
                  "_on_action_decision_right_click", "_action_decision_open_selected", "_action_decision_open_row")
# (_action_decision_set_progress / _action_decision_undo は fix1 で「最後に1行追加」だけ許可 → ALLOWED_TO_CHANGE で検査)
MUST_STAY_UNCHANGED = (
    ["MailManagerGUI._run_cockpit_v2", "MailManagerGUI._reformat_cockpit_v2", "MailManagerGUI._save_cockpit_v2_result",
     "MailSummarizer.generate_cockpit_v2_data", "HTMLReportGenerator.generate_cockpit_v2_report",
     "load_cockpit_v2_acknowledged", "save_cockpit_v2_acknowledged", "load_action_status", "save_action_status",
     "load_cockpit_v2_project_overrides", "save_cockpit_v2_project_overrides", "classify_cockpit_item",
     "should_include_in_cockpit_queue", "cockpit_item_reasons", "MailManagerGUI.__init__",
     "MailManagerGUI._build_main_tabs"]
    + list(_loader.A1_FUNCTIONS) + [f"{GUI_CLS}.{n}" for n in A1_GUI_METHODS])
WRITE_CALLS = {"json.dump", "os.replace", "os.rename", "os.remove", "os.unlink", "os.rmdir", "shutil.copy",
               "shutil.copy2", "shutil.copyfile", "shutil.move", "shutil.rmtree"}
WRITE_ATTRS = {"write", "writelines", "write_text", "write_bytes", "set_action_progress"}


def func_node(path, qualified):
    """"name" (モジュール直下) または "Class.method" の FunctionDef。"""
    cls_name, _, meth = qualified.rpartition(".")
    for node in a6tabs._parse(path).body:
        if not cls_name and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == meth:
            return node
        if cls_name and isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == meth:
                    return sub
    raise AssertionError(f"{qualified} が {os.path.basename(path)} に無い")


def class_rest(path, cls_name, allow_prefix=None):
    """クラス直下の (関数・docstring 以外の) 文の AST ダンプ。allow_prefix で始まる名前への単純な代入は除く。"""
    for node in a6tabs._parse(path).body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            out = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) or a6tabs._is_docstring(sub):
                    continue
                if allow_prefix and isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    if targets and all(isinstance(t, ast.Name) and t.id.startswith(allow_prefix) for t in targets):
                        continue
                out.append(ast.dump(sub))
            return out
    raise AssertionError(f"クラス {cls_name} が無い")


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.append(node.id if isinstance(node, ast.Name) else "?")
    return ".".join(reversed(parts))


def _is_self_attr(node, attr):
    return (isinstance(node, ast.Attribute) and node.attr == attr
            and isinstance(node.value, ast.Name) and node.value.id == "self")


class TestScopeGuardA6b(unittest.TestCase):
    """_08 → _09: 変えてよい既存メソッドは _ui_action_tab と、(fix1) _action_decision_set_progress・_action_decision_undo
    (どれも最後に1行追加) だけ。追加は仕様の定数2つ・関数1つ・メソッドだけ。"""

    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest(f"A6b のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = a6tabs._index_source(cls.baseline)
        cls.new = a6tabs._index_source(cls.target)
        cls.added = sorted(set(cls.new[0]) - set(cls.old[0]))

    def new_code(self):
        return [(q, func_node(self.target, q)) for q in self.added]

    # ---- 関数・メソッド -----------------------------------------------
    def test_nothing_is_removed(self):
        self.assertEqual(sorted(n for n in self.old[0] if n not in self.new[0]), [])
        self.assertEqual(sorted(n for n in self.old[1] if n not in self.new[1]), [])

    def test_only_the_allowed_methods_are_changed(self):
        """既存の関数/メソッドで変わったのは _ui_action_tab・_action_decision_set_progress・_action_decision_undo だけ。"""
        changed = sorted(n for n, s in self.old[0].items() if n in self.new[0] and self.new[0][n] != s)
        self.assertEqual(changed, sorted(ALLOWED_TO_CHANGE))

    def test_each_allowed_method_only_gets_one_line_at_the_end(self):
        """_ui_action_tab: 最後の self._ui_action_decision_panel(main) の次に self._ui_action_my_court_panel(main)。
        (fix1) _action_decision_set_progress / _action_decision_undo: 最後の self._refresh_action_decision_view() の次に
        self._refresh_action_my_court_view()。それぞれ1行だけで、docstring・引数・他の行は同じ。"""
        for q, (anchor, added) in ALLOWED_TO_CHANGE.items():
            with self.subTest(q=q):
                old_fn, new_fn = func_node(self.baseline, q), func_node(self.target, q)
                self.assertEqual(ast.dump(new_fn.args), ast.dump(old_fn.args))
                self.assertEqual([ast.dump(d) for d in new_fn.decorator_list],
                                 [ast.dump(d) for d in old_fn.decorator_list])
                old_body = [ast.dump(s) for s in old_fn.body]
                self.assertEqual(old_body[-1], ast.dump(ast.parse(anchor).body[0]),
                                 f"(比較元の前提) 旧版の最後が {anchor}")
                new_body = [ast.dump(s) for s in new_fn.body]
                if new_body != old_body + [ast.dump(ast.parse(added).body[0])]:
                    self.fail(f"{q} が「最後に1行追加だけ」になっていない:\n" + a6tabs.short_diff(
                        [ast.unparse(s).splitlines()[0] for s in old_fn.body] + [added],
                        [ast.unparse(s).splitlines()[0] for s in new_fn.body]))

    def test_required_new_definitions_exist(self):
        for q in [NEW_FUNC] + REQUIRED_METHODS:
            with self.subTest(q=q):
                self.assertIn(q, self.new[0])

    def test_only_spec_names_are_added(self):
        """追加は build_cockpit_v2_my_court_snapshot・4つのメソッド・MailManagerGUI._action_my_court_* のハンドラだけ。"""
        extra = [q for q in self.added
                 if q != NEW_FUNC and q not in REQUIRED_METHODS and not q.startswith(HANDLER_PREFIX)]
        self.assertEqual(extra, [])

    def test_the_new_function_is_module_level_with_the_spec_signature(self):
        fn = func_node(self.target, NEW_FUNC)
        a = fn.args
        self.assertEqual([x.arg for x in a.args], ["now", "saved", "acknowledged", "action_statuses", "project_overrides"])
        self.assertEqual([ast.dump(d) for d in a.defaults], [ast.dump(ast.Constant(None))] * 4)
        self.assertEqual((a.posonlyargs, a.vararg, a.kwonlyargs, a.kwarg), ([], None, [], None))
        self.assertEqual(fn.decorator_list, [])

    def test_new_methods_take_the_spec_arguments(self):
        """_ui_action_my_court_panel(self, parent) / _refresh_…(self) / _apply_…(self, snap) / _action_my_court_tick(self)。"""
        for q, n in zip(REQUIRED_METHODS, (2, 1, 2, 1)):
            with self.subTest(q=q):
                fn = func_node(self.target, q)
                self.assertEqual(len(fn.args.args), n)
                self.assertEqual(fn.args.args[0].arg, "self")
                self.assertEqual((fn.args.vararg, fn.args.kwarg, fn.decorator_list), (None, None, []))

    # ---- 定数・import・骨格 ------------------------------------------
    def test_constants(self):
        """モジュール直下の新しい定数は2つだけ。既存の定数は不変 (クラス直下に足すなら _action_my_court_* だけ)。"""
        old_c, new_c = self.old[1], self.new[1]
        added = sorted(set(new_c) - set(old_c))
        self.assertEqual([a for a in added if "." not in a], sorted(NEW_CONSTS))
        self.assertEqual([a for a in added if "." in a and not a.startswith(HANDLER_PREFIX)], [])
        self.assertEqual(sorted(n for n, s in old_c.items() if new_c.get(n) != s), [])

    def test_constant_values_in_the_source(self):
        values = {}
        for node in a6tabs._parse(self.target).body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in NEW_CONSTS:
                        values[t.id] = ast.literal_eval(node.value)
        self.assertEqual(values, {"COCKPIT_V2_MY_COURT_CATEGORIES": CATS4, "COCKPIT_V2_STALE_DAYS": 7})

    def test_imports_are_kept(self):
        self.assertEqual(self.old[2] - self.new[2], set())

    def test_other_top_level_statements_are_unchanged(self):
        self.assertEqual(self.old[3], self.new[3])

    def test_class_skeletons_are_unchanged(self):
        """クラスの骨格 (継承・デコレータ・クラス直下の文) は不変 (MailManagerGUI に _action_my_court_* を足すのは除く)。"""
        self.assertEqual(sorted(self.new[4]), sorted(self.old[4]), "クラスの追加/削除")
        for cls_name, (header, rest) in self.old[4].items():
            with self.subTest(cls=cls_name):
                new_header, new_rest = self.new[4][cls_name]
                self.assertEqual(new_header, header)
                if cls_name == GUI_CLS:
                    self.assertEqual(class_rest(self.target, GUI_CLS, allow_prefix="_action_my_court_"), rest)
                else:
                    self.assertEqual(new_rest, rest)

    def test_spec_unchanged_functions_are_identical(self):
        """_run_cockpit_v2 / _reformat_cockpit_v2 / generate_cockpit_v2_data / v2 の HTML・保存 / 読込関数 /
        A1 の関数とメソッド / __init__ / _build_main_tabs は、旧版と AST が同じ。"""
        for q in MUST_STAY_UNCHANGED:
            with self.subTest(q=q):
                self.assertIn(q, self.old[0], f"{q} が旧版に無い (比較の前提が崩れた)")
                self.assertEqual(self.new[0].get(q), self.old[0][q], f"{q} が変わっている")

    # ---- 新しいコードの中身 (機械的な検査) ------------------------------
    def test_new_code_writes_no_files(self):
        """新しい関数・メソッドに、ファイルを書く呼び出し (書込みモードの open・json.dump・save_*・os.replace 等) が無い。"""
        bad = []
        for q, fn in self.new_code():
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                name = _dotted(n.func)
                last = name.rsplit(".", 1)[-1]
                if name in WRITE_CALLS or last in WRITE_ATTRS or last.startswith("save_"):
                    bad.append(f"{q}: {ast.unparse(n)[:100]}")
                elif last == "open" and name in ("open", "io.open", "builtins.open", "codecs.open"):
                    mode = n.args[1] if len(n.args) >= 2 else next((k.value for k in n.keywords if k.arg == "mode"), None)
                    if mode is not None and not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                                                 and not set(mode.value) & set("wax+")):
                        bad.append(f"{q}: {ast.unparse(n)[:100]}")
        self.assertEqual(bad, [])

    def test_new_code_uses_outlook_only_to_open_a_thread_and_no_ai(self):
        """新しいコードが触る self.outlook の属性は show_thread_in_explorer だけ。AI (summarizer)・HTML (reporter)・
        v2 の実行/再生成には触れない。"""
        outlook, other = set(), []
        for q, fn in self.new_code():
            for n in ast.walk(fn):
                if isinstance(n, ast.Attribute) and _is_self_attr(n.value, "outlook"):
                    outlook.add(n.attr)
                if (_is_self_attr(n, "summarizer") or _is_self_attr(n, "reporter")
                        or _is_self_attr(n, "_run_cockpit_v2") or _is_self_attr(n, "_reformat_cockpit_v2")):
                    other.append(f"{q}: self.{n.attr}")
                if isinstance(n, ast.Name) and n.id in ("win32com", "pythoncom", "requests", "_CommonGeminiClient", "genai"):
                    other.append(f"{q}: {n.id}")
        self.assertEqual(outlook, {"show_thread_in_explorer"})
        self.assertEqual(other, [])

    def test_new_code_does_not_touch_the_tab_heading_or_the_selected_tab(self):
        """新しいコードに、タブの文言を変える .tab(…, text=…) と、タブを選ぶ .select(…) (引数あり) が無い。"""
        bad = []
        for q, fn in self.new_code():
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    if n.func.attr == "tab" and n.keywords:
                        bad.append(f"{q}: {ast.unparse(n)[:100]}")
                    if n.func.attr == "select" and (n.args or n.keywords):
                        bad.append(f"{q}: {ast.unparse(n)[:100]}")
        self.assertEqual(bad, [])

    def test_new_code_binds_the_tab_change_with_add(self):
        """<<NotebookTabChanged>> のバインドは add="+" 付きで、少なくとも1か所ある (A1 のバインドを壊さない)。"""
        binds = []
        for q, fn in self.new_code():
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "bind"
                        and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "<<NotebookTabChanged>>"):
                    add = [k.value for k in n.keywords if k.arg == "add"] or n.args[2:3]
                    binds.append((q, bool(add and isinstance(add[0], ast.Constant) and add[0].value)))
        self.assertTrue(binds, "<<NotebookTabChanged>> のバインドが無い")
        self.assertEqual([q for q, ok in binds if not ok], [])


class TestSpecGapScopeGuardA6b(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = _loader.rev_path(NEW_REV)
        baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(target) and os.path.isfile(baseline)):
            raise unittest.SkipTest(f"A6b のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.target, cls.baseline = target, baseline
        cls.old = a6tabs._index_source(baseline)
        cls.new = a6tabs._index_source(target)

    def test_no_new_import(self):
        # 仕様の「追加」は定数・関数・メソッドだけ。必要な部品 (json/threading/datetime/ttk) は既存の import にある
        # ので、新しい import は無い、と解釈する
        self.assertEqual(self.new[2] - self.old[2], set())

    def test_no_class_level_attribute_is_added(self):
        # 仕様の「追加」にクラス直下の属性は無い。実行中フラグなどはインスタンス属性 (パネルを作るときに初期化) と解釈する
        self.assertEqual(class_rest(self.target, GUI_CLS), self.old[4][GUI_CLS][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
