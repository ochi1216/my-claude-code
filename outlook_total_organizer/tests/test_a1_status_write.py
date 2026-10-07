# -*- coding: utf-8 -*-
"""A1 判断待ち: 書込系テスト (仕様13 set_action_progress / 仕様8,9 save/load_action_last_run)。

仕様書 (A1_SPEC.md) だけを根拠に、実装を見ずに書いている。
クラス名に SpecGap を含むものは、仕様が曖昧/未記載のため「最も自然な解釈」で書いたもの
(失敗は「バグ」ではなく「仕様の確認が必要」の合図)。
"""
import copy
import json
import os
import re
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

import _loader
from _loader import (
    LAST_RUN_PATH, STATUS_PATH, make_status, read_bytes, read_json, tempdir_cwd, write_bytes,
    write_json, write_text,
)


def oto():
    return _loader.load()


def lock_is_free():
    """action_status_lock が (ブロックせず) 取れること。取れたらすぐ解放する。"""
    lock = oto().action_status_lock
    got = lock.acquire(timeout=2)
    if got:
        lock.release()
    return got


def file_state(path):
    st = os.stat(path)
    return read_bytes(path), st.st_mtime_ns


# ============================================================
# 13. set_action_progress
# ============================================================
class TestSetActionProgressNormal(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def sap(self, d):
        return oto().set_action_progress(d)

    def test_updates_progress_and_updated_at_only(self):
        initial = {
            "k1": {"progress": "not_started", "priority": "high", "comment": "メモ1",
                   "updated_at": "2026-01-01T00:00:00", "extra": {"x": [1, 2]}},
            "k2": make_status("in_progress", "top", "メモ2"),
        }
        write_json(STATUS_PATH, initial)
        before = datetime.now().replace(microsecond=0)
        res = self.sap({"k1": "done"})
        after = datetime.now()
        self.assertEqual(res, {"k1": "not_started"})
        data = read_json(STATUS_PATH)
        self.assertEqual(data["k2"], initial["k2"], "他のキーが変わった")
        e = data["k1"]
        self.assertEqual(e["progress"], "done")
        self.assertEqual(e["priority"], "high")
        self.assertEqual(e["comment"], "メモ1")
        self.assertEqual(e["extra"], {"x": [1, 2]})
        self.assertNotEqual(e["updated_at"], "2026-01-01T00:00:00")
        ts = datetime.fromisoformat(e["updated_at"])
        self.assertLessEqual(before - timedelta(seconds=1), ts)
        self.assertLessEqual(ts, after + timedelta(seconds=1))
        self.assertEqual(set(data), {"k1", "k2"})

    def test_returns_previous_progress_per_key(self):
        write_json(STATUS_PATH, {
            "k1": make_status("not_started"), "k2": make_status("in_progress"),
            "k3": make_status("done"), "k5": make_status("ignored"),
        })
        res = self.sap({"k1": "done", "k2": "ignored", "k3": "in_progress", "k4": "done", "k5": "not_started"})
        self.assertEqual(res, {"k1": "not_started", "k2": "in_progress", "k3": "done", "k4": None,
                               "k5": "ignored"})
        data = read_json(STATUS_PATH)
        self.assertEqual({k: v["progress"] for k, v in data.items()},
                         {"k1": "done", "k2": "ignored", "k3": "in_progress", "k4": "done",
                          "k5": "not_started"})

    def test_new_key_entry_shape(self):
        write_json(STATUS_PATH, {"other": make_status("done", "high", "c")})
        res = self.sap({"newkey": "in_progress"})
        self.assertEqual(res, {"newkey": None})
        e = read_json(STATUS_PATH)["newkey"]
        self.assertEqual(set(e), {"progress", "priority", "comment", "updated_at"})
        self.assertEqual(e["progress"], "in_progress")
        self.assertEqual(e["priority"], "")
        self.assertEqual(e["comment"], "")
        self.assertEqual(read_json(STATUS_PATH)["other"], make_status("done", "high", "c"))

    def test_all_valid_progress_values_are_accepted(self):
        for v in ("not_started", "in_progress", "done", "ignored"):
            with self.subTest(progress=v):
                self.sap({"k": v})
                self.assertEqual(read_json(STATUS_PATH)["k"]["progress"], v)

    def test_same_value_again_returns_new_previous(self):
        self.assertEqual(self.sap({"k": "done"}), {"k": None})
        self.assertEqual(self.sap({"k": "done"}), {"k": "done"})

    def test_undo_roundtrip_with_returned_previous(self):
        write_json(STATUS_PATH, {"k1": make_status("in_progress", "high", "メモ")})
        prev = self.sap({"k1": "done", "k2": "ignored"})
        self.assertEqual(prev, {"k1": "in_progress", "k2": None})
        restore = {k: ("not_started" if v is None else v) for k, v in prev.items()}   # GUIの「元に戻す」
        self.sap(restore)
        data = read_json(STATUS_PATH)
        self.assertEqual(data["k1"]["progress"], "in_progress")
        self.assertEqual(data["k1"]["priority"], "high")
        self.assertEqual(data["k1"]["comment"], "メモ")
        self.assertEqual(data["k2"]["progress"], "not_started")

    def test_japanese_and_emoji_comment_survive(self):
        write_json(STATUS_PATH, {"k1": make_status("not_started", "", "確認済み🙆 ｶﾅ ①")})
        self.sap({"k1": "done"})
        raw = read_bytes(STATUS_PATH).decode("utf-8")           # UTF-8 で読めること
        self.assertEqual(json.loads(raw)["k1"]["comment"], "確認済み🙆 ｶﾅ ①")

    def test_unrelated_non_dict_entries_are_preserved(self):
        write_json(STATUS_PATH, {"weird": "string", "n": 5, "k1": make_status("not_started")})
        self.sap({"k1": "done"})
        data = read_json(STATUS_PATH)
        self.assertEqual(data["weird"], "string")
        self.assertEqual(data["n"], 5)
        self.assertEqual(data["k1"]["progress"], "done")

    def test_empty_dict_returns_empty_and_changes_nothing(self):
        initial = {"k1": make_status("done", "high", "c")}
        write_json(STATUS_PATH, initial)
        self.assertEqual(self.sap({}), {})
        self.assertEqual(read_json(STATUS_PATH), initial)

    def test_large_batch(self):
        keys = [f"key{i:04d}" for i in range(300)]
        write_json(STATUS_PATH, {k: make_status("not_started", "high", f"c{k}") for k in keys[:150]})
        res = self.sap({k: "done" for k in keys})
        self.assertEqual(len(res), 300)
        self.assertEqual({k for k, v in res.items() if v is None}, set(keys[150:]))
        data = read_json(STATUS_PATH)
        self.assertEqual(len(data), 300)
        self.assertTrue(all(v["progress"] == "done" for v in data.values()))
        self.assertTrue(all(data[k]["priority"] == "high" and data[k]["comment"] == f"c{k}"
                            for k in keys[:150]))

    def test_save_action_status_is_used_once_per_call(self):
        write_json(STATUS_PATH, {"k1": make_status("not_started")})
        calls = []
        orig = oto().save_action_status

        def spy(data):
            calls.append(copy.deepcopy(data))
            return orig(data)

        with mock.patch.object(oto(), "save_action_status", spy):
            self.sap({"k1": "done", "k2": "ignored", "k3": "in_progress"})
        self.assertEqual(len(calls), 1, "複数キーの更新は1回の save_action_status にまとめる想定")
        self.assertEqual(set(calls[0]), {"k1", "k2", "k3"})

    def test_lock_is_released_after_success(self):
        self.sap({"k": "done"})
        self.assertTrue(lock_is_free())


class TestSetActionProgressRejects(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def sap(self, d):
        return oto().set_action_progress(d)

    def seed(self):
        write_json(STATUS_PATH, {"k1": make_status("not_started", "high", "c"), "k2": make_status("done")})
        return file_state(STATUS_PATH)

    def test_invalid_progress_raises_value_error_and_writes_nothing(self):
        bad_values = ("finished", "DONE", "Done", "done ", " done", "", "not started", "in-progress",
                      "completed", None, 1, 0, True, ["done"], {"progress": "done"})
        for bad in bad_values:
            with self.subTest(progress=bad):
                before = self.seed()
                with self.assertRaises(ValueError):
                    self.sap({"k1": bad})
                self.assertEqual(file_state(STATUS_PATH), before, "不正なprogressでファイルが変わった")
                self.assertTrue(lock_is_free())

    def test_invalid_progress_does_not_create_missing_file(self):
        with self.assertRaises(ValueError):
            self.sap({"k1": "bogus"})
        self.assertFalse(os.path.exists(STATUS_PATH))

    def test_one_invalid_value_blocks_the_whole_batch(self):
        before = self.seed()
        with self.assertRaises(ValueError):
            self.sap({"k1": "done", "k2": "ignored", "k3": "bogus"})
        self.assertEqual(file_state(STATUS_PATH), before)
        with self.assertRaises(ValueError):
            self.sap({"k3": "bogus", "k1": "done"})          # 不正値が先頭でも末尾でも
        self.assertEqual(file_state(STATUS_PATH), before)

    def test_invalid_progress_does_not_call_save(self):
        self.seed()
        with mock.patch.object(oto(), "save_action_status") as save:
            with self.assertRaises(ValueError):
                self.sap({"k1": "bogus"})
        save.assert_not_called()

    def test_corrupt_json_raises_and_file_is_left_untouched(self):
        corrupt = ["{broken", "{", "not json at all", '{"a": ', '{"a": 1,}', "\x00\x01\x02", "{'a': 1}"]
        for raw in corrupt:
            with self.subTest(raw=raw):
                write_text(STATUS_PATH, raw)
                before = file_state(STATUS_PATH)
                with self.assertRaises(Exception):
                    self.sap({"k1": "done"})
                self.assertEqual(file_state(STATUS_PATH), before, "壊れたファイルを上書きした")
                self.assertTrue(lock_is_free(), "例外時にロックが解放されていない")

    def test_non_dict_json_raises_and_file_is_left_untouched(self):
        for raw in ("[]", "[1, 2]", '[{"k1": {}}]', '"string"', "123", "1.5", "null", "true", "false"):
            with self.subTest(raw=raw):
                write_text(STATUS_PATH, raw)
                before = file_state(STATUS_PATH)
                with self.assertRaises(Exception):
                    self.sap({"k1": "done"})
                self.assertEqual(file_state(STATUS_PATH), before, "dict以外のJSONを上書きした")
                self.assertTrue(lock_is_free())

    def test_non_utf8_file_raises_and_file_is_left_untouched(self):
        write_bytes(STATUS_PATH, b'{"k1": {"comment": "\xff\xfe\x80"}}')
        before = file_state(STATUS_PATH)
        with self.assertRaises(Exception):
            self.sap({"k1": "done"})
        self.assertEqual(file_state(STATUS_PATH), before)
        self.assertTrue(lock_is_free())

    def test_corrupt_file_does_not_call_save(self):
        write_text(STATUS_PATH, "{broken")
        with mock.patch.object(oto(), "save_action_status") as save:
            with self.assertRaises(Exception):
                self.sap({"k1": "done"})
        save.assert_not_called()

    def test_recovers_after_file_is_repaired(self):
        write_text(STATUS_PATH, "{broken")
        with self.assertRaises(Exception):
            self.sap({"k1": "done"})
        write_json(STATUS_PATH, {"k1": make_status("not_started")})
        self.assertEqual(self.sap({"k1": "done"}), {"k1": "not_started"})

    def test_zero_byte_file_is_treated_as_empty(self):
        write_bytes(STATUS_PATH, b"")
        res = self.sap({"k1": "done"})
        self.assertEqual(res, {"k1": None})
        self.assertEqual(read_json(STATUS_PATH)["k1"]["progress"], "done")

    def test_missing_file_and_dir_are_created(self):
        self.assertFalse(os.path.exists("json"))
        res = self.sap({"k1": "ignored"})
        self.assertEqual(res, {"k1": None})
        self.assertEqual(read_json(STATUS_PATH)["k1"]["progress"], "ignored")

    def test_missing_file_but_dir_exists(self):
        os.makedirs("json")
        self.assertEqual(self.sap({"k1": "done"}), {"k1": None})
        self.assertTrue(os.path.isfile(STATUS_PATH))

    def test_empty_key_is_ignored(self):
        initial = {"k1": make_status("not_started")}
        write_json(STATUS_PATH, initial)
        self.assertEqual(self.sap({"": "done"}), {})
        self.assertEqual(read_json(STATUS_PATH), initial)
        self.assertNotIn("", read_json(STATUS_PATH))

    def test_empty_key_is_ignored_but_other_keys_are_applied(self):
        write_json(STATUS_PATH, {"k1": make_status("not_started")})
        res = self.sap({"": "done", "k1": "done"})
        self.assertEqual(res, {"k1": "not_started"})
        data = read_json(STATUS_PATH)
        self.assertNotIn("", data)
        self.assertEqual(data["k1"]["progress"], "done")

    def test_empty_key_only_with_missing_file_creates_no_entry(self):
        res = self.sap({"": "done"})
        self.assertEqual(res, {})
        if os.path.exists(STATUS_PATH):
            self.assertEqual(read_json(STATUS_PATH), {})


class TestSetActionProgressLocking(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_blocks_while_action_status_lock_is_held(self):
        # 仕様: HTTPハンドラ /update_action_status と同じ action_status_lock を使う
        write_json(STATUS_PATH, {"k1": make_status("not_started")})
        lock = oto().action_status_lock
        done = threading.Event()
        errors = []

        def worker():
            try:
                oto().set_action_progress({"k1": "done"})
            except BaseException as e:      # noqa: BLE001
                errors.append(e)
            finally:
                done.set()

        lock.acquire()
        released = False
        try:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            self.assertFalse(done.wait(0.4), "ロック保持中に set_action_progress が進んだ (別のロックを使っている?)")
            self.assertEqual(read_json(STATUS_PATH)["k1"]["progress"], "not_started")
            lock.release()
            released = True
            self.assertTrue(done.wait(5), "ロック解放後も完了しない")
        finally:
            if not released:
                lock.release()
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(read_json(STATUS_PATH)["k1"]["progress"], "done")

    def test_reads_inside_the_lock_so_external_update_is_not_lost(self):
        # ロックを持つ側が書換え中 (読込→更新→保存) に set_action_progress が割り込まないこと
        write_json(STATUS_PATH, {"k1": make_status("not_started")})
        lock = oto().action_status_lock
        started = threading.Event()

        def worker():
            started.set()
            oto().set_action_progress({"k2": "done"})

        with lock:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            started.wait(2)
            time.sleep(0.2)
            data = oto().load_action_status()
            data["k1"]["priority"] = "top"
            oto().save_action_status(data)
        t.join(5)
        final = read_json(STATUS_PATH)
        self.assertEqual(final["k1"]["priority"], "top")
        self.assertEqual(final["k2"]["progress"], "done")


class TestSpecGapSetActionProgress(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_updated_at_uses_the_same_format_as_the_http_handler(self):
        # 仕様は "ISO" とだけ記載。既存ハンドラは '%Y-%m-%dT%H:%M:%S' (秒まで・タイムゾーン無し)
        oto().set_action_progress({"k1": "done"})
        v = read_json(STATUS_PATH)["k1"]["updated_at"]
        self.assertRegex(v, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_previous_is_none_or_not_started_when_entry_has_no_progress_field(self):
        # 仕様: 「更新前のprogress（エントリ無し=None）」。progressキーだけ無いエントリは未記載
        write_json(STATUS_PATH, {"k1": {"priority": "high", "comment": "x"}})
        res = oto().set_action_progress({"k1": "done"})
        self.assertIn(res["k1"], (None, "not_started"))
        e = read_json(STATUS_PATH)["k1"]
        self.assertEqual(e["progress"], "done")
        self.assertEqual(e["priority"], "high")
        self.assertEqual(e["comment"], "x")

    def test_whitespace_only_key_does_not_create_entry(self):
        # 仕様は「空文字 → 無視」。HTTPハンドラは strip() 後に空なら拒否する → 空白のみも作らないのが自然
        write_json(STATUS_PATH, {"k1": make_status("not_started")})
        try:
            oto().set_action_progress({"   ": "done"})
        except Exception:                      # noqa: BLE001  (拒否でも可)
            pass
        self.assertNotIn("   ", read_json(STATUS_PATH))

    def test_accepts_any_mapping_iteration_order(self):
        from collections import OrderedDict
        res = oto().set_action_progress(OrderedDict([("b", "done"), ("a", "ignored")]))
        self.assertEqual(res, {"a": None, "b": None})


# ============================================================
# 8. save_action_last_run
# ============================================================
class TestSaveActionLastRun(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def save(self, *a, **k):
        return oto().save_action_last_run(*a, **k)

    def test_creates_dir_and_file_with_exact_format(self):
        self.assertFalse(os.path.exists("json"))
        res = self.save(7, "1週間", now=datetime(2026, 10, 4, 9, 30, 15))
        self.assertIsNone(res)
        self.assertEqual(read_json(LAST_RUN_PATH),
                         {"finished_at": "2026-10-04T09:30:15", "days": 7, "period_label": "1週間"})

    def test_microseconds_are_dropped(self):
        self.save(7, "1週間", now=datetime(2026, 10, 4, 9, 30, 15, 999999))
        self.assertEqual(read_json(LAST_RUN_PATH)["finished_at"], "2026-10-04T09:30:15")

    def test_zero_padding_of_all_fields(self):
        self.save(0, "24H", now=datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(read_json(LAST_RUN_PATH),
                         {"finished_at": "2026-01-02T03:04:05", "days": 0, "period_label": "24H"})

    def test_now_none_uses_current_time(self):
        before = datetime.now().replace(microsecond=0)
        self.save(14, "2週間")
        after = datetime.now()
        d = read_json(LAST_RUN_PATH)
        ts = datetime.strptime(d["finished_at"], "%Y-%m-%dT%H:%M:%S")
        self.assertLessEqual(before - timedelta(seconds=1), ts)
        self.assertLessEqual(ts, after + timedelta(seconds=1))
        self.assertEqual(d["days"], 14)
        self.assertEqual(d["period_label"], "2週間")

    def test_days_is_stored_as_int(self):
        self.save(30, "1ヶ月", now=datetime(2026, 10, 4, 9, 0, 0))
        d = read_json(LAST_RUN_PATH)
        self.assertIsInstance(d["days"], int)
        self.assertNotIsInstance(d["days"], bool)

    def test_overwrites_previous_record(self):
        self.save(7, "1週間", now=datetime(2026, 10, 3, 9, 0, 0))
        self.save(3, "3日間", now=datetime(2026, 10, 4, 10, 0, 0))
        self.assertEqual(read_json(LAST_RUN_PATH),
                         {"finished_at": "2026-10-04T10:00:00", "days": 3, "period_label": "3日間"})

    def test_no_tmp_file_remains(self):
        for i in range(5):
            self.save(7, "1週間", now=datetime(2026, 10, 4, 9, 0, i))
        self.assertEqual(sorted(os.listdir("json")), ["action_last_run.json"])
        for dirpath, _d, files in os.walk("."):
            for fn in files:
                self.assertFalse(fn.endswith(".tmp"), f"一時ファイルが残っている: {dirpath}/{fn}")

    def test_label_special_characters_roundtrip(self):
        for label in ("対象期間: 1週間 / 自分宛て(To/With/Cc)", 'quote"and\\backslash', "改行\nあり", "🙂 emoji", ""):
            with self.subTest(label=label):
                self.save(7, label, now=datetime(2026, 10, 4, 9, 0, 0))
                raw = read_bytes(LAST_RUN_PATH).decode("utf-8")            # UTF-8
                self.assertEqual(json.loads(raw)["period_label"], label)

    def test_load_returns_what_save_wrote(self):
        self.save(7, "1週間", now=datetime(2026, 10, 4, 9, 30, 15))
        d = oto().load_action_last_run()
        self.assertEqual(d["finished_at"], "2026-10-04T09:30:15")
        self.assertIsInstance(d["finished_at"], str)
        self.assertEqual(d["days"], 7)
        self.assertEqual(d["period_label"], "1週間")

    def test_failed_replace_keeps_old_content(self):
        # 仕様: .tmp に書いて os.replace (原子的)。replace が失敗しても旧ファイルは壊れない
        self.save(7, "1週間", now=datetime(2026, 10, 3, 9, 0, 0))
        old = read_json(LAST_RUN_PATH)
        with mock.patch("os.replace", side_effect=OSError("boom")):
            try:
                self.save(3, "3日間", now=datetime(2026, 10, 4, 9, 0, 0))
            except OSError:
                pass
        self.assertEqual(read_json(LAST_RUN_PATH), old)

    def test_failed_serialization_never_leaves_a_corrupt_file(self):
        # 途中で失敗しても (シリアライズ不能な値)、最終ファイルが壊れた状態で残らないこと
        self.save(7, "1週間", now=datetime(2026, 10, 3, 9, 0, 0))
        try:
            self.save(3, object(), now=datetime(2026, 10, 4, 9, 0, 0))
        except Exception:                                  # noqa: BLE001
            pass
        self.assertIsNotNone(oto().load_action_last_run(), "壊れたファイルが残った (非原子的な書込?)")
        # ファイルが無い状態から失敗しても、壊れたファイルを作らない (別の空ディレクトリで)
        with tempdir_cwd():
            try:
                self.save(3, object(), now=datetime(2026, 10, 4, 9, 0, 0))
            except Exception:                              # noqa: BLE001
                pass
            if os.path.exists(LAST_RUN_PATH):
                self.assertIsNotNone(oto().load_action_last_run(), "失敗後に壊れたファイルが残った")

    @unittest.skipIf(sys.platform.startswith("win"), "Windowsは読込中のreplaceがPermissionErrorになり得るため対象外")
    def test_readers_never_see_a_partial_file_while_writing(self):
        # 書き手1 / 読み手2。原子的ならデコード不能な中間状態は見えない
        self.save(7, "1週間", now=datetime(2026, 10, 4, 9, 0, 0))
        stop = threading.Event()
        bad = []

        def reader():
            while not stop.is_set():
                if oto().load_action_last_run() is None:
                    bad.append("None")

        readers = [threading.Thread(target=reader, daemon=True) for _ in range(2)]
        for r in readers:
            r.start()
        try:
            for i in range(300):
                self.save(7, "1週間" * (1 + i % 5), now=datetime(2026, 10, 4, 9, 0, i % 60))
        finally:
            stop.set()
            for r in readers:
                r.join(5)
        self.assertEqual(bad, [], "書込み中に読むと壊れた/空のファイルが見えた (非原子的)")


# ============================================================
# 9. load_action_last_run
# ============================================================
class TestLoadActionLastRun(unittest.TestCase):
    GOOD = {"finished_at": "2026-10-04T09:30:15", "days": 7, "period_label": "1週間"}

    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def load(self):
        return oto().load_action_last_run()

    def test_missing_file_is_none(self):
        self.assertIsNone(self.load())

    def test_missing_file_creates_nothing(self):
        # 読み取り専用: ファイルが無くても json/ ディレクトリ等を作らない
        self.assertIsNone(self.load())
        self.assertEqual(os.listdir("."), [])

    def test_valid_file_returns_dict_with_string_finished_at(self):
        write_json(LAST_RUN_PATH, self.GOOD)
        d = self.load()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["finished_at"], "2026-10-04T09:30:15")
        self.assertIsInstance(d["finished_at"], str)
        self.assertEqual(d["days"], 7)
        self.assertEqual(d["period_label"], "1週間")

    def test_invalid_json_is_none(self):
        for raw in ("{broken", "{", "garbage", '{"finished_at": ', "\x00\x01"):
            with self.subTest(raw=raw):
                write_text(LAST_RUN_PATH, raw)
                self.assertIsNone(self.load())

    def test_zero_byte_and_whitespace_files_are_none(self):
        for raw in (b"", b" \n\t "):
            with self.subTest(raw=raw):
                write_bytes(LAST_RUN_PATH, raw)
                self.assertIsNone(self.load())

    def test_non_dict_json_is_none(self):
        for raw in ("[]", "[1]", '"x"', "123", "null", "true", "[" + json.dumps(self.GOOD) + "]"):
            with self.subTest(raw=raw):
                write_text(LAST_RUN_PATH, raw)
                self.assertIsNone(self.load())

    def test_missing_finished_at_is_none(self):
        # finished_at が必須であることだけは仕様から確定 (「finished_at がパース不可 → None」)
        d = dict(self.GOOD)
        del d["finished_at"]
        write_json(LAST_RUN_PATH, d)
        self.assertIsNone(self.load())
        write_json(LAST_RUN_PATH, {})
        self.assertIsNone(self.load())

    def test_unparseable_finished_at_is_none(self):
        for bad in ("garbage", "", None, 12345, "2026-13-45T25:61:61", "yesterday", [], {},
                    "2026-10-04Tabc", "2026/10/04 09:30:15"):
            d = dict(self.GOOD)
            d["finished_at"] = bad
            with self.subTest(finished_at=bad):
                write_json(LAST_RUN_PATH, d)
                self.assertIsNone(self.load())

    def test_non_utf8_bytes_are_none_not_exception(self):
        write_bytes(LAST_RUN_PATH, b'{"finished_at": "\xff\xfe", "days": 7, "period_label": "x"}')
        self.assertIsNone(self.load())

    def test_directory_at_path_is_none(self):
        os.makedirs(LAST_RUN_PATH)
        self.assertIsNone(self.load())

    def test_extra_keys_do_not_invalidate(self):
        d = dict(self.GOOD)
        d["note"] = "手編集"
        write_json(LAST_RUN_PATH, d)
        self.assertIsNotNone(self.load())

    def test_does_not_modify_file(self):
        write_json(LAST_RUN_PATH, self.GOOD)
        before = file_state(LAST_RUN_PATH)
        self.load()
        self.assertEqual(file_state(LAST_RUN_PATH), before)


class TestSpecGapLoadActionLastRun(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_missing_days_is_none(self):
        # 仕様: 「必須キー欠落 → None」。どのキーが必須かは未記載。
        # days は snapshot の horizon 計算に必須なので、欠落なら None が自然。
        d = {"finished_at": "2026-10-04T09:30:15", "period_label": "1週間"}
        write_json(LAST_RUN_PATH, d)
        self.assertIsNone(oto().load_action_last_run())

    def test_missing_period_label_is_none_or_filled_with_a_string(self):
        # period_label は表示用。欠落を None にするか、空文字等で補って返すかは未記載 (どちらも妥当)。
        # どちらでも「返すなら period_label が str」であること。
        d = {"finished_at": "2026-10-04T09:30:15", "days": 7}
        write_json(LAST_RUN_PATH, d)
        res = oto().load_action_last_run()
        self.assertTrue(res is None or isinstance(res.get("period_label"), str))

    def test_wrong_type_of_days_or_label_does_not_raise(self):
        # 仕様は finished_at のパース可否しか書いていない。days/period_label の型崩れ
        # (手編集・旧版ファイル) は None を返すか、そのまま返すかが未記載 → 例外にしないことだけ確認
        for patch in ({"days": "abc"}, {"days": None}, {"days": [7]}, {"period_label": None}, {"period_label": 5}):
            d = {"finished_at": "2026-10-04T09:30:15", "days": 7, "period_label": "1週間"}
            d.update(patch)
            with self.subTest(patch=patch):
                write_json(LAST_RUN_PATH, d)
                res = oto().load_action_last_run()
                self.assertTrue(res is None or isinstance(res, dict))

    def test_timezone_aware_finished_at_is_none_or_harmless(self):
        # "+09:00" 付きは naive との引き算で TypeError になり得る。load が None にするか、
        # 通しても build_decision_heading が落ちないこと
        write_json(LAST_RUN_PATH, {"finished_at": "2026-10-04T09:30:15+09:00", "days": 7, "period_label": "x"})
        res = oto().load_action_last_run()
        if res is not None:
            h = oto().build_decision_heading("B", 1, res, 0, datetime(2026, 10, 4, 12, 0, 0))
            self.assertIsInstance(h, str)

    def test_space_separated_timestamp_is_handled_without_exception(self):
        write_json(LAST_RUN_PATH, {"finished_at": "2026-10-04 09:30:15", "days": 7, "period_label": "x"})
        res = oto().load_action_last_run()
        self.assertTrue(res is None or isinstance(res, dict))


# ローカルタイムゾーンを JST(+9) / EST(-5) にして、updated_at / finished_at が「ローカル時刻」であることを再確認する
_loader.make_tz_variants(globals(), [TestSetActionProgressNormal, TestSaveActionLastRun])


if __name__ == "__main__":
    unittest.main(verbosity=2)
