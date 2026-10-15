# -*- coding: utf-8 -*-
"""A1 判断待ち: 並行実行テスト。

(a) set_action_progress と HTTPハンドラ相当 (/update_action_status と同じ手順 =
    action_status_lock 内で load_action_status → 更新 → save_action_status) を並行実行しても
    更新が失われない。snapshot が書込み途中の中間状態を読まない。
(b) 既知の潜在競合の「記録テスト」: MailSummarizer.summarize_action_dashboard の旧キー移行
    (save_action_status(action_statuses) をロック外で、古い読込結果のまま書き戻す) が、
    並行する更新を消してしまう。@unittest.expectedFailure で「現状は再現する」ことを固定する。
    実運用では 競合の窓は短く、旧キー(文言ベース)→新キー(添字ベース)の移行が発生した回に限って稀に起きる
    (テストは窓を決定的に開けて再現している)。
    (修正は越智さん承認後。直ったら expectedFailure が「想定外の成功」になるので、デコレータを外す)

仕様書 (A1_SPEC.md) だけを根拠に、実装を見ずに書いている。
"""
import json
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

import _loader
from _loader import (
    CACHE_PATH, LAST_RUN_PATH, NOW, STATUS_PATH, make_action, make_cache, make_last_run, make_status,
    make_thread, read_json, tempdir_cwd, ts_ago, write_json,
)

JOIN_TIMEOUT = 60


def oto():
    return _loader.load()


def lock_is_free():
    lock = oto().action_status_lock
    got = lock.acquire(timeout=2)
    if got:
        lock.release()
    return got


def http_style_update(key, **fields):
    """/update_action_status と同じ手順 (ロック内で 読込 → setdefault → 更新 → 保存)。"""
    mod = oto()
    with mod.action_status_lock:
        statuses = mod.load_action_status()
        entry = statuses.setdefault(key, {"progress": "not_started", "priority": "", "comment": ""})
        for k, v in fields.items():
            entry[k] = v
        entry["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        statuses[key] = entry
        mod.save_action_status(statuses)


def run_threads(targets, timeout=JOIN_TIMEOUT):
    """targets: 引数なしの callable のリスト。全員を Barrier で同時スタートし、例外を集めて返す。
    返り値: (errors, alive_count)"""
    barrier = threading.Barrier(len(targets))
    errors = []

    def wrap(fn):
        def run():
            try:
                barrier.wait(10)
                fn()
            except BaseException as e:      # noqa: BLE001
                errors.append(repr(e))
        return run

    threads = [threading.Thread(target=wrap(fn), daemon=True) for fn in targets]
    for t in threads:
        t.start()
    deadline = time.time() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.time()))
    return errors, sum(t.is_alive() for t in threads)


