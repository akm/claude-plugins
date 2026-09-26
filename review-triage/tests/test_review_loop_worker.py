#!/usr/bin/env python3
"""ワーカーのスクリプト (review-triage/scripts/review-loop-worker.sh) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s review-triage/tests

一時ディレクトリに git のリポジトリと周回の置き場を作り、claude の名前で偽のコマンド
(review-triage/tests/fake-claude) を PATH の先頭に置いて、スクリプトを subprocess で走らせる。
実際の claude は呼ばない。

振る舞いの正本は review-triage/skills/review-loop/references/worker.md、
置き場のファイルの様式の正本は同じディレクトリの loop-files.md。
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.path.join(_HERE, "..", "scripts", "review-loop-worker.sh")
_FAKE = os.path.join(_HERE, "fake-claude")
_LOOP_FILES = os.path.join(_HERE, "..", "skills", "review-loop", "references", "loop-files.md")

RID = "20260926-1400-feat-x-1-code-review-opus"
RID2 = "20260926-1410-feat-x-2-code-review-opus"
LOOP_ID = "20260926-1400-feat-x"

PROMPT = "依頼文 {req} のとおりに作業し、結果を依頼文が指す出力先に書く。"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _read_yaml(path):
    """ワーカーが書く YAML (2 段までの入れ子・スカラー・JSON 形式の列) を読む。"""
    root = {}
    parent = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            m = re.match(r"^( *)([A-Za-z_]+):(?: (.*))?$", line)
            if not m:
                raise ValueError(f"読めない行: {line!r}")
            indent, key, value = m.group(1), m.group(2), m.group(3)
            if value is None:
                root[key] = {}
                parent = root[key]
                continue
            v = value.strip()
            if v.startswith('"') or v.startswith("["):
                v = json.loads(v)
            elif re.fullmatch(r"-?\d+", v):
                v = int(v)
            elif v in ("true", "false"):
                v = v == "true"
            if indent:
                parent[key] = v
            else:
                root[key] = v
                parent = None
    return root


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def _contract_keys(heading):
    """loop-files.md の見出し heading の直後の表から、(必須のキーの集合, 全キーの集合) を返す。"""
    with open(_LOOP_FILES, encoding="utf-8") as f:
        text = f.read()
    start = text.index(heading)
    rows = []
    in_table = False
    for line in text[start:].splitlines()[1:]:
        if line.startswith("| キー |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip("|").split("|")]
            m = re.fullmatch(r"`([^`]+)`", cells[0])
            if m:
                rows.append((m.group(1), cells[1] == "◯"))
    return {k for k, req in rows if req}, {k for k, _ in rows}


def _group_alive(pgid):
    out = subprocess.run(
        ["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == str(pgid) and not parts[1].startswith("Z"):
            return True
    return False


def _read_pids(path):
    with open(path, encoding="utf-8") as f:
        return [int(x) for x in f.read().split()]


def _pid_alive(pid):
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()
    return bool(out) and not out.startswith("Z")


class WorkerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self._tmp.name)
        self.repo = os.path.join(root, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "README.md"), "w", encoding="utf-8") as f:
            f.write("# テスト\n")
        with open(os.path.join(self.repo, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("tmp/\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.loop = os.path.join(self.repo, "tmp", "review-loop", LOOP_ID)
        os.makedirs(self.loop)
        with open(self.path("loop.yaml"), "w", encoding="utf-8") as f:
            f.write(f'id: "{LOOP_ID}"\nrepo_dir: "{self.repo}"\nstate: active\n')
        self.bin = os.path.join(root, "bin")
        os.makedirs(self.bin)
        os.symlink(os.path.realpath(_FAKE), os.path.join(self.bin, "claude"))
        self.args_file = os.path.join(root, "claude-args.jsonl")
        self.pids_file = os.path.join(root, "claude-pids")
        self.env = dict(os.environ)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["FAKE_CLAUDE_ARGS"] = self.args_file
        self.env["FAKE_CLAUDE_PIDS"] = self.pids_file
        for k in ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_SLEEP", "FAKE_CLAUDE_STREAM", "FAKE_CLAUDE_EXIT"):
            self.env.pop(k, None)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.communicate()
        if os.path.exists(self.pids_file):
            for pid in _read_pids(self.pids_file):
                try:
                    os.killpg(int(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self._tmp.cleanup()

    # ---- 準備 ----

    def path(self, name):
        return os.path.join(self.loop, name)

    def head(self):
        return _git(self.repo, "rev-parse", "--short", "HEAD")

    def put_request(self, rid=RID, head=None):
        result = self.path(f"review-{rid}.yaml")
        text = (
            "# レビューの依頼 (テスト)\n\n"
            "## 出力様式\n\n"
            f"出力先: `{result}` — この 1 ファイルだけ。\n\n"
            "```yaml\n"
            "skill: code-review\n"
            f'run_id: "{rid}"\n'
            f'head: "{head or self.head()}"\n'
            "findings: []\n"
            "```\n"
        )
        tmp = self.path(f".review-request-{rid}.md.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.rename(tmp, self.path(f"review-request-{rid}.md"))

    def put_stream(self, lines):
        p = os.path.join(os.path.dirname(self.args_file), "stream.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for line in lines:
                f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
        self.env["FAKE_CLAUDE_STREAM"] = p

    # ---- 起動と観察 ----

    def start(self, *extra, cwd=None, env=None):
        args = ["bash", _WORKER, self.loop, "--model", "opus", "--effort", "high", *extra]
        p = subprocess.Popen(
            args, cwd=cwd or self.repo, env=env or self.env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.procs.append(p)
        return p

    def wait_for(self, pred, timeout=20, interval=0.1, what="条件"):
        deadline = time.time() + timeout
        while time.time() < deadline:
            v = pred()
            if v:
                return v
            time.sleep(interval)
        self.fail(f"{timeout} 秒待っても{what}が成り立たない")

    def worker_state(self):
        try:
            return _read_yaml(self.path("worker.yaml"))
        except (OSError, ValueError):
            return {}

    def wait_state(self, state, timeout=20):
        return self.wait_for(lambda: self.worker_state().get("state") == state and self.worker_state(),
                             timeout=timeout, what=f"worker.yaml の state: {state}")

    def wait_marker(self, rid=RID, timeout=25):
        p = self.path(f"delivered-{rid}.yaml")
        self.wait_for(lambda: os.path.exists(p), timeout=timeout, what=f"完了の印 {rid}")
        return _read_yaml(p)

    def finish(self, p, sig=signal.SIGTERM, timeout=20):
        p.send_signal(sig)
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err

    def claude_calls(self):
        if not os.path.exists(self.args_file):
            return []
        with open(self.args_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def assert_contract(self, heading, data):
        required, allowed = _contract_keys(heading)
        keys = set(_flatten(data))
        self.assertTrue(required, f"{heading} の表からキーを読めなかった")
        self.assertLessEqual(required, keys, f"必須のキーが無い: {sorted(required - keys)}")
        self.assertLessEqual(keys, allowed, f"表に無いキーがある: {sorted(keys - allowed)}")


def _option_values(args, name):
    """--allowedTools のような可変長の引数の値を、次の -- で始まる引数の手前まで集める。"""
    i = args.index(name)
    out = []
    for a in args[i + 1:]:
        if a.startswith("--"):
            break
        out.append(a)
    return out


class TestHappyPath(WorkerTestBase):
    def test_one_round(self):
        # AE1: idle → reviewing (識別子入り) → idle と遷移し、ok の印とログが残る
        self.env["FAKE_CLAUDE_SLEEP"] = "2"
        p = self.start()
        idle = self.wait_state("idle")
        self.assertEqual(idle["current_request"], "")
        self.assert_contract("## `worker.yaml`", idle)
        head = self.head()
        self.put_request()
        reviewing = self.wait_state("reviewing", timeout=10)
        self.assertEqual(reviewing["current_request"], RID)
        marker = self.wait_marker()
        self.wait_state("idle")

        self.assertEqual(marker["status"], "ok", marker)
        self.assertEqual(marker["id"], RID)
        self.assertEqual(marker["model"], {"specified": "opus", "effective": "opus-5"})
        self.assertEqual(marker["effort"], "high")
        self.assertIs(marker["skill_called"], True)
        self.assertEqual(marker["permission_denials"], {"count": 0, "tools": []})
        self.assertEqual(marker["head_before"], head)
        self.assertEqual(marker["head_after"], head)
        self.assertIs(marker["tree_clean_after"], True)
        self.assertEqual(marker["exit_code"], 0)
        self.assertEqual(marker["log"], f"{RID}.log")
        self.assertNotIn("error", marker)
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        self.assertTrue(os.path.exists(self.path(f"{RID}.log")))
        self.assertEqual([n for n in os.listdir(self.loop) if n.endswith(".tmp")], [])
        self.assertEqual(self.worker_state()["rounds_served"], 1)

        # 偽の claude が受けた引数
        calls = self.claude_calls()
        self.assertEqual(len(calls), 1)
        args = calls[0]
        req = self.path(f"review-request-{RID}.md")
        self.assertEqual(args[:2], ["-p", PROMPT.format(req=req)])
        for opt, val in (("--model", "opus"), ("--effort", "high"),
                         ("--permission-mode", "default"), ("--output-format", "stream-json")):
            self.assertEqual(args[args.index(opt) + 1], val, opt)
        self.assertIn("--verbose", args)
        self.assertEqual(_option_values(args, "--disallowedTools"), ["AskUserQuestion"])
        tools = _option_values(args, "--allowedTools")
        self.assertIn("Read", tools)
        self.assertIn("Skill", tools)
        self.assertIn("Agent", tools)
        self.assertIn("Bash(git diff:*)", tools)
        self.assertEqual(tools[-1], "Edit(/" + self.path(f"review-{RID}.yaml") + ")")
        self.assertTrue(tools[-1].startswith("Edit(//"))

        rc, _, _ = self.finish(p)
        self.assertEqual(rc, 143)
        self.assertEqual(self.worker_state()["state"], "left")

    def test_two_requests_in_identifier_order(self):
        self.put_request(RID2)
        self.put_request(RID)
        p = self.start()
        self.wait_marker(RID)
        self.wait_marker(RID2)
        prompts = [c[1] for c in self.claude_calls()]
        self.assertEqual(prompts, [
            PROMPT.format(req=self.path(f"review-request-{RID}.md")),
            PROMPT.format(req=self.path(f"review-request-{RID2}.md")),
        ])
        self.finish(p)

    def test_extra_args_are_passed_through(self):
        self.put_request()
        p = self.start("--", "--plugin-dir", "/x/y")
        self.wait_marker()
        args = self.claude_calls()[0]
        self.assertEqual(args[-2:], ["--plugin-dir", "/x/y"])
        self.finish(p)

    def test_allowed_tools_replace_default(self):
        self.put_request()
        p = self.start("--allowed-tools", "Read", "--allowed-tools", "Bash(git diff:*)",
                       "--permission-mode", "acceptEdits")
        self.wait_marker()
        args = self.claude_calls()[0]
        self.assertEqual(_option_values(args, "--allowedTools"), [
            "Read", "Bash(git diff:*)", "Edit(/" + self.path(f"review-{RID}.yaml") + ")",
        ])
        self.assertEqual(args[args.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(self.worker_state()["permission_mode"], "acceptEdits")
        self.finish(p)

    def test_heartbeat_advances_during_review(self):
        # レビュアの実行中 (偽の claude が 12 秒待つ) にも、worker.yaml の更新時刻が 5 秒おきに進む
        self.env["FAKE_CLAUDE_SLEEP"] = "12"
        self.put_request()
        p = self.start()
        self.wait_state("reviewing")
        seen = set()
        end = time.time() + 11
        while time.time() < end:
            seen.add(os.stat(self.path("worker.yaml")).st_mtime)
            time.sleep(0.5)
        self.assertGreaterEqual(len(seen), 3, seen)
        self.wait_marker()
        self.finish(p)


class TestResultChecks(WorkerTestBase):
    def run_one(self, mode):
        self.env["FAKE_CLAUDE_MODE"] = mode
        self.put_request()
        p = self.start()
        marker = self.wait_marker()
        self.wait_state("idle")
        self.finish(p)
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        return marker

    def test_empty_run_id(self):
        # AE5
        marker = self.run_one("empty_run_id")
        self.assertEqual(marker["status"], "failed")
        self.assertIn("run_id mismatch", marker["error"])

    def test_no_result(self):
        marker = self.run_one("no_result")
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], "no result")

    def test_no_findings(self):
        marker = self.run_one("no_findings")
        self.assertEqual(marker["status"], "failed")
        self.assertIn("no findings key", marker["error"])

    def test_dirty_tree(self):
        # AE7
        marker = self.run_one("dirty_tree")
        self.assertEqual(marker["status"], "failed")
        self.assertIs(marker["tree_clean_after"], False)
        self.assertIn("tree not clean (README.md)", marker["error"])

    def test_loop_dir_modified(self):
        # レビュアの実行が置き場に依頼文を置くと failed にし、その依頼文をレビュアの実行に回さない
        marker = self.run_one("write_request")
        bogus = "29990101-0000-x-9-code-review-opus"
        self.assertEqual(marker["status"], "failed")
        self.assertIn(f"loop dir modified (review-request-{bogus}.md)", marker["error"])
        self.assertEqual(len(self.claude_calls()), 1)
        self.assertFalse(os.path.exists(self.path(f"delivered-{bogus}.yaml")))

    def test_loop_dir_modified_request_is_not_picked_up_later(self):
        self.env["FAKE_CLAUDE_MODE"] = "write_request"
        self.put_request()
        p = self.start()
        self.wait_marker()
        time.sleep(7)  # 探索の周期 (5 秒) を 1 回以上待つ
        self.assertEqual(len(self.claude_calls()), 1)
        self.finish(p)

    def test_loop_yaml_rewritten_during_review_is_not_a_modification(self):
        # 作業側が再開や停止のときにレビュー中に loop.yaml を書き換えても、置き場の変化として数えない
        self.env["FAKE_CLAUDE_SLEEP"] = "4"
        self.put_request()
        p = self.start()
        self.wait_state("reviewing")
        time.sleep(1)
        tmp = self.path(".loop.yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f'id: "{LOOP_ID}"\nrepo_dir: "{self.repo}"\nstate: stopped\n')
        os.rename(tmp, self.path("loop.yaml"))
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "ok", marker)

    def test_head_mismatch_does_not_run_reviewer(self):
        # AE8: 依頼文の head と HEAD が違うと、偽の claude を呼ばずに failed の印を書く
        old = self.head()
        with open(os.path.join(self.repo, "a.txt"), "w", encoding="utf-8") as f:
            f.write("a\n")
        _git(self.repo, "add", "a.txt")
        _git(self.repo, "commit", "-q", "-m", "second")
        self.put_request(head=old)
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], f"head mismatch (expected {old}, actual {self.head()})")
        self.assertEqual(self.claude_calls(), [])
        for key in ("head_after", "tree_clean_after", "exit_code", "log"):
            self.assertNotIn(key, marker)
        self.assertEqual(marker["skill_called"], "unknown")
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)

    def test_tree_not_clean_before_review(self):
        self.put_request()
        with open(os.path.join(self.repo, "README.md"), "a", encoding="utf-8") as f:
            f.write("x\n")
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], "tree not clean (README.md)")
        self.assertEqual(self.claude_calls(), [])

    def test_malformed_request(self):
        req = self.path(f"review-request-{RID}.md")
        with open(req, "w", encoding="utf-8") as f:
            f.write("# 依頼文\n\n## 出力様式\n\nhead: \"{{head}}\"\n")
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "failed")
        self.assertIn("request malformed", marker["error"])
        self.assertEqual(self.claude_calls(), [])


class TestLogReading(WorkerTestBase):
    def run_with_stream(self, lines):
        self.put_stream(lines)
        self.put_request()
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        return marker

    def test_permission_denials(self):
        marker = self.run_with_stream([
            {"type": "system", "subtype": "init", "model": "claude-opus-5"},
            {"type": "result", "subtype": "success", "permission_denials": [
                {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "make test"}},
                {"tool_name": "Write", "tool_use_id": "t2", "tool_input": {}},
            ]},
        ])
        self.assertEqual(marker["permission_denials"], {"count": 2, "tools": ["Bash", "Write"]})
        self.assertEqual(marker["skill_called"], "unknown")

    def test_no_result_line_is_unknown(self):
        marker = self.run_with_stream([
            {"type": "system", "subtype": "init", "model": "claude-opus-5"},
        ])
        self.assertEqual(marker["permission_denials"], {"count": "unknown", "tools": []})

    def test_subagent_lines_and_tool_results_are_ignored(self):
        marker = self.run_with_stream([
            "hook の出力など JSON でない行",
            {"type": "system", "subtype": "init", "model": "claude-haiku-4-5",
             "parent_tool_use_id": "toolu_sub"},
            {"type": "system", "subtype": "init", "model": "claude-opus-5", "parent_tool_use_id": None},
            {"type": "assistant", "parent_tool_use_id": None,
             "message": {"content": [{"type": "text", "text": "Skill を呼ばずに読む"}]}},
            {"type": "assistant", "parent_tool_use_id": "toolu_sub",
             "message": {"model": "claude-haiku-4-5",
                         "content": [{"type": "tool_use", "name": "Skill", "input": {}}]}},
            {"type": "user", "parent_tool_use_id": None,
             "message": {"content": [{"type": "tool_result",
                                      "content": '{"name":"Skill","model":"claude-sonnet-5"}'}]}},
            {"type": "result", "subtype": "success", "permission_denials": []},
        ])
        self.assertEqual(marker["model"]["effective"], "opus-5")
        self.assertIs(marker["skill_called"], False)
        self.assertEqual(marker["status"], "ok")

    def test_no_init_line_is_unknown(self):
        marker = self.run_with_stream(["not json"])
        self.assertEqual(marker["model"]["effective"], "unknown")
        self.assertEqual(marker["skill_called"], "unknown")


class TestStartChecks(WorkerTestBase):
    def test_other_worktree(self):
        # AE6
        wt = os.path.join(os.path.dirname(self.repo), "wt")
        _git(self.repo, "worktree", "add", "-q", "-b", "wt", wt)
        p = self.start(cwd=wt)
        _, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        state = self.worker_state()
        self.assertEqual(state["state"], "unavailable")
        self.assertIn("別の worktree", state["error"])
        self.assert_contract("## `worker.yaml`", state)

    def test_other_repository(self):
        other = os.path.join(os.path.dirname(self.repo), "other")
        os.makedirs(other)
        _git(other, "init", "-q")
        p = self.start(cwd=other)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn("別の作業ツリー", self.worker_state()["error"])

    def test_end_exists(self):
        open(self.path("end"), "w").close()
        p = self.start()
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(self.worker_state()["state"], "unavailable")
        self.assertIn("end", self.worker_state()["error"])

    def test_missing_loop_yaml(self):
        os.remove(self.path("loop.yaml"))
        p = self.start()
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn("loop.yaml", self.worker_state()["error"])

    def test_claude_missing(self):
        tools = os.path.join(os.path.dirname(self.repo), "tools")
        os.makedirs(tools)
        os.symlink(shutil.which("git"), os.path.join(tools, "git"))
        os.symlink(sys.executable, os.path.join(tools, "python3"))
        env = dict(self.env)
        env["PATH"] = os.pathsep.join([tools, "/usr/bin", "/bin"])
        p = self.start(env=env)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn("claude", self.worker_state()["error"])

    def write_other_worker(self, pid, ago=0, state="idle"):
        path = self.path("worker.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'state: {state}\ncurrent_request: ""\npid: {pid}\n')
        if ago:
            t = time.time() - ago
            os.utime(path, (t, t))
        with open(path, "rb") as f:
            return f.read()

    def test_live_other_worker(self):
        # AE14: 他のワーカーが動いていれば、worker.yaml に触れずに終了コード 2
        before = self.write_other_worker(os.getpid())
        p = self.start()
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn(str(os.getpid()), err)
        with open(self.path("worker.yaml"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_live_other_worker_from_other_worktree(self):
        wt = os.path.join(os.path.dirname(self.repo), "wt")
        _git(self.repo, "worktree", "add", "-q", "-b", "wt", wt)
        before = self.write_other_worker(os.getpid(), state="reviewing")
        p = self.start(cwd=wt)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        with open(self.path("worker.yaml"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_dead_or_stale_other_worker_does_not_block(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        for label, pid, ago in (("終了したプロセス", dead.pid, 0), ("古い更新時刻", os.getpid(), 40)):
            with self.subTest(label):
                self.write_other_worker(pid, ago=ago)
                p = self.start()
                state = self.wait_for(
                    lambda: self.worker_state().get("pid") == p.pid and self.worker_state(),
                    what="新しいワーカーの worker.yaml")
                self.assertEqual(state["state"], "idle")
                self.finish(p)


class TestArguments(WorkerTestBase):
    def run_args(self, *args):
        p = subprocess.run(["bash", _WORKER, *args], cwd=self.repo, env=self.env,
                           capture_output=True, text=True, timeout=20)
        return p.returncode, p.stderr

    def test_errors(self):
        cases = {
            "--model が無い": [self.loop, "--effort", "high"],
            "--effort が無い": [self.loop, "--model", "opus"],
            "effort の値": [self.loop, "--model", "opus", "--effort", "ultra"],
            "相対パス": ["tmp/review-loop/" + LOOP_ID, "--model", "opus", "--effort", "high"],
            "bypassPermissions": [self.loop, "--model", "opus", "--effort", "high",
                                  "--permission-mode", "bypassPermissions"],
            "分の値": [self.loop, "--model", "opus", "--effort", "high", "--idle-minutes", "0"],
            "知らない引数": [self.loop, "--model", "opus", "--effort", "high", "--foo"],
        }
        for label, args in cases.items():
            with self.subTest(label):
                rc, err = self.run_args(*args)
                self.assertEqual(rc, 2)
                self.assertIn("使い方", err)
        self.assertFalse(os.path.exists(self.path("worker.yaml")))


class TestEnding(WorkerTestBase):
    def test_idle_expiry(self):
        # AE10
        p = self.start("--idle-minutes", "0.05")
        out, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 124)
        self.assertEqual(self.worker_state()["state"], "expired")
        self.assertIn("この起動で応じた回: 0 回", out)

    def test_end_lists_served_rounds(self):
        # AE11
        self.put_request()
        p = self.start()
        self.wait_marker()
        self.wait_state("idle")
        with open(self.path("end"), "w", encoding="utf-8") as f:
            f.write("人間が置いた\n")
        out, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.worker_state()["state"], "left")
        self.assertIn("この起動で応じた回: 1 回", out)
        self.assertIn(RID, out)
        self.assertIn("ok", out)

    def test_interrupt_while_idle(self):
        p = self.start()
        self.wait_state("idle")
        os.killpg(p.pid, signal.SIGINT)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 130)
        self.assertEqual(self.worker_state()["state"], "left")
        self.assertEqual([n for n in os.listdir(self.loop) if n.startswith("delivered-")], [])
        self.wait_for(lambda: not _group_alive(p.pid), timeout=3, what="ワーカーのプロセスグループが空になる")

    def test_timeout(self):
        # AE15: 終わらない偽の claude を上限で止め、子プロセスも残さない
        self.env["FAKE_CLAUDE_MODE"] = "hang"
        self.put_request()
        p = self.start("--review-timeout-minutes", "0.05")
        marker = self.wait_marker(timeout=30)
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], "timeout")
        self.wait_state("idle")
        pids = _read_pids(self.pids_file)
        for pid in pids:
            self.wait_for(lambda: not _pid_alive(pid), timeout=5, what=f"プロセス {pid} の終了")
        self.finish(p)

    def test_interrupt_while_reviewing(self):
        # AE16: 割り込みを受けたら、レビュアの実行とその子を止めて failed の印と left を書く
        for sig, code in ((signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 129)):
            with self.subTest(sig=sig.name):
                for n in os.listdir(self.loop):
                    if n != "loop.yaml" and not n.startswith("review-request-"):
                        os.remove(self.path(n))
                if os.path.exists(self.pids_file):
                    os.remove(self.pids_file)
                self.env["FAKE_CLAUDE_MODE"] = "hang"
                if not os.path.exists(self.path(f"review-request-{RID}.md")):
                    self.put_request()
                p = self.start()
                self.wait_state("reviewing")
                self.wait_for(lambda: os.path.exists(self.pids_file), what="偽の claude の起動")
                pids = _read_pids(self.pids_file)
                started = time.time()
                os.killpg(p.pid, sig)  # 端末の Ctrl-C と同じく、ワーカーのフォアグラウンドのプロセスグループに送る
                p.communicate(timeout=20)
                self.assertLess(time.time() - started, 8)
                self.assertEqual(p.returncode, code)
                marker = _read_yaml(self.path(f"delivered-{RID}.yaml"))
                self.assertEqual(marker["status"], "failed")
                self.assertEqual(marker["error"], "interrupted")
                self.assertEqual(self.worker_state()["state"], "left")
                for pid in pids:
                    self.wait_for(lambda: not _pid_alive(pid), timeout=3, what=f"プロセス {pid} の終了")
                self.wait_for(lambda: not _group_alive(p.pid), timeout=3,
                              what="ワーカーのプロセスグループ (更新時刻を進める処理を含む) が空になる")

    def test_sigkill_stops_heartbeat(self):
        # AE17: ワーカーを SIGKILL で消すと、10 秒以内に worker.yaml の更新時刻が止まる
        p = self.start()
        self.wait_state("idle")
        os.kill(p.pid, signal.SIGKILL)
        p.communicate(timeout=20)
        time.sleep(7)
        m1 = os.stat(self.path("worker.yaml")).st_mtime
        time.sleep(6)
        m2 = os.stat(self.path("worker.yaml")).st_mtime
        self.assertEqual(m1, m2)
        self.assertFalse(_group_alive(p.pid))


if __name__ == "__main__":
    unittest.main()
