#!/usr/bin/env python3
"""閉じる前の検査 (close check)・共通の条件のコピーの比較 (checkboxes common)・依存先が片付いたことの書き込み
(dependents plan・dependents resolve) のテスト (計画の U3・KTD9・KTD10・R19・R20・R22・R49・R50)。

偽の gh (ファイル `issue-practice/tests/fake-gh`) で、管理 Issue・作業 Issue・PR を返す。
"""

import os
import unittest

from fakegh_case import FakeGhCase, fixture_json

from issue_practice import bodies, closecheck, mergeplan  # noqa: E402

REPO = "o/r"
LOGIN = "akm"


def issue_url(n):
    return f"https://github.com/{REPO}/issues/{n}"


def pr_url(n):
    return f"https://github.com/{REPO}/pull/{n}"


COMMON = """### すべての作業 Issue に共通するクローズ条件

期待する状態:

- [ ] 自動テストが CI で成功する

確認するポイント:

- [ ] 確認用のリポジトリで実行した
    - 確認の方法: 手で確認する
    - 記録先: 作業 Issue のコメント"""


def managing_body(rows, own="- [x] 作業 Issue がすべて閉じている (根拠: https://github.com/o/r/issues/10#issuecomment-1)",
                  settings=("ブランチの構成: 1", "PR をマージする人: 利用者"), common=COMMON):
    text = "\n".join(f"- {s}" for s in settings) + "\n\n| " + " | ".join(mergeplan.HEADER) + " |\n" \
        + "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(f"| {' | '.join(r)} |" for r in rows) + "\n"
    content = mergeplan.render(mergeplan.parse(text))
    return (f"## 問題\n\n本文\n\n## クローズ条件\n\n<!-- issue-practice:closing-conditions -->\n\n"
            f"### 管理 Issue (#10) 自身のクローズ条件\n\n期待する状態:\n\n{own}\n\n{common}\n\n"
            f"<!-- /issue-practice:closing-conditions -->\n\n## PR マージ計画\n\n<!-- issue-practice:merge-plan -->\n\n"
            f"{content}\n\n<!-- /issue-practice:merge-plan -->\n")


ROWS = [("1", "#12 一つ目", "`feat/12-a`", "main", "なし", pr_url(20)), ("2", "#13 二つ目", "`feat/13-b`", "main", "#12", "")]


def working_body(common_items=("- [x] 自動テストが CI で成功する (根拠: https://github.com/o/r/pull/20)",
                               "- [x] 確認用のリポジトリで実行した (根拠: https://github.com/o/r/issues/12#issuecomment-5)\n"
                               "    - 確認の方法: 手で確認する\n    - 記録先: この Issue のコメント"),
                 own="- [x] 図を作る (切り出し: https://github.com/o/r/issues/30)"):
    expected, verification = common_items
    return (f"作業 Issue の説明\n\n## クローズ条件\n\n### 共通 (#10 の「すべての作業 Issue に共通するクローズ条件」からコピー)\n\n"
            f"期待する状態:\n\n{expected}\n\n確認するポイント:\n\n{verification}\n\n### この作業 Issue に固有の条件\n\n"
            f"期待する状態:\n\n{own}\n")


