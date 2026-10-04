# -*- coding: utf-8 -*-
"""A1 判断待ち: build_action_decision_snapshot (仕様12 + 仕様変更第2回) のテスト。

一時cwdに合成の analysis_cache/action_dashboard.json, json/action_status.json,
json/action_last_run.json を作り、fresh / stale / 記録なし / 時計ずれ / キャッシュ破損 /
解析失敗 / horizon / since_ts 境界 / older_rows / others_count / partial / 再浮上 を
heading・status_text・rows で確認する。

仕様書 (A1_SPEC.md + A1_SPEC_DELTA_round2.md) だけを根拠に、実装を見ずに書いている。
クラス名に SpecGap を含むものは、仕様が曖昧/未記載のため「最も自然な解釈」で書いたもの。
失敗は「バグ」ではなく「仕様の確認が必要」の合図。
"""
import os
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

import _loader
from _loader import (
    CACHE_PATH, DAY, HOUR, LAST_RUN_PATH, NOW, ROW_KEYS, SNAPSHOT_KEYS, STATUS_PATH, iso_epoch,
    make_action, make_cache, make_last_run, make_status, make_thread, read_bytes, read_json,
    snapshot_files, tempdir_cwd, ts_ago, write_bytes, write_json, write_text,
)


def oto():
    return _loader.load()


BASE = "📋 アクション"

# --- 仕様変更(第2回) で確定した status_text の文言 (A1_SPEC_DELTA_round2.md 6) ---
NOTICE = ("※解析済みの受信トレイ直下のメールだけを数えています。最終解析以降の新着・返信済みは反映されません"
          "（最新にするには「📋 アクション一覧を生成」）。")
OLD_NOTICE = "最終解析以降に届いたメールは数えていません"          # 旧文言 (無くなった)
NO_RECORD = "最終解析の記録がありません（または日時が不正です）。"
STALE_WARN = "⚠ 24時間以上前の結果です。要更新です。"


def partial_warn(period):
    return f"⚠ 最終解析の範囲が7日未満（{period}）です。それより前に届いた依頼は解析していません。"


def older_line(horizon, n):
    return f"📅 {horizon}日より前に届いた未対応が{n}件あります（「🕰 古い案件も表示」で確認できます）。"


def others_line(n):
    return f"📌 判断語に当たらない自分宛ての依頼が、他に{n}件あります（この一覧には含めていません）。"


def errors_line(n):
    return (f"⚠ 解析に失敗したスレッドが{n}件あります。その期間を含めて「📋 アクション一覧を生成」すると"
            "再試行されます。")