class ConcBase(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


# ============================================================
# (a) 更新が失われない
# ============================================================
class TestNoLostUpdates(ConcBase):
    N_THREADS = 4
    PER_THREAD = 15

    def test_set_action_progress_and_http_style_updates_on_different_keys(self):
        mod = oto()
        write_json(STATUS_PATH, {f"S{i:02d}": make_status("not_started", "", "orig") for i in range(20)})
        tasks, p_keys, h_keys = [], [], []

        def progress_worker(t):
            def run():
                for i in range(self.PER_THREAD):
                    mod.set_action_progress({f"P{t}_{i:02d}": "done"})
            return run

        def http_worker(t):
            def run():
                for i in range(self.PER_THREAD):
                    http_style_update(f"H{t}_{i:02d}", priority="high", comment=f"h{t}_{i}")
            return run

        for t in range(self.N_THREADS):
            tasks.append(progress_worker(t))
            tasks.append(http_worker(t))
            p_keys += [f"P{t}_{i:02d}" for i in range(self.PER_THREAD)]
            h_keys += [f"H{t}_{i:02d}" for i in range(self.PER_THREAD)]
        errors, alive = run_threads(tasks)
        self.assertEqual(errors, [])
        self.assertEqual(alive, 0, "デッドロック? (スレッドが終わらない)")
        final = read_json(STATUS_PATH)
        missing = [k for k in p_keys + h_keys if k not in final]
        self.assertEqual(missing, [], f"更新が失われた (消えたキー {len(missing)}件)")
        self.assertTrue(all(final[k]["progress"] == "done" for k in p_keys))
        self.assertTrue(all(final[k]["priority"] == "high" and final[k]["progress"] == "not_started"
                            for k in h_keys))
        self.assertTrue(all(final[f"S{i:02d}"]["comment"] == "orig" for i in range(20)))
        self.assertEqual(len(final), 20 + len(p_keys) + len(h_keys))
        self.assertTrue(lock_is_free())

    def test_both_kinds_of_updates_on_the_same_keys_both_survive(self):
        # 同じキーに対し、片方は progress (set_action_progress)、もう片方は priority/comment (HTTP相当)
        mod = oto()
        keys = [f"K{i:02d}" for i in range(25)]
        write_json(STATUS_PATH, {k: make_status("not_started", "", "") for k in keys})

        def a():
            for k in keys:
                mod.set_action_progress({k: "in_progress"})

        def b():
            for i, k in enumerate(keys):
                http_style_update(k, priority="top", comment=f"c{i}")

        def c():
            for k in keys:
                mod.set_action_progress({k: "in_progress"})

        errors, alive = run_threads([a, b, c, b])
        self.assertEqual(errors, [])
        self.assertEqual(alive, 0)
        final = read_json(STATUS_PATH)
        for i, k in enumerate(keys):
            with self.subTest(key=k):
                self.assertEqual(final[k]["progress"], "in_progress")
                self.assertEqual(final[k]["priority"], "top")
                self.assertEqual(final[k]["comment"], f"c{i}")

    def test_many_threads_updating_the_same_key_keep_file_valid(self):
        mod = oto()
        write_json(STATUS_PATH, {"K": make_status("not_started", "high", "keep")})
        values = ["done", "ignored", "in_progress", "not_started"]
        errors, alive = run_threads(
            [lambda v=v: [mod.set_action_progress({"K": v}) for _ in range(30)] for v in values] * 2)
        self.assertEqual(errors, [])
        self.assertEqual(alive, 0)
        final = read_json(STATUS_PATH)                       # 壊れていないこと
        self.assertIn(final["K"]["progress"], values)
        self.assertEqual(final["K"]["priority"], "high")
        self.assertEqual(final["K"]["comment"], "keep")

    def test_real_http_handler_and_set_action_progress_do_not_lose_updates(self):
        # 実際の OutlookRequestHandler (/update_action_status) を localhost で起動して並行させる
        from http.server import ThreadingHTTPServer
        mod = oto()
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), mod.OutlookRequestHandler)
        except OSError as e:
            self.skipTest(f"localhost にバインドできない: {e}")
        port = server.server_address[1]
        srv = threading.Thread(target=server.serve_forever, daemon=True)
        srv.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # プロキシ環境変数を無視

        def post(key, **fields):
            body = json.dumps({"action_key": key, **fields}).encode("utf-8")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/update_action_status", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(req, timeout=20) as resp:
                self.assertEqual(resp.status, 200)
                resp.read()

        n = 12
        write_json(STATUS_PATH, {})

        def http_worker(t):
            return lambda: [post(f"H{t}_{i}", priority="high") for i in range(n)]

        def progress_worker(t):
            return lambda: [mod.set_action_progress({f"P{t}_{i}": "done"}) for i in range(n)]

        def shared_http():
            for i in range(n):
                post(f"S{i}", priority="top")

        def shared_progress():
            for i in range(n):
                mod.set_action_progress({f"S{i}": "ignored"})

        tasks = [http_worker(0), http_worker(1), progress_worker(0), progress_worker(1), shared_http,
                 shared_progress]
        errors, alive = run_threads(tasks)
        self.assertEqual(errors, [])
        self.assertEqual(alive, 0)
        final = read_json(STATUS_PATH)
        for t in (0, 1):
            for i in range(n):
                self.assertEqual(final[f"H{t}_{i}"]["priority"], "high")
                self.assertEqual(final[f"P{t}_{i}"]["progress"], "done")
        for i in range(n):
            self.assertEqual(final[f"S{i}"]["priority"], "top")
            self.assertEqual(final[f"S{i}"]["progress"], "ignored")
        self.assertEqual(len(final), 2 * n + 2 * n + n)


