#!/usr/bin/env python3
"""記録のコメント (ファイル `issue-practice/scripts/issue_practice/records.py`) のテスト。"""

import os
import unittest

from fakegh_case import FakeGhCase, fixture_json

from issue_practice import records  # noqa: E402

SESSION_ID = "local_89aab7c6-87c8-432f-97dc-4de4f3bc345d"

# 種類ごとの、すべてのキーを書いた値の例
EXAMPLES = {
    "session": {"role": "working", "session": SESSION_ID, "branch": "feat/266-issue-practice-base", "previous": "local_1"},
    "approval": {"draft": "20261114-0010-managing-issue-plan-239.md"},
    "plan-change": {"draft": "20261114-0010-managing-issue-plan-239.md"},
    "report": {"type": "pr", "pr": "https://github.com/akm/claude-plugins/pull/271"},
    "draft-removed": {"date": "2026-11-14", "draft": "20261114-0010-release-issue-plan-285.md"},
    "current-swap": {"date": "2026-11-14", "old": "#280"},
    "release-start": {},
    "dependency-resolved": {"issue": "akm/claude-plugins#266"},
    "close-check": {"result": "pass"},
    "abandon": {"session": SESSION_ID},
    "created-from": {"draft": "20261114-0010-new-issue-next.md", "key": "u1"},
}


def comment(body, login="akm", id=1):
    return {"id": id, "html_url": f"https://github.com/o/r/issues/1#issuecomment-{id}", "created_at": "2026-11-14T00:00:00Z",
            "updated_at": "2026-11-14T00:00:00Z", "body": body, "user": {"login": login, "type": "User"}}


class LineTest(unittest.TestCase):

    def test_every_kind_has_an_example(self):
        self.assertEqual(set(EXAMPLES), set(records.KINDS))

    def test_round_trip(self):
        """1 行目を生成して解析すると、元の値に戻る。"""
        for kind, values in EXAMPLES.items():
            with self.subTest(kind=kind):
                line = records.format_line(kind, values)["line"]
                self.assertEqual(records.parse_line(line), {"kind": kind, "values": values})
                spec = records.KINDS[kind]
                required_only = {k: values[k] for k in spec["required"]}
                line = records.format_line(kind, required_only)["line"]
                self.assertEqual(records.parse_line(line), {"kind": kind, "values": required_only}, "必須のキーだけでもよい")

    def test_format_orders_keys(self):
        line = records.format_line("session", {"branch": "b", "session": "s1", "role": "managing"})["line"]
        self.assertEqual(line, "issue-practice: session role=managing session=s1 branch=b")

    def test_existing_session_comment_parses(self):
        """管理セッションが U1 の前に書いた session の記録 (1 行目) が、この形で読める。"""
        body = fixture_json("issue-comments-266")[0][0]["body"]
        parsed = records.parse_line(body.split("\n", 1)[0])
        self.assertEqual(parsed["kind"], "session")
        self.assertEqual(parsed["values"]["session"], SESSION_ID)

    def test_errors(self):
        cases = {
            "知らない種類": "issue-practice: unknown x=1",
            "知らないキー": "issue-practice: approval draft=20261114-0010-new-issue-1.md extra=1",
            "必須のキーが無い": "issue-practice: session role=working",
            "値の形": "issue-practice: session role=boss session=s1",
            "日付": "issue-practice: draft-removed date=2026-13-01",
            "日付の書き方": "issue-practice: draft-removed date=20261114",
            "同じキー": "issue-practice: close-check result=pass result=fail",
            "キーと値の形ではない": "issue-practice: close-check pass",
            "空の値": "issue-practice: close-check result=",
            "PR ではない URL": "issue-practice: report type=pr pr=https://github.com/o/r/issues/1",
            "Issue の参照ではない": "issue-practice: dependency-resolved issue=https://github.com/o/r/issues/1",
            "計画案のファイル名ではない": "issue-practice: approval draft=plan.md",
            "種類が無い": "issue-practice:",
            "接頭辞が無い": "session role=working session=s1",
        }
        for label, line in cases.items():
            with self.subTest(label=label):
                r = records.parse_line(line)
                self.assertIn("errors", r)
                self.assertTrue(r["errors"])
        self.assertIn("errors", records.format_line("session", {"role": "working"}))
        self.assertIn("errors", records.format_line("close-check", {"result": "a b"}), "値に空白を入れないこと")

    def test_where(self):
        self.assertIn("errors", records.parse_line(records.format_line("created-from", EXAMPLES["created-from"])["line"],
                                                   where="comment"))
        self.assertIn("errors", records.format_line("approval", EXAMPLES["approval"], where="body"))
        self.assertNotIn("errors", records.format_line("created-from", EXAMPLES["created-from"], where="body"))


