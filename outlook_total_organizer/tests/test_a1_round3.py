# -*- coding: utf-8 -*-
"""A1 判断待ち: 第2回レビュー後の追加分のテスト。

(1) 「無視」した依頼のスレッドに、その後の新着がある件数を状態文に開示する (ignored_new_count)。
    無視は再浮上させない(一覧・見出しの件数には入れない)が、「静かに見落とす」経路を黙らせないための件数開示。
(2) 短い見出し(⚖)に切り替わっているときだけ、記号の凡例を状態文に足す。

注: ここで追加した挙動は、レビュー第2回の指摘(Ma1/m4)への対応。仕様書 A1_SPEC_DELTA_round2.md には無い。
"""
import unittest

import _loader
from _loader import (
    HOUR, NOW, iso_epoch, make_action, make_cache, make_last_run, make_status, make_thread, ts_ago,
    write_json, tempdir_cwd, CACHE_PATH, LAST_RUN_PATH, STATUS_PATH,
)
from test_a1_gui_smoke import BASE, GuiCase, make_row, make_snapshot, _const


def oto():
    return _loader.load()


IGNORED_NEW_LINE = ("🙈 「無視」した依頼のスレッドに、その後の新着が{n}件あります"
                    "（無視は再表示しません。アクション一覧のHTMLで確認できます）。")