class SnapBase(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def key(self, cid, idx=0):
        return oto().make_action_key_by_index(cid, idx)

    def snap(self, now=NOW, **kw):
        return oto().build_action_decision_snapshot(now=now, **kw)

    def env(self, threads=None, statuses=None, finished=None, days=7, label="1週間"):
        """None は「そのファイルを作らない」。finished は datetime (最終解析の完了時刻)。"""
        if threads is not None:
            write_json(CACHE_PATH, make_cache(threads))
        if statuses is not None:
            write_json(STATUS_PATH, statuses)
        if finished is not None:
            write_json(LAST_RUN_PATH, make_last_run(finished, days, label))

    def ago(self, **delta):
        return NOW - timedelta(**delta)

    def since_of(self, finished, days=7):
        """仕様12の horizon: finished_at(epoch) - max(days>0 ? days : 1, 7) * 86400"""
        window = max(days if days > 0 else 1, 7)
        return finished.timestamp() - window * DAY

    def standard_threads(self):
        return {
            "P1": make_thread([make_action(deadline="10/10")], latest_ts=ts_ago(3), topic="件名P1",
                              real_topic="実件名P1"),
            "P2": make_thread([make_action()], latest_ts=ts_ago(5), topic="件名P2"),
            "P3": make_thread([make_action()], latest_ts=ts_ago(7), topic="件名P3"),
            "DONE": make_thread(latest_ts=ts_ago(1)),
            "IGN": make_thread(latest_ts=ts_ago(2)),
            "OTHER": make_thread([make_action(target="Nakai")], latest_ts=ts_ago(2)),
            # 自分宛てだが判断語に当たらない → others_count に数えられる (rows には出ない)
            "NODEC": make_thread([make_action(action="資料送付")], action_type="作業・依頼",
                                 latest_ts=ts_ago(2)),
            "NOMETA": make_thread(meta=False),
        }

    def standard_statuses(self):
        return {self.key("DONE"): make_status("done"), self.key("IGN"): make_status("ignored"),
                self.key("P2"): make_status("in_progress", "high", "確認中")}


# ============================================================
# 基本: fresh
# ============================================================
class TestSnapshotFresh(SnapBase):
    def test_full_contract_when_fresh(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        s = self.snap()
        for k in SNAPSHOT_KEYS:
            self.assertIn(k, s, f"snapshot に {k} が無い")
        # rows: 判断待ち3件。順序は 優先度(P2=high) → 期限あり(P1) → その他(P3)
        self.assertIsInstance(s["rows"], list)
        self.assertEqual([r["cid"] for r in s["rows"]], ["P2", "P1", "P3"])
        for r in s["rows"]:
            for k in ROW_KEYS:
                self.assertIn(k, r)
        self.assertEqual(s["pending_count"], 3)
        self.assertEqual(s["error_count"], 0)
        self.assertIs(s["stale"], False)
        self.assertIs(s["freshness_unknown"], False)
        self.assertEqual(s["last_run"], make_last_run(self.ago(hours=2)))
        self.assertEqual(s["heading"], f"{BASE} (判断待ち3・解析2時間前)")
        self.assertEqual(s["heading_compact"], f"{BASE} ⚖3")
        self.assertIsInstance(s["status_text"], str)
        self.assertTrue(s["status_text"].strip())
        self.assertAlmostEqual(s["since_ts"], self.since_of(self.ago(hours=2)), delta=1.0)
        # 仕様変更(第2回) の追加キー
        self.assertEqual(s["older_rows"], [])
        self.assertEqual(s["others_count"], 1, "NODEC (自分宛て・判断語なし) だけが数えられる")
        self.assertIs(s["partial"], False)
        self.assertEqual(s["horizon_days"], 7)

    def test_new_key_types(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        s = self.snap()
        self.assertIsInstance(s["older_rows"], list)
        self.assertIsInstance(s["others_count"], int)
        self.assertNotIsInstance(s["others_count"], bool)
        self.assertIsInstance(s["partial"], bool)
        self.assertIsInstance(s["horizon_days"], int)
        self.assertNotIsInstance(s["horizon_days"], bool)
        self.assertIsInstance(s["heading_compact"], str)

    def test_row_progress_priority_comment_come_from_status_file(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        p2 = [r for r in self.snap()["rows"] if r["cid"] == "P2"][0]
        self.assertEqual((p2["progress"], p2["priority"], p2["comment"]), ("in_progress", "high", "確認中"))
        self.assertEqual(p2["key"], self.key("P2"))
        self.assertIs(p2["resurfaced"], False)
        self.assertIs(p2["is_decision"], True)

    def test_done_ignored_other_target_nondecision_nometa_are_excluded(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        cids = {r["cid"] for r in self.snap()["rows"]}
        self.assertFalse(cids & {"DONE", "IGN", "OTHER", "NODEC", "NOMETA"})

    def test_pending_count_equals_len_rows(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual(s["pending_count"], len(s["rows"]))

    def test_fresh_just_under_24h(self):
        self.env(self.standard_threads(), self.standard_statuses(),
                 finished=NOW - timedelta(hours=23, minutes=59, seconds=59))
        s = self.snap()
        self.assertIs(s["stale"], False)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち3・解析23時間前)")

    def test_fresh_under_one_hour(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(minutes=20))
        self.assertEqual(self.snap()["heading"], f"{BASE} (判断待ち3・解析1時間以内)")

    def test_empty_cache_dict_means_zero_pending_not_unknown(self):
        self.env({}, {}, finished=self.ago(hours=1))
        s = self.snap()
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["older_rows"], [])
        self.assertEqual(s["pending_count"], 0)
        self.assertEqual(s["error_count"], 0)
        self.assertEqual(s["others_count"], 0)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち0・解析1時間前)")

    def test_missing_cache_file_means_zero_pending_not_unknown(self):
        # キャッシュ「ファイル無し」は 0件 (読込失敗とは区別する)
        self.env(None, {}, finished=self.ago(hours=1))
        s = self.snap()
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["pending_count"], 0)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち0・解析1時間前)")

    def test_missing_status_file_means_everything_not_started(self):
        self.env({"P1": make_thread(), "P2": make_thread()}, None, finished=self.ago(hours=1))
        s = self.snap()
        self.assertEqual(s["pending_count"], 2)
        self.assertTrue(all(r["progress"] == "not_started" for r in s["rows"]))

    def test_legacy_key_status_is_honored(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("L1", "Nakai", "承認をお願いします")
        self.env({"L1": make_thread([a]), "L2": make_thread()}, {legacy: make_status("done")},
                 finished=self.ago(hours=1))
        self.assertEqual([r["cid"] for r in self.snap()["rows"]], ["L2"])

    def test_extra_aliases_are_passed_through(self):
        self.env({"Y": make_thread([make_action(target="Taro Yamada")])}, {}, finished=self.ago(hours=1))
        self.assertEqual(self.snap()["pending_count"], 0)
        s = self.snap(extra_aliases=("taro yamada",))
        self.assertEqual([r["cid"] for r in s["rows"]], ["Y"])
        s = self.snap(extra_aliases=["taro yamada"])
        self.assertEqual(s["pending_count"], 1)

    def test_default_extra_aliases_and_now_arguments(self):
        # 引数なし (now=None → 現在時刻) でも動く
        finished = datetime.now() - timedelta(minutes=90)
        write_json(CACHE_PATH, make_cache({"P": make_thread(latest_ts=int(time.time()) - 3600)}))
        write_json(LAST_RUN_PATH, make_last_run(finished))
        s = oto().build_action_decision_snapshot()
        self.assertEqual(s["pending_count"], 1)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち1・解析1時間前)")
        self.assertAlmostEqual(s["since_ts"], finished.timestamp() - 7 * DAY, delta=1.0)

    def test_now_none_without_last_run_uses_current_time_for_horizon(self):
        s = oto().build_action_decision_snapshot(now=None)
        self.assertAlmostEqual(s["since_ts"], time.time() - 7 * DAY, delta=30)
        self.assertEqual(s["horizon_days"], 7)

    def test_snapshot_is_repeatable(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        self.assertEqual(self.snap(), self.snap())


# ============================================================
# stale / 記録なし / 時計ずれ
# ============================================================
class TestSnapshotStaleAndUnknown(SnapBase):
    def test_exactly_24h_is_stale(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=24))
        s = self.snap()
        self.assertIs(s["stale"], True)
        self.assertIs(s["freshness_unknown"], False)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち?・要更新)")
        self.assertEqual(s["heading_compact"], f"{BASE} ⚖?")
        # stale でも件数自体は計算済み (見出しが「?」になるだけ)
        self.assertEqual(s["pending_count"], 3)
        self.assertEqual(len(s["rows"]), 3)

    def test_24h_and_one_second_is_stale(self):
        self.env(self.standard_threads(), None, finished=self.ago(hours=24, seconds=1))
        s = self.snap()
        self.assertIs(s["stale"], True)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち?・要更新)")

    def test_days_old_is_stale(self):
        self.env(self.standard_threads(), None, finished=self.ago(days=10))
        s = self.snap()
        self.assertIs(s["stale"], True)
        self.assertIs(s["freshness_unknown"], False)

    def test_no_record_at_all(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=None)
        s = self.snap()
        self.assertIsNone(s["last_run"])
        self.assertIs(s["freshness_unknown"], True)
        self.assertIsInstance(s["stale"], bool)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち?・要更新)")
        self.assertEqual(s["heading_compact"], f"{BASE} ⚖?")
        self.assertAlmostEqual(s["since_ts"], NOW.timestamp() - 7 * DAY, delta=1.0)
        self.assertEqual(s["horizon_days"], 7)
        # 記録が無くても一覧自体は出す (now-7日の範囲)
        self.assertEqual([r["cid"] for r in s["rows"]], ["P2", "P1", "P3"])
        self.assertEqual(s["pending_count"], 3)

    def test_corrupt_last_run_file_is_treated_as_no_record(self):
        self.env(self.standard_threads(), None)
        for raw in ("{broken", "", "[]", '{"finished_at": "garbage", "days": 7, "period_label": "x"}'):
            with self.subTest(raw=raw):
                write_text(LAST_RUN_PATH, raw)
                s = self.snap()
                self.assertIsNone(s["last_run"])
                self.assertIs(s["freshness_unknown"], True)
                self.assertEqual(s["heading"], f"{BASE} (判断待ち?・要更新)")
                self.assertAlmostEqual(s["since_ts"], NOW.timestamp() - 7 * DAY, delta=1.0)

    def test_future_finished_at_within_5_minutes_is_not_stale_and_age_zero(self):
        # 仕様変更(第2回): 0〜5分(300秒)以内の未来は従来どおり age=0 (「1時間以内」)
        for secs in (1, 60, 240, 300):
            with self.subTest(future_seconds=secs):
                self.env(self.standard_threads(), self.standard_statuses(),
                         finished=NOW + timedelta(seconds=secs))
                s = self.snap()
                self.assertIs(s["stale"], False)
                self.assertIs(s["freshness_unknown"], False)
                self.assertEqual(s["heading"], f"{BASE} (判断待ち3・解析1時間以内)")
                self.assertEqual(s["heading_compact"], f"{BASE} ⚖3")

    def test_future_finished_at_over_5_minutes_is_unknown(self):
        # 仕様変更(第2回): 5分(300秒)を超えて未来 → unknown 扱い (freshness_unknown=True / stale=True)
        for secs in (301, 600, 3600, 3 * 86400):
            with self.subTest(future_seconds=secs):
                self.env(self.standard_threads(), self.standard_statuses(),
                         finished=NOW + timedelta(seconds=secs))
                s = self.snap()
                self.assertIs(s["freshness_unknown"], True)
                self.assertIs(s["stale"], True)
                self.assertEqual(s["heading"], f"{BASE} (判断待ち?・要更新)")
                self.assertEqual(s["heading_compact"], f"{BASE} ⚖?")

    def test_now_param_drives_staleness(self):
        self.env(self.standard_threads(), None, finished=self.ago(hours=2))
        self.assertIs(self.snap(now=NOW)["stale"], False)
        self.assertIs(self.snap(now=NOW + timedelta(hours=22))["stale"], True)       # 24h ちょうど
        self.assertIs(self.snap(now=NOW + timedelta(hours=21, minutes=59))["stale"], False)

    def test_now_param_drives_the_clock_skew_check(self):
        self.env(self.standard_threads(), None, finished=self.ago(hours=2))
        self.assertIs(self.snap(now=NOW - timedelta(hours=2, seconds=300))["freshness_unknown"], False)
        self.assertIs(self.snap(now=NOW - timedelta(hours=2, seconds=301))["freshness_unknown"], True)


class TestSpecGapSnapshotClockSkew(SnapBase):
    def test_skewed_last_run_does_not_hide_recent_threads(self):
        # 時計ずれ (未来すぎる finished_at) は「unknown 扱い」。信頼できない日時を horizon の基準にして
        # 直近のスレッドを「古い」へ追いやらない = 記録なしと同じ now-7日 が自然
        far = NOW + timedelta(days=3)
        threads = {"EDGE": make_thread(latest_ts=ts_ago(6.5 * 24)), "NEW": make_thread(latest_ts=ts_ago(2))}
        self.env(threads, {}, finished=far)
        s = self.snap()
        self.assertIs(s["freshness_unknown"], True)
        self.assertEqual(sorted(r["cid"] for r in s["rows"]), ["EDGE", "NEW"])
        self.assertEqual(s["older_rows"], [])
        self.assertAlmostEqual(s["since_ts"], NOW.timestamp() - 7 * DAY, delta=1.0)

    def test_skewed_last_run_shows_the_no_record_line(self):
        self.env({"P": make_thread()}, {}, finished=NOW + timedelta(hours=2))
        self.assertIn(NO_RECORD, self.snap()["status_text"])


