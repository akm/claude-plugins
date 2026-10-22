#!/usr/bin/env python3
"""Issue と PR の読み書き (issue-dispatch/scripts/issue_dispatch/issues.py) と、CLI の `issue create` / `issue add-label` /
`blocked-by add` / `pr observe` のテスト。偽の gh (fake-gh) と固定データ (fixtures/gh/pr-observe-*・issue-list-open・
label-list・api-user) で動く。偽の gh の用意は test_project.FakeGhCase と同じ。

  python3 -m unittest discover -s issue-dispatch/tests

様式の正本は issue-dispatch/skills/issue-dispatch/references/issue-format.md。
"""

import json
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _HERE)  # test_project の FakeGhCase を使う (discover でなく、ファイルのパスで実行したときのため)

from issue_dispatch import ids, issues  # noqa: E402
from test_project import FakeGhCase, fixture_json  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "issue-format.md")
REPO = "akm/issue-dispatch-verify-a"
PR4 = f"https://github.com/{REPO}/pull/4"
ISSUE3 = f"https://github.com/{REPO}/issues/3"
DECLARATION = f"https://github.com/{REPO}/issues/3#issuecomment-3500000001"

USER_ENTRY = {"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}}


def pr_entry(name):
    return {"substring": "query PrObserve", "stdout": {"fixture": name}}


def cli(*args):
    r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr


class PrRefTest(unittest.TestCase):

    def test_parse_pr_url(self):
        self.assertEqual(ids.parse_pr_url(PR4), {"repo": REPO, "number": 4, "url": PR4})
        self.assertEqual(ids.parse_pr_url(PR4 + "/"), {"repo": REPO, "number": 4, "url": PR4})
        self.assertIsNone(ids.parse_pr_url(ISSUE3), "Issue の URL は PR の参照ではない")
        self.assertIsNone(ids.parse_pr_url(f"{REPO}#4"), "PR には owner/repo#番号 の形を使わない (Issue と区別できない)")
        self.assertIsNone(ids.parse_pr_url(None))


class ObservePrTest(FakeGhCase):

    def test_merged_pr_with_open_issue(self):
        """Covers AE7, AE58. マージ済みの PR が参照する Issue が開いたままなら種類 merged_issue_open を返し、書き込みは無い。"""
        self.responses([USER_ENTRY, pr_entry("pr-observe-merged")])
        result = issues.observe_pr(PR4)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "merged_issue_open")
        pr = result["pr"]
        self.assertEqual((pr["number"], pr["state"], pr["draft"], pr["author"], pr["base_ref"]), (4, "MERGED", False, "akm", "main"))
        self.assertEqual(pr["issues"], [{"key": f"{REPO}#1", "number": 1, "url": f"https://github.com/{REPO}/issues/1", "state": "OPEN"}])
        self.assertEqual(pr["files"], [{"path": "u1-1.txt", "additions": 1, "deletions": 0, "change_type": "ADDED"}])
        self.assertEqual(result["rate_limit"]["cost"], 1)
        calls = self.recorded_full()
        self.assertEqual([c["args"][:2] for c in calls], [["api", "user"], ["api", "graphql"]], "読むだけで、書き込みの gh は実行しないこと")
        self.assertEqual(self.body(calls[1])["variables"], {"owner": "akm", "name": "issue-dispatch-verify-a", "number": 4})

    def test_merged_pr_with_closed_issue(self):
        data = fixture_json("pr-observe-merged")
        data["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"][0]["state"] = "CLOSED"
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": data}])
        self.assertEqual(issues.observe_pr(PR4)["kind"], "merged")

    def test_merged_pr_without_reference(self):
        """参照する Issue が無いマージ済みの PR は merged (何もしない) ではなく merged_without_reference (Issue はマージで閉じない)。"""
        data = fixture_json("pr-observe-merged")
        data["data"]["repository"]["pullRequest"]["closingIssuesReferences"] = {"totalCount": 0, "nodes": []}
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": data}])
        result = issues.observe_pr(PR4)
        self.assertEqual(result["kind"], "merged_without_reference")
        self.assertEqual(result["pr"]["issues"], [])

    def test_closed_pr(self):
        self.responses([USER_ENTRY, pr_entry("pr-observe-closed")])
        result = issues.observe_pr(f"https://github.com/{REPO}/pull/5")
        self.assertEqual(result["kind"], "closed")
        self.assertEqual(result["pr"]["issues"][0]["state"], "CLOSED")

    def test_open_pr_without_closing_reference(self):
        """Covers AE6. closingIssuesReferences に Issue が無い PR は「本文の追記が要る」(needs_closing_reference) を返す。"""
        self.responses([USER_ENTRY, pr_entry("pr-observe-open-other-base")])
        result = issues.observe_pr(f"https://github.com/{REPO}/pull/6")
        self.assertEqual(result["kind"], "needs_closing_reference")
        self.assertEqual(result["pr"]["issues"], [])
        self.assertEqual(result["pr"]["base_ref"], "other-base")

    def _open_pr(self, draft, with_issue=True):
        data = fixture_json("pr-observe-open-other-base")
        pr = data["data"]["repository"]["pullRequest"]
        pr["isDraft"] = draft
        if with_issue:
            pr["closingIssuesReferences"] = {"totalCount": 1, "nodes": [
                {"number": 3, "url": ISSUE3, "state": "OPEN", "repository": {"nameWithOwner": REPO}}]}
        return data

    def test_draft_pr_is_not_in_review(self):
        """Covers AE6. draft は参照があっても In review にしない。"""
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": self._open_pr(draft=True)}])
        result = issues.observe_pr(f"https://github.com/{REPO}/pull/6")
        self.assertEqual(result["kind"], "draft")
        self.assertTrue(result["pr"]["draft"])

    def test_ready_pr_with_reference_is_in_review(self):
        """Covers AE6. ready for review で参照がある PR は In review を返す。"""
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": self._open_pr(draft=False)}])
        result = issues.observe_pr(f"https://github.com/{REPO}/pull/6")
        self.assertEqual(result["kind"], "in_review")
        self.assertEqual(result["pr"]["issues"][0]["key"], f"{REPO}#3")

    def test_other_author_is_treated_as_absent(self):
        """Covers AE28. 作者のログインがトークンのログインと違う PR は、無いものとして扱う (中身を返さない)。"""
        data = fixture_json("pr-observe-merged")
        data["data"]["repository"]["pullRequest"]["author"] = {"login": "someone-else"}
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": data}])
        result = issues.observe_pr(PR4)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kind"], "other_author")
        self.assertIsNone(result["pr"])
        self.assertEqual(result["author"], "someone-else")

    def test_login_given_skips_api_user(self):
        self.responses([pr_entry("pr-observe-merged")])
        result = issues.observe_pr(PR4, login="akm")
        self.assertEqual(result["kind"], "merged_issue_open")
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["api", "graphql"]])

    def test_files_follow_pages(self):
        page1 = fixture_json("pr-observe-merged")
        pr = page1["data"]["repository"]["pullRequest"]
        pr["files"] = {"totalCount": 2, "pageInfo": {"hasNextPage": True, "endCursor": "C1"},
                       "nodes": [{"path": "a.txt", "additions": 1, "deletions": 0, "changeType": "ADDED"}]}
        page2 = json.loads(json.dumps(page1))
        page2["data"]["repository"]["pullRequest"]["files"] = {"totalCount": 2, "pageInfo": {"hasNextPage": False, "endCursor": None},
                                                               "nodes": [{"path": "b.txt", "additions": 0, "deletions": 1, "changeType": "DELETED"}]}
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": page1, "once": True},
                        {"substring": "query PrObserve", "stdout": page2}])
        result = issues.observe_pr(PR4)
        self.assertEqual([f["path"] for f in result["pr"]["files"]], ["a.txt", "b.txt"])
        self.assertEqual(self.body(self.recorded_full()[2])["variables"]["filesCursor"], "C1")

    def test_missing_pr(self):
        data = fixture_json("pr-observe-merged")
        data["data"]["repository"]["pullRequest"] = None
        data["errors"] = [{"type": "NOT_FOUND", "message": "Could not resolve to a PullRequest with the number of 999."}]
        self.responses([USER_ENTRY, {"substring": "query PrObserve", "stdout": data}])
        result = issues.observe_pr(f"https://github.com/{REPO}/pull/999")
        self.assertEqual(result["status"], "error")
        self.assertIn("999", result["message"])

    def test_bad_url_does_not_run_gh(self):
        result = issues.observe_pr(ISSUE3)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.recorded(), [])

    def test_gh_failure(self):
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        result = issues.observe_pr(PR4)
        self.assertEqual((result["status"], result["failure"]), ("error", "auth"))


