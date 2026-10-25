"""待機 (poll) のテスト。CLI を子プロセスで動かし、偽の gh (tests/fake-gh) と固定データで終わる条件・終了コード・wait.pid を確かめる。
間隔と期限は分の小数で短くする。項目の合成は test_itemstate の補助を使う。"""

import json
import os
import signal
import subprocess
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _HERE)

from issue_dispatch import config, gh, observe, poll  # noqa: E402
from test_itemstate import (A, A1, A2, ASSIGN1, DECL1, LOGIN, M1, PR9, USER_ENTRY, W7, _go, _wait, gql_comment, items_data, mcomment,  # noqa: E402
                            node_of, pr_fixture, t, wcomment)
from test_project import FakeGhCase  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "observation.md")
META = {"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}}
A3 = f"{A}#3"
FAST = ["--interval", "0.002", "--minutes", "0.02"]   # 0.12 秒おきに 1.2 秒まで


def assigned_item3(nodes, extra=(), status=None, state=None, field=W7):
    """固定データの項目 3 を W-7 の割り当て中にする。"""
    node = node_of(nodes, 3)
    c = node["content"]
    c["assignees"]["nodes"] = [{"login": LOGIN}]
    if state:
        c["state"] = state
        if state == "CLOSED":
            c["timelineItems"]["nodes"].append({"__typename": "ClosedEvent", "createdAt": t(50), "stateReason": "COMPLETED", "closer": None})
    for fv in node["fieldValues"]["nodes"]:
        if fv and (fv.get("field") or {}).get("name") == "Agent session ID":
            fv["text"] = field
        if fv and (fv.get("field") or {}).get("name") == "Status" and status:
            fv["name"] = status
    c["comments"]["nodes"] += [gql_comment(x) for x in (ASSIGN1, *extra)]


class WaiterTest(unittest.TestCase):
    """Waiter の共通の処理 (子プロセスを使わない)。"""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.pid_path = os.path.join(self._tmp.name, "wait.pid")
        self.out = []

    def tearDown(self):
        self._tmp.cleanup()

    def _waiter(self, minutes=0.01, interval=0.0005):
        class Out:
            def write(inner, s):
                self.out.append(s)

            def flush(inner):
                pass
        return poll.Waiter(self.pid_path, M1, "wait", minutes, interval, out=Out())

    def test_result_line_and_pid_file(self):
        """最初の行は pid、終わりの行は poll の結果。終わるときに wait.pid を消す。"""
        calls = []

        def do_poll():
            calls.append(1)
            return (0, "diff status") if len(calls) == 2 else None
        code = self._waiter().run(do_poll)
        self.assertEqual((code, "".join(self.out)), (0, f"pid {os.getpid()}\ndiff status\n"))
        self.assertFalse(os.path.exists(self.pid_path))

    def test_stop_during_poll_discards_result(self):
        """読み取りの間に SIGTERM を受けたら、その読み取りの結果 (終わる条件) を捨てて stopped と 6 で終わる。"""
        w = self._waiter()

        def poll_then_stop():
            w.stopped = True
            return (0, "diff status")
        code = w.run(poll_then_stop)
        self.assertEqual((code, "".join(self.out)), (6, f"pid {os.getpid()}\nstopped {os.getpid()}\n"))

    def test_stop_previous_reports_alive_after_grace(self):
        """前の待機が待機時間の後も動いていれば alive を返し、起動は続ける (wait.pid は消す)。"""
        import signal as _signal
        holder = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])
        try:
            time.sleep(0.3)
            fake_command_entry = {"pid": holder.pid, "started_at": poll.process_start(holder.pid), "owner": M1, "wait": "wait"}
            original = poll.is_our_wait
            poll.is_our_wait = lambda entry: True
            try:
                with open(self.pid_path, "w", encoding="utf-8") as f:
                    json.dump(fake_command_entry, f)
                result = poll.stop_previous(self.pid_path, grace_seconds=0.3)
            finally:
                poll.is_our_wait = original
            self.assertEqual(result, {"stopped": holder.pid, "alive": True})
            self.assertFalse(os.path.exists(self.pid_path))
        finally:
            holder.kill()
            holder.wait()

    def test_timeout_checks_once_more_before_124(self):
        calls = []
        code = self._waiter(minutes=0.003, interval=0.001).run(lambda: calls.append(1))
        self.assertEqual((code, "".join(self.out)), (124, f"pid {os.getpid()}\n"))
        self.assertGreaterEqual(len(calls), 2, "期限切れを宣言する前にもう 1 度確かめる")

    def test_failures_by_kind(self):
        """認証切れは 8、ネットワークの失敗が 3 回続けば 4 (間に成功があれば数え直す)。"""
        self.assertEqual(self._waiter().run(lambda: ("failure", "auth")), 8)
        calls = []

        def flaky():
            calls.append(1)
            return None if len(calls) == 2 else ("failure", "network")
        self.assertEqual(self._waiter(minutes=0.05).run(flaky), 4)
        self.assertEqual(len(calls), 5, "成功 (2 回目) で数え直すので、4 で終わるのは 5 回目")

    def test_rate_limit_waits_until_reset_within_deadline(self):
        """レート制限の再開が期限内なら待機して続け、期限を越えるか読めなければ 3。"""
        calls = []
        original = gh.rate_limit_reset_at
        try:
            gh.rate_limit_reset_at = lambda: time.time() + 0.1

            def limited_once():
                calls.append(1)
                return ("failure", "rate_limit") if len(calls) == 1 else (0, "diff closed")
            self.assertEqual(self._waiter(minutes=0.1).run(limited_once), 0)
            gh.rate_limit_reset_at = lambda: time.time() + 600
            self.assertEqual(self._waiter(minutes=0.01).run(lambda: ("failure", "rate_limit")), 3)
            gh.rate_limit_reset_at = lambda: None
            self.assertEqual(self._waiter(minutes=0.01).run(lambda: ("failure", "rate_limit")), 3)
        finally:
            gh.rate_limit_reset_at = original

    def test_stop_previous_removes_reused_pid_without_killing(self):
        """wait.pid の PID の開始時刻かコマンドが違えば (再利用)、そのプロセスを止めずに wait.pid だけ消す。"""
        sleeper = subprocess.Popen(["sleep", "30"])
        try:
            with open(self.pid_path, "w", encoding="utf-8") as f:
                json.dump({"pid": sleeper.pid, "started_at": "not the real start", "owner": M1, "wait": "wait"}, f)
            self.assertEqual(poll.stop_previous(self.pid_path), {"removed": sleeper.pid})
            self.assertFalse(os.path.exists(self.pid_path))
            self.assertIsNone(sleeper.poll(), "止めていない")
            with open(self.pid_path, "w", encoding="utf-8") as f:
                json.dump({"pid": sleeper.pid, "started_at": poll.process_start(sleeper.pid), "owner": M1, "wait": "wait"}, f)
            self.assertEqual(poll.stop_previous(self.pid_path), {"removed": sleeper.pid}, "開始時刻が同じでもコマンドが待機でなければ止めない")
            self.assertIsNone(sleeper.poll())
        finally:
            sleeper.kill()
            sleeper.wait()

    def test_stop_previous_without_file(self):
        self.assertEqual(poll.stop_previous(self.pid_path), {"none": True})


