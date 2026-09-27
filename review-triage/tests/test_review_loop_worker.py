#!/usr/bin/env python3
"""ワーカーのスクリプト (review-triage/scripts/review-loop-worker.sh) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s review-triage/tests

一時ディレクトリに git のリポジトリと周回の置き場を作り、claude の名前で偽のコマンド
(review-triage/tests/fake-claude) を PATH の先頭に置いて、スクリプトを subprocess で走らせる。
実際の claude は呼ばない。

ワーカーは macOS でだけ起動する (起動時の確認で `uname -s` を見る)。CI (ubuntu) でも走るように、
uname の名前で偽のコマンド (review-triage/tests/fake-uname。既定で Darwin を返す) も PATH の先頭に置く。
ワーカーの環境変数 HOME と TMPDIR は、テストの一時ディレクトリの中の別々のディレクトリにする
(利用者の設定 ~/.claude/settings.json を読まないように、また作業場所の条件を満たすように)。

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
_FAKE_UNAME = os.path.join(_HERE, "fake-uname")
_LOOP_FILES = os.path.join(_HERE, "..", "skills", "review-loop", "references", "loop-files.md")
_PLUGIN_JSON = os.path.join(_HERE, "..", ".claude-plugin", "plugin.json")

# サンドボックスの中の Bash が既定で書き込める一時ディレクトリ。ワーカーは、作業側と周回の置き場がこの下にあると起動しない
_SANDBOX_TMP = f"/private/tmp/claude-{os.getuid()}"

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


def _make_repo(repo):
    """repo に、コミットが 1 つある git のリポジトリを作る。tmp/ は追跡しない。"""
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as f:
        f.write("# テスト\n")
    with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("tmp/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")


def _make_loop_dir(loop, repo):
    """loop に周回の置き場を作り、repo を作業側とする loop.yaml を置く。"""
    os.makedirs(loop)
    with open(os.path.join(loop, "loop.yaml"), "w", encoding="utf-8") as f:
        f.write(f'id: "{LOOP_ID}"\nrepo_dir: "{repo}"\nstate: active\n')


class WorkerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self._tmp.name)
        self.root = root
        self.repo = os.path.join(root, "repo")
        _make_repo(self.repo)
        self.loop = os.path.join(self.repo, "tmp", "review-loop", LOOP_ID)
        _make_loop_dir(self.loop, self.repo)
        self.bin = os.path.join(root, "bin")
        os.makedirs(self.bin)
        os.symlink(os.path.realpath(_FAKE), os.path.join(self.bin, "claude"))
        os.symlink(os.path.realpath(_FAKE_UNAME), os.path.join(self.bin, "uname"))
        # HOME を差し替えると、asdf のような版の管理ツールの python3 は (HOME の下の設定を探すので) 起動しなくなる。
        # ワーカーと偽の claude が使う python3 は、このテストを走らせている python の実行ファイルにする
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))
        # ワーカーの HOME と TMPDIR は、リポジトリとは別の、互いに重ならない場所にする
        self.home = os.path.join(root, "home")
        self.tmpdir = os.path.join(root, "tmpdir")
        os.makedirs(self.home)
        os.makedirs(self.tmpdir)
        self.args_file = os.path.join(root, "claude-args.jsonl")
        self.pids_file = os.path.join(root, "claude-pids")
        self.env = dict(os.environ)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["HOME"] = self.home
        self.env["TMPDIR"] = self.tmpdir
        self.env["FAKE_CLAUDE_ARGS"] = self.args_file
        self.env["FAKE_CLAUDE_PIDS"] = self.pids_file
        for k in ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_SLEEP", "FAKE_CLAUDE_STREAM", "FAKE_CLAUDE_EXIT",
                  "FAKE_UNAME_S"):
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

    def write_user_settings(self, content):
        """ワーカーの HOME の .claude/settings.json (利用者の設定) を書く。content が文字列ならそのまま書く。"""
        d = os.path.join(self.home, ".claude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "settings.json"), "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))

    # ---- 起動と観察 ----

    def start(self, *extra, cwd=None, env=None, loop=None, shell="bash"):
        args = [shell, _WORKER, loop or self.loop, "--model", "opus", "--effort", "high", *extra]
        p = subprocess.Popen(
            args, cwd=cwd or self.repo, env=env or self.env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.procs.append(p)
        return p

    def start_unavailable(self, *extra, contains, cwd=None, env=None, loop=None):
        """起動時の確認が通らず、worker.yaml が unavailable と理由 (contains を含む) で書かれ、終了コード 2 で終わることを確かめる。"""
        loop = loop or self.loop
        yaml_path = os.path.join(loop, "worker.yaml")
        if os.path.exists(yaml_path):
            os.remove(yaml_path)
        p = self.start(*extra, cwd=cwd, env=env, loop=loop)
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2, err)
        state = _read_yaml(yaml_path)
        self.assertEqual(state["state"], "unavailable", state)
        for s in contains if isinstance(contains, (list, tuple)) else [contains]:
            self.assertIn(s, state["error"])
        self.assert_contract("## `worker.yaml`", state)
        return state

    def start_idle(self, *extra, **kw):
        """起動時の確認が通り、worker.yaml が idle で書かれることを確かめ、止めて (標準出力, worker.yaml の中身) を返す。"""
        p = self.start(*extra, **kw)
        state = self.wait_for(
            lambda: self.worker_state().get("pid") == p.pid and self.worker_state(),
            what="この起動が worker.yaml を書くこと")
        self.assertEqual(state["state"], "idle", state)
        _, out, _ = self.finish(p)
        return out, state

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
                         ("--permission-mode", "auto"), ("--output-format", "stream-json")):
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
        # 権限モードを指定すれば既定 (auto) に代わる。0.13.0 で始めた周回は default を指定して続ける
        self.put_request()
        p = self.start("--allowed-tools", "Read", "--allowed-tools", "Bash(git diff:*)",
                       "--permission-mode", "default")
        self.wait_marker()
        args = self.claude_calls()[0]
        self.assertEqual(_option_values(args, "--allowedTools"), [
            "Read", "Bash(git diff:*)", "Edit(/" + self.path(f"review-{RID}.yaml") + ")",
        ])
        self.assertEqual(args[args.index("--permission-mode") + 1], "default")
        self.assertEqual(self.worker_state()["permission_mode"], "default")
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
        os.symlink(os.path.realpath(_FAKE_UNAME), os.path.join(tools, "uname"))
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
            "--sandbox-allow-write の値が無い": [self.loop, "--model", "opus", "--effort", "high",
                                                "--sandbox-allow-write"],
            "--sandbox-allowed-domain の値が無い": [self.loop, "--model", "opus", "--effort", "high",
                                                   "--sandbox-allowed-domain"],
        }
        for label, args in cases.items():
            with self.subTest(label):
                rc, err = self.run_args(*args)
                self.assertEqual(rc, 2)
                self.assertIn("使い方", err)
        self.assertFalse(os.path.exists(self.path("worker.yaml")))


def _plugin_version():
    with open(_PLUGIN_JSON, encoding="utf-8") as f:
        return json.load(f)["version"]


class TestWorkerYamlOnStart(WorkerTestBase):
    """起動時の確認が通ったときに書く worker.yaml の中身。"""

    def test_defaults(self):
        # 権限の引数・--sandbox-allow-write・--sandbox-allowed-domain・-- 以降を付けない起動
        _, state = self.start_idle()
        self.assertEqual(state["permission_mode"], "auto")
        self.assertEqual(state["worker_version"], _plugin_version())
        self.assertEqual(state["sandbox_allow_write"], [])
        self.assertEqual(state["sandbox_allowed_domains"], [])
        self.assert_contract("## `worker.yaml`", state)

    def test_sandbox_values(self):
        # --sandbox-allow-write と --sandbox-allowed-domain は繰り返して指定でき、指定の順に書く。
        # --sandbox-allow-write の値の先頭の ~ は、ワーカーの HOME に展開する
        cache = os.path.join(self.root, "cache")
        _, state = self.start_idle(
            "--sandbox-allow-write", "~/Library/Caches/go-build",
            "--sandbox-allow-write", cache,
            "--sandbox-allowed-domain", "proxy.golang.org",
            "--sandbox-allowed-domain", "sum.golang.org",
        )
        self.assertEqual(state["sandbox_allow_write"],
                         [os.path.join(self.home, "Library", "Caches", "go-build"), cache])
        self.assertEqual(state["sandbox_allowed_domains"], ["proxy.golang.org", "sum.golang.org"])
        self.assert_contract("## `worker.yaml`", state)

    def test_empty_arrays_under_set_u(self):
        # -- 以降・--sandbox-allow-write・--sandbox-allowed-domain・--allowed-tools をどれも付けない (配列がどれも空の) 起動で、
        # 1 回の処理を終えられる。macOS の /bin/bash (3.2) は set -u のもとで空の配列の展開をエラーにすることがあるので、
        # /bin/bash があればそれで走らせる
        shell = "/bin/bash" if os.path.exists("/bin/bash") else "bash"
        self.put_request()
        p = self.start(shell=shell)
        marker = self.wait_marker()
        self.wait_state("idle")
        _, _, err = self.finish(p)
        self.assertEqual(marker["status"], "ok", marker)
        self.assertNotIn("unbound variable", err)


class TestSandboxStartChecks(WorkerTestBase):
    """起動時の確認のうち、レビュアの実行をサンドボックスで走らせるための項目 (worker.md の「起動時の確認」の 3 と 9〜14)。"""

    def test_not_macos(self):
        # AE11: uname -s が Linux
        self.env["FAKE_UNAME_S"] = "Linux"
        self.start_unavailable(contains=["macOS", "Linux"])

    def test_not_macos_is_checked_before_loop_yaml(self):
        # 確認は worker.md の表の順に行う (3 の macOS が、4 の loop.yaml より先)
        self.env["FAKE_UNAME_S"] = "Linux"
        os.remove(self.path("loop.yaml"))
        self.start_unavailable(contains="macOS")

    def test_tmpdir(self):
        # AE11: TMPDIR が無い、またはホームの下。作業側が TMPDIR の下
        under_home = os.path.join(self.home, "tmp")
        os.makedirs(under_home)
        link_to_home = os.path.join(self.root, "tmp-link")
        os.symlink(under_home, link_to_home)
        under_repo = os.path.join(self.repo, "tmp", "t")
        os.makedirs(under_repo)
        cases = (
            ("TMPDIR が無い", None, "環境変数 TMPDIR が無い"),
            ("TMPDIR が存在しない", os.path.join(self.root, "nowhere"), "TMPDIR がディレクトリとして存在しない"),
            ("TMPDIR がホームの下", under_home, "TMPDIR の実体がホームの下にある"),
            ("TMPDIR がホームの下を指すシンボリックリンク", link_to_home, "TMPDIR の実体がホームの下にある"),
            ("TMPDIR が作業側の下", under_repo, "TMPDIR の実体が作業側の下にある"),
            ("作業側が TMPDIR の下", self.root, "作業側が TMPDIR の実体の下にある"),
        )
        for label, tmpdir, contains in cases:
            with self.subTest(label):
                env = dict(self.env)
                if tmpdir is None:
                    env.pop("TMPDIR")
                else:
                    env["TMPDIR"] = tmpdir
                self.start_unavailable(env=env, contains=contains)

    def test_sandbox_tmp(self):
        # AE11: 作業側か周回の置き場が、サンドボックスの一時ディレクトリ (/private/tmp/claude-<利用者の番号>) の下
        if not (os.path.isdir(_SANDBOX_TMP) and os.access(_SANDBOX_TMP, os.W_OK)):
            self.skipTest(f"{_SANDBOX_TMP} が無い (macOS で Claude Code のサンドボックスを使った機材でだけ確かめられる)")
        base = tempfile.mkdtemp(prefix="review-loop-worker-test-", dir=_SANDBOX_TMP)
        self.addCleanup(shutil.rmtree, base, True)
        with self.subTest("周回の置き場"):
            loop = os.path.join(base, "loop")
            _make_loop_dir(loop, self.repo)
            self.start_unavailable(loop=loop, contains=["周回の置き場", "サンドボックスの一時ディレクトリ"])
        with self.subTest("作業側"):
            repo = os.path.join(base, "repo")
            _make_repo(repo)
            loop = os.path.join(repo, "tmp", "review-loop", LOOP_ID)
            _make_loop_dir(loop, repo)
            self.start_unavailable(loop=loop, cwd=repo, contains=["作業側", "サンドボックスの一時ディレクトリ"])

    def test_special_characters_in_paths(self):
        # 許可と拒否の規則に書けない文字を、作業側・周回の置き場・TMPDIR の実体パスに含まない
        for c in "()[]{}*?!#":
            with self.subTest(f"TMPDIR に {c}"):
                tmpdir = os.path.join(self.root, f"tmp{c}dir")
                os.makedirs(tmpdir)
                self.start_unavailable(env=dict(self.env, TMPDIR=tmpdir), contains=["TMPDIR", f"「{c}」"])
        with self.subTest("周回の置き場に #"):
            loop = os.path.join(self.root, "loop#1")
            _make_loop_dir(loop, self.repo)
            self.start_unavailable(loop=loop, contains=["周回の置き場", "「#」"])
        with self.subTest("作業側に ("):
            repo = os.path.join(self.root, "repo (copy)")
            _make_repo(repo)
            loop = os.path.join(repo, "tmp", "review-loop", LOOP_ID)
            _make_loop_dir(loop, repo)
            self.start_unavailable(loop=loop, cwd=repo, contains=["作業側", "「(」"])

    def test_sandbox_allow_write_must_not_contain_protected_places(self):
        # AE11: --sandbox-allow-write ~ など。ホーム・作業側・周回の置き場と同じか、その祖先の値は受け付けない。
        # 1 つ目に問題の無い値を置いて、2 つ目以降の値も確かめていることを見る
        link = os.path.join(self.root, "home-link")
        os.symlink(self.home, link)
        cases = (
            ("~", "~", "ホーム"),
            ("ホーム", self.home, "ホーム"),
            ("ホームへのシンボリックリンク", link, "ホーム"),
            ("~/.. (ホームの祖先)", "~/..", "ホーム"),
            ("ホームの祖先", self.root, "ホーム"),
            ("/", "/", "ホーム"),
            ("作業側", self.repo, "作業側"),
            ("周回の置き場", self.loop, "周回の置き場"),
            ("周回の置き場の祖先", os.path.join(self.repo, "tmp"), "周回の置き場"),
        )
        for label, value, contains in cases:
            with self.subTest(label):
                self.start_unavailable("--sandbox-allow-write", os.path.join(self.root, "cache"),
                                       "--sandbox-allow-write", value,
                                       contains=["--sandbox-allow-write", contains])

    def test_sandbox_allow_write_must_be_absolute(self):
        # 相対パスは、どこを基準にするかで指す場所が変わるので受け付けない。~ の後に名前が続く形 (~ユーザー名) も展開しない
        for value in ("cache", "./cache", "~other/cache"):
            with self.subTest(value):
                self.start_unavailable("--sandbox-allow-write", value,
                                       contains=["--sandbox-allow-write", "絶対パス"])

    def test_extra_args_outside_the_allowed_list(self):
        # AE11: 追加の引数に --add-dir。--settings が JSON でない・enabledPlugins 以外のキーを持つ・値が真偽値の対応でない
        cases = (
            ("--add-dir", ["--add-dir", "/x"], "--add-dir"),
            ("--dangerously-skip-permissions", ["--dangerously-skip-permissions"], "--dangerously-skip-permissions"),
            ("受け付ける引数の後に受け付けない引数", ["--plugin-dir", "/x", "--mcp-config", "{}"], "--mcp-config"),
            ("--plugin-dir の値が無い", ["--plugin-dir"], "--plugin-dir"),
            ("--plugin-dir の値が - で始まる", ["--plugin-dir", "--add-dir"], "--plugin-dir"),
            ("--settings が JSON でない", ["--settings", "settings.json"], "JSON"),
            ("--settings のトップレベルがオブジェクトでない", ["--settings", "[]"], "enabledPlugins"),
            ("--settings に enabledPlugins が無い", ["--settings", "{}"], "enabledPlugins"),
            ("--settings に enabledPlugins 以外のキー",
             ["--settings", json.dumps({"enabledPlugins": {}, "permissions": {"allow": ["Bash"]}})], "permissions"),
            ("enabledPlugins の値が真偽値でない",
             ["--settings", json.dumps({"enabledPlugins": {"review-triage@akm": "false"}})], "真偽値"),
            ("enabledPlugins の値が対応でない",
             ["--settings", json.dumps({"enabledPlugins": ["review-triage@akm"]})], "真偽値"),
        )
        for label, extra, contains in cases:
            with self.subTest(label):
                self.start_unavailable("--", *extra, contains=["追加の引数", contains])

    def test_extra_args_in_the_allowed_list(self):
        # --plugin-dir <ディレクトリ> と、enabledPlugins だけを持つ --settings なら起動する
        plugin = os.path.join(self.root, "plugin")
        os.makedirs(plugin)
        settings = json.dumps({"enabledPlugins": {"review-triage@akm": False, "other@akm": True}})
        self.start_idle("--", "--plugin-dir", plugin, "--settings", settings)

    def test_user_settings_excluded_commands(self):
        # AE11: 利用者の設定に sandbox.excludedCommands がある。JSON として読めない設定も、検査できないので止める
        cases = (
            ("sandbox.excludedCommands がある", {"sandbox": {"excludedCommands": ["docker"]}},
             "sandbox.excludedCommands"),
            ("JSON として読めない", "{ not json", "JSON として読めない"),
            ("トップレベルがオブジェクトでない", "[]", "オブジェクト"),
        )
        for label, content, contains in cases:
            with self.subTest(label):
                self.write_user_settings(content)
                self.start_unavailable(contains=["利用者の設定", contains])

    def test_user_settings_without_excluded_commands(self):
        cases = (
            ("excludedCommands が空", {"sandbox": {"enabled": True, "excludedCommands": []}}),
            ("sandbox が無い", {"permissions": {"allow": ["Read"]}}),
        )
        for label, content in cases:
            with self.subTest(label):
                self.write_user_settings(content)
                self.start_idle()


class TestNetworkNotice(WorkerTestBase):
    """起動時の表示 (worker.md の「起動時の確認」の 15): 利用者の設定の WebFetch(domain:…) の許可は、
    サンドボックスの接続を許すホストに加わるので、それを表示する。止めはしない。"""

    def test_all_hosts(self):
        # AE17
        self.write_user_settings({"permissions": {"allow": ["Read", "WebFetch(domain:*)"]}})
        out, _ = self.start_idle()
        self.assertIn("外のすべてのホストに接続できる", out)

    def test_domains(self):
        self.write_user_settings({"permissions": {"allow": [
            "WebFetch(domain:example.com)", "Bash(ls:*)", "WebFetch(domain:docs.example.org)",
        ]}})
        out, _ = self.start_idle()
        self.assertIn("example.com", out)
        self.assertIn("docs.example.org", out)
        self.assertNotIn("すべてのホスト", out)
        self.assertNotIn("Bash(ls:*)", out)

    def test_no_webfetch_rule(self):
        self.write_user_settings({"permissions": {"allow": ["Read"]}})
        out, _ = self.start_idle()
        self.assertNotIn("WebFetch", out)


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

    def test_sigkill_during_review_leaves_no_worker_processes(self):
        # レビュー中にワーカーを SIGKILL で消すと、ワーカーのプロセスグループ (更新時刻を進める処理と、上限を測る処理) は
        # 10 秒以内に空になる。レビュアの実行は専用のプロセスグループなので残る (trap が動かないので止められない)
        self.env["FAKE_CLAUDE_MODE"] = "hang"
        self.put_request()
        p = self.start()
        self.wait_state("reviewing")
        self.wait_for(lambda: os.path.exists(self.pids_file), what="偽の claude の起動")
        os.kill(p.pid, signal.SIGKILL)
        self.wait_for(lambda: not _group_alive(p.pid), timeout=10,
                      what="ワーカーのプロセスグループが空になる")
        reviewer = _read_pids(self.pids_file)[0]
        self.assertTrue(_pid_alive(reviewer))

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