class CreateIssueTest(FakeGhCase):

    NEW_URL = f"https://github.com/{REPO}/issues/7"

    def _entries(self, open_issues=None):
        return [{"prefix": ["issue", "list"], "stdout": open_issues if open_issues is not None else {"fixture": "issue-list-open"}},
                {"prefix": ["issue", "create"], "stdout": self.NEW_URL + "\n"}]

    def test_first_line_format(self):
        self.assertEqual(issues.split_from_line(DECLARATION), f"split-from: {DECLARATION}")
        self.assertIsNone(issues.split_from_line(ISSUE3), "宣言のコメントの URL (#issuecomment-<id> 付き) だけを受け付ける")
        self.assertIsNone(issues.split_from_line(f"{REPO}#3"))

    def test_creates_issue_with_first_line(self):
        """Covers AE44. 本文の先頭行に分割の元を書いて Issue を作り、番号を返す。Status と sub-issue は書かない。"""
        self.responses(self._entries())
        result = issues.create_issue(REPO, "分けた部分", "本文の 1 行目\n2 行目", DECLARATION, labels=["resource:verify"], assignees=["akm"])
        self.assertEqual(result, {"status": "ok", "created": True, "number": 7, "url": self.NEW_URL})
        calls = self.recorded_full()
        self.assertEqual(calls[0]["args"][:2], ["issue", "list"])
        self.assertIn("--state", calls[0]["args"])
        self.assertEqual(calls[0]["args"][calls[0]["args"].index("--state") + 1], "open")
        create = calls[1]["args"]
        self.assertEqual(create[:2], ["issue", "create"])
        self.assertEqual(create[create.index("-R") + 1], REPO)
        self.assertEqual(create[create.index("--title") + 1], "分けた部分")
        self.assertEqual(create[create.index("--body") + 1], f"split-from: {DECLARATION}\n\n本文の 1 行目\n2 行目")
        self.assertEqual(create[create.index("--label") + 1], "resource:verify")
        self.assertEqual(create[create.index("--assignee") + 1], "akm")
        self.assertEqual([c["args"][:2] for c in calls], [["issue", "list"], ["issue", "create"]], "project や sub-issue の書き込みは無いこと")

    def test_reuses_open_issue_with_same_first_line(self):
        """Covers AE44. 同じ先頭行を持つ開いた Issue が既にあれば作らずにその番号を返す (再開のときに 2 つ作らない)。"""
        existing = fixture_json("issue-list-open")
        existing[0]["body"] = f"split-from: {DECLARATION}\n\n前に作ったときの本文"
        self.responses(self._entries(existing))
        result = issues.create_issue(REPO, "分けた部分", "本文", DECLARATION)
        self.assertEqual(result, {"status": "ok", "created": False, "number": existing[0]["number"], "url": existing[0]["url"]})
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["issue", "list"]], "issue create を実行しないこと")

    def test_first_line_must_match_exactly(self):
        existing = fixture_json("issue-list-open")
        existing[0]["body"] = f"split-from: {DECLARATION}0\n\n別の宣言から作った Issue"
        self.responses(self._entries(existing))
        self.assertTrue(issues.create_issue(REPO, "t", "b", DECLARATION)["created"])

    def test_bad_split_from_does_not_run_gh(self):
        result = issues.create_issue(REPO, "t", "b", ISSUE3)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.recorded(), [])

    def test_list_failure_does_not_create(self):
        self.responses([{"prefix": ["issue", "list"], "stdout": "", "stderr": "GraphQL: Could not resolve to a Repository", "exit": 1}])
        result = issues.create_issue(REPO, "t", "b", DECLARATION)
        self.assertEqual(result["status"], "error")
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["issue", "list"]], "一覧が読めなければ作らない (2 つ作りうるため)")

    def test_create_failure(self):
        self.responses([{"prefix": ["issue", "list"], "stdout": []},
                        {"prefix": ["issue", "create"], "stdout": "", "stderr": "GraphQL: Resource not accessible by integration", "exit": 1}])
        result = issues.create_issue(REPO, "t", "b", DECLARATION)
        self.assertEqual(result["status"], "error")
        self.assertIn("not accessible", result["message"])