class CloseCase(FakeGhCase):

    def view_body(self, n, body, state="OPEN"):
        return {"prefix": ["issue", "view", str(n), "-R", REPO, "--json", bodies.ISSUE_FIELDS],
                "stdout": {"number": n, "url": issue_url(n), "state": state, "title": f"#{n}", "body": body,
                           "updatedAt": "2026-11-14T00:00:00Z"}}

    def view_meta(self, n, state="OPEN", milestone=None, blocking=()):
        return {"prefix": ["issue", "view", str(n), "-R", REPO, "--json", closecheck.META_FIELDS],
                "stdout": {"number": n, "url": issue_url(n), "state": state,
                           "milestone": {"number": 1, "title": milestone, "description": "", "dueOn": None} if milestone else None,
                           "blocking": {"nodes": [{"number": b, "url": issue_url(b), "state": s, "title": f"#{b}"}
                                                  for b, s in blocking], "totalCount": len(blocking)}}}

    def pr_view(self, n, state="MERGED", base="main"):
        return {"prefix": ["pr", "view", pr_url(n), "--json", closecheck.PR_FIELDS],
                "stdout": {"number": n, "url": pr_url(n), "state": state, "baseRefName": base, "isDraft": False,
                           "mergedAt": "2026-11-14T00:00:00Z" if state == "MERGED" else None}}

    def working(self, work_body=None, pr_state="MERGED", pr_base="main", work_milestone=None, managing_milestone=None,
                blocking=(), managing=None):
        self.responses([self.view_body(12, work_body or working_body()),
                        self.view_meta(12, milestone=work_milestone, blocking=blocking),
                        self.view_body(10, managing or managing_body(ROWS)),
                        self.view_meta(10, milestone=managing_milestone),
                        self.pr_view(20, state=pr_state, base=pr_base)])
        return self.cli("close", "check", "--issue", f"{REPO}#12", "--role", "working", "--managing", f"{REPO}#10")


class WorkingCheckTest(CloseCase):

    def test_satisfied(self):
        code, out, err = self.working(blocking=[(40, "OPEN"), (41, "CLOSED")])
        self.assertEqual(code, 0, err)
        self.assertTrue(out["satisfied"])
        self.assertEqual(out["unsatisfied"], [])
        self.assertEqual(out["pr"]["url"], pr_url(20))
        self.assertIn(pr_url(20), out["evidence"])
        self.assertIn("https://github.com/o/r/issues/12#issuecomment-5", out["evidence"])
        self.assertIn("https://github.com/o/r/issues/30", out["evidence"], "切り出し済みの項目は満たすとして数える")
        self.assertEqual([b["number"] for b in out["blocking"]], [40], "閉じる Issue を依存先とする開いた Issue を返す")

    def test_unchecked_and_without_evidence(self):
        cases = {
            "チェックが無い": working_body(own="- [ ] 図を作る"),
            "根拠が無い": working_body(own="- [x] 図を作る"),
        }
        for name, body in cases.items():
            with self.subTest(name):
                code, out, _ = self.working(work_body=body)
                self.assertEqual(code, 3)
                self.assertFalse(out["satisfied"])
                self.assertEqual([(u["kind"], u["line"]) for u in out["unsatisfied"]], [("checkbox", 21)])

    def test_pr_not_merged(self):
        for name, kwargs in {"マージされていない": {"pr_state": "OPEN"}, "閉じた": {"pr_state": "CLOSED"},
                             "別のブランチにマージした": {"pr_base": "dev"}}.items():
            with self.subTest(name):
                code, out, _ = self.working(**kwargs)
                self.assertEqual(code, 3)
                self.assertEqual([u["kind"] for u in out["unsatisfied"]], ["pr"])

    def test_no_pr_in_table(self):
        rows = [("1", "#12 一つ目", "`feat/12-a`", "main", "なし", "")]
        self.responses([self.view_body(12, working_body()), self.view_meta(12),
                        self.view_body(10, managing_body(rows)), self.view_meta(10)])
        code, out, _ = self.cli("close", "check", "--issue", f"{REPO}#12", "--role", "working", "--managing", f"{REPO}#10")
        self.assertEqual(code, 3)
        self.assertEqual(out["unsatisfied"][0]["kind"], "pr")
        self.assertIn("PR が無い", out["unsatisfied"][0]["message"])

    def test_outdated_common_copy(self):
        changed = COMMON.replace("自動テストが CI で成功する", "自動テストがあり、CI で成功する")
        code, out, _ = self.working(managing=managing_body(ROWS, common=changed))
        self.assertEqual(code, 3)
        self.assertEqual([u["kind"] for u in out["unsatisfied"]], ["common"])

    def test_milestone_differs_from_managing_issue(self):
        code, out, _ = self.working(work_milestone="R5 (a)", managing_milestone="R6 (b)")
        self.assertEqual(code, 3)
        self.assertEqual([u["kind"] for u in out["unsatisfied"]], ["milestone"])

    def test_gh_failure(self):
        os.environ["FAKE_GH_MODE"] = "rate_limited"
        code, out, _ = self.cli("close", "check", "--issue", f"{REPO}#12", "--role", "working", "--managing", f"{REPO}#10")
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "rate_limit")

    def test_working_needs_managing(self):
        code, out, _ = self.cli("close", "check", "--issue", f"{REPO}#12", "--role", "working")
        self.assertEqual(code, 3)
        self.assertEqual(self.recorded(), [])