# ============================================================
# キャッシュ/ステータス破損 / 解析失敗
# ============================================================
class TestSnapshotCacheFailureAndErrors(SnapBase):
    def test_corrupt_cache_gives_unknown(self):
        self.env(None, {}, finished=self.ago(hours=2))
        for raw in ("{broken", "[]", '{"threads": null}', '{"threads": []}', '"x"', "null"):
            with self.subTest(raw=raw):
                write_text(CACHE_PATH, raw)
                s = self.snap()
                self.assertIsNone(s["rows"])
                self.assertIsNone(s["older_rows"])
                self.assertIsNone(s["pending_count"])
                self.assertEqual(s["error_count"], 0)
                self.assertEqual(s["others_count"], 0)
                self.assertEqual(s["heading"], f"{BASE} (判断待ち?・読込失敗)")
                self.assertEqual(s["heading_compact"], f"{BASE} ⚖!")
                self.assertIs(s["stale"], False)
                self.assertIs(s["freshness_unknown"], False)
                self.assertIsInstance(s["since_ts"], (int, float))
                self.assertIsInstance(s["status_text"], str)
                self.assertTrue(s["status_text"].strip())

    def test_zero_byte_cache_is_unknown(self):
        self.env(None, {}, finished=self.ago(hours=2))
        write_bytes(CACHE_PATH, b"")
        s = self.snap()
        self.assertIsNone(s["rows"])
        self.assertIsNone(s["pending_count"])

    def test_non_utf8_cache_is_unknown(self):
        self.env(None, {}, finished=self.ago(hours=2))
        write_bytes(CACHE_PATH, b'{"threads": {"a": "\xff\xfe"}}')
        s = self.snap()
        self.assertIsNone(s["rows"])
        self.assertEqual(s["heading"], f"{BASE} (判断待ち?・読込失敗)")

    def test_corrupt_status_file_gives_unknown(self):
        # 仕様変更(第2回): 「キャッシュ/ステータス読込失敗時は rows=older_rows=None, pending_count=None,
        # others_count=0」。壊れた action_status.json を {} 扱いにして完了済みが復活して見えることは無い
        self.env({"P": make_thread(), "D": make_thread()}, {self.key("D"): make_status("done")},
                 finished=self.ago(hours=2))
        self.assertEqual(self.snap()["pending_count"], 1)
        for raw in ("{broken", "{", "\x00\x01", '{"a": '):
            with self.subTest(raw=raw):
                write_text(STATUS_PATH, raw)
                before = read_bytes(STATUS_PATH)
                s = self.snap()
                self.assertIsNone(s["rows"])
                self.assertIsNone(s["older_rows"])
                self.assertIsNone(s["pending_count"])
                self.assertEqual(s["others_count"], 0)
                self.assertEqual(s["heading"], f"{BASE} (判断待ち?・読込失敗)")
                self.assertEqual(s["heading_compact"], f"{BASE} ⚖!")
                self.assertEqual(read_bytes(STATUS_PATH), before, "壊れたファイルを書き換えた")

    def test_corrupt_cache_with_stale_or_missing_last_run_follows_rule_order(self):
        # 仕様の列挙順 (①記録なし/24h以上 → 要更新 ②pending=None → 読込失敗) どおりに要更新が優先
        write_text(CACHE_PATH, "{broken")
        s = self.snap()
        self.assertEqual(s["heading"], f"{BASE} (判断待ち?・要更新)")
        write_json(LAST_RUN_PATH, make_last_run(self.ago(hours=30)))
        self.assertEqual(self.snap()["heading"], f"{BASE} (判断待ち?・要更新)")

    def test_error_threads_are_counted_within_horizon_only(self):
        since_edge = self.since_of(self.ago(hours=2))
        threads = {
            "E1": make_thread(error=True, latest_ts=ts_ago(1)),
            "E2": make_thread(error=True, latest_ts=ts_ago(100)),
            "E_EDGE": make_thread(error=True, latest_ts=int(since_edge)),
            "E_OLD": make_thread(error=True, latest_ts=int(since_edge) - 1),
            "E_NOMETA": make_thread(error=True, meta=False),
            "P1": make_thread(latest_ts=ts_ago(3)),
        }
        self.env(threads, {}, finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual(s["error_count"], 3)
        self.assertEqual([r["cid"] for r in s["rows"]], ["P1"])
        self.assertEqual(s["pending_count"], 1)
        # 解析失敗があると件数に「+」(取りこぼしの可能性)、末尾に「・解析失敗3件」
        self.assertEqual(s["heading"], f"{BASE} (判断待ち1+・解析2時間前・解析失敗3件)")
        self.assertEqual(s["heading_compact"], f"{BASE} ⚖1+")

    def test_no_errors_no_suffix_and_no_plus(self):
        self.env({"P1": make_thread()}, {}, finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual(s["error_count"], 0)
        self.assertNotIn("解析失敗", s["heading"])
        self.assertNotIn("+", s["heading"])
        self.assertNotIn("+", s["heading_compact"])

    def test_error_threads_are_never_pending(self):
        t = make_thread([make_action(action="承認してください")], error=True)
        self.env({"E": t}, {}, finished=self.ago(hours=1))
        s = self.snap()
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["older_rows"], [])
        self.assertEqual(s["others_count"], 0)
        self.assertEqual(s["error_count"], 1)

    def test_error_count_in_stale_heading_is_hidden(self):
        self.env({"E": make_thread(error=True)}, {}, finished=self.ago(hours=30))
        self.assertEqual(self.snap()["heading"], f"{BASE} (判断待ち?・要更新)")


# ============================================================
# horizon / since_ts / partial / horizon_days
# ============================================================
class TestSnapshotHorizon(SnapBase):
    def test_window_days_table(self):
        # window_days = days>0 ? days : 1 、ただし max(window_days, 7)。horizon_days はその日数
        table = ((0, 7), (1, 7), (2, 7), (3, 7), (6, 7), (7, 7), (8, 8), (14, 14), (21, 21),
                 (30, 30), (180, 180), (-1, 7), (-100, 7))
        finished = self.ago(hours=2)
        for days, win in table:
            with self.subTest(days=days):
                write_json(LAST_RUN_PATH, make_last_run(finished, days=days))
                write_json(CACHE_PATH, make_cache({}))
                s = self.snap()
                self.assertAlmostEqual(s["since_ts"], finished.timestamp() - win * DAY, delta=1.0,
                                       msg=f"days={days} の horizon が {win}日になっていない")
                self.assertEqual(s["horizon_days"], win)

    def test_partial_flag_when_range_under_7_days(self):
        finished = self.ago(hours=2)
        for days, want in ((0, True), (1, True), (2, True), (3, True), (6, True), (7, False), (8, False),
                           (14, False), (30, False), (180, False)):
            with self.subTest(days=days):
                write_json(LAST_RUN_PATH, make_last_run(finished, days=days, label=f"{days}d"))
                write_json(CACHE_PATH, make_cache({}))
                self.assertIs(self.snap()["partial"], want)

    def test_days_1_still_reaches_back_7_days(self):
        finished = self.ago(hours=2)
        f = finished.timestamp()
        threads = {
            "IN": make_thread(latest_ts=int(f - 6.5 * DAY)),
            "OUT": make_thread(latest_ts=int(f - 7.5 * DAY)),
        }
        for days in (0, 1):
            with self.subTest(days=days):
                self.env(threads, {}, finished=finished, days=days)
                s = self.snap()
                self.assertEqual([r["cid"] for r in s["rows"]], ["IN"])
                self.assertEqual([r["cid"] for r in s["older_rows"]], ["OUT"])

    def test_days_14_extends_horizon(self):
        finished = self.ago(hours=2)
        f = finished.timestamp()
        threads = {"MID": make_thread(latest_ts=int(f - 10 * DAY)), "OLD": make_thread(latest_ts=int(f - 15 * DAY)),
                   "NEW": make_thread(latest_ts=int(f - 1 * DAY))}
        self.env(threads, {}, finished=finished, days=14)
        s = self.snap()
        self.assertEqual(sorted(r["cid"] for r in s["rows"]), ["MID", "NEW"])
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["OLD"])

    def test_boundary_of_since_ts_is_inclusive(self):
        finished = self.ago(hours=2)
        since = int(finished.timestamp() - 7 * DAY)
        threads = {"AT": make_thread(latest_ts=since), "BEFORE": make_thread(latest_ts=since - 1),
                   "AFTER": make_thread(latest_ts=since + 1)}
        self.env(threads, {}, finished=finished, days=7)
        s = self.snap()
        self.assertEqual(sorted(r["cid"] for r in s["rows"]), ["AFTER", "AT"])
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["BEFORE"])

    def test_no_last_run_horizon_is_now_minus_7_days(self):
        threads = {"IN": make_thread(latest_ts=ts_ago(6 * 24)), "OUT": make_thread(latest_ts=ts_ago(8 * 24)),
                   "AT": make_thread(latest_ts=int(NOW.timestamp() - 7 * DAY))}
        self.env(threads, {}, finished=None)
        s = self.snap()
        self.assertEqual(sorted(r["cid"] for r in s["rows"]), ["AT", "IN"])
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["OUT"])

    def test_stale_last_run_horizon_is_relative_to_finished_at_not_now(self):
        finished = self.ago(days=3)           # 3日前に最終解析 (stale)
        threads = {"IN": make_thread(latest_ts=ts_ago(9 * 24)),       # now-9日 = finished-6日 → 範囲内
                   "OUT": make_thread(latest_ts=ts_ago(11 * 24))}     # now-11日 = finished-8日 → 範囲外
        self.env(threads, {}, finished=finished, days=7)
        s = self.snap()
        self.assertIs(s["stale"], True)
        self.assertAlmostEqual(s["since_ts"], finished.timestamp() - 7 * DAY, delta=1.0)
        self.assertEqual([r["cid"] for r in s["rows"]], ["IN"])

    def test_threads_newer_than_last_run_are_not_excluded(self):
        # 下限だけの条件。最終解析より新しいスレッド (キャッシュにあれば) は除外しない
        finished = self.ago(hours=5)
        self.env({"NEWER": make_thread(latest_ts=ts_ago(1))}, {}, finished=finished)
        self.assertEqual([r["cid"] for r in self.snap()["rows"]], ["NEWER"])

    def test_older_threads_do_not_count_as_pending_nor_errors(self):
        finished = self.ago(hours=2)
        old = int(finished.timestamp() - 8 * DAY)
        self.env({"OLD": make_thread(latest_ts=old), "OLDERR": make_thread(error=True, latest_ts=old)}, {},
                 finished=finished)
        s = self.snap()
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["pending_count"], 0)
        self.assertEqual(s["error_count"], 0)
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["OLD"])          # 判断待ちは older_rows 側