class AddBlockedByTest(FakeGhCase):

    def test_adds_with_urls(self):
        self.responses([{"prefix": ["issue", "edit"], "stdout": ISSUE3 + "\n"}])
        result = issues.add_blocked_by(f"{REPO}#3", f"{REPO}#1")
        self.assertEqual(result, {"status": "ok", "issue": f"{REPO}#3", "blocker": f"{REPO}#1"})
        args = self.recorded()[0]
        self.assertEqual(args, ["issue", "edit", ISSUE3, "--add-blocked-by", f"https://github.com/{REPO}/issues/1"],
                         "Issue も blocker も URL の形で渡すこと (--add-blocked-by は URL の形だけを受け付ける。U1)")

    def test_failure_is_returned_without_retry(self):
        self.responses([{"prefix": ["issue", "edit"], "stdout": "", "stderr": "GraphQL: Could not resolve to an Issue with the number of 999.", "exit": 1}])
        result = issues.add_blocked_by(ISSUE3, f"{REPO}#999")
        self.assertEqual((result["status"], result["exit_code"]), ("error", 1))
        self.assertIn("999", result["message"])
        self.assertEqual(len(self.recorded()), 1, "失敗しても再試行しないこと")

    def test_bad_ref_does_not_run_gh(self):
        result = issues.add_blocked_by(ISSUE3, PR4)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.recorded(), [])