class CliBase(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.manager = os.path.join(self.root, "manager")
        os.makedirs(os.path.dirname(os.path.join(self.manager, config.CONFIG_PATH)))
        with open(os.path.join(self.manager, config.CONFIG_PATH), "w", encoding="utf-8") as f:
            json.dump({"project": {"owner": "akm", "number": 3}, "record_dir": "rec"}, f)
        self.record_dir = os.path.join(self.manager, "rec", "akm-3")
        self.tmpdir = os.path.join(self.root, "tmp")
        os.makedirs(self.tmpdir)
        self.env = {**os.environ, "TMPDIR": self.tmpdir, "CLAUDE_CODE_HOST_SESSION_ID": W7}
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)

    def run_cli(self, *args, env=None, timeout=30):
        r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=timeout)
        return r.returncode, r.stdout.splitlines(), r.stderr

    def popen(self, *args, env=None):
        return subprocess.Popen([sys.executable, _CLI, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**self.env, **(env or {})})

    def write_snapshot(self, mutate=None):
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        code, out, err = self.run_cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual(code, 0, err)

    def worker_pid_path(self):
        return os.path.join(self.tmpdir, "issue-dispatch", W7, "wait.pid")


class ManagerWaitTest(CliBase):

    def test_wait_without_snapshot_is_5(self):
        """スナップショットが無い (壊れている) と、上書きせずに 5 で止まる。"""
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST)
        self.assertEqual((code, out), (5, []), err)
        os.makedirs(self.record_dir, exist_ok=True)
        with open(os.path.join(self.record_dir, "snapshot.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST)
        self.assertEqual(code, 5, err)
        with open(os.path.join(self.record_dir, "snapshot.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "{broken", "上書きしない")

    def test_wait_returns_diff_kinds_and_does_not_write_snapshot(self):
        """差分があれば種類を 1 行に書いて 0 で終わる (起動の前からの変化も最初の読み取りで返す)。スナップショットは書かない。"""
        self.write_snapshot()
        taken = observe.load_snapshot(self.record_dir)["snapshot"]["taken_at"]
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: node_of(nodes, 1)["content"].__setitem__("state", "CLOSED"))}])
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST)
        self.assertEqual((code, out[0].startswith("pid "), out[1]), (0, True, "diff closed"), err)
        self.assertEqual(observe.load_snapshot(self.record_dir)["snapshot"]["taken_at"], taken)
        self.assertFalse(os.path.exists(os.path.join(self.record_dir, "wait.pid")))

    def test_wait_times_out_with_124(self):
        self.write_snapshot()
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST)
        self.assertEqual((code, len(out)), (124, 1), err)

    def test_wait_uses_config_defaults_and_rejects_interval_not_shorter(self):
        self.write_snapshot()
        code, out, err = self.run_cli("wait", "--dir", self.manager, "--interval", "0.02", "--minutes", "0.02")
        self.assertEqual(code, 2, err)
        self.assertIn("--interval", err)

    def test_wait_exit_codes_for_gh_failures(self):
        """認証切れは 8 (argparse の 2 と区別)。ネットワークの失敗が 3 回続けば 4。レート制限の再開を読めなければ 3。"""
        self.write_snapshot()
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST, env={"FAKE_GH_MODE": "auth_expired"})
        self.assertEqual(code, 8, err)
        code, out, err = self.run_cli("wait", "--dir", self.manager, "--interval", "0.001", "--minutes", "0.05", env={"FAKE_GH_MODE": "network"})
        self.assertEqual(code, 4, err)
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST, env={"FAKE_GH_MODE": "rate_limited"})
        self.assertEqual(code, 3, err)
        code, out, err = self.run_cli("wait", "--dir", self.manager, "--bogus")
        self.assertEqual(code, 2)

    def test_wait_sigterm_writes_stopped_and_6(self):
        """SIGTERM を受けると stopped と PID の行を書いて 6 で終わる。wait.pid に別の PID が書かれていれば消さない。"""
        self.write_snapshot()
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        p = self.popen("wait", "--dir", self.manager, "--interval", "0.01", "--minutes", "1")
        first = p.stdout.readline().strip()
        self.assertTrue(first.startswith("pid "), first)
        pid = int(first.split()[1])
        pid_path = os.path.join(self.record_dir, "wait.pid")
        self.assertEqual(poll.read_pid_file(pid_path)["pid"], pid)
        with open(pid_path, "w", encoding="utf-8") as f:
            json.dump({"pid": pid + 100000, "started_at": "x", "owner": M1, "wait": "wait"}, f)
        os.kill(pid, signal.SIGTERM)
        out, err = p.communicate(timeout=30)
        self.assertEqual((p.returncode, out.strip().splitlines()[-1]), (6, f"stopped {pid}"), err)
        self.assertTrue(os.path.exists(pid_path), "別の PID の wait.pid は消さない")

    def test_new_wait_stops_previous_wait(self):
        """起動の前に、動いている前の待機 (wait.pid の PID。開始時刻とコマンドが一致) を止める。"""
        self.write_snapshot()
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        first = self.popen("wait", "--dir", self.manager, "--interval", "0.01", "--minutes", "1")
        pid_line = first.stdout.readline().strip()
        pid = int(pid_line.split()[1])
        code, out, err = self.run_cli("wait", "--dir", self.manager, *FAST)
        self.assertEqual(code, 124, err)
        out1, err1 = first.communicate(timeout=30)
        self.assertEqual((first.returncode, out1.strip().splitlines()[-1]), (6, f"stopped {pid}"), err1)


