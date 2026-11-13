#!/usr/bin/env python3
"""`gh` の実行 (ファイル `issue-practice/scripts/issue_practice/gh.py`) と、偽の `gh` (ファイル `issue-practice/tests/fake-gh`) のテスト。

PATH の先頭に偽の `gh` のディレクトリを加えて `gh.run` を実行する。実物の `gh` は使わない。

  python3 -m unittest discover -s issue-practice/tests
"""

import json
import os
import subprocess
import sys
import time
import unittest

from fakegh_case import FIXTURES, SCRIPTS, FakeGhCase, fixture

from issue_practice import gh  # noqa: E402


class RunTest(FakeGhCase):

    def test_passes_args_and_returns_exit_code_and_stderr_tail(self):
        stderr = "\n".join(f"line {i}" for i in range(1, 31)) + "\n"
        self.responses([{"prefix": ["issue", "view"], "stdout": {"number": 1}, "stderr": stderr, "exit": 3}])
        r = gh.run(["issue", "view", "1", "-R", "o/r", "--json", "number"])
        self.assertEqual(self.recorded()[0], ["issue", "view", "1", "-R", "o/r", "--json", "number"],
                         "引数の配列をそのまま渡すこと")
        self.assertEqual(r["exit_code"], 3)
        self.assertEqual(r["json"], {"number": 1}, "標準出力が JSON なら読んだ値を返すこと")
        self.assertEqual(r["stderr_tail"].splitlines(), [f"line {i}" for i in range(11, 31)],
                         f"stderr の末尾 {gh.STDERR_TAIL_LINES} 行を返すこと")
        self.assertFalse(r["timed_out"])
        self.assertEqual(r["failure"], "other")

    def test_success_has_no_failure(self):
        self.responses([{"prefix": ["issue", "view"], "stdout": {"fixture": "issue-view-266"}}])
        r = gh.run(["issue", "view", "266", "-R", "akm/claude-plugins", "--json", "number,body"], expect_json=True)
        self.assertEqual(r["exit_code"], 0)
        self.assertIsNone(r["failure"])
        self.assertFalse(gh.failed(r))
        self.assertEqual(r["json"]["number"], 266)

    def test_non_json_stdout(self):
        self.responses([{"prefix": ["auth"], "stdout": "Logged in to github.com\n"},
                        {"prefix": ["api", "repos/o/r/issues", "--paginate"], "stdout": '[{"a":1}][{"a":2}]'},
                        {"prefix": ["api", "x"], "stdout": ""}])
        r = gh.run(["auth", "status"])
        self.assertIsNone(r["json"])
        self.assertIsNone(r["json_error"], "JSON を期待しない呼び出しでは json_error を入れないこと")
        r = gh.run(["api", "repos/o/r/issues", "--paginate"], expect_json=True)
        self.assertEqual((r["exit_code"], r["failure"], r["json"]), (0, None, None))
        self.assertTrue(r["json_error"], "--paginate のつないだ JSON は読めないことを返すこと (--slurp と一緒に使う)")
        self.assertTrue(gh.failed(r), "JSON を期待したのに読めなければ失敗として扱うこと")
        r = gh.run(["api", "x"])
        self.assertEqual((r["json"], r["json_error"]), (None, None), "空の出力では json_error も None")

    def test_timeout(self):
        os.environ["FAKE_GH_MODE"] = "hang"
        started = time.monotonic()
        r = gh.run(["api", "graphql"], timeout=0.5)
        self.assertLess(time.monotonic() - started, 5, "タイムアウトで打ち切ること")
        self.assertTrue(r["timed_out"])
        self.assertIsNone(r["exit_code"])
        self.assertEqual(r["failure"], "timeout")

    def test_gh_not_on_path(self):
        os.environ["PATH"] = os.path.join(self.root, "empty-bin")
        os.makedirs(os.environ["PATH"])
        r = gh.run(["issue", "view", "1"])
        self.assertEqual(r["failure"], "missing", "gh が無ければ例外ではなく失敗の種類を返すこと")
        self.assertIsNone(r["exit_code"])
        self.assertIn("gh", r["stderr_tail"])

    def test_other_os_error_is_not_missing(self):
        """gh が入っていても起きる起動の失敗 (引数が長すぎる) は missing にしない。"""
        r = gh.run(["api", "x" * 3_000_000])
        self.assertEqual(r["failure"], "other")
        self.assertIsNone(r["exit_code"])
        self.assertIn("gh を起動できない", r["stderr_tail"])

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
                         "stderr": fixture("graphql-bad-field", "stderr"), "exit": 1},
                        {"prefix": ["issue"], "stderr": fixture("issue-not-found", "stderr"), "exit": 1}])
        self.assertEqual(gh.run(["api", "graphql"])["failure"], "other", "GraphQL のフィールドの誤りは other")
        self.assertEqual(gh.run(["issue", "view", "999"])["failure"], "other", "無い Issue は other")

    def test_user_text_in_stdout_does_not_change_classification(self):
        """標準出力の data (利用者の文字列) に「rate limit」や「gh auth login」があっても、分類は stderr と errors[].type で決まる。"""
        body = "Please handle the rate limit and run gh auth login first"
        self.responses([{"prefix": ["api", "graphql"],
                         "stdout": {"data": {"repository": {"issue": {"body": body}}},
                                    "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to an Issue"}]},
                         "stderr": "gh: Could not resolve to an Issue (repository.issue2)\n", "exit": 1}])
        self.assertEqual(gh.run(["api", "graphql", "-f", "query=x"])["failure"], "other")

    def test_classify_uses_stderr_and_graphql_error_types(self):
        self.assertEqual(gh.classify(1, "", "gh: Bad credentials (HTTP 401)\n", False), "auth")
        self.assertEqual(gh.classify(1, '{"errors":[{"type":"RATE_LIMITED"}]}', "", False), "rate_limit",
                         "標準出力の errors[].type でも分けること")
        self.assertEqual(gh.classify(1, '{"data":{"x":"Bad credentials HTTP 401 rate limit"}}', "gh: boom\n", False), "other",
                         "標準出力の data の文字列では分けないこと")
        self.assertEqual(gh.classify(1, "", 'Post "https://api.github.com/graphql": dial tcp: i/o timeout\n', False), "network")
        self.assertEqual(gh.classify(1, '{"errors": null}', "gh: x\n", False), "other", "errors が配列でなくても例外にしないこと")
        self.assertEqual(gh.classify(0, "", "", False), None)
        self.assertEqual(gh.classify(None, "", "", True), "timeout")

    def test_mutation_calls_are_spaced(self):
        self.responses([{"prefix": ["api"], "stdout": "{}"}])
        gh.run(["api", "graphql", "-f", "query=mutation{a}"], mutation=True)
        gh.run(["api", "graphql", "-f", "query=mutation{b}"], mutation=True)
        started = time.monotonic()
        gh.run(["api", "graphql", "-f", "query=query{c}"])
        times = [rec["time"] for rec in self.recorded_full()]
        self.assertGreaterEqual(times[1] - times[0], gh.MUTATION_INTERVAL, "変更系の呼び出しは 1 秒以上空けること")
        self.assertLess(time.monotonic() - started, gh.MUTATION_INTERVAL, "読むだけの呼び出しは待機しないこと")

    def test_mutation_spacing_holds_across_processes(self):
        """CLI はサブコマンドごとに 1 プロセスなので、別のプロセスで続けて変更系を実行しても 1 秒以上空く。"""
        self.responses([{"prefix": ["api"], "stdout": "{}"}])
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from issue_practice import gh; "
                "gh.run(['api', 'graphql', '-f', 'query=mutation{x}'], mutation=True)")
        for _ in range(2):
            subprocess.run([sys.executable, "-c", code, SCRIPTS], check=True, env=dict(os.environ))
        times = [rec["time"] for rec in self.recorded_full()]
        self.assertGreaterEqual(times[1] - times[0], gh.MUTATION_INTERVAL)

    def test_stdin_is_passed(self):
        self.responses([{"prefix": ["issue", "edit"], "substring": "新しい本文", "stdout": ""}])
        r = gh.run(["issue", "edit", "1", "--body-file", "-"], stdin="新しい本文\n")
        self.assertIsNone(r["failure"])
        self.assertEqual(self.recorded_full()[0]["stdin"], "新しい本文\n")