class ManagingCheckTest(CloseCase):

    def managing(self, body, states=("CLOSED", "CLOSED"), extra=()):
        self.responses([self.view_body(10, body), self.view_meta(10, blocking=[(50, "OPEN")]),
                        self.view_meta(12, state=states[0]), self.view_meta(13, state=states[1]), *extra])
        return self.cli("close", "check", "--issue", f"{REPO}#10", "--role", "managing")

    def test_all_work_issues_closed(self):
        code, out, err = self.managing(managing_body(ROWS))
        self.assertEqual(code, 0, err)
        self.assertEqual([w["number"] for w in out["work_issues"]], [12, 13])
        self.assertEqual(out["checkboxes"]["counts"]["unchecked"], 0,
                         "節「すべての作業 Issue に共通するクローズ条件」の項目は数えない")
        self.assertEqual([b["number"] for b in out["blocking"]], [50])

    def test_open_work_issue(self):
        code, out, _ = self.managing(managing_body(ROWS), states=("CLOSED", "OPEN"))
        self.assertEqual(code, 3)
        self.assertEqual([(u["kind"], u["url"]) for u in out["unsatisfied"]], [("work-issue", issue_url(13))])

    def test_own_condition_unchecked(self):
        code, out, _ = self.managing(managing_body(ROWS, own="- [ ] 作業 Issue がすべて閉じている"))
        self.assertEqual(code, 3)
        self.assertEqual([u["kind"] for u in out["unsatisfied"]], ["checkbox"])

    def test_config_2_needs_merged_managing_pr(self):
        rows = [(r[0], r[1], r[2], "feat/10-list", r[4], r[5]) for r in ROWS]
        settings = ("ブランチの構成: 2", "PR をマージする人: 利用者", "管理 Issue のブランチ: feat/10-list",
                    "管理 Issue のブランチのマージ先: main")
        code, out, _ = self.managing(managing_body(rows, settings=settings + ("管理 Issue の PR: なし",)))
        self.assertEqual(code, 3)
        self.assertEqual([u["kind"] for u in out["unsatisfied"]], ["managing-pr"])
        os.remove(self.args_file)
        code, out, _ = self.managing(managing_body(rows, settings=settings + (f"管理 Issue の PR: {pr_url(25)}",)),
                                     extra=[self.pr_view(25, state="OPEN")])
        self.assertEqual(code, 3)
        self.assertEqual([u["kind"] for u in out["unsatisfied"]], ["managing-pr"])
        os.remove(self.args_file)
        code, out, err = self.managing(managing_body(rows, settings=settings + (f"管理 Issue の PR: {pr_url(25)}",)),
                                       extra=[self.pr_view(25)])
        self.assertEqual(code, 0, err)


class SelfManagingCheckTest(CloseCase):

    def test_self_managing(self):
        rows = [("1", "#12 自分", "`fix/12-a`", "main", "なし", pr_url(20))]
        body = working_body().replace("### 共通 (#10 の「すべての作業 Issue に共通するクローズ条件」からコピー)", "### 条件") \
            + "\n## PR マージ計画\n\n" + managing_body(rows).split("## PR マージ計画\n\n")[1]
        self.responses([self.view_body(12, body), self.view_meta(12), self.pr_view(20)])
        code, out, err = self.cli("close", "check", "--issue", f"{REPO}#12", "--role", "self-managing")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["pr"]["url"], pr_url(20))

    def test_self_managing_row_must_be_itself(self):
        rows = [("1", "#99 別の Issue", "`fix/99-a`", "main", "なし", pr_url(20))]
        body = working_body() + "\n## PR マージ計画\n\n" + managing_body(rows).split("## PR マージ計画\n\n")[1]
        self.responses([self.view_body(12, body), self.view_meta(12), self.pr_view(20)])
        code, out, _ = self.cli("close", "check", "--issue", f"{REPO}#12", "--role", "self-managing")
        self.assertEqual(code, 3)