class TestSnapshotUnderConcurrentWrites(ConcBase):
    def test_snapshot_never_reads_a_partial_or_empty_status_file(self):
        # 書込み (トランケート→書込み) の最中に読むと {} になり、完了済み案件が「復活」して見える。
        # snapshot が action_status_lock を取っていれば、件数は単調に減るだけ (一度減ったら戻らない)。
        mod = oto()
        n = 60
        cids = [f"K{i:02d}" for i in range(n)]
        # 仕様変更(第2回): done は updated_at >= latest_ts のときだけ除外 (新着で再浮上)。set_action_progress は
        # 実時計で updated_at を書くので、スレッドの latest_ts も実時計基準 (1時間前) にして「完了=除外」にする
        now_real = datetime.now()
        latest = int(time.time()) - 3600
        write_json(CACHE_PATH, make_cache({c: make_thread(latest_ts=latest) for c in cids}))
        keys = {c: mod.make_action_key_by_index(c, 0) for c in cids}
        write_json(STATUS_PATH, {keys[c]: make_status("not_started", "high", "c" * 40) for c in cids})
        write_json(LAST_RUN_PATH, make_last_run(now_real - timedelta(minutes=30)))

        stop = threading.Event()
        seen, errors = [], []

        def writer(chunk):
            def run():
                for c in chunk:
                    mod.set_action_progress({keys[c]: "done"})
            return run

        def reader():
            try:
                while not stop.is_set():
                    s = mod.build_action_decision_snapshot(now=now_real)
                    seen.append(s["pending_count"])
                    time.sleep(0)
                seen.append(mod.build_action_decision_snapshot(now=now_real)["pending_count"])
            except BaseException as e:      # noqa: BLE001
                errors.append(repr(e))

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        chunks = [cids[i::4] for i in range(4)]
        w_errors, alive = run_threads([writer(ch) for ch in chunks])
        stop.set()
        rt.join(30)
        self.assertEqual(w_errors, [])
        self.assertEqual(alive, 0)
        self.assertEqual(errors, [])
        self.assertTrue(seen, "snapshot が1回も完了しなかった")
        self.assertTrue(all(isinstance(x, int) for x in seen), f"pending_count が None になった: {seen}")
        for a, b in zip(seen, seen[1:]):
            self.assertGreaterEqual(a, b, f"件数が増えた = 書込み途中の状態を読んだ疑い: {seen}")
        self.assertEqual(seen[-1], 0)