class IgnoredBase(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def key(self, cid, idx=0):
        return oto().make_action_key_by_index(cid, idx)

    def write_env(self, threads, statuses):
        write_json(CACHE_PATH, make_cache(threads))
        write_json(STATUS_PATH, statuses)
        write_json(LAST_RUN_PATH, make_last_run(NOW - __import__("datetime").timedelta(hours=1)))

    def snap(self):
        return oto().build_action_decision_snapshot(now=NOW)


class TestIgnoredNewCount(IgnoredBase):
    def ignored_at(self, hours_ago):
        """無視を付けた日時 (ISO文字列)。"""
        from datetime import timedelta
        return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S")

    def test_ignored_thread_with_newer_mail_is_disclosed_but_not_listed(self):
        # 無視は3時間前。スレッドの最終受信は1時間前(無視より新しい)。
        self.write_env({"T": make_thread(latest_ts=ts_ago(1))},
                       {self.key("T"): make_status("ignored", updated_at=self.ignored_at(3))})
        s = self.snap()
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["pending_count"], 0)
        self.assertEqual(s["ignored_new_count"], 1)
        self.assertIn(IGNORED_NEW_LINE.format(n=1), s["status_text"])
        self.assertTrue(s["heading"].startswith(f"{BASE} (判断待ち0"), s["heading"])

    def test_ignored_thread_without_newer_mail_is_silent(self):
        # 無視は1時間前。スレッドの最終受信は3時間前(無視より古い)。
        self.write_env({"T": make_thread(latest_ts=ts_ago(3))},
                       {self.key("T"): make_status("ignored", updated_at=self.ignored_at(1))})
        s = self.snap()
        self.assertEqual(s["ignored_new_count"], 0)
        self.assertNotIn("🙈", s["status_text"])

    def test_ignored_mail_at_the_same_second_is_silent(self):
        ts = ts_ago(2)
        iso = __import__("datetime").datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
        self.write_env({"T": make_thread(latest_ts=ts)}, {self.key("T"): make_status("ignored", updated_at=iso)})
        self.assertEqual(self.snap()["ignored_new_count"], 0)

    def test_ignored_without_updated_at_is_silent(self):
        st = make_status("ignored")
        del st["updated_at"]
        self.write_env({"T": make_thread(latest_ts=ts_ago(1))}, {self.key("T"): st})
        self.assertEqual(self.snap()["ignored_new_count"], 0)

    def test_ignored_with_invalid_updated_at_is_silent(self):
        self.write_env({"T": make_thread(latest_ts=ts_ago(1))},
                       {self.key("T"): make_status("ignored", updated_at="いつか")})
        self.assertEqual(self.snap()["ignored_new_count"], 0)

    def test_non_decision_ignored_thread_is_not_counted(self):
        # 判断語に当たらない依頼を無視した場合は、判断待ちの見落としではないので開示しない
        th = make_thread([make_action(action="資料を共有してください")], action_type="通知・共有", latest_ts=ts_ago(1))
        self.write_env({"T": th}, {self.key("T"): make_status("ignored", updated_at=self.ignored_at(3))})
        s = self.snap()
        self.assertEqual(s["ignored_new_count"], 0)
        self.assertEqual(s["others_count"], 0)           # 無視した依頼は「その他の自分宛て」にも入らない

    def test_other_person_target_is_not_counted(self):
        th = make_thread([make_action(target="Nakai")], latest_ts=ts_ago(1))
        self.write_env({"T": th}, {self.key("T"): make_status("ignored", updated_at=self.ignored_at(3))})
        self.assertEqual(self.snap()["ignored_new_count"], 0)

    def test_ignored_thread_older_than_the_horizon_is_not_counted(self):
        # 最終解析1時間前・範囲7日。最終受信が20日前のスレッドは対象期間外
        from datetime import timedelta
        old_ts = int((NOW - timedelta(days=20)).timestamp())
        newer_ignore = (NOW - timedelta(days=25)).strftime("%Y-%m-%dT%H:%M:%S")      # 無視はさらに前 → 「新着あり」だが古い
        self.write_env({"T": make_thread(latest_ts=old_ts)},
                       {self.key("T"): make_status("ignored", updated_at=newer_ignore)})
        s = self.snap()
        self.assertEqual(s["ignored_new_count"], 0)
        self.assertEqual(s["older_rows"], [])

    def test_counts_each_action_and_does_not_disturb_other_rows(self):
        th_ignored = make_thread([make_action(action="予算を承認してください")], latest_ts=ts_ago(1))
        th_open = make_thread([make_action(action="見積を承認してください")], latest_ts=ts_ago(2))
        self.write_env({"I": th_ignored, "O": th_open},
                       {self.key("I"): make_status("ignored", updated_at=self.ignored_at(3))})
        s = self.snap()
        self.assertEqual([r["cid"] for r in s["rows"]], ["O"])
        self.assertEqual(s["pending_count"], 1)
        self.assertEqual(s["ignored_new_count"], 1)
        self.assertIn(IGNORED_NEW_LINE.format(n=1), s["status_text"])

    def test_ignored_new_count_is_zero_when_the_cache_cannot_be_read(self):
        import os
        write_json(STATUS_PATH, {})
        write_json(LAST_RUN_PATH, make_last_run(NOW))
        os.makedirs("analysis_cache", exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            f.write("{broken")
        s = self.snap()
        self.assertIsNone(s["rows"])
        self.assertEqual(s["ignored_new_count"], 0)
        self.assertNotIn("🙈", s["status_text"])


class TestCollectIgnoredNew(IgnoredBase):
    def collect(self, include):
        cache = make_cache({"T": make_thread(latest_ts=ts_ago(1))})
        from datetime import timedelta
        statuses = {self.key("T"): make_status("ignored", updated_at=(NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"))}
        return oto()._collect_pending_self_actions(cache, statuses, (), None, include_ignored_new=include)

    def test_default_never_returns_ignored(self):
        self.assertEqual(self.collect(False), [])

    def test_opt_in_returns_the_row_flagged_ignored_new(self):
        rows = self.collect(True)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["ignored_new"])
        self.assertEqual(rows[0]["progress"], "ignored")
        self.assertFalse(rows[0]["resurfaced"])

    def test_public_compute_pending_decisions_still_excludes_ignored(self):
        cache = make_cache({"T": make_thread(latest_ts=ts_ago(1))})
        from datetime import timedelta
        statuses = {self.key("T"): make_status("ignored", updated_at=(NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"))}
        self.assertEqual(oto().compute_pending_decisions(cache, statuses, (), None), [])

    def test_regular_rows_carry_ignored_new_false(self):
        cache = make_cache({"T": make_thread(latest_ts=ts_ago(1))})
        rows = oto().compute_pending_decisions(cache, {}, (), None)
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0]["ignored_new"], False)


class TestCompactLegend(GuiCase):
    LONG = f"{BASE} (判断待ち12+・解析23時間前・3日間のみ・解析失敗15件)"
    COMPACT = f"{BASE} ⚖12+"
    LEGEND = "見出しの「⚖」: 数字=判断待ちの件数 / ?=要更新 / !=読込失敗 / +=それ以上の可能性"

    def need_px(self, heading):
        import tkinter.font as tkfont
        font = tkfont.nametofont("TkDefaultFont")
        pad = _const("ACTION_TAB_PADDING_PX")
        total = 0
        for tab in self.gui.notebook.tabs():
            text = heading if str(tab) == str(self.gui.tab_action) else self.gui.notebook.tab(tab, "text")
            total += font.measure(text) + pad
        return total

    def resize(self, width):
        self.gui.root.geometry(f"{width}x400+0+0")
        self.gui.root.update()
        self.gui.root.update_idletasks()
        got = self.gui.notebook.winfo_width()
        if abs(got - width) > 60:
            self.skipTest(f"ウィンドウ幅を {width}px にできない (実際 {got}px): ウィンドウマネージャ依存")

    def test_legend_is_added_only_when_the_compact_heading_is_used(self):
        self.make_gui(select_action=True)
        snap = make_snapshot([make_row("A")], heading=self.LONG, heading_compact=self.COMPACT,
                             status_text="最終解析: 10/04 10:00（範囲: 3日間）")
        self.resize(self.need_px(self.LONG) + 150)
        self.apply(snap)
        self.assertEqual(self.tab_text(), self.LONG)
        self.assertNotIn(self.LEGEND, self.gui._action_decision_status_var.get())
        self.resize(max(self.need_px(self.LONG) - 150, 120))
        self.apply(snap)
        self.assertEqual(self.tab_text(), self.COMPACT)
        status = self.gui._action_decision_status_var.get()
        self.assertIn(self.LEGEND, status)
        self.assertTrue(status.startswith("最終解析: 10/04 10:00"), status)       # 元の文言は先頭に残る

    def test_legend_is_not_added_when_both_headings_are_identical(self):
        # 通常の見出しと短い見出しが同じ(読込失敗の集計など)なら、短縮ではないので凡例は不要
        self.make_gui(select_action=True)
        snap = make_snapshot([make_row("A")], heading=self.COMPACT, heading_compact=self.COMPACT, status_text="本文")
        self.resize(max(self.need_px(self.COMPACT) - 150, 120))
        self.apply(snap)
        self.assertNotIn(self.LEGEND, self.gui._action_decision_status_var.get())


if __name__ == "__main__":
    unittest.main()