class CommonCopiesTest(CloseCase):

    def test_lists_outdated_open_work_issues(self):
        changed = COMMON.replace("自動テストが CI で成功する", "自動テストがあり、CI で成功する")
        rows = ROWS + [("3", "#14 三つ目", "`feat/14-c`", "main", "なし", "")]
        self.responses([self.view_body(10, managing_body(rows, common=changed)), self.view_body(12, working_body()),
                        self.view_body(13, working_body(), state="CLOSED"),
                        self.view_body(14, working_body().replace("自動テストが CI で成功する", "自動テストがあり、CI で成功する"))])
        code, out, err = self.cli("checkboxes", "common", "--issue", f"{REPO}#10")
        self.assertEqual(code, 3, err)
        self.assertEqual([o["number"] for o in out["outdated"]], [12])
        self.assertEqual(out["outdated"][0]["expected"][0], {"group": "expected", "text": "自動テストがあり、CI で成功する"})
        self.assertEqual([s["number"] for s in out["skipped"]], [13], "閉じた作業 Issue は比べない")

    def test_all_up_to_date(self):
        self.responses([self.view_body(10, managing_body(ROWS)), self.view_body(12, working_body()),
                        self.view_body(13, working_body())])
        code, out, err = self.cli("checkboxes", "common", "--issue", f"{REPO}#10")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["outdated"], [])


class RemoveDependencyTest(unittest.TestCase):

    BODY = ("## 問題\n\n困っている。\n\n## 依存先\n\n- #12 の修正を待つ\n    - 補足の行\n- https://github.com/o/r/pull/7 のマージ\n"
            "- #120 の判断\n\n## クローズ条件\n\n- [ ] x\n")

    def test_removes_only_the_item(self):
        ref = {"owner": "o", "repo": "r", "number": 12, "key": "o/r#12", "url": issue_url(12)}
        result = closecheck.remove_dependency(self.BODY, ref, "o/r")
        self.assertEqual(result["removed"], ["- #12 の修正を待つ", "    - 補足の行"])
        self.assertFalse(result["section_removed"])
        self.assertIn("- #120 の判断", result["body"], "#120 は #12 として扱わない")
        self.assertIn("## クローズ条件\n\n- [ ] x\n", result["body"])

    def test_removes_section_when_empty(self):
        body = "## 問題\n\n困っている。\n\n## 依存先\n\n- https://github.com/o/r/issues/12 の修正\n\n## クローズ条件\n\n- [ ] x\n"
        ref = {"owner": "o", "repo": "r", "number": 12, "key": "o/r#12", "url": issue_url(12)}
        result = closecheck.remove_dependency(body, ref, "o/r")
        self.assertTrue(result["section_removed"])
        self.assertEqual(result["body"], "## 問題\n\n困っている。\n\n## クローズ条件\n\n- [ ] x\n")

    def test_other_repository_reference(self):
        body = "## 依存先\n\n- other/x#12 の修正\n- #12 の修正\n"
        ref = {"owner": "other", "repo": "x", "number": 12, "key": "other/x#12", "url": "https://github.com/other/x/issues/12"}
        result = closecheck.remove_dependency(body, ref, "o/r")
        self.assertEqual(result["removed"], ["- other/x#12 の修正"], "別のリポジトリの Issue は #番号 では照合しない")

    def test_no_section(self):
        ref = {"owner": "o", "repo": "r", "number": 12, "key": "o/r#12", "url": issue_url(12)}
        result = closecheck.remove_dependency("## 問題\n\nx\n", ref, "o/r")
        self.assertEqual((result["removed"], result["section_removed"]), ([], False))


