#!/usr/bin/env python3
"""管理 Issue の計画案の解析と、計画案を GitHub に書く「示す」(managing plan) と「実行する」(managing apply) のテスト
(計画の U3・KTD3・KTD5・KTD7・KTD8・R6・R7・R19・R26・R49)。

偽の gh (ファイル `issue-practice/tests/fake-gh`) で、計画する Issue・リポジトリのラベルとマイルストーン・作り済みの Issue を返す。
"""

import os
import re
import unittest

from fakegh_case import HERE, FakeGhCase

from issue_practice import bodies, closecheck, issues, managing, mergeplan  # noqa: E402

REPO = "o/r"
LOGIN = "akm"
NAME = "20261114-1200-managing-issue-plan-10.md"
SELF_NAME = "20261114-1200-managing-issue-plan-12.md"


def url(n):
    return f"https://github.com/{REPO}/issues/{n}"


TARGET_BODY = "## 問題\n\n一覧が使いにくい。\n\n## クローズ条件\n\n決まっていない。\n"
SELF_BODY = "## 問題\n\n誤字がある。\n\n## クローズ条件\n\n- [ ] 誤字が無い\n"

CLOSING = """### 管理 Issue (#10) 自身のクローズ条件

期待する状態:

- [ ] 作業 Issue がすべて閉じている

### すべての作業 Issue に共通するクローズ条件

期待する状態:

- [ ] 自動テストが CI で成功する"""

MERGE = """- ブランチの構成: 1
- PR をマージする人: 利用者

| 順 | 作業 Issue | ブランチ | マージ先 | 先にマージが要る作業 Issue | PR |
| --- | --- | --- | --- | --- | --- |
| 1 | a 一覧の絞り込み | `feat/<番号>-filter` | main | なし | |
| 2 | b 一覧の並べ替え | `feat/<番号>-sort` | main | a | |"""

WORK_BODY = """## 要望

絞り込みたい。

## クローズ条件

### 共通 (#10 の「すべての作業 Issue に共通するクローズ条件」からコピー)

期待する状態:

- [ ] 自動テストが CI で成功する"""


def work_item(key, title, milestone="なし"):
    return (f"### {key}: {title}\n\n- 親 Issue: #10\n- 依存先の Issue: なし\n- マイルストーン: {milestone}\n- ラベル: なし\n\n"
            f"~~~markdown\n{WORK_BODY}\n~~~\n")


def draft_text(target_body=TARGET_BODY, kind="管理 Issue", closing=CLOSING, merge=MERGE, items=None, number=10,
               target=None):
    items = [work_item("a", "一覧の絞り込み"), work_item("b", "一覧の並べ替え")] if items is None else items
    text = (f"# 計画案: 一覧の改善\n\n## 元にした Issue\n\n- {url(number)} 本文の SHA-256: {bodies.body_sha256(target_body)}\n\n"
            f"## 対象\n\n- Issue: {target or url(number)}\n- 種類: {kind}\n\n## クローズ条件\n\n{closing}\n\n"
            f"## PR マージ計画\n\n{merge}\n")
    if items:
        text += "\n## 作る Issue\n\n" + "\n".join(items)
    return text