# ============================================================
# 仕様変更(第2回): older_rows
# ============================================================
class TestSnapshotOlderRows(SnapBase):
    """older_rows = rows と同条件 (自分宛て×判断語・未完了) で latest_ts < since_ts (対象期間より古い未対応)。"""

    def build(self):
        finished = self.ago(hours=2)
        since = int(self.since_of(finished))
        threads = {
            "NEW": make_thread(latest_ts=ts_ago(3)),
            "OLD1": make_thread(latest_ts=since - 3600),
            "OLD2": make_thread([make_action(deadline="10/1")], latest_ts=since - 10 * DAY),
            "OLD_DONE": make_thread(latest_ts=since - 3600),
            "OLD_IGN": make_thread(latest_ts=since - 3600),
            "OLD_OTHER": make_thread([make_action(target="Nakai")], latest_ts=since - 3600),
            "OLD_PLAIN": make_thread([make_action(action="資料送付")], action_type="作業・依頼",
                                     latest_ts=since - 3600),
            "OLD_ERR": make_thread(error=True, latest_ts=since - 3600),
            "OLD_NOMETA": make_thread(meta=False),
        }
        statuses = {self.key("OLD_DONE"): make_status("done"), self.key("OLD_IGN"): make_status("ignored")}
        self.env(threads, statuses, finished=finished)
        return since

    def test_older_rows_hold_old_pending_decisions_only(self):
        self.build()
        s = self.snap()
        self.assertEqual([r["cid"] for r in s["rows"]], ["NEW"])
        self.assertEqual({r["cid"] for r in s["older_rows"]}, {"OLD1", "OLD2"})
        for r in s["older_rows"]:
            for k in ROW_KEYS:
                self.assertIn(k, r)
            self.assertIs(r["is_decision"], True)
            self.assertIs(r["resurfaced"], False)

    def test_pending_count_and_heading_count_only_rows(self):
        self.build()
        s = self.snap()
        self.assertEqual(s["pending_count"], 1)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち1・解析2時間前)")
        self.assertEqual(s["heading_compact"], f"{BASE} ⚖1")

    def test_older_rows_do_not_count_as_errors_or_others(self):
        self.build()
        s = self.snap()
        self.assertEqual(s["error_count"], 0)                 # 期間より古い解析失敗は数えない
        self.assertEqual(s["others_count"], 0)                # 期間より古い「判断語なし」は数えない

    def test_older_line_in_status_text(self):
        self.build()
        self.assertIn(older_line(7, 2), self.snap()["status_text"])

    def test_older_line_uses_horizon_days(self):
        finished = self.ago(hours=2)
        since = int(self.since_of(finished, 14))
        self.env({"A": make_thread(latest_ts=since - 100), "B": make_thread(latest_ts=since - 200),
                  "C": make_thread(latest_ts=since - 300), "N": make_thread(latest_ts=ts_ago(1))}, {},
                 finished=finished, days=14, label="2週間")
        s = self.snap()
        self.assertEqual(s["horizon_days"], 14)
        self.assertEqual(len(s["older_rows"]), 3)
        self.assertIn(older_line(14, 3), s["status_text"])

    def test_no_older_line_when_there_are_none(self):
        self.env({"N": make_thread(latest_ts=ts_ago(1))}, {}, finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual(s["older_rows"], [])
        self.assertNotIn("古い案件も表示", s["status_text"])
        self.assertNotIn("📅", s["status_text"])

    def test_boundary_at_since_goes_to_rows_and_just_before_goes_to_older(self):
        finished = self.ago(hours=2)
        since = int(self.since_of(finished))
        self.env({"AT": make_thread(latest_ts=since), "BEFORE": make_thread(latest_ts=since - 1)}, {},
                 finished=finished)
        s = self.snap()
        self.assertEqual([r["cid"] for r in s["rows"]], ["AT"])
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["BEFORE"])

    def test_older_rows_when_no_last_run_use_now_minus_7_days(self):
        self.env({"IN": make_thread(latest_ts=ts_ago(6 * 24)), "OUT": make_thread(latest_ts=ts_ago(9 * 24))}, {},
                 finished=None)
        s = self.snap()
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["OUT"])
        self.assertIn(older_line(7, 1), s["status_text"])

    def test_older_rows_are_computed_even_when_stale(self):
        finished = self.ago(hours=30)
        since = int(self.since_of(finished))
        self.env({"OLD": make_thread(latest_ts=since - 100)}, {}, finished=finished)
        s = self.snap()
        self.assertIs(s["stale"], True)
        self.assertEqual([r["cid"] for r in s["older_rows"]], ["OLD"])

    def test_older_rows_follow_target_and_alias_rules(self):
        finished = self.ago(hours=2)
        since = int(self.since_of(finished))
        self.env({"Y": make_thread([make_action(target="Taro Yamada")], latest_ts=since - 100)}, {},
                 finished=finished)
        self.assertEqual(self.snap()["older_rows"], [])
        self.assertEqual([r["cid"] for r in self.snap(extra_aliases=("taro yamada",))["older_rows"]], ["Y"])

    def test_older_rows_none_on_cache_or_status_failure(self):
        self.build()
        write_text(CACHE_PATH, "{broken")
        self.assertIsNone(self.snap()["older_rows"])
        self.build()
        write_text(STATUS_PATH, "{broken")
        self.assertIsNone(self.snap()["older_rows"])