class AddLabelTest(FakeGhCase):

    @staticmethod
    def view_entry(names):
        return {"prefix": ["issue", "view"], "stdout": {"labels": [{"name": n} for n in names]}}

    def test_creates_missing_label_then_adds(self):
        """リポジトリにラベルが無ければ先に作ってから Issue に足す。"""
        self.responses([self.view_entry(["bug"]), {"prefix": ["label", "list"], "stdout": {"fixture": "label-list"}},
                        {"prefix": ["label", "create"], "stdout": "✓ Label \"resource:db\" created in akm/issue-dispatch-verify-a\n"},
                        {"prefix": ["issue", "edit"], "stdout": ISSUE3 + "\n"}])
        result = issues.add_label(ISSUE3, "resource:db", description="DB を使う")
        self.assertEqual(result, {"status": "ok", "issue": f"{REPO}#3", "label": "resource:db", "label_created": True, "added": True})
        calls = self.recorded()
        self.assertEqual([c[:2] for c in calls], [["issue", "view"], ["label", "list"], ["label", "create"], ["issue", "edit"]])
        create = calls[2]
        self.assertEqual(create[2], "resource:db")
        self.assertEqual(create[create.index("--description") + 1], "DB を使う")
        self.assertNotIn("--color", create, "色は gh のデフォルトに任せる")
        self.assertEqual(calls[3], ["issue", "edit", ISSUE3, "--add-label", "resource:db"])

    def test_existing_label_is_not_created(self):
        self.responses([self.view_entry([]), {"prefix": ["label", "list"], "stdout": {"fixture": "label-list"}},
                        {"prefix": ["issue", "edit"], "stdout": ISSUE3 + "\n"}])
        result = issues.add_label(ISSUE3, "resource:verify")
        self.assertEqual((result["label_created"], result["added"]), (False, True))
        self.assertEqual([c[:2] for c in self.recorded()], [["issue", "view"], ["label", "list"], ["issue", "edit"]])

    def test_already_attached_does_nothing(self):
        """既に付いていれば何もしない (ラベルの一覧も読まない)。"""
        self.responses([self.view_entry(["resource:verify", "bug"])])
        result = issues.add_label(f"{REPO}#3", "resource:verify")
        self.assertEqual((result["label_created"], result["added"]), (False, False))
        self.assertEqual([c[:2] for c in self.recorded()], [["issue", "view"]])

    def test_label_names_compare_case_insensitively(self):
        """GitHub はラベルの名前を大文字小文字を区別せずに一意にするので、綴りだけ違うラベルがあれば作らずにその綴りで足す。"""
        self.responses([self.view_entry(["bug"]), {"prefix": ["label", "list"], "stdout": [{"name": "Resource:DB"}]},
                        {"prefix": ["issue", "edit"], "stdout": ISSUE3 + "\n"}])
        result = issues.add_label(ISSUE3, "resource:db")
        self.assertEqual((result["label"], result["label_created"], result["added"]), ("Resource:DB", False, True))
        calls = self.recorded()
        self.assertEqual([c[:2] for c in calls], [["issue", "view"], ["label", "list"], ["issue", "edit"]], "label create を実行しないこと")
        self.assertEqual(calls[2][calls[2].index("--add-label") + 1], "Resource:DB", "既にある綴りで足すこと")

    def test_attached_label_compares_case_insensitively(self):
        self.responses([self.view_entry(["Resource:DB"])])
        result = issues.add_label(ISSUE3, "resource:db")
        self.assertEqual((result["label"], result["added"]), ("Resource:DB", False))
        self.assertEqual([c[:2] for c in self.recorded()], [["issue", "view"]])

    def test_label_create_failure_stops(self):
        self.responses([self.view_entry([]), {"prefix": ["label", "list"], "stdout": []},
                        {"prefix": ["label", "create"], "stdout": "", "stderr": "HTTP 403: Resource not accessible", "exit": 1}])
        result = issues.add_label(ISSUE3, "human-handed")
        self.assertEqual(result["status"], "error")
        self.assertEqual([c[:2] for c in self.recorded()], [["issue", "view"], ["label", "list"], ["label", "create"]], "作れなければ足さない")


