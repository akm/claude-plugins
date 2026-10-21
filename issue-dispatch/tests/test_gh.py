#!/usr/bin/env python3
"""`gh` の実行 (issue-dispatch/scripts/issue_dispatch/gh.py) と、偽の `gh` (issue-dispatch/tests/fake-gh) のテスト。

PATH の先頭に偽の `gh` のディレクトリを加えて `gh.run` を実行する。実物の `gh` は使わない。

  python3 -m unittest discover -s issue-dispatch/tests
"""

import json
import os
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import gh  # noqa: E402

_FAKE = os.path.join(_HERE, "fake-gh")
_FIXTURES = os.path.join(_HERE, "fixtures", "gh")


class FakeGhTest(unittest.TestCase):
    """偽の `gh` を PATH の先頭に置き、環境変数で振る舞いを決める。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        os.symlink(_FAKE, os.path.join(self.bin, "gh"))
        self.args_file = os.path.join(self.root, "args.jsonl")
        self.responses_file = os.path.join(self.root, "responses.json")
        self._saved = {k: os.environ.get(k) for k in
                       ("PATH", "FAKE_GH_ARGS", "FAKE_GH_RESPONSES", "FAKE_GH_MODE", "FAKE_GH_SLEEP", "FAKE_GH_EXIT")}
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_GH_ARGS"] = self.args_file
        os.environ["FAKE_GH_RESPONSES"] = self.responses_file
        for k in ("FAKE_GH_MODE", "FAKE_GH_SLEEP", "FAKE_GH_EXIT"):
            os.environ.pop(k, None)
        gh._last_mutation_end = None

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def responses(self, entries):
        with open(self.responses_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)

    def recorded(self):
        with open(self.args_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def fixture(self, name, kind):
        with open(os.path.join(_FIXTURES, f"{name}.{kind}"), encoding="utf-8") as f:
            return f.read()


class RunTest(FakeGhTest):

    def test_passes_args_and_returns_exit_code_and_stderr_tail(self):
        stderr = "\n".join(f"line {i}" for i in range(1, 31)) + "\n"
        self.responses([{"prefix": ["issue", "view"], "stdout": {"number": 1}, "stderr": stderr, "exit": 3}])
        r = gh.run(["issue", "view", "1", "-R", "o/r", "--json", "number"])
        self.assertEqual(self.recorded()[0]["args"], ["issue", "view", "1", "-R", "o/r", "--json", "number"],
                         "引数の配列をそのまま渡すこと")
        self.assertEqual(r["exit_code"], 3)
        self.assertEqual(r["stdout"], '{"number": 1}')
        self.assertEqual(r["json"], {"number": 1}, "標準出力が JSON なら読んだ値を返すこと")
        self.assertEqual(r["stderr_tail"].splitlines(), [f"line {i}" for i in range(11, 31)],
                         f"stderr の末尾 {gh.STDERR_TAIL_LINES} 行を返すこと")
        self.assertFalse(r["timed_out"])
        self.assertEqual(r["failure"], "other")

    def test_success_has_no_failure(self):
        self.responses([{"prefix": ["api", "graphql"], "stdout": {"fixture": "graphql-issue-ok"}}])
        r = gh.run(["api", "graphql", "-f", "query=..."])
        self.assertEqual(r["exit_code"], 0)
        self.assertIsNone(r["failure"])
        self.assertEqual(r["json"]["data"]["repository"]["issue"]["number"], 1)
        self.assertIn("resetAt", r["json"]["data"]["rateLimit"])

    def test_non_json_stdout(self):
        self.responses([{"prefix": ["auth"], "stdout": "Logged in to github.com\n"}])
        r = gh.run(["auth", "status"])
        self.assertIsNone(r["json"])
        self.assertEqual(r["stdout"], "Logged in to github.com\n")

    def test_timeout(self):
        os.environ["FAKE_GH_MODE"] = "hang"
        started = time.monotonic()
        r = gh.run(["api", "graphql"], timeout=0.5)
        self.assertLess(time.monotonic() - started, 5, "タイムアウトで打ち切ること")
        self.assertTrue(r["timed_out"])
        self.assertIsNone(r["exit_code"])
        self.assertEqual(r["failure"], "timeout")

    def test_failure_classification_from_fixtures(self):
        cases = (("auth_expired", "auth"), ("not_logged_in", "auth"), ("rate_limited", "rate_limit"), ("network", "network"))
        for mode, expected in cases:
            with self.subTest(mode=mode):
                os.environ["FAKE_GH_MODE"] = mode
                r = gh.run(["api", "graphql"])
                self.assertNotEqual(r["exit_code"], 0)
                self.assertEqual(r["failure"], expected)
        os.environ.pop("FAKE_GH_MODE")
        self.responses([{"prefix": ["api"], "stdout": {"fixture": "graphql-bad-field"},
                         "stderr": self.fixture("graphql-bad-field", "stderr"), "exit": 1},
                        {"prefix": ["issue"], "stderr": self.fixture("issue-not-found", "stderr"), "exit": 1}])
        self.assertEqual(gh.run(["api", "graphql"])["failure"], "other", "GraphQL のフィールドの誤りは other")
        self.assertEqual(gh.run(["issue", "view", "999"])["failure"], "other", "無い Issue は other")

    def test_classify_uses_stderr_and_stdout(self):
        self.assertEqual(gh.classify(1, "", "gh: Bad credentials (HTTP 401)\n", False), "auth")
        self.assertEqual(gh.classify(1, '{"errors":[{"type":"RATE_LIMITED"}]}', "", False), "rate_limit",
                         "標準出力の errors の type でも分けること")
        self.assertEqual(gh.classify(1, "", 'Post "https://api.github.com/graphql": dial tcp: i/o timeout\n', False), "network")
        self.assertEqual(gh.classify(0, "", "", False), None)
        self.assertEqual(gh.classify(None, "", "", True), "timeout")

    def test_mutation_calls_are_spaced(self):
        self.responses([{"prefix": ["api"], "stdout": "{}"}])
        gh.run(["api", "graphql", "-f", "query=mutation{a}"], mutation=True)
        gh.run(["api", "graphql", "-f", "query=mutation{b}"], mutation=True)
        gh.run(["api", "graphql", "-f", "query=query{c}"])
        times = [rec["time"] for rec in self.recorded()]
        self.assertGreaterEqual(times[1] - times[0], gh.MUTATION_INTERVAL, "変更系の呼び出しは 1 秒以上空けること")
        self.assertLess(times[2] - times[1], gh.MUTATION_INTERVAL, "読むだけの呼び出しは待たないこと")

    def test_rate_limit_reset_at(self):
        self.responses([{"prefix": ["api", "rate_limit"], "stdout": {"fixture": "rate-limit-status"}}])
        self.assertEqual(gh.rate_limit_reset_at(), 1792573722, "graphql の reset (UNIX 時刻) を返すこと")
        os.environ["FAKE_GH_MODE"] = "network"
        self.assertIsNone(gh.rate_limit_reset_at(), "読めなければ None")


class FakeGhBehaviorTest(FakeGhTest):
    """偽の `gh` の応答の指定 (後の単位のテストが使う)。"""

    def test_once_entry_is_used_only_once(self):
        """書き込みの直後に別の値を返す場合: 1 回目は古い値、2 回目から新しい値。"""
        self.responses([{"prefix": ["x"], "stdout": "old", "once": True}, {"prefix": ["x"], "stdout": "new"}])
        self.assertEqual(gh.run(["x"])["stdout"], "old")
        self.assertEqual(gh.run(["x"])["stdout"], "new")
        self.assertEqual(gh.run(["x"])["stdout"], "new")

    def test_contains_and_prefix(self):
        self.responses([{"prefix": ["issue", "view"], "contains": ["--json"], "stdout": "a"},
                        {"prefix": ["issue", "view"], "stdout": "b"}])
        self.assertEqual(gh.run(["issue", "view", "1", "--json", "number"])["stdout"], "a")
        self.assertEqual(gh.run(["issue", "view", "1"])["stdout"], "b")

    def test_unmatched_args_fail_loudly(self):
        self.responses([{"prefix": ["issue"], "stdout": "a"}])
        r = gh.run(["pr", "view"])
        self.assertEqual(r["exit_code"], 99, "指定の漏れを成功と取り違えないこと")
        self.assertEqual(r["failure"], "other")
        self.assertIn("pr", r["stderr_tail"])

    def test_exit_mode(self):
        os.environ["FAKE_GH_MODE"] = "exit"
        os.environ["FAKE_GH_EXIT"] = "7"
        self.assertEqual(gh.run(["anything"])["exit_code"], 7)


class FixturesTest(unittest.TestCase):

    def test_every_fixture_is_listed_in_readme(self):
        with open(os.path.join(_FIXTURES, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        names = {os.path.splitext(n)[0] for n in os.listdir(_FIXTURES) if n.endswith((".stdout", ".stderr"))}
        self.assertTrue(names)
        for name in sorted(names):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", readme, "固定データの表に出所を書くこと")

    def test_real_fixtures_parse(self):
        for name in ("graphql-issue-ok", "graphql-bad-field", "issue-view-ok", "pr-view-ok", "rate-limit-status",
                     "auth-invalid-token", "graphql-rate-limited"):
            with self.subTest(name=name), open(os.path.join(_FIXTURES, f"{name}.stdout"), encoding="utf-8") as f:
                json.load(f)


if __name__ == "__main__":
    unittest.main()