class TestSpecGapSnapshotOlderRows(SnapBase):
    def test_older_rows_are_sorted_like_rows(self):
        # 並び順の記載は無い。rows と同じ (優先度 → 期限あり → 新しい順 → key) が自然
        finished = self.ago(hours=2)
        since = int(self.since_of(finished))
        threads = {"OLD_A": make_thread(latest_ts=since - 100), "OLD_B": make_thread(latest_ts=since - 5000),
                   "OLD_C": make_thread([make_action(deadline="10/1")], latest_ts=since - 9000),
                   "OLD_D": make_thread(latest_ts=since - 7000)}
        statuses = {self.key("OLD_D"): make_status("not_started", "top")}
        self.env(threads, statuses, finished=finished)
        got = [r["cid"] for r in self.snap()["older_rows"]]
        self.assertEqual(got, ["OLD_D", "OLD_C", "OLD_A", "OLD_B"])

    def test_resurfaced_old_threads_are_in_older_rows_with_flag(self):
        finished = self.ago(hours=2)
        since = int(self.since_of(finished))
        latest = since - 3600
        upd = datetime.fromtimestamp(latest - 600).strftime("%Y-%m-%dT%H:%M:%S")
        self.env({"R": make_thread(latest_ts=latest)}, {self.key("R"): make_status("done", updated_at=upd)},
                 finished=finished)
        s = self.snap()
        self.assertEqual([(r["cid"], r["resurfaced"]) for r in s["older_rows"]], [("R", True)])


# ============================================================
# 仕様変更(第2回): others_count
# ============================================================
class TestSnapshotOthersCount(SnapBase):
    """others_count = 自分宛て・未完了だが判断語に当たらないもので latest_ts >= since_ts の件数。"""

    def build(self, finished=None, **env_kw):
        finished = finished or self.ago(hours=2)
        since = int(self.since_of(finished))
        threads = {
            "SELF_PLAIN1": make_thread([make_action(action="資料送付")], action_type="作業・依頼"),
            "SELF_PLAIN2": make_thread([make_action(target="", action="確認ください")], action_type="通知・共有"),
            "SELF_SUMI": make_thread([make_action(action="承認済みです")], action_type="作業・依頼"),
            "SELF_INPROG": make_thread([make_action(action="共有ください")], action_type="その他"),
            "DECISION": make_thread(),
            "NOT_SELF": make_thread([make_action(target="Nakai", action="資料送付")], action_type="作業・依頼"),
            "PLAIN_DONE": make_thread([make_action(action="資料送付")], action_type="作業・依頼"),
            "PLAIN_IGN": make_thread([make_action(action="資料送付")], action_type="作業・依頼"),
            "PLAIN_ERR": make_thread([make_action(action="資料送付")], action_type="作業・依頼", error=True),
            "PLAIN_OLD": make_thread([make_action(action="資料送付")], action_type="作業・依頼",
                                     latest_ts=since - 100),
            "PLAIN_NOMETA": make_thread([make_action(action="資料送付")], action_type="作業・依頼", meta=False),
        }
        statuses = {self.key("PLAIN_DONE"): make_status("done"), self.key("PLAIN_IGN"): make_status("ignored"),
                    self.key("SELF_INPROG"): make_status("in_progress")}
        self.env(threads, statuses, finished=finished, **env_kw)
        return since

    def test_counts_self_incomplete_non_decision_within_horizon(self):
        self.build()
        s = self.snap()
        self.assertEqual(s["others_count"], 4)          # PLAIN1, PLAIN2, SUMI, INPROG
        self.assertEqual([r["cid"] for r in s["rows"]], ["DECISION"])

    def test_others_line_in_status_text(self):
        self.build()
        self.assertIn(others_line(4), self.snap()["status_text"])

    def test_no_others_line_when_zero(self):
        self.env({"D": make_thread()}, {}, finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual(s["others_count"], 0)
        self.assertNotIn("📌", s["status_text"])
        self.assertNotIn("判断語に当たらない", s["status_text"])

    def test_sumi_phrase_counts_as_other_not_decision(self):
        # 「承認済みです」は判断語として数えない (仕様変更(第2回)) → 判断待ちではなく others に回る
        self.env({"S": make_thread([make_action(action="承認済みです")], action_type="作業・依頼")}, {},
                 finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["others_count"], 1)

    def test_since_boundary(self):
        finished = self.ago(hours=2)
        since = int(self.since_of(finished))
        plain = dict(action_type="作業・依頼")
        self.env({"AT": make_thread([make_action(action="資料送付")], latest_ts=since, **plain),
                  "BEFORE": make_thread([make_action(action="資料送付")], latest_ts=since - 1, **plain)}, {},
                 finished=finished)
        self.assertEqual(self.snap()["others_count"], 1)

    def test_others_follow_extra_aliases(self):
        self.env({"Y": make_thread([make_action(target="Taro Yamada", action="資料送付")],
                                   action_type="作業・依頼")}, {}, finished=self.ago(hours=2))
        self.assertEqual(self.snap()["others_count"], 0)
        self.assertEqual(self.snap(extra_aliases=("taro yamada",))["others_count"], 1)

    def test_zero_on_cache_or_status_failure(self):
        self.build()
        write_text(CACHE_PATH, "{broken")
        s = self.snap()
        self.assertEqual(s["others_count"], 0)
        self.assertNotIn("📌", s["status_text"])
        self.build()
        write_text(STATUS_PATH, "{broken")
        s = self.snap()
        self.assertEqual(s["others_count"], 0)
        self.assertNotIn("📌", s["status_text"])

    def test_others_do_not_change_pending_count_or_heading(self):
        self.build()
        s = self.snap()
        self.assertEqual(s["pending_count"], 1)
        # build() には解析失敗スレッド PLAIN_ERR (期間内) が1件ある → 「+」と「・解析失敗1件」だけが付く
        self.assertEqual(s["error_count"], 1)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち1+・解析2時間前・解析失敗1件)")
        self.assertNotIn("4", s["heading"])


class TestSpecGapSnapshotOthersCount(SnapBase):
    def test_counts_actions_not_threads(self):
        # 「件」の単位は未記載。行 (action) 単位の判断待ちと揃えて action 単位が自然
        t = make_thread([make_action(action="資料送付"), make_action(action="確認ください"),
                         make_action(action="承認をお願いします")], action_type="作業・依頼")
        self.env({"T": t}, {}, finished=self.ago(hours=2))
        s = self.snap()
        self.assertEqual([r["key"] for r in s["rows"]], [self.key("T", 2)])
        self.assertEqual(s["others_count"], 2)

    def test_empty_action_text_is_not_counted(self):
        t = make_thread([make_action(action=""), make_action(action="   ")], action_type="作業・依頼")
        self.env({"T": t}, {}, finished=self.ago(hours=2))
        self.assertEqual(self.snap()["others_count"], 0)

    def test_resurfaced_done_non_decision_is_counted_like_incomplete(self):
        # 再浮上(done + 新着)は「未完了」として扱うのが自然 → others にも数える
        latest = ts_ago(2)
        upd = datetime.fromtimestamp(latest - 600).strftime("%Y-%m-%dT%H:%M:%S")
        t = make_thread([make_action(action="資料送付")], action_type="作業・依頼", latest_ts=latest)
        self.env({"T": t}, {self.key("T"): make_status("done", updated_at=upd)}, finished=self.ago(hours=2))
        self.assertEqual(self.snap()["others_count"], 1)