# ============================================================
# (b) 既知の潜在競合 (記録テスト)
# ============================================================
class TestKnownLatentRaceInSummarizeActionDashboard(ConcBase):
    """MailSummarizer.summarize_action_dashboard は、旧キー(文言ベース)から新キー(添字ベース)への
    移行が起きたとき、末尾で save_action_status(action_statuses) をロック外で呼ぶ。
    action_statuses は関数の途中で読んだ古いスナップショットのため、その間に別スレッド
    (HTTPハンドラ / A1の set_action_progress) が書いた更新を巻き戻して消す。

    決定的な再現方法: load_action_status をラップし、「最初の読込の直後」に別スレッドで更新を実行する。
    (同スレッドで実行しても再現するが、将来この関数がロック内で読むように直った場合に
     非再入ロックで固まらないよう、別スレッド+join(タイムアウト付き) にしている)
    """

    CID = "C-LEGACY"
    OTHER = "OTHER-KEY"
    INJECT_JOIN = 2.0

    def prepare(self):
        mod = oto()
        threads = {self.CID: make_thread(
            [make_action(owner="Nakai", target="あなた", action="承認をお願いします")], latest_ts=ts_ago(2))}
        write_json(CACHE_PATH, make_cache(threads))
        self.legacy = mod.make_action_key(self.CID, "Nakai", "承認をお願いします")
        self.new_key = mod.make_action_key_by_index(self.CID, 0)
        write_json(STATUS_PATH, {
            self.legacy: make_status("in_progress", "high", "legacy"),
            self.OTHER: make_status("not_started", "", "mine"),
        })

    def run_scenario(self, injector):
        """summarize_action_dashboard({}, expand_from_cache=True) を呼び、最初の load_action_status の直後に
        injector() を別スレッドで実行する。返り値: (戻り値, 最終の action_status.json, info)"""
        mod = oto()
        summ = mod.MailSummarizer.__new__(mod.MailSummarizer)
        orig = mod.load_action_status
        info = {"calls": 0, "thread": None, "error": None}

        def runner():
            try:
                injector()
            except BaseException as e:      # noqa: BLE001
                info["error"] = repr(e)

        def wrapped(*a, **k):
            result = orig(*a, **k)
            info["calls"] += 1
            if info["calls"] == 1:
                t = threading.Thread(target=runner, daemon=True)
                info["thread"] = t
                t.start()
                t.join(self.INJECT_JOIN)
            return result

        with mock.patch.object(mod, "load_action_status", wrapped):
            res = summ.summarize_action_dashboard({}, expand_from_cache=True)
        if info["thread"] is not None:
            info["thread"].join(10)
        return res, read_json(STATUS_PATH), info

    def via_set_action_progress(self):
        oto().set_action_progress({self.OTHER: "done"})

    def via_http_style(self):
        http_style_update(self.OTHER, priority="top")

    # ---- シナリオ自体が成立していること (常に通る) ------------------------
    def test_scenario_without_concurrent_writer_saves_the_migration(self):
        self.prepare()
        res, final, info = self.run_scenario(lambda: None)
        self.assertEqual(info["calls"], 1)
        self.assertIn(self.new_key, final, "旧キー→新キーの移行が保存されていない (シナリオの前提が崩れている)")
        self.assertEqual(final[self.new_key]["progress"], "in_progress")
        self.assertEqual(final[self.new_key]["comment"], "legacy")
        self.assertEqual(final[self.OTHER]["progress"], "not_started")
        self.assertEqual(len(res["action_cards"]), 1)

    def test_scenario_preconditions_hold_with_set_action_progress(self):
        self.prepare()
        res, final, info = self.run_scenario(self.via_set_action_progress)
        self.assertIsNone(info["error"], f"注入した更新が失敗: {info['error']}")
        self.assertIsNotNone(info["thread"])
        self.assertFalse(info["thread"].is_alive(), "注入した更新が終わらない")
        self.assertIn(self.new_key, final, "移行が保存されていない (シナリオの前提が崩れている)")
        self.assertEqual(final[self.new_key]["progress"], "in_progress")
        # 注入した更新が「残る(競合が直った)」か「消える(競合が再現)」のどちらかであること
        self.assertIn(final[self.OTHER]["progress"], ("done", "not_started"))
        self.assertTrue(lock_is_free())

    def test_scenario_preconditions_hold_with_http_style_update(self):
        self.prepare()
        res, final, info = self.run_scenario(self.via_http_style)
        self.assertIsNone(info["error"], f"注入した更新が失敗: {info['error']}")
        self.assertFalse(info["thread"].is_alive())
        self.assertIn(self.new_key, final)
        self.assertIn(final[self.OTHER]["priority"], ("top", ""))
        self.assertTrue(lock_is_free())

    # ---- 既知の競合 (現状は更新が失われる = 期待された失敗) ----------------
    @unittest.expectedFailure
    def test_known_race_set_action_progress_update_survives_migration(self):
        """既知の潜在競合。修正は越智さん承認後。

        旧キー移行 (statuses_migrated) の最後の save_action_status(action_statuses) が、
        ロック外で古いスナップショットを書き戻し、直前に set_action_progress が書いた
        OTHER の progress="done" を "not_started" に戻してしまう。
        (実運用では窓は短く、旧キー移行が発生した回に限り稀に起きる。テストは窓を決定的に開けて再現)
        「更新が残ること」をassertする。現状は失われるので expectedFailure。
        """
        self.prepare()
        res, final, info = self.run_scenario(self.via_set_action_progress)
        self.assertEqual(final[self.OTHER]["progress"], "done",
                         "並行する set_action_progress の更新が summarize_action_dashboard に巻き戻された")

    @unittest.expectedFailure
    def test_known_race_http_handler_update_survives_migration(self):
        """既知の潜在競合。修正は越智さん承認後。

        上と同じ競合を、A1より前から存在する経路 (HTTPハンドラ /update_action_status 相当) で再現する。
        A1 が新しく作った競合ではなく、既存コードの競合に A1 の書込み経路が加わるだけであることの記録。
        (窓は短く、旧キー移行が発生した回に限り稀に起きる)
        """
        self.prepare()
        res, final, info = self.run_scenario(self.via_http_style)
        self.assertEqual(final[self.OTHER]["priority"], "top",
                         "並行するHTTPハンドラ相当の更新が summarize_action_dashboard に巻き戻された")


if __name__ == "__main__":
    unittest.main(verbosity=2)