class ReadTest(unittest.TestCase):

    def test_reads_managing_draft(self):
        parsed = managing.parse(draft_text(), NAME, REPO)
        self.assertEqual(parsed["errors"], [])
        self.assertEqual((parsed["target"]["ref"]["number"], parsed["target"]["kind"]), (10, "管理 Issue"))
        self.assertEqual(parsed["closing"], CLOSING)
        self.assertEqual([r["work"]["key"] for r in parsed["merge_plan"]["rows"]], ["a", "b"])
        self.assertEqual([i["key"] for i in parsed["items"]], ["a", "b"])

    def test_errors(self):
        self_merge = MERGE.split("| 1 |")[0] + "| 1 | #12 誤字 | `fix/12-typo` | main | なし | |"
        cases = {
            "対象が元にした Issue に無い": draft_text(target=url(99)),
            "知らない種類": draft_text(kind="親 Issue"),
            "自己管理 Issue に作る Issue": draft_text(target_body=SELF_BODY, kind="自己管理 Issue", number=12, merge=self_merge,
                                               closing="- [ ] 誤字が無い"),
            "自己管理 Issue の表が自分ではない": draft_text(target_body=SELF_BODY, kind="自己管理 Issue", number=12, items=[],
                                                 closing="- [ ] 誤字が無い"),
            "表のキーが作る Issue に無い": draft_text(items=[work_item("a", "一覧の絞り込み")]),
            "クローズ条件にマーク": draft_text(closing="<!-- issue-practice:closing-conditions -->\n\n- [ ] x"),
            "クローズ条件が空": draft_text(closing=""),
            "節の順序": draft_text().replace("## 対象", "## 対象X"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(managing.parse(text, NAME, REPO)["errors"], name)

    def test_self_managing(self):
        merge = MERGE.split("| 1 |")[0] + "| 1 | #12 誤字 | `fix/12-typo` | main | なし | |"
        parsed = managing.parse(draft_text(target_body=SELF_BODY, kind="自己管理 Issue", number=12, merge=merge, items=[],
                                           closing="- [ ] 誤字が無い\n- [ ] 文書の検査が成功する"), SELF_NAME, REPO)
        self.assertEqual(parsed["errors"], [])
        self.assertEqual(parsed["items"], [])


class ComposeTest(unittest.TestCase):

    def test_managing_wraps_existing_section_and_appends_merge_plan(self):
        new = managing.compose(TARGET_BODY, "管理 Issue", CLOSING, "MERGE")
        self.assertEqual(new, "## 問題\n\n一覧が使いにくい。\n\n## クローズ条件\n\n<!-- issue-practice:closing-conditions -->\n\n"
                              f"{CLOSING}\n\n<!-- /issue-practice:closing-conditions -->\n\n## PR マージ計画\n\n"
                              "<!-- issue-practice:merge-plan -->\n\nMERGE\n\n<!-- /issue-practice:merge-plan -->\n")
        self.assertEqual(managing.compose(new, "管理 Issue", CLOSING, "MERGE"), new, "もう一度書いても変わらない")

    def test_managing_appends_closing_section_when_missing(self):
        new = managing.compose("## 問題\n\nx\n", "管理 Issue", "C", "M")
        self.assertIn("## 問題\n\nx\n\n## クローズ条件\n\n<!-- issue-practice:closing-conditions -->\n\nC\n\n", new)

    def test_replaces_regions_and_keeps_the_rest(self):
        body = ("前\n\n## クローズ条件\n\n<!-- issue-practice:closing-conditions -->\n\n古い\n\n<!-- /issue-practice:closing-conditions -->\n\n"
                "## 経緯\n\n経緯の本文\n\n## PR マージ計画\n\n<!-- issue-practice:merge-plan -->\n\n古い表\n\n"
                "<!-- /issue-practice:merge-plan -->\n\n後ろ\n")
        new = managing.compose(body, "管理 Issue", "C", "M")
        self.assertEqual(new, body.replace("古い表", "M").replace("古い", "C"))

    def test_self_managing_section_has_no_marks(self):
        new = managing.compose(SELF_BODY, "自己管理 Issue", "- [ ] 誤字が無い\n- [ ] 検査", "M")
        self.assertIn("## クローズ条件\n\n- [ ] 誤字が無い\n- [ ] 検査\n\n## PR マージ計画\n\n<!-- issue-practice:merge-plan -->", new)
        self.assertNotIn("closing-conditions", new)
        self.assertIn("error", managing.compose_checked(
            "## クローズ条件\n\n<!-- issue-practice:closing-conditions -->\n\nx\n\n<!-- /issue-practice:closing-conditions -->\n",
            "自己管理 Issue", "C", "M"))


class ManagingCliCase(FakeGhCase):

    def write_draft(self, text, name=NAME):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def github(self, body=TARGET_BODY, number=10, open_issues=(), relations=None, milestone=None, comments=(), extra=()):
        relations = relations or {}
        entries = list(extra) + [
            {"prefix": ["issue", "view", str(number), "-R", REPO, "--json", bodies.ISSUE_FIELDS],
             "stdout": {"number": number, "url": url(number), "state": "OPEN", "title": "対象", "body": body, "updatedAt": "x"}},
            {"prefix": ["issue", "view", str(number), "-R", REPO, "--json", closecheck.META_FIELDS],
             "stdout": {"number": number, "url": url(number), "state": "OPEN",
                        "milestone": {"number": 1, "title": milestone, "description": "", "dueOn": None} if milestone else None,
                        "blocking": {"nodes": [], "totalCount": 0}}},
            {"prefix": ["issue", "view", str(number), "-R", REPO, "--json", "number,url,state,title"],
             "stdout": {"number": number, "url": url(number), "state": "OPEN", "title": "対象"}},
            {"prefix": ["label", "list"], "stdout": [{"name": "bug"}]},
            {"prefix": ["api", f"repos/{REPO}/milestones?state=open&per_page=100"], "stdout": [[
                {"number": 1, "title": "R5 (a)", "description": url(5), "html_url": f"https://github.com/{REPO}/milestone/1",
                 "state": "open"}]]},
            {"prefix": ["api", f"repos/{REPO}/issues?state=open&per_page=100"], "stdout": [[
                {"html_url": url(n), "number": n, "title": key, "state": "open", "user": {"login": LOGIN},
                 "body": f"本文\n\n{issues.created_from_line(NAME, key)}"} for n, key in open_issues]]},
            {"prefix": ["api", "user"], "stdout": {"login": LOGIN}},
            {"prefix": ["api", f"repos/{REPO}/issues/{number}/comments"], "stdout": [list(comments)]},
            {"prefix": ["api"], "substring": "/comments", "stdout": [[]]},
            {"prefix": ["issue", "create"], "contains": ["一覧の絞り込み"], "stdout": url(21) + "\n"},
            {"prefix": ["issue", "create"], "contains": ["一覧の並べ替え"], "stdout": url(22) + "\n"},
            {"prefix": ["issue", "edit"], "stdout": ""},
            {"prefix": ["issue", "comment"], "stdout": url(number) + "#issuecomment-1\n"},
        ]
        for n, rel in relations.items():
            entries.insert(0, {"prefix": ["issue", "view", url(n)], "stdout": {
                "number": n, "url": url(n), "state": "OPEN", "milestone": rel.get("milestone"), "labels": [],
                "parent": rel.get("parent"), "blockedBy": {"nodes": [], "totalCount": 0}}})
        self.responses(entries)

    def writes(self):
        return [r for r in self.recorded_full() if r["args"][:2] in (["issue", "create"], ["issue", "edit"],
                                                                    ["issue", "comment"], ["label", "create"])]


class ManagingPlanTest(ManagingCliCase):

    def test_shows_writes_without_writing(self):
        path = self.write_draft(draft_text())
        self.github()
        code, out, err = self.cli("managing", "plan", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["body_state"], "pending")
        self.assertEqual([i["key"] for i in out["issues"]["items"]], ["a", "b"])
        self.assertIn("| 2 | b 一覧の並べ替え | `feat/<番号>-sort` | main | a | |", out["merge_plan"]["content"])
        self.assertFalse(out["approval_recorded"])
        self.assertEqual(self.writes(), [], "示すときは書き込まない")

    def test_changed_body_is_unsatisfied(self):
        path = self.write_draft(draft_text())
        self.github(body=TARGET_BODY + "\n追記\n")
        code, out, _ = self.cli("managing", "plan", path, "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertEqual(out["body_state"], "changed")

    def test_milestone_must_match_target(self):
        path = self.write_draft(draft_text())
        self.github(milestone="R5 (a)")
        code, out, _ = self.cli("managing", "plan", path, "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertTrue(any("マイルストーン" in e["message"] for e in out["errors"]))


class ManagingApplyTest(ManagingCliCase):

    def test_creates_issues_and_writes_body(self):
        path = self.write_draft(draft_text())
        self.github()
        code, out, err = self.cli("managing", "apply", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        creates = [r for r in self.writes() if r["args"][:2] == ["issue", "create"]]
        self.assertEqual(len(creates), 2)
        body_edits = [r for r in self.writes() if r["args"] == ["issue", "edit", url(10), "--body-file", "-"]]
        self.assertEqual(len(body_edits), 1)
        written = body_edits[0]["stdin"]
        self.assertIn("<!-- issue-practice:closing-conditions -->\n\n" + CLOSING, written)
        self.assertIn("| 1 | #21 一覧の絞り込み | `feat/21-filter` | main | なし | |", written,
                      "キーを作った Issue の番号に、ブランチの <番号> を番号に置き換える")
        self.assertIn("| 2 | #22 一覧の並べ替え | `feat/22-sort` | main | #21 | |", written)
        region = mergeplan.read_region(written)
        self.assertEqual(region["errors"], [])
        self.assertEqual(mergeplan.extract_graph(region["content"]), mergeplan.graph(region))
        comments = [r for r in self.writes() if r["args"][:2] == ["issue", "comment"]]
        self.assertEqual([c["args"][2] for c in comments], [url(21), url(22), url(10)],
                         "作った作業 Issue と、計画した Issue に approval の記録を書く")
        self.assertTrue(comments[-1]["stdin"].startswith(f"issue-practice: approval draft={NAME}\n\n"))
        self.assertEqual([d["action"] for d in out["done"] if d["action"] in ("write-body", "record-approval")],
                         ["record-approval", "record-approval", "write-body", "record-approval"])

    def test_retry_after_everything_was_written(self):
        path = self.write_draft(draft_text())
        self.github()
        self.cli("managing", "apply", path, "--repo", REPO)
        written = [r for r in self.writes() if r["args"] == ["issue", "edit", url(10), "--body-file", "-"]][0]["stdin"]
        os.remove(self.args_file)
        approval = {"id": 1, "html_url": url(10) + "#issuecomment-1", "created_at": "x", "updated_at": "x",
                    "body": f"issue-practice: approval draft={NAME}\n\n承認", "user": {"login": LOGIN}}
        work_approval = lambda n: {"prefix": ["api", f"repos/{REPO}/issues/{n}/comments"], "stdout": [[  # noqa: E731
            {**approval, "html_url": url(n) + "#issuecomment-2"}]]}
        self.github(body=written, open_issues=[(21, "a"), (22, "b")],
                    relations={21: {"parent": {"url": url(10)}}, 22: {"parent": {"url": url(10)}}},
                    comments=[approval], extra=[work_approval(21), work_approval(22)])
        code, out, err = self.cli("managing", "plan", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["body_state"], "applied")
        code, out, err = self.cli("managing", "apply", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [], "書き込み済みなら何も書かない")

    def test_changed_body_writes_nothing(self):
        path = self.write_draft(draft_text())
        self.github(body=TARGET_BODY + "\n追記\n")
        code, out, _ = self.cli("managing", "apply", path, "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertEqual(self.writes(), [], "本文が変わっていれば、作業 Issue も作らない")

    def test_self_managing(self):
        merge = MERGE.split("| 1 |")[0] + "| 1 | #12 誤字 | `fix/12-typo` | main | なし | |"
        path = self.write_draft(draft_text(target_body=SELF_BODY, kind="自己管理 Issue", number=12, merge=merge, items=[],
                                           closing="- [ ] 誤字が無い\n- [ ] 文書の検査が成功する"), name=SELF_NAME)
        self.github(body=SELF_BODY, number=12)
        code, out, err = self.cli("managing", "apply", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        written = [r for r in self.writes() if r["args"][:2] == ["issue", "edit"]][0]["stdin"]
        self.assertIn("## クローズ条件\n\n- [ ] 誤字が無い\n- [ ] 文書の検査が成功する\n\n## PR マージ計画", written)
        self.assertIn("| 1 | #12 誤字 | `fix/12-typo` | main | なし | |", written)
        self.assertFalse([r for r in self.writes() if r["args"][:2] == ["issue", "create"]])


class DocTest(unittest.TestCase):
    """文書 `issue-practice/skills/managing-issue-plan/references/merge-plan.md` の計画案の節が、モジュールの定数と一致すること。"""

    def test_sections_and_fields(self):
        path = os.path.join(HERE, "..", "skills", "managing-issue-plan", "references", "merge-plan.md")
        with open(path, encoding="utf-8") as f:
            doc = f.read()
        table_text = doc.split("| 節 | 書くこと |\n| --- | --- |\n")[1].split("\n\n")[0]
        self.assertEqual(tuple(line.split("|")[1].strip() for line in table_text.splitlines()), managing.SECTIONS)
        first = table_text.splitlines()[0]
        self.assertEqual(tuple(re.findall(r"項目「([^」]+)」", first)), managing.TARGET_FIELDS)
        self.assertEqual(tuple(re.findall(r"`([^`]+)`", first)), managing.KINDS)


if __name__ == "__main__":
    unittest.main()