# ============================================================
# 仕様変更(第2回): done の再浮上 (B1)
# ============================================================
class TestSnapshotResurfacing(SnapBase):
    def test_done_with_newer_mail_resurfaces_in_rows_and_counts(self):
        latest = ts_ago(2)
        before = datetime.fromtimestamp(latest - 600).strftime("%Y-%m-%dT%H:%M:%S")
        threads = {"R": make_thread(latest_ts=latest), "P": make_thread(latest_ts=ts_ago(3))}
        statuses = {self.key("R"): make_status("done", updated_at=before)}
        self.env(threads, statuses, finished=self.ago(hours=2))
        s = self.snap()
        got = {r["cid"]: r["resurfaced"] for r in s["rows"]}
        self.assertEqual(got, {"R": True, "P": False})
        self.assertEqual(s["pending_count"], 2)
        self.assertEqual(s["heading"], f"{BASE} (判断待ち2・解析2時間前)")

    def test_done_not_older_than_latest_stays_hidden(self):
        latest = ts_ago(2)
        for delta in (0, 60, 3600):
            with self.subTest(updated_after_latest_by=delta):
                upd = datetime.fromtimestamp(latest + delta).strftime("%Y-%m-%dT%H:%M:%S")
                self.env({"R": make_thread(latest_ts=latest)}, {self.key("R"): make_status("done", updated_at=upd)},
                         finished=self.ago(hours=2))
                self.assertEqual(self.snap()["rows"], [])

    def test_done_without_or_with_invalid_updated_at_stays_hidden(self):
        for st in ({"progress": "done", "priority": "", "comment": ""},
                   make_status("done", updated_at="garbage"), make_status("done", updated_at=""),
                   make_status("done", updated_at=None), make_status("done", updated_at=12345)):
            with self.subTest(status=st):
                self.env({"R": make_thread(latest_ts=ts_ago(2))}, {self.key("R"): st}, finished=self.ago(hours=2))
                self.assertEqual(self.snap()["rows"], [])

    def test_ignored_never_resurfaces(self):
        latest = ts_ago(2)
        before = datetime.fromtimestamp(latest - 600).strftime("%Y-%m-%dT%H:%M:%S")
        self.env({"R": make_thread(latest_ts=latest)}, {self.key("R"): make_status("ignored", updated_at=before)},
                 finished=self.ago(hours=2))
        self.assertEqual(self.snap()["rows"], [])

    def test_legacy_key_done_resurfaces(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("L1", "Nakai", "承認をお願いします")
        latest = ts_ago(2)
        before = datetime.fromtimestamp(latest - 600).strftime("%Y-%m-%dT%H:%M:%S")
        self.env({"L1": make_thread([a], latest_ts=latest)}, {legacy: make_status("done", updated_at=before)},
                 finished=self.ago(hours=2))
        self.assertEqual([(r["cid"], r["resurfaced"]) for r in self.snap()["rows"]], [("L1", True)])

    def test_completing_again_hides_it_again_with_real_clock(self):
        # 完了(set_action_progress)した直後は除外に戻る (updated_at が「今」になる)。実時計で確認
        now_real = datetime.now()
        latest = int(time.time()) - 3600
        old = datetime.fromtimestamp(latest - 7200).strftime("%Y-%m-%dT%H:%M:%S")
        write_json(CACHE_PATH, make_cache({"R": make_thread(latest_ts=latest)}))
        write_json(STATUS_PATH, {self.key("R"): make_status("done", updated_at=old)})
        write_json(LAST_RUN_PATH, make_last_run(now_real - timedelta(minutes=30)))
        s = oto().build_action_decision_snapshot(now=now_real)
        self.assertEqual([(r["cid"], r["resurfaced"]) for r in s["rows"]], [("R", True)])
        oto().set_action_progress({self.key("R"): "done"})
        s = oto().build_action_decision_snapshot(now=now_real)
        self.assertEqual(s["rows"], [])
        self.assertEqual(s["pending_count"], 0)


# ============================================================
# 読み取り専用 / ロック / COM・AI非接触
# ============================================================
class TestSnapshotIsReadOnly(SnapBase):
    def test_existing_files_are_untouched(self):
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        before = snapshot_files(".")
        self.snap()
        self.snap(extra_aliases=("x y",))
        self.assertEqual(snapshot_files("."), before, "snapshot がファイルを書き換えた/作った")

    def test_no_new_files_are_created_when_inputs_are_missing(self):
        self.env({"P": make_thread()}, None, finished=None)        # cache だけ
        before = snapshot_files(".")
        self.snap()
        self.assertEqual(snapshot_files("."), before)
        self.assertFalse(os.path.exists(STATUS_PATH))
        self.assertFalse(os.path.exists(LAST_RUN_PATH))

    def test_nothing_is_created_in_an_empty_directory(self):
        self.snap()
        self.assertEqual(snapshot_files("."), {})
        self.assertFalse(os.path.exists(CACHE_PATH))

    def test_legacy_key_migration_is_not_written_back(self):
        # 旧キーの引継ぎは「読み取りのみ。書き戻しはしない」
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("L1", "Nakai", "承認をお願いします")
        self.env({"L1": make_thread([a])}, {legacy: make_status("in_progress")}, finished=self.ago(hours=1))
        before = read_bytes(STATUS_PATH)
        self.snap()
        self.assertEqual(read_bytes(STATUS_PATH), before)
        self.assertNotIn(self.key("L1"), read_json(STATUS_PATH))

    def test_corrupt_status_file_is_not_modified_and_does_not_raise(self):
        self.env({"P": make_thread()}, None, finished=self.ago(hours=1))
        write_text(STATUS_PATH, "{broken")
        before = read_bytes(STATUS_PATH)
        s = self.snap()
        self.assertEqual(read_bytes(STATUS_PATH), before)
        self.assertIsInstance(s["heading"], str)

    def test_resurfacing_does_not_write_status(self):
        latest = ts_ago(2)
        before_iso = datetime.fromtimestamp(latest - 600).strftime("%Y-%m-%dT%H:%M:%S")
        self.env({"R": make_thread(latest_ts=latest)}, {self.key("R"): make_status("done", updated_at=before_iso)},
                 finished=self.ago(hours=2))
        before = snapshot_files(".")
        self.snap()
        self.assertEqual(snapshot_files("."), before)


class TestSnapshotLocking(SnapBase):
    def test_takes_action_status_lock_to_read_statuses(self):
        # 仕様: action_status_lock を取ってステータスを読む
        self.env({"P": make_thread()}, {}, finished=self.ago(hours=1))
        lock = oto().action_status_lock
        result, done = {}, threading.Event()

        def worker():
            try:
                result["snap"] = oto().build_action_decision_snapshot(now=NOW)
            except BaseException as e:      # noqa: BLE001
                result["err"] = e
            finally:
                done.set()

        lock.acquire()
        released = False
        try:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            self.assertFalse(done.wait(0.4), "ロック保持中に snapshot が進んだ (ロックを取っていない?)")
            lock.release()
            released = True
            self.assertTrue(done.wait(5), "ロック解放後も完了しない")
        finally:
            if not released:
                lock.release()
        t.join(5)
        self.assertNotIn("err", result)
        self.assertEqual(result["snap"]["pending_count"], 1)

    def test_lock_is_released_after_normal_call(self):
        self.env({"P": make_thread()}, {}, finished=self.ago(hours=1))
        self.snap()
        got = oto().action_status_lock.acquire(timeout=2)
        self.assertTrue(got)
        oto().action_status_lock.release()

    def test_lock_is_released_even_if_status_read_raises(self):
        self.env({"P": make_thread()}, {}, finished=self.ago(hours=1))
        with mock.patch.object(oto(), "load_action_status", side_effect=RuntimeError("boom")):
            try:
                self.snap()
            except RuntimeError:
                pass                                   # 伝播しても握りつぶしてもよい
        got = oto().action_status_lock.acquire(timeout=2)
        self.assertTrue(got, "例外時にロックが解放されていない")
        oto().action_status_lock.release()

    def test_lock_is_released_after_status_failure(self):
        self.env({"P": make_thread()}, None, finished=self.ago(hours=1))
        write_text(STATUS_PATH, "{broken")
        self.snap()
        got = oto().action_status_lock.acquire(timeout=2)
        self.assertTrue(got, "読込失敗の経路でロックが解放されていない")
        oto().action_status_lock.release()

    def test_reading_never_observes_a_half_written_status_file(self):
        # ロック保持者が action_status.json を書き換え中 (トランケート直後で未書込) の瞬間に
        # snapshot が割り込めないこと。割り込めるなら壊れた/空の状態を読んでしまう。
        self.env({"P": make_thread(), "D": make_thread()}, {self.key("D"): make_status("done")},
                 finished=self.ago(hours=1))
        lock = oto().action_status_lock
        result, done = {}, threading.Event()

        def worker():
            try:
                result["snap"] = oto().build_action_decision_snapshot(now=NOW)
            except BaseException as e:      # noqa: BLE001
                result["err"] = e
            finally:
                done.set()

        content = read_bytes(STATUS_PATH)
        with lock:
            with open(STATUS_PATH, "wb") as f:           # 書き換え途中: 空にした直後
                f.flush()
                t = threading.Thread(target=worker, daemon=True)
                t.start()
                time.sleep(0.3)
                f.write(content)
            self.assertFalse(done.is_set(), "ロック保持中に snapshot が完了した")
        self.assertTrue(done.wait(5))
        t.join(5)
        self.assertNotIn("err", result)
        s = result["snap"]
        self.assertEqual([r["cid"] for r in s["rows"]], ["P"], "書込み途中の空ファイルを読んだ可能性")


class _Boom:
    """触れたら失敗するオブジェクト (COM/AI/ネットワーク用)。"""

    def __init__(self, label):
        self._label = label

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"A1が {self._label}.{name} に触れた (COM/AI/ネットワーク禁止)")

    def __call__(self, *a, **k):
        raise AssertionError(f"A1が {self._label} を呼んだ (COM/AI/ネットワーク禁止)")