class CollectTest(unittest.TestCase):

    def test_skips_other_authors_and_non_records(self):
        comments = [
            comment("issue-practice: close-check result=pass\n\n確認した。", id=1),
            comment("issue-practice: close-check result=fail\n\n第三者が書いた。", login="someone", id=2),
            comment("普通のコメント\nissue-practice: close-check result=pass", id=3),
            comment("issue-practice: unknown\n", id=4),
            comment("issue-practice: approval draft=20261114-0010-new-issue-1.md\r\n\r\n承認した。", login="AKM", id=5),
        ]
        r = records.collect(comments, "akm")
        self.assertEqual([(x["kind"], x["id"]) for x in r["records"]], [("close-check", 1), ("approval", 5)])
        self.assertEqual(r["records"][0]["body"], "確認した。")
        self.assertEqual(r["records"][1]["body"], "承認した。", "1 行目と続く空行を除くこと")
        self.assertEqual([x["id"] for x in r["invalid"]], [4])
        self.assertEqual(r["skipped_other_authors"], 1)

    def test_comment_without_user(self):
        self.assertEqual(records.collect([{"id": 1, "body": "issue-practice: release-start"}], "akm")["records"], [])


class RecordsCliTest(FakeGhCase):

    def entries(self, comments_stdout=None):
        return [{"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}},
                {"prefix": ["api", "repos/akm/claude-plugins/issues/266/comments"],
                 "stdout": comments_stdout if comments_stdout is not None else {"fixture": "issue-comments-266"}}]

    def test_list(self):
        self.responses(self.entries())
        code, out, _ = self.cli("records", "list", "--issue", "https://github.com/akm/claude-plugins/issues/266")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["login"], "akm")
        self.assertEqual([r["kind"] for r in out["records"]], ["session"])
        self.assertEqual(out["records"][0]["values"]["branch"], "feat/266-issue-practice-base")
        self.assertIn(["api", "repos/akm/claude-plugins/issues/266/comments", "--paginate", "--slurp"], self.recorded())

    def test_list_filters_kind_and_flattens_pages(self):
        pages = [[comment("issue-practice: release-start", id=1)], [comment("issue-practice: close-check result=pass", id=2)]]
        self.responses(self.entries(pages))
        code, out, _ = self.cli("records", "list", "--issue", "akm/claude-plugins#266", "--kind", "close-check")
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in out["records"]], [2])

    def test_invalid_record_is_exit_3(self):
        self.responses(self.entries([[comment("issue-practice: session role=working", id=9)]]))
        code, out, _ = self.cli("records", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 3)
        self.assertEqual(out["invalid"][0]["id"], 9)

    def test_gh_failure_is_exit_4(self):
        for mode in ("network", "auth_expired"):
            with self.subTest(mode=mode):
                os.environ["FAKE_GH_MODE"] = mode
                code, out, _ = self.cli("records", "list", "--issue", "akm/claude-plugins#266")
                self.assertEqual(code, 4)
                self.assertTrue(out["gh_error"]["failure"])

    def test_unexpected_shape_is_exit_4(self):
        self.responses(self.entries({"message": "x"}))
        code, out, _ = self.cli("records", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 4)
        self.assertTrue(out["gh_error"]["json_error"])

    def test_format_and_parse(self):
        code, out, _ = self.cli("records", "format", "report", "type=pr", "pr=https://github.com/akm/claude-plugins/pull/271")
        self.assertEqual(code, 0)
        self.assertEqual(out["line"], "issue-practice: report type=pr pr=https://github.com/akm/claude-plugins/pull/271")
        code, out, _ = self.cli("records", "parse", out["line"])
        self.assertEqual((code, out["kind"]), (0, "report"))
        code, out, _ = self.cli("records", "format", "report")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])
        code, out, _ = self.cli("records", "format", "created-from", "draft=20261114-0010-new-issue-1.md", "key=a")
        self.assertEqual(code, 3, "本文の行の種類は、コメントの 1 行目としては作らないこと")
        code, out, _ = self.cli("records", "format", "created-from", "draft=20261114-0010-new-issue-1.md", "key=a", "--body-line")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