class ViewerLoginTest(FakeGhCase):

    def test_reads_login(self):
        self.responses([{"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}}])
        self.assertEqual(gh.viewer_login(), ("akm", None))

    def test_failure_is_returned(self):
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        login, result = gh.viewer_login()
        self.assertIsNone(login)
        self.assertEqual(result["failure"], "auth")

    def test_missing_login_is_failure(self):
        self.responses([{"prefix": ["api", "user"], "stdout": {"id": 1}}])
        login, result = gh.viewer_login()
        self.assertIsNone(login)
        self.assertTrue(result["json_error"], "login の無い応答を読めたことにしないこと")


class FakeGhBehaviorTest(FakeGhCase):
    """偽の `gh` の応答の指定 (後の単位のテストが使う)。"""

    def test_once_entry_is_used_only_once(self):
        """書き込みの直後に別の値を返す場合: 1 回目は古い値、2 回目から新しい値。"""
        self.responses([{"prefix": ["x"], "stdout": "old", "once": True}, {"prefix": ["x"], "stdout": "new"}])
        self.assertEqual(gh.run(["x"])["stdout"], "old")
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

    def test_exit_mode(self):
        os.environ["FAKE_GH_MODE"] = "exit"
        os.environ["FAKE_GH_EXIT"] = "7"
        self.assertEqual(gh.run(["anything"])["exit_code"], 7)


class FixturesTest(unittest.TestCase):

    def test_every_fixture_is_listed_in_readme(self):
        with open(os.path.join(FIXTURES, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        names = {os.path.splitext(n)[0] for n in os.listdir(FIXTURES) if n.endswith((".stdout", ".stderr"))}
        self.assertTrue(names)
        for name in sorted(names):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", readme, "固定データの表に出所を書くこと")

    def test_json_fixtures_parse(self):
        for name in ("graphql-bad-field", "graphql-rate-limited", "auth-invalid-token", "api-user",
                     "issue-view-266", "issue-view-239", "issue-comments-266"):
            with self.subTest(name=name), open(os.path.join(FIXTURES, f"{name}.stdout"), encoding="utf-8") as f:
                json.load(f)


if __name__ == "__main__":
    unittest.main()