class TestSnapshotDoesNotTouchComOrAi(SnapBase):
    def test_snapshot_and_pure_functions_do_not_touch_outlook_or_ai(self):
        mod = oto()
        self.env(self.standard_threads(), self.standard_statuses(), finished=self.ago(hours=2))
        patches = [mock.patch.object(mod, name, _Boom(name), create=True)
                   for name in ("win32com", "pythoncom", "requests", "BeautifulSoup",
                                "_CommonGeminiClient", "_generate_advanced")]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        s = self.snap()
        self.assertEqual(s["pending_count"], 3)
        mod.build_decision_heading(BASE, 1, None, 0, NOW)
        mod.build_decision_heading_compact(BASE, 1, None, 0, NOW)
        mod.compute_pending_decisions(make_cache(self.standard_threads()), {})
        mod.build_self_aliases("Ochi, Yuichi", "yuichi.ochi@example.com")


# ============================================================
# 純関数との一貫性 / 性能
# ============================================================
class TestSnapshotConsistency(SnapBase):
    def assert_consistent(self, s, extra=()):
        mod = oto()
        cache = mod.load_action_dashboard_cache()
        statuses = read_json(STATUS_PATH) if os.path.exists(STATUS_PATH) else {}
        if cache is None:
            self.assertIsNone(s["rows"])
            self.assertIsNone(s["older_rows"])
            self.assertIsNone(s["pending_count"])
        else:
            expected = mod.compute_pending_decisions(cache, statuses, extra_aliases=extra, since_ts=s["since_ts"])
            self.assertEqual(s["rows"], expected)
            self.assertEqual(s["pending_count"], len(expected))
            self.assertEqual(s["error_count"], mod.count_recent_error_threads(cache, s["since_ts"]))
            # older_rows = 同条件で期間より古いもの
            everything = mod.compute_pending_decisions(cache, statuses, extra_aliases=extra, since_ts=None)
            older_keys = {r["key"] for r in everything if r["latest_ts"] < s["since_ts"]}
            self.assertEqual({r["key"] for r in s["older_rows"]}, older_keys)
            self.assertEqual({r["key"] for r in s["rows"]} | older_keys, {r["key"] for r in everything})
        self.assertEqual(
            s["heading"],
            mod.build_decision_heading(BASE, s["pending_count"], s["last_run"], s["error_count"], NOW))
        self.assertEqual(
            s["heading_compact"],
            mod.build_decision_heading_compact(BASE, s["pending_count"], s["last_run"], s["error_count"], NOW))

    def test_consistency_across_scenarios(self):
        scenarios = {
            "fresh": dict(finished=self.ago(hours=2)),
            "stale": dict(finished=self.ago(hours=24)),
            "none": dict(finished=None),
            "days14": dict(finished=self.ago(hours=3), days=14, label="2週間"),
            "days3": dict(finished=self.ago(hours=3), days=3, label="3日間"),
            "skew": dict(finished=NOW + timedelta(hours=2)),
        }
        for name, kw in scenarios.items():
            with self.subTest(scenario=name):
                with tempdir_cwd():                          # シナリオごとに空ディレクトリから始める
                    threads = self.standard_threads()
                    threads["E1"] = make_thread(error=True, latest_ts=ts_ago(2))
                    threads["OLDP"] = make_thread(latest_ts=ts_ago(24 * 20))
                    self.env(threads, self.standard_statuses(), **kw)
                    self.assert_consistent(self.snap())

    def test_consistency_with_corrupt_cache(self):
        self.env(None, {}, finished=self.ago(hours=2))
        write_text(CACHE_PATH, "{broken")
        self.assert_consistent(self.snap())

    def test_consistency_with_extra_aliases(self):
        self.env({"Y": make_thread([make_action(target="Taro Yamada")]), "Z": make_thread()}, {},
                 finished=self.ago(hours=2))
        self.assert_consistent(self.snap(extra_aliases=("taro yamada",)), extra=("taro yamada",))


class TestSnapshotPerformance(SnapBase):
    def test_3000_threads_finish_quickly_and_count_correctly(self):
        threads, statuses = {}, {}
        for i in range(3000):
            cid = f"C{i:05d}"
            m = i % 5
            if m == 0:                                   # 判断待ち
                threads[cid] = make_thread(latest_ts=ts_ago(1))
            elif m == 1:                                 # 完了
                threads[cid] = make_thread(latest_ts=ts_ago(1))
                statuses[self.key(cid)] = make_status("done")
            elif m == 2:                                 # 他人宛て
                threads[cid] = make_thread([make_action(target="Nakai")], latest_ts=ts_ago(1))
            elif m == 3:                                 # 決裁でない (自分宛て) → others_count
                threads[cid] = make_thread([make_action(action="資料送付")], action_type="作業・依頼",
                                           latest_ts=ts_ago(1))
            else:                                        # 解析失敗
                threads[cid] = make_thread(error=True, latest_ts=ts_ago(1))
        self.env(threads, statuses, finished=self.ago(hours=1))
        t0 = time.time()
        s = self.snap()
        elapsed = time.time() - t0
        self.assertEqual(s["pending_count"], 600)
        self.assertEqual(s["error_count"], 600)
        self.assertEqual(s["others_count"], 600)
        self.assertEqual(s["older_rows"], [])
        self.assertLess(elapsed, 5.0, f"3000スレッドの snapshot が遅い: {elapsed:.2f}s")


