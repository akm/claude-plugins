#!/usr/bin/env python3
"""`gh` の実行 (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/gh.py`) と、偽の `gh`
(ファイル `gh-notification-dispatch/tests/fake-gh`) のテスト。

PATH の先頭に偽の `gh` のディレクトリを加えて `gh.run` を実行する。実物の `gh` は使わない。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import json
import os
import time
import unittest

from fakegh_case import FIXTURES, FakeGhCase, fixture, http, link_next

from gh_notification_dispatch import gh  # noqa: E402


class RunTest(FakeGhCase):

    def test_passes_args_and_returns_exit_code_and_stderr_tail(self):
        stderr = "\n".join(f"line {i}" for i in range(1, 31)) + "\n"
        self.responses([{"prefix": ["api", "repos/o/r"], "stdout": {"full_name": "o/r"}, "stderr": stderr, "exit": 3}])
        r = gh.run(["api", "repos/o/r"])
        self.assertEqual(self.recorded()[0], ["api", "repos/o/r"], "引数の配列をそのまま渡すこと")
        self.assertEqual(r["exit_code"], 3)
        self.assertEqual(r["json"], {"full_name": "o/r"}, "標準出力が JSON なら読んだ値を返すこと")
        self.assertEqual(r["stderr_tail"].splitlines(), [f"line {i}" for i in range(11, 31)],
                         f"stderr の末尾 {gh.STDERR_TAIL_LINES} 行を返すこと")
        self.assertFalse(r["timed_out"])
        self.assertEqual(r["failure"], "other")

    def test_success_has_no_failure(self):
        self.responses([{"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}}])
        r = gh.run(["api", "user"], expect_json=True)
        self.assertEqual(r["exit_code"], 0)
        self.assertIsNone(r["failure"])
        self.assertFalse(gh.failed(r))
        self.assertEqual(r["json"]["login"], "akm")

    def test_non_json_stdout(self):
        self.responses([{"prefix": ["auth"], "stdout": "Logged in to github.com\n"},
                        {"prefix": ["api", "notifications", "--paginate"], "stdout": '[{"a":1}][{"a":2}]'},
                        {"prefix": ["api", "x"], "stdout": ""}])
        r = gh.run(["auth", "status"])
        self.assertIsNone(r["json"])
        self.assertIsNone(r["json_error"], "JSON を期待しない呼び出しでは json_error を入れないこと")
        r = gh.run(["api", "notifications", "--paginate"], expect_json=True)
        self.assertEqual((r["exit_code"], r["failure"], r["json"]), (0, None, None))
        self.assertTrue(r["json_error"], "--paginate のつないだ JSON は読めないことを返すこと (--slurp と一緒に使う)")
        self.assertTrue(gh.failed(r), "JSON を期待したのに読めなければ失敗として扱うこと")
        r = gh.run(["api", "x"])
        self.assertEqual((r["json"], r["json_error"]), (None, None), "空の出力では json_error も None")

    def test_stdin_is_not_passed(self):
        self.responses([{"prefix": ["api"], "stdout": "{}"}])
        gh.run(["api", "user"])
        self.assertEqual(self.recorded_full()[0]["stdin"], "", "標準入力は /dev/null にすること")

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
        r = gh.run(["api", "user"])
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
                         "stderr": fixture("graphql-bad-field", "stderr"), "exit": 1}])
        self.assertEqual(gh.run(["api", "graphql"])["failure"], "other", "GraphQL のフィールドの誤りは other")

    def test_not_found_from_fixture(self):
        """読めないリポジトリ (存在しない名前) の API は 404 を返し、gh は終了コード 1 で終了する (計画の U1 の 7)。"""
        self.responses([{"prefix": ["api", "repos/akm/no-such-repo"], "stdout": {"fixture": "repo-not-found"},
                         "stderr": fixture("repo-not-found", "stderr"), "exit": 1}])
        r = gh.run(["api", "repos/akm/no-such-repo"], expect_json=True)
        self.assertEqual(r["exit_code"], 1)
        self.assertEqual(r["failure"], "not_found")
        self.assertTrue(gh.failed(r))

    def test_user_text_in_stdout_does_not_change_classification(self):
        """標準出力の data (利用者の文字列) に「rate limit」や「gh auth login」があっても、分類は stderr と errors[].type で決まる。"""
        title = "Please handle the rate limit and run gh auth login first"
        self.responses([{"prefix": ["api", "graphql"],
                         "stdout": {"data": {"repository": {"pullRequest": {"title": title}}},
                                    "errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a PullRequest"}]},
                         "stderr": "gh: Could not resolve to a PullRequest (repository.pullRequest)\n", "exit": 1}])
        self.assertEqual(gh.run(["api", "graphql", "-f", "query=x"])["failure"], "other")

    def test_classify_uses_stderr_and_graphql_error_types(self):
        self.assertEqual(gh.classify(1, "", "gh: Bad credentials (HTTP 401)\n", False), "auth")
        self.assertEqual(gh.classify(1, "", "gh: Not Found (HTTP 404)\n", False), "not_found")
        self.assertEqual(gh.classify(1, '{"title":"Not Found (HTTP 404)"}', "gh: boom\n", False), "other",
                         "標準出力の文字列の 404 では not_found にしないこと")
        self.assertEqual(gh.classify(1, '{"errors":[{"type":"RATE_LIMITED"}]}', "", False), "rate_limit",
                         "標準出力の errors[].type でも分けること")
        self.assertEqual(gh.classify(1, '{"data":{"x":"Bad credentials HTTP 401 rate limit"}}', "gh: boom\n", False), "other",
                         "標準出力の data の文字列では分けないこと")
        self.assertEqual(gh.classify(1, "", 'Post "https://api.github.com/graphql": dial tcp: i/o timeout\n', False), "network")
        self.assertEqual(gh.classify(1, '{"errors": null}', "gh: x\n", False), "other", "errors が配列でなくても例外にしないこと")
        self.assertEqual(gh.classify(0, "", "", False), None)
        self.assertEqual(gh.classify(None, "", "", True), "timeout")


class GetTest(FakeGhCase):
    """`gh api -i` での GET (状態コードとヘッダ) と、一覧のページ送り (計画の KTD4・KTD5)。"""

    def test_status_headers_and_json(self):
        self.responses([{"prefix": ["api", "-i", "user"],
                         "stdout": http(200, {"login": "akm"}, {"Etag": 'W/"abc"', "X-Poll-Interval": "60"})}])
        r = gh.get("user", headers={"If-None-Match": '"x"'})
        self.assertEqual(self.recorded()[0], ["api", "-i", "user", "-H", 'If-None-Match: "x"'])
        self.assertEqual((r["status"], r["json"], r["failure"]), (200, {"login": "akm"}, None))
        self.assertEqual(r["headers"]["etag"], 'W/"abc"', "ヘッダのキーは小文字にすること")
        self.assertFalse(gh.failed(r))

    def test_not_modified_is_not_failure(self):
        """gh は 304 でも終了コード 1 を返すが、失敗にしない (計画の U1)。"""
        self.responses([{"prefix": ["api", "-i", "notifications"], "stdout": {"fixture": "notifications-not-modified"},
                         "stderr": fixture("notifications-not-modified", "stderr"), "exit": 1}])
        r = gh.get("notifications")
        self.assertEqual((r["status"], r["exit_code"], r["failure"], r["json"]), (304, 1, None, None))
        self.assertFalse(gh.failed(r))

    def test_not_found(self):
        self.responses([{"prefix": ["api", "-i"], "stdout": http(404, {"message": "Not Found"}),
                         "stderr": fixture("repo-not-found", "stderr"), "exit": 1}])
        r = gh.get("repos/akm/no-such-repo/issues/1/timeline")
        self.assertEqual((r["status"], r["failure"]), (404, "not_found"))
        self.assertTrue(gh.failed(r))

    def test_missing_status_line_or_bad_json(self):
        self.responses([{"prefix": ["api", "-i", "a"], "stdout": '{"x": 1}'},
                        {"prefix": ["api", "-i", "b"], "stdout": "HTTP/2.0 200 OK\n\nnot json"}])
        self.assertIn("状態行", gh.get("a")["json_error"])
        self.assertIn("JSON", gh.get("b")["json_error"])

    def test_get_all_follows_next_link(self):
        self.responses([
            {"prefix": ["api", "-i", "notifications?all=true&per_page=50"],
             "stdout": http(200, [{"id": "1"}, {"id": "2"}], {"Etag": 'W/"e1"',
                                                              "Link": link_next("notifications?all=true&per_page=50&page=2")})},
            {"prefix": ["api", "-i", "notifications?all=true&per_page=50&page=2"], "stdout": http(200, [{"id": "3"}])},
        ])
        items, first, failure = gh.get_all("notifications?all=true&per_page=50", headers={"If-None-Match": 'W/"e0"'})
        self.assertIsNone(failure)
        self.assertEqual([i["id"] for i in items], ["1", "2", "3"])
        self.assertEqual(first["headers"]["etag"], 'W/"e1"')
        calls = self.recorded()
        self.assertEqual(calls[1], ["api", "-i", "notifications?all=true&per_page=50&page=2"],
                         "2 ページ目は、Link の URL から API_ORIGIN を除いたパスで、条件のヘッダを付けずに読むこと")

    def test_get_all_not_modified(self):
        self.responses([{"prefix": ["api", "-i"], "stdout": {"fixture": "notifications-not-modified"},
                         "stderr": "gh: HTTP 304\n", "exit": 1}])
        items, first, failure = gh.get_all("notifications", headers={"If-None-Match": 'W/"e"'})
        self.assertEqual((items, first["status"], failure), (None, 304, None))
        self.assertEqual(len(self.recorded()), 1)

    def test_get_all_failure_on_later_page(self):
        self.responses([
            {"prefix": ["api", "-i", "x?per_page=100"], "stdout": http(200, [1], {"Link": link_next("x?per_page=100&page=2")})},
            {"prefix": ["api", "-i", "x?per_page=100&page=2"], "stdout": "", "stderr": "gh: Bad credentials (HTTP 401)\n",
             "exit": 1},
        ])
        items, first, failure = gh.get_all("x?per_page=100")
        self.assertIsNone(items)
        self.assertEqual(first["status"], 200)
        self.assertEqual(failure["failure"], "auth")
        self.assertEqual(failure["args"][2], "x?per_page=100&page=2", "失敗したページの呼び出しを返すこと")

    def test_get_all_rejects_non_list_and_other_host(self):
        self.responses([{"prefix": ["api", "-i", "a"], "stdout": http(200, {"not": "list"})},
                        {"prefix": ["api", "-i", "b"],
                         "stdout": http(200, [1], {"Link": '<https://example.com/b?page=2>; rel="next"'})}])
        self.assertIn("配列でない", gh.get_all("a")[2]["json_error"])
        self.assertIn("api.github.com", gh.get_all("b")[2]["json_error"])

    def test_get_all_page_limit(self):
        self.responses([{"prefix": ["api", "-i"], "stdout": http(200, [1], {"Link": link_next("loop?page=2")})}])
        original = gh.MAX_PAGES
        gh.MAX_PAGES = 3
        try:
            items, _, failure = gh.get_all("loop")
        finally:
            gh.MAX_PAGES = original
        self.assertIsNone(items)
        self.assertIn("3 を超えた", failure["json_error"])
        self.assertEqual(len(self.recorded()), 3)


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
        """1 回目と 2 回目で別の値を返す場合: 1 回目は古い値、2 回目から新しい値。"""
        self.responses([{"prefix": ["x"], "stdout": "old", "once": True}, {"prefix": ["x"], "stdout": "new"}])
        self.assertEqual(gh.run(["x"])["stdout"], "old")
        self.assertEqual(gh.run(["x"])["stdout"], "new")

    def test_contains_and_prefix(self):
        self.responses([{"prefix": ["api", "notifications"], "contains": ["-i"], "stdout": "a"},
                        {"prefix": ["api", "notifications"], "stdout": "b"}])
        self.assertEqual(gh.run(["api", "notifications", "-i"])["stdout"], "a")
        self.assertEqual(gh.run(["api", "notifications"])["stdout"], "b")

    def test_unmatched_args_fail_loudly(self):
        self.responses([{"prefix": ["api"], "stdout": "a"}])
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
        names = sorted(os.path.splitext(n)[0] for n in os.listdir(FIXTURES) if n.endswith(".stdout"))
        for name in names:
            with self.subTest(name=name), open(os.path.join(FIXTURES, f"{name}.stdout"), encoding="utf-8") as f:
                text = f.read()
                if text.startswith("HTTP/"):  # gh api -i の出力は、空の行の後の本文だけを JSON として読む
                    text = text.split("\n\n", 1)[1]
                if text.strip():
                    json.loads(text)


if __name__ == "__main__":
    unittest.main()
