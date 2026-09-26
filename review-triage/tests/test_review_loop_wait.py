#!/usr/bin/env python3
"""作業側の待機スクリプト (review-triage/scripts/review-loop-wait.sh) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s review-triage/tests

一時ディレクトリを周回の置き場に見立て、スクリプトを subprocess で起動して、
ファイルを置いたときに返る終了コードと標準出力の 1 行を確かめる。
ファイルの様式と事象の正本は review-triage/skills/review-loop/references/loop-files.md。
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "review-loop-wait.sh"
)

RID = "20260926-1400-feat-x-1-code-review-opus"


def _write(path, text=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _set_mtime_ago(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


class WaitTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, name):
        return os.path.join(self.dir, name)

    def put_request(self, rid=RID):
        _write(self.path(f"review-request-{rid}.md"), "# 依頼文\n")

    def put_result(self, rid=RID):
        _write(self.path(f"review-{rid}.yaml"), f'run_id: "{rid}"\nfindings: []\n')

    def put_marker(self, status="ok", rid=RID):
        _write(self.path(f"delivered-{rid}.yaml"), f'id: "{rid}"\nstatus: {status}\n')

    def put_worker(self, state="idle", ago=0, pid=1):
        p = self.path("worker.yaml")
        _write(p, f"state: {state}\ncurrent_request: \"\"\npid: {pid}\n")
        if ago:
            _set_mtime_ago(p, ago)

    def run_wait(self, minutes="1", stale=None, actions=(), timeout=30, await_worker=False):
        """スクリプトを起動し、actions ((秒, 関数) の列) をその時刻に行い、終了を待つ。"""
        args = ["bash", _SCRIPT] + (["--await-worker"] if await_worker else []) + [self.dir, RID, str(minutes)]
        if stale is not None:
            args.append(str(stale))
        started = time.time()
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        timers = [threading.Timer(at, fn) for at, fn in actions]
        for t in timers:
            t.start()
        try:
            out, err = proc.communicate(timeout=timeout)
        finally:
            for t in timers:
                t.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        return proc.returncode, out.strip(), err, time.time() - started


class TestDelivered(WaitTestBase):
    def test_ok_marker_with_request_and_result_returns_zero(self):
        # 待っている間に 3 点 (印・依頼文・結果) が揃うと 0 で返る
        rc, out, err, _ = self.run_wait(
            actions=[(1, lambda: (self.put_request(), self.put_result(), self.put_marker("ok")))]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, f"delivered {RID}")

    def test_ok_marker_without_request_does_not_return(self):
        # status: ok の印だけで依頼文が無いときは返らない (3 点が揃うまで待つ)
        self.put_result()
        self.put_marker("ok")
        rc, out, _, _ = self.run_wait(minutes="0.1")
        self.assertEqual(rc, 124)
        self.assertEqual(out, "")

    def test_ok_marker_without_result_does_not_return(self):
        self.put_request()
        self.put_marker("ok")
        rc, _, _, _ = self.run_wait(minutes="0.1")
        self.assertEqual(rc, 124)

    def test_failed_marker_needs_only_request(self):
        # status: failed の印は結果が無くても、依頼文があれば 0 で返る (2 点一致)
        self.put_request()
        self.put_marker("failed")
        rc, out, err, elapsed = self.run_wait()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, f"delivered {RID}")
        self.assertLess(elapsed, 3)

    def test_temporary_name_is_ignored_until_renamed(self):
        # 一時名 (. で始まる名前) の印には反応せず、改名すると返る
        self.put_request()
        self.put_result()
        tmp = self.path(f".delivered-{RID}.yaml.tmp")
        _write(tmp, f'id: "{RID}"\nstatus: ok\n')
        rename_at = 6
        rc, out, err, elapsed = self.run_wait(
            actions=[(rename_at, lambda: os.rename(tmp, self.path(f"delivered-{RID}.yaml")))]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, f"delivered {RID}")
        self.assertGreaterEqual(elapsed, rename_at)

    def test_marker_of_other_identifier_is_ignored(self):
        other = "20260926-1300-feat-x-1-code-review-opus"
        self.put_request(other)
        self.put_marker("failed", other)
        rc, _, _, _ = self.run_wait(minutes="0.1")
        self.assertEqual(rc, 124)


class TestEnd(WaitTestBase):
    def test_end_returns_zero(self):
        _write(self.path("end"), "人間が置いた\n")
        rc, out, err, _ = self.run_wait()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "end")

    def test_marker_is_reported_before_end(self):
        # 同じ周期に印と end があれば、印を先に返す (作業側が印を取り込めるように)
        self.put_request()
        self.put_marker("failed")
        _write(self.path("end"), "")
        rc, out, _, _ = self.run_wait()
        self.assertEqual(rc, 0)
        self.assertEqual(out, f"delivered {RID}")


class TestWorker(WaitTestBase):
    def test_terminal_states_return_zero(self):
        for state in ("expired", "left", "unavailable"):
            with self.subTest(state=state):
                self.put_worker(state)
                rc, out, err, _ = self.run_wait()
                self.assertEqual(rc, 0, err)
                self.assertEqual(out, f"worker {state}")

    def test_stale_worker_returns_zero(self):
        # 更新時刻が停滞の秒数 (既定 30) より古ければ、状態に関わらず停滞として返る
        self.put_worker("reviewing", ago=31)
        rc, out, err, _ = self.run_wait()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "worker stale")

    def test_stale_seconds_argument(self):
        self.put_worker("idle", ago=11)
        rc, out, _, _ = self.run_wait(stale=10)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "worker stale")

    def test_fresh_reviewing_worker_does_not_return(self):
        # 更新時刻が新しければ reviewing でも返らない (ワーカーはレビュー中も更新時刻を進める)
        self.put_worker("reviewing")
        p = self.path("worker.yaml")
        rc, _, _, _ = self.run_wait(
            minutes="0.1", actions=[(3, lambda: os.utime(p, None))]
        )
        self.assertEqual(rc, 124)

    def test_missing_worker_is_not_stale_and_appearance_returns(self):
        # worker.yaml が無い間は停滞と判定せず、現れたら worker <state> で返る
        rc, out, err, elapsed = self.run_wait(actions=[(6, lambda: self.put_worker("idle"))])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "worker idle")
        self.assertGreaterEqual(elapsed, 6)

    def test_existing_idle_worker_does_not_return(self):
        # 起動時からある worker.yaml は、出現としては返さない
        self.put_worker("idle")
        p = self.path("worker.yaml")
        rc, _, _, _ = self.run_wait(
            minutes="0.1", actions=[(3, lambda: os.utime(p, None))]
        )
        self.assertEqual(rc, 124)

    def test_restarted_worker_returns_as_appearance(self):
        # 起動時にあった worker.yaml でも、pid が変われば新しいワーカーの出現として返す
        self.put_worker("idle", pid=100)
        rc, out, err, _ = self.run_wait(actions=[(1, lambda: self.put_worker("idle", pid=200))])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "worker idle")

    def test_unreadable_state_returns_invalid(self):
        _write(self.path("worker.yaml"), "pid: 1\n")
        rc, out, _, _ = self.run_wait()
        self.assertEqual(rc, 0)
        self.assertEqual(out, "worker invalid")


class TestAwaitWorker(WaitTestBase):
    """--await-worker: 起動時のワーカーは居ないものとして、新しいワーカーの出現を待つ。"""

    def test_terminal_state_at_start_is_not_an_event(self):
        for state in ("expired", "left", "unavailable"):
            with self.subTest(state=state):
                self.put_worker(state, pid=100)
                rc, _, _, _ = self.run_wait(minutes="0.1", await_worker=True)
                self.assertEqual(rc, 124)

    def test_stale_worker_at_start_is_not_an_event(self):
        self.put_worker("idle", ago=100, pid=100)
        rc, _, _, _ = self.run_wait(minutes="0.1", await_worker=True)
        self.assertEqual(rc, 124)

    def test_new_worker_returns(self):
        self.put_worker("expired", pid=100)
        rc, out, err, _ = self.run_wait(
            await_worker=True, actions=[(1, lambda: self.put_worker("idle", pid=200))]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "worker idle")

    def test_new_worker_that_fails_to_start_returns(self):
        self.put_worker("expired", pid=100)
        rc, out, _, _ = self.run_wait(
            await_worker=True, actions=[(1, lambda: self.put_worker("unavailable", pid=200))]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "worker unavailable")

    def test_marker_and_end_still_return(self):
        self.put_worker("expired", pid=100)
        self.put_request()
        self.put_marker("failed")
        rc, out, _, _ = self.run_wait(await_worker=True)
        self.assertEqual(rc, 0)
        self.assertEqual(out, f"delivered {RID}")


class TestDeadline(WaitTestBase):
    def test_nothing_returns_124(self):
        rc, out, _, elapsed = self.run_wait(minutes="0.1")
        self.assertEqual(rc, 124)
        self.assertEqual(out, "")
        self.assertGreaterEqual(elapsed, 5.5)
        self.assertLess(elapsed, 9)

    def test_file_placed_just_before_deadline_returns_zero(self):
        # 期限切れを宣言する前にもう 1 度確かめるので、締切の直前に置いたものは 0 で返る
        rc, out, err, _ = self.run_wait(
            minutes="0.1", actions=[(5.5, lambda: _write(self.path("end"), ""))]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "end")


class TestArguments(WaitTestBase):
    def test_bad_minutes_is_an_error(self):
        proc = subprocess.run(
            ["bash", _SCRIPT, self.dir, RID, "abc"], capture_output=True, text=True
        )
        self.assertNotIn(proc.returncode, (0, 124))
        self.assertIn("分", proc.stderr)

    def test_missing_dir_is_an_error(self):
        proc = subprocess.run(
            ["bash", _SCRIPT, self.path("nope"), RID, "1"], capture_output=True, text=True
        )
        self.assertNotIn(proc.returncode, (0, 124))


if __name__ == "__main__":
    unittest.main()