class DependentsTest(CloseCase):

    DEPENDENT = "## 問題\n\nx\n\n## 依存先\n\n- #12 の修正を待つ\n\n## クローズ条件\n\n- [ ] y\n"

    def setup(self, state="CLOSED", comments=()):
        self.responses([self.view_meta(12, state=state, blocking=[(40, "OPEN"), (41, "CLOSED")]),
                        self.view_body(40, self.DEPENDENT),
                        {"prefix": ["api", "user"], "stdout": {"login": LOGIN}},
                        {"prefix": ["api", f"repos/{REPO}/issues/40/comments"], "stdout": [list(comments)]},
                        {"prefix": ["issue", "comment"], "stdout": issue_url(40) + "#issuecomment-9\n"},
                        {"prefix": ["issue", "edit"], "stdout": ""}])

    def test_plan(self):
        self.setup()
        code, out, err = self.cli("dependents", "plan", "--issue", f"{REPO}#12")
        self.assertEqual(code, 0, err)
        self.assertEqual([d["number"] for d in out["dependents"]], [40], "閉じた Issue は対象にしない")
        actions = [a["action"] for a in out["dependents"][0]["actions"]]
        self.assertEqual(actions, ["comment", "edit-dependencies"])
        self.assertEqual(out["dependents"][0]["actions"][0]["line"], "issue-practice: dependency-resolved issue=#12")
        self.assertFalse([a for a in self.recorded() if a[:2] in (["issue", "comment"], ["issue", "edit"])])

    def test_resolve(self):
        self.setup()
        code, out, err = self.cli("dependents", "resolve", "--issue", f"{REPO}#12")
        self.assertEqual(code, 0, err)
        comments = [r for r in self.recorded_full() if r["args"][:2] == ["issue", "comment"]]
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0]["stdin"].startswith("issue-practice: dependency-resolved issue=#12\n\n"))
        edits = [r for r in self.recorded_full() if r["args"][:2] == ["issue", "edit"]]
        self.assertEqual(edits[0]["stdin"], "## 問題\n\nx\n\n## クローズ条件\n\n- [ ] y\n")
        self.assertEqual([d["action"] for d in out["done"]], ["comment", "edit-dependencies"])

    def test_resolve_skips_recorded_comment(self):
        self.setup(comments=[{"id": 1, "html_url": issue_url(40) + "#issuecomment-1", "created_at": "x", "updated_at": "x",
                              "body": "issue-practice: dependency-resolved issue=#12\n\n済み", "user": {"login": LOGIN}}])
        code, out, err = self.cli("dependents", "resolve", "--issue", f"{REPO}#12")
        self.assertEqual(code, 0, err)
        self.assertFalse([a for a in self.recorded() if a[:2] == ["issue", "comment"]], "記録が既にあれば書かない")

    def test_resolve_needs_closed_issue(self):
        self.setup(state="OPEN")
        code, out, _ = self.cli("dependents", "resolve", "--issue", f"{REPO}#12")
        self.assertEqual(code, 3)
        self.assertFalse([a for a in self.recorded() if a[:2] in (["issue", "comment"], ["issue", "edit"])])


class FixtureShapeTest(unittest.TestCase):
    """固定データの形が、モジュールが読む形と合うこと。"""

    def test_pr_view(self):
        merged = fixture_json("pr-view-273")
        self.assertEqual(sorted(merged), sorted(closecheck.PR_FIELDS.split(",")))
        self.assertTrue(closecheck.pr_merged(merged))
        self.assertFalse(closecheck.pr_merged(fixture_json("pr-view-48")), "閉じたがマージされていない PR")

    def test_blocking(self):
        data = fixture_json("sandbox-issue-view-blocking")
        self.assertEqual([n["number"] for n in closecheck.open_blocking(data)], [2])


if __name__ == "__main__":
    unittest.main()