class WaitAssignmentTest(CliBase):

    def _respond(self, mutate, extra_entries=()):
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}, *extra_entries])

    def test_new_assignment_is_returned_from_first_read(self):
        """自分の ID がフィールドにあり、自分宛ての `割り当て` があってその番号の `解放` が無く、Status が In Progress の項目を返す (起動の前からでも最初の読み取りで)。"""
        self._respond(lambda nodes: assigned_item3(nodes, status="In Progress"))
        code, out, err = self.run_cli("wait-assignment", "--project", "akm/3", *FAST)
        self.assertEqual((code, out[1]), (0, f"assignment {A3}"), err)
        self.assertFalse(os.path.exists(self.worker_pid_path()))

    def test_assignment_without_comment_or_released_is_not_returned(self):
        """コメント `割り当て` が無い (書き込みの途中) 項目と、今の番号の `解放` がある項目は返さない。"""
        def only_field(nodes):
            node = node_of(nodes, 3)
            node["content"]["assignees"]["nodes"] = [{"login": LOGIN}]
            for fv in node["fieldValues"]["nodes"]:
                if fv and (fv.get("field") or {}).get("name") == "Agent session ID":
                    fv["text"] = W7
        self._respond(only_field)
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", *FAST)[0], 124)
        released = mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "解除"}, t(20), 101)
        self._respond(lambda nodes: assigned_item3(nodes, [released], status="In Progress"))
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", *FAST)[0], 124, "見る Issue でない項目の解放では終わらない")

    def test_blocked_in_review_and_pending(self):
        """--blocked は In Progress に戻ると返す。--in-review は In Progress でも返さない。--pending は戻れば返し、閉じたままなら返さない。"""
        self._respond(lambda nodes: assigned_item3(nodes, status="Blocked"))
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", "--blocked", A3, *FAST)[0], 124)
        self._respond(lambda nodes: assigned_item3(nodes, status="In Progress"))
        code, out, _ = self.run_cli("wait-assignment", "--project", "akm/3", "--blocked", A3, *FAST)
        self.assertEqual((code, out[1]), (0, f"resumed {A3}"))
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", "--in-review", A3, *FAST)[0], 124)
        self._respond(lambda nodes: assigned_item3(nodes, status="Done", state="CLOSED"))
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", "--pending", A3, *FAST)[0], 124, "進行中の close のまま")
        self._respond(lambda nodes: assigned_item3(nodes, status="Blocked"))
        code, out, _ = self.run_cli("wait-assignment", "--project", "akm/3", "--pending", A3, *FAST)
        self.assertEqual((code, out[1]), (0, f"resumed {A3}"))

    def test_stop_on_release_and_normal_end(self):
        """見る Issue の解放で stop と理由。--in-review の正常な終わり (ready for review の後の close) で stop close。"""
        released = mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "close"}, t(20), 101)
        self._respond(lambda nodes: assigned_item3(nodes, [released], status="Done", state="CLOSED"))
        code, out, _ = self.run_cli("wait-assignment", "--project", "akm/3", "--pending", A3, *FAST)
        self.assertEqual((code, out[1]), (0, "stop close"))
        report = wcomment("PR の報告", None, t(30), 300, body=PR9)
        self._respond(lambda nodes: assigned_item3(nodes, [DECL1, _go(400, t(13), 500), report], status="Done", state="CLOSED"),
                      [{"substring": "query PrObserve", "stdout": pr_fixture("MERGED", merged=True)}])
        code, out, _ = self.run_cli("wait-assignment", "--project", "akm/3", "--in-review", A3, *FAST)
        self.assertEqual((code, out[1]), (0, "stop close"))
        self._respond(lambda nodes: assigned_item3(nodes, [DECL1, _go(400, t(13), 500)], status="Done", state="CLOSED"))
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", "--in-review", A3, *FAST)[0], 124, "進行中の Issue の close では終わらない")

    def test_request_for_body_append(self):
        """自分宛ての `依頼` (本文の追記) で、その PR が開いていて閉じる参照に Issue が無ければ request。追記が済めば終わらない。"""
        req = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "本文の追記", "pr": PR9}, t(31), 301)
        self._respond(lambda nodes: assigned_item3(nodes, [DECL1, _go(400, t(13), 500), req], status="In Progress"),
                      [{"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        code, out, _ = self.run_cli("wait-assignment", "--project", "akm/3", "--in-review", A3, *FAST)
        self.assertEqual((code, out[1]), (0, "request"))
        done = pr_fixture("OPEN")
        done["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"] = [{"number": 3, "url": f"https://github.com/{A}/issues/3", "state": "OPEN", "repository": {"nameWithOwner": A}}]
        self._respond(lambda nodes: assigned_item3(nodes, [DECL1, _go(400, t(13), 500), req], status="In Progress"), [{"substring": "query PrObserve", "stdout": done}])
        self.assertEqual(self.run_cli("wait-assignment", "--project", "akm/3", "--in-review", A3, *FAST)[0], 124)

    def test_prs_of_ended_items_are_not_read(self):
        """終わった項目 (閉じていて見る Issue でない) の `PR の報告` の PR は読まない。今の割り当ての項目の PR だけを読む。"""
        old_assign = mcomment("割り当て", {"to": W7, "assignment": 1}, t(1), 90, name="mgr", sid=M1)
        old_report = wcomment("PR の報告", None, t(2), 91, body=f"https://github.com/{A}/pull/2")
        report = wcomment("PR の報告", None, t(30), 300, body=PR9)
        def mutate(nodes):
            old = node_of(nodes, 2)["content"]
            old["comments"]["nodes"] += [gql_comment(old_assign), gql_comment(old_report)]
            assigned_item3(nodes, [DECL1, _go(400, t(13), 500), report], status="In Progress")
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}, {"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        code, out, _ = self.run_cli("wait-assignment", "--project", "akm/3", "--in-review", A3, *FAST)
        self.assertEqual(code, 124)
        observed = [r for r in self.recorded_full() if "PrObserve" in (r.get("stdin") or "")]
        self.assertTrue(observed, "今の割り当ての項目の PR は読む")
        self.assertFalse(any("pull/2" in (r.get("stdin") or "") for r in observed), "終わった項目の PR は読まない")

    def test_interval_must_be_shorter_than_minutes(self):
        code, out, err = self.run_cli("wait-assignment", "--project", "akm/3", "--interval", "1", "--minutes", "1")
        self.assertEqual(code, 2, err)


class WaitDecisionTest(CliBase):

    def _respond(self, extra, status="In Progress", events=None):
        def mutate(nodes):
            assigned_item3(nodes, extra, status=status)
            if events:
                node_of(nodes, 3)["content"]["timelineItems"]["nodes"] += events
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}])

    def test_go_request_wait(self):
        """自分宛てで渡した宣言の ID の `開始可` で go、宣言の修正の `依頼` で request、管理のセッションが書いた Blocked で wait。"""
        self._respond([DECL1, _go(400, t(13), 500)])
        code, out, _ = self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", *FAST)
        self.assertEqual((code, out[1]), (0, "go"))
        req = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の修正", "declaration": 400}, t(13), 500)
        self._respond([DECL1, req])
        code, out, _ = self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", *FAST)
        self.assertEqual((code, out[1]), (0, "request"))
        blocked_event = {"__typename": "ProjectV2ItemStatusChangedEvent", "createdAt": t(14), "status": "Blocked", "previousStatus": "In Progress", "wasAutomated": False, "project": {"number": 3}}
        self._respond([DECL1, _wait(400, [{"kind": "Issue", "issue": A1}], t(13), 500)], status="Blocked", events=[blocked_event])
        code, out, _ = self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", *FAST)
        self.assertEqual((code, out[1]), (0, "wait"))

    def test_user_blocked_and_other_declaration_do_not_end(self):
        """利用者が手で付けた Blocked (待機より前の変化) と、別の宣言への `開始可` では終わらない。"""
        early = {"__typename": "ProjectV2ItemStatusChangedEvent", "createdAt": t(12), "status": "Blocked", "previousStatus": "In Progress", "wasAutomated": False, "project": {"number": 3}}
        self._respond([DECL1, _wait(400, [{"kind": "Issue", "issue": A1}], t(13), 500)], status="Blocked", events=[early])
        self.assertEqual(self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", *FAST)[0], 124)
        self._respond([DECL1, _go(399, t(13), 500)])
        self.assertEqual(self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", *FAST)[0], 124)

    def test_stop_on_release_and_review_update_normal_end(self):
        released = mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "解除"}, t(20), 101)
        self._respond([DECL1, released])
        code, out, _ = self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", *FAST)
        self.assertEqual((code, out[1]), (0, "stop 解除"))
        report = wcomment("PR の報告", None, t(30), 300, body=PR9)
        update = wcomment("宣言の更新", None, t(31), 401, body=DECL1["body"].split("\n\n", 1)[1])
        def closed(nodes):
            assigned_item3(nodes, [DECL1, _go(400, t(13), 500), report, update], status="Done", state="CLOSED")
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(closed)}, {"substring": "query PrObserve", "stdout": pr_fixture("MERGED", merged=True)}])
        self.assertEqual(self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "401", *FAST)[0], 124, "--review-update が無ければ正常な終わりでは終わらない")
        code, out, _ = self.run_cli("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "401", "--review-update", *FAST)
        self.assertEqual((code, out[1]), (0, "stop close"))

    def test_worker_wait_pid_in_session_temp_dir(self):
        """作業の待機は wait.pid を ${TMPDIR}/issue-dispatch/<セッション ID>/ に書き、作業ツリーには何も書かない。"""
        self._respond([DECL1])
        p = self.popen("wait-decision", "--project", "akm/3", "--issue", A3, "--declaration", "400", "--interval", "0.01", "--minutes", "1")
        pid = int(p.stdout.readline().split()[1])
        self.assertEqual(poll.read_pid_file(self.worker_pid_path())["pid"], pid)
        os.kill(pid, signal.SIGTERM)
        out, err = p.communicate(timeout=30)
        self.assertEqual((p.returncode, out.strip().splitlines()[-1]), (6, f"stopped {pid}"), err)
        self.assertFalse(os.path.exists(self.worker_pid_path()))


class DocTest(unittest.TestCase):

    def test_doc_lists_waits_exit_codes_and_words(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for key in ("`wait.pid`", "`wait-assignment`", "`wait-decision`", "`--blocked`", "`--in-review`", "`--pending`", "`--review-update`", "`pid`", "`stopped`"):
            self.assertIn(key, doc, f"{key} が文書に無い")
        for word in poll.RESULT_WORDS:
            self.assertTrue(f"`{word}`" in doc or f"`{word} <" in doc, f"終わりの行の語 {word} が文書に無い")
        for code in (0, 3, 4, 5, 6, 8, 124):
            self.assertIn(f"| {code} |", doc, f"終了コード {code} が文書に無い")


if __name__ == "__main__":
    unittest.main()