class CliTest(FakeGhCase):

    def test_pr_observe(self):
        self.responses([USER_ENTRY, pr_entry("pr-observe-merged")])
        code, out, _ = cli("pr", "observe", "--url", PR4)
        self.assertEqual(code, 0)
        self.assertEqual((out["status"], out["kind"], out["pr"]["number"], out["errors"]), ("ok", "merged_issue_open", 4, []))

    def test_pr_observe_bad_url(self):
        code, out, _ = cli("pr", "observe", "--url", ISSUE3)
        self.assertEqual((code, out["status"]), (0, "error"))
        self.assertEqual(out["errors"][0]["key"], "url")

    def test_issue_create(self):
        self.responses([{"prefix": ["issue", "list"], "stdout": []}, {"prefix": ["issue", "create"], "stdout": f"https://github.com/{REPO}/issues/8\n"}])
        code, out, _ = cli("issue", "create", "--repo", REPO, "--title", "t", "--body", "本文", "--split-from", DECLARATION,
                           "--label", "resource:verify", "--assignee", "akm")
        self.assertEqual((code, out["status"], out["created"], out["number"]), (0, "ok", True, 8))
        create = self.recorded()[1]
        self.assertEqual(create[create.index("--body") + 1], f"split-from: {DECLARATION}\n\n本文")

    def test_issue_create_body_from_stdin(self):
        self.responses([{"prefix": ["issue", "list"], "stdout": []}, {"prefix": ["issue", "create"], "stdout": f"https://github.com/{REPO}/issues/8\n"}])
        r = subprocess.run([sys.executable, _CLI, "issue", "create", "--repo", REPO, "--title", "t", "--body-file", "-", "--split-from", DECLARATION],
                           input="標準入力の本文\n", capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout)["number"], 8)
        create = self.recorded()[1]
        self.assertEqual(create[create.index("--body") + 1], f"split-from: {DECLARATION}\n\n標準入力の本文\n")

    def test_blocked_by_add(self):
        self.responses([{"prefix": ["issue", "edit"], "stdout": ISSUE3 + "\n"}])
        code, out, _ = cli("blocked-by", "add", "--issue", f"{REPO}#3", "--blocker", f"{REPO}#1")
        self.assertEqual((code, out["status"], out["blocker"]), (0, "ok", f"{REPO}#1"))

    def test_blocked_by_add_failure(self):
        self.responses([{"prefix": ["issue", "edit"], "stdout": "", "stderr": "GraphQL: Could not resolve to an Issue", "exit": 1}])
        code, out, _ = cli("blocked-by", "add", "--issue", f"{REPO}#3", "--blocker", f"{REPO}#999")
        self.assertEqual((code, out["status"]), (0, "error"))
        self.assertEqual(out["errors"][0]["key"], "blocked-by")

    def test_issue_add_label(self):
        self.responses([{"prefix": ["issue", "view"], "stdout": {"labels": []}}, {"prefix": ["label", "list"], "stdout": {"fixture": "label-list"}},
                        {"prefix": ["issue", "edit"], "stdout": ISSUE3 + "\n"}])
        code, out, _ = cli("issue", "add-label", "--issue", ISSUE3, "--label", "resource:verify")
        self.assertEqual((code, out["status"], out["added"], out["label_created"]), (0, "ok", True, False))


class DocTest(unittest.TestCase):

    def test_doc_lists_kinds_and_first_line(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for kind in issues.PR_KINDS:
            self.assertIn(f"`{kind}`", doc, f"pr observe の種類 {kind} が文書に無い")
        self.assertIn("`split-from: ", doc)


if __name__ == "__main__":
    unittest.main()