# ============================================================
# status_text (仕様変更(第2回) 6 で文言が確定した行)
# ============================================================
class TestSnapshotStatusText(SnapBase):
    def text(self, **env_kw):
        self.env(**env_kw)
        return self.snap()["status_text"]

    def test_permanent_notice_is_always_present(self):
        # 常設の注意文 (fresh / stale / 記録なし / キャッシュ読込失敗)
        std = self.standard_threads()
        self.assertIn(NOTICE, self.text(threads=std, statuses={}, finished=self.ago(hours=2)))
        self.assertIn(NOTICE, self.text(threads=std, statuses={}, finished=self.ago(hours=30)))
        with tempdir_cwd():
            self.assertIn(NOTICE, self.text(threads=std, statuses={}, finished=None))
        with tempdir_cwd():
            self.env(None, {}, finished=self.ago(hours=2))
            write_text(CACHE_PATH, "{broken")
            self.assertIn(NOTICE, self.snap()["status_text"])

    def test_old_notice_is_gone(self):
        t = self.text(threads=self.standard_threads(), statuses={}, finished=self.ago(hours=2))
        self.assertNotIn(OLD_NOTICE, t)

    def test_no_record_line_only_without_a_valid_last_run(self):
        std = self.standard_threads()
        fresh = self.text(threads=std, statuses={}, finished=self.ago(hours=2))
        self.assertNotIn("記録がありません", fresh)
        with tempdir_cwd():
            self.assertIn(NO_RECORD, self.text(threads=std, statuses={}, finished=None))
        with tempdir_cwd():
            self.env(std, {})
            write_text(LAST_RUN_PATH, '{"finished_at": "garbage", "days": 7, "period_label": "x"}')
            self.assertIn(NO_RECORD, self.snap()["status_text"])

    def test_stale_line_only_when_stale(self):
        std = self.standard_threads()
        self.assertIn(STALE_WARN, self.text(threads=std, statuses={}, finished=self.ago(hours=24)))
        self.assertIn(STALE_WARN, self.text(threads=std, statuses={}, finished=self.ago(days=5)))
        self.assertNotIn(STALE_WARN, self.text(threads=std, statuses={}, finished=self.ago(hours=23, minutes=59)))
        self.assertNotIn(STALE_WARN, self.text(threads=std, statuses={}, finished=self.ago(hours=2)))

    def test_partial_line_only_when_range_under_7_days(self):
        std = self.standard_threads()
        for days, label in ((0, "24H"), (1, "今日"), (3, "3日間"), (6, "6日")):
            with self.subTest(days=days):
                t = self.text(threads=std, statuses={}, finished=self.ago(hours=2), days=days, label=label)
                self.assertIn(partial_warn(label), t)
        for days, label in ((7, "1週間"), (14, "2週間"), (30, "1ヶ月")):
            with self.subTest(days=days):
                t = self.text(threads=std, statuses={}, finished=self.ago(hours=2), days=days, label=label)
                self.assertNotIn("7日未満", t)
                self.assertNotIn("それより前に届いた依頼は解析していません", t)

    def test_error_line_with_count(self):
        t = self.text(threads={"P": make_thread(), "E1": make_thread(error=True), "E2": make_thread(error=True)},
                      statuses={}, finished=self.ago(hours=2))
        self.assertIn(errors_line(2), t)
        t = self.text(threads={"P": make_thread(), "E1": make_thread(error=True)}, statuses={},
                      finished=self.ago(hours=2))
        self.assertIn(errors_line(1), t)

    def test_no_error_line_without_errors(self):
        t = self.text(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=2))
        self.assertNotIn("解析に失敗したスレッド", t)

    def test_all_conditional_lines_can_appear_together(self):
        finished = self.ago(hours=30)
        since = int(self.since_of(finished, 3))
        threads = {"P": make_thread(latest_ts=int(finished.timestamp()) - 3600),
                   "OLD": make_thread(latest_ts=since - 100),
                   "PLAIN": make_thread([make_action(action="資料送付")], action_type="作業・依頼",
                                        latest_ts=int(finished.timestamp()) - 3600),
                   "E": make_thread(error=True, latest_ts=int(finished.timestamp()) - 3600)}
        t = self.text(threads=threads, statuses={}, finished=finished, days=3, label="3日間")
        for line in (NOTICE, STALE_WARN, partial_warn("3日間"), older_line(7, 1), others_line(1), errors_line(1)):
            self.assertIn(line, t)

    def test_lines_are_independent_of_each_other(self):
        # older/others の行は、該当が無ければ他の条件 (stale・範囲7日未満 等) があっても出ない
        t = self.text(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=30), days=3, label="3日間")
        self.assertNotIn("古い案件も表示", t)
        self.assertNotIn("判断語に当たらない", t)

    def test_status_text_is_a_nonempty_string_in_every_situation(self):
        std = self.standard_threads()
        for kw in (dict(finished=self.ago(hours=2)), dict(finished=None), dict(finished=self.ago(hours=30)),
                   dict(finished=NOW + timedelta(days=1))):
            with tempdir_cwd():
                t = self.text(threads=std, statuses={}, **kw)
                self.assertIsInstance(t, str)
                self.assertTrue(t.strip())


class TestSpecGapSnapshotStatusText(SnapBase):
    """文言が仕様に明記されていない部分 (最終解析の日時・範囲の表示、読込失敗の警告)。自然な語で確認する。"""

    def text(self, **env_kw):
        self.env(**env_kw)
        return self.snap()["status_text"]

    def test_fresh_text_shows_finished_time_and_range(self):
        t = self.text(threads=self.standard_threads(), statuses={}, finished=self.ago(hours=2), days=7,
                      label="1週間")
        self.assertIn("10:00", t, "最終解析の日時 (HH:MM) が見当たらない")
        self.assertIn("1週間", t, "最終解析の範囲 (period_label) が見当たらない")

    def test_text_for_other_range_label(self):
        t = self.text(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=2), days=14,
                      label="2週間")
        self.assertIn("2週間", t)

    def test_cache_failure_warning(self):
        self.env(None, {}, finished=self.ago(hours=2))
        write_text(CACHE_PATH, "{broken")
        t = self.snap()["status_text"]
        self.assertTrue(any(w in t for w in ("読込", "読み込", "失敗")), f"読込失敗の警告が見当たらない: {t!r}")

    def test_status_failure_warning(self):
        self.env({"P": make_thread()}, None, finished=self.ago(hours=2))
        write_text(STATUS_PATH, "{broken")
        t = self.snap()["status_text"]
        self.assertTrue(any(w in t for w in ("読込", "読み込", "失敗")), f"読込失敗の警告が見当たらない: {t!r}")
        self.assertIn("action_status", t, "どのファイルが読めないのか (action_status.json) が分からない")

    def test_partial_line_for_negative_days_uses_one_day_range(self):
        # snapshot の window_days は「days>0 ? days : 1」。負も1日扱い → 7日未満
        t = self.text(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=2), days=-1, label="謎")
        self.assertIn(partial_warn("謎"), t)
        self.assertIs(self.snap()["partial"], True)


class TestSpecGapSnapshotInputs(SnapBase):
    """仕様に記載の無い入力。例外にしないことの確認。"""

    def test_last_run_with_wrong_typed_days_does_not_raise(self):
        self.env({"P": make_thread()}, {})
        for patch in ({"days": "abc"}, {"days": None}, {"days": [7]}, {"days": 7.5}, {"days": True}):
            d = make_last_run(self.ago(hours=2))
            d.update(patch)
            with self.subTest(patch=patch):
                write_json(LAST_RUN_PATH, d)
                s = self.snap()
                self.assertIsInstance(s["heading"], str)
                self.assertIsInstance(s["since_ts"], (int, float))
                self.assertIsInstance(s["horizon_days"], int)
                self.assertIsInstance(s["partial"], bool)

    def test_status_file_with_non_dict_json_does_not_raise(self):
        self.env({"P": make_thread()}, None, finished=self.ago(hours=2))
        for raw in ("[]", "null", '"x"', "5", '{"k": "not a dict"}', '{"k": null}'):
            with self.subTest(raw=raw):
                write_text(STATUS_PATH, raw)
                s = self.snap()
                self.assertIsInstance(s["heading"], str)

    def test_status_file_with_non_dict_json_is_a_read_failure(self):
        # strict 読込 (set_action_progress と同じ) の「dict以外 → 失敗」に揃えるのが自然
        self.env({"P": make_thread()}, None, finished=self.ago(hours=2))
        for raw in ("[]", "null", '"x"', "5", "true"):
            with self.subTest(raw=raw):
                write_text(STATUS_PATH, raw)
                s = self.snap()
                self.assertIsNone(s["rows"])
                self.assertIsNone(s["pending_count"])

    def test_zero_byte_status_file_is_empty_not_a_failure(self):
        # strict 読込の「0バイト → {}」に揃えるのが自然 (まだ何も記録していない状態)
        self.env({"P": make_thread()}, None, finished=self.ago(hours=2))
        write_bytes(STATUS_PATH, b"")
        s = self.snap()
        self.assertEqual(s["pending_count"], 1)

    def test_extra_aliases_none_is_accepted(self):
        self.env({"P": make_thread()}, {}, finished=self.ago(hours=2))
        self.assertEqual(self.snap(extra_aliases=None)["pending_count"], 1)

    def test_partial_when_no_record_is_a_bool(self):
        self.env({"P": make_thread()}, {}, finished=None)
        self.assertIsInstance(self.snap()["partial"], bool)


# ローカルタイムゾーンを JST(+9) / EST(-5) にして、時刻まわり (鮮度・horizon・再浮上・時計ずれ) を再実行する
_loader.make_tz_variants(globals(), [TestSnapshotFresh, TestSnapshotStaleAndUnknown, TestSnapshotHorizon,
                                     TestSnapshotOlderRows, TestSnapshotResurfacing])


if __name__ == "__main__":
    unittest.main(verbosity=2)
