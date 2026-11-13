#!/usr/bin/env python3
"""計画案の節「作る Issue」の解析と、Issue を作る「示す」(issues plan) と「実行する」(issues create) のテスト (計画の U2)。

偽の gh (ファイル `issue-practice/tests/fake-gh`) で、リポジトリのラベル・マイルストーン・Issue を返す。
"""

import os
import re
import unittest

from fakegh_case import HERE, FakeGhCase, fixture, fixture_json

from issue_practice import issues  # noqa: E402

REPO = "o/r"
LOGIN = "akm"
DRAFT_NAME = "20261114-1200-new-issue-carve-out.md"


def url(number):
    return f"https://github.com/{REPO}/issues/{number}"


def item(key, title, parent="なし", blocked="なし", milestone="なし", labels="なし", body="## 問題\n\n困っている。"):
    return (f"### {key}: {title}\n\n- 親 Issue: {parent}\n- 依存先の Issue: {blocked}\n- マイルストーン: {milestone}\n"
            f"- ラベル: {labels}\n\n~~~markdown\n{body}\n~~~\n")


def draft_text(*items, sources="- なし"):
    return "# 計画案: 切り出し\n\n## 元にした Issue\n\n" + sources + "\n\n## 作る Issue\n\n" + "\n".join(items)


THREE = [
    item("a", "一つ目", parent="#239", blocked="#12", milestone="R5 (確認用のリリース)", labels="bug"),
    item("b", "二つ目", parent="#239", body="## 問題\n\n```sh\necho x\n```\n\n## 依存先\n\n- https://github.com/o/r/pull/7 のマージ"),
    item("c", "三つ目", labels="no-release"),
]


class ParseItemsTest(unittest.TestCase):

    def test_reads_items(self):
        parsed = issues.parse_items(draft_text(*THREE), REPO)
        self.assertEqual(parsed["errors"], [])
        a, b, c = parsed["items"]
        self.assertEqual((a["key"], a["title"], a["parent"]["key"], [r["key"] for r in a["blocked_by"]], a["milestone"],
                          a["labels"]), ("a", "一つ目", "o/r#239", ["o/r#12"], "R5 (確認用のリリース)", ["bug"]))
        self.assertIn("## 依存先", b["body"], "本文の中の見出しは、計画案の節の区切りとして扱わない")
        self.assertIn("```sh", b["body"])
        self.assertEqual((c["parent"], c["blocked_by"], c["milestone"], c["labels"]), (None, [], None, ["no-release"]))

    def test_errors_have_line_numbers(self):
        cases = {
            "項目が足りない": "### a: x\n\n- 親 Issue: なし\n\n~~~markdown\nb\n~~~\n",
            "項目の順序が違う": "### a: x\n\n- 依存先の Issue: なし\n- 親 Issue: なし\n- マイルストーン: なし\n- ラベル: なし\n\n~~~markdown\nb\n~~~\n",
            "本文が閉じていない": "### a: x\n\n- 親 Issue: なし\n- 依存先の Issue: なし\n- マイルストーン: なし\n- ラベル: なし\n\n~~~markdown\nb\n",
            "本文が無い": "### a: x\n\n- 親 Issue: なし\n- 依存先の Issue: なし\n- マイルストーン: なし\n- ラベル: なし\n",
            "同じキー": item("a", "x") + item("a", "y"),
            "依存先が PR": item("a", "x", blocked="https://github.com/o/r/pull/7"),
            "マイルストーンと no-release": item("a", "x", milestone="R5 (a)", labels="no-release"),
            "見出しの形が違う": "### 題名だけ\n",
        }
        for name, section in cases.items():
            with self.subTest(name):
                parsed = issues.parse_items(draft_text(section), REPO)
                self.assertTrue(parsed["errors"])
                self.assertTrue(all(e["line"] for e in parsed["errors"]), parsed["errors"])

    def test_missing_section(self):
        parsed = issues.parse_items("# 計画案: x\n\n## 元にした Issue\n\n- なし\n", REPO)
        self.assertEqual(parsed["errors"][0]["line"], None)

    def test_created_from(self):
        line = issues.created_from_line(DRAFT_NAME, "a")
        self.assertEqual(line, f"issue-practice: created-from draft={DRAFT_NAME} key=a")
        self.assertEqual(issues.created_from(f"本文\n\n{line}\n"), {"draft": DRAFT_NAME, "key": "a"})
        self.assertIsNone(issues.created_from(f"{line}\n\n後ろに行がある"))
        self.assertIsNone(issues.created_from(None))


class IssuesCliCase(FakeGhCase):

    def write_draft(self, text, name=DRAFT_NAME):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def github(self, open_issues=(), relations=None, labels=("bug", "enhancement"), extra=()):
        """リポジトリの今の状態を返す応答を設定する。open_issues は作り済みの Issue (番号, キー) の配列、
        relations は作り済みの Issue の番号から関係 (milestone・labels・parent・blockedBy) への辞書。extra は先頭に足す応答。"""
        relations = relations or {}
        entries = list(extra)
        entries += [
            {"prefix": ["label", "list"], "stdout": [{"name": n} for n in labels]},
            {"prefix": ["api", f"repos/{REPO}/milestones?state=open&per_page=100"], "stdout": [[
                {"number": 1, "title": "R5 (確認用のリリース)", "description": url(5), "html_url": f"https://github.com/{REPO}/milestone/1",
                 "state": "open"}]]},
            {"prefix": ["api", f"repos/{REPO}/issues?state=open&per_page=100"], "stdout": [[
                {"html_url": url(n), "number": n, "title": key, "state": "open", "user": {"login": LOGIN},
                 "body": f"本文\n\n{issues.created_from_line(DRAFT_NAME, key)}"} for n, key in open_issues]
                + [{"html_url": f"https://github.com/{REPO}/pull/7", "number": 7, "title": "PR", "state": "open",
                    "body": "", "pull_request": {"html_url": f"https://github.com/{REPO}/pull/7"}}]]},
            {"prefix": ["api", "user"], "stdout": {"login": LOGIN}},
        ]
        for n, rel in relations.items():
            entries.append({"prefix": ["issue", "view", url(n)], "stdout": {
                "number": n, "url": url(n), "state": "OPEN", "milestone": rel.get("milestone"),
                "labels": [{"name": l} for l in rel.get("labels", [])], "parent": rel.get("parent"),
                "blockedBy": {"nodes": [{"url": u} for u in rel.get("blockedBy", [])], "totalCount": 0}}})
        for n, state in ((239, "OPEN"), (12, "OPEN"), (13, "CLOSED")):
            entries.append({"prefix": ["issue", "view", str(n), "-R", REPO],
                            "stdout": {"number": n, "url": url(n), "state": state, "title": f"#{n}"}})
        entries.append({"prefix": ["issue", "view", "7", "-R", REPO],
                        "stdout": {"number": 7, "url": f"https://github.com/{REPO}/pull/7", "state": "OPEN", "title": "PR"}})
        entries.append({"prefix": ["label", "create"], "stdout": ""})
        entries.append({"prefix": ["issue", "edit"], "stdout": ""})
        entries.append({"prefix": ["issue", "comment"], "stdout": "https://github.com/o/r/issues/1#issuecomment-1\n"})
        self.responses(entries)

    def creates(self):
        return [a for a in self.recorded() if a[:2] == ["issue", "create"]]

    def edits(self):
        return [a for a in self.recorded() if a[:2] == ["issue", "edit"]]

    def create_ok(self, title, number, once=True):
        return {"prefix": ["issue", "create"], "contains": [title], "stdout": url(number) + "\n", "once": once}


class IssuesPlanTest(IssuesCliCase):

    def test_three_items(self):
        path = self.write_draft(draft_text(*THREE))
        self.github(labels=("bug",))
        code, out, err = self.cli("issues", "plan", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["errors"], [])
        self.assertEqual([i["key"] for i in out["items"]], ["a", "b", "c"])
        actions = {i["key"]: [a["action"] for a in i["actions"]] for i in out["items"]}
        self.assertEqual(actions, {"a": ["create", "set-parent", "add-blocked-by"], "b": ["create", "set-parent"],
                                   "c": ["create"]})
        a = out["items"][0]["actions"]
        self.assertEqual((a[0]["milestone"], a[0]["labels"], a[1]["parent"], a[2]["issues"]),
                         ("R5 (確認用のリリース)", ["bug"], url(239), [url(12)]))
        self.assertEqual(out["labels_to_create"],
                         [{"name": "no-release", "color": "cfd3d7", "description": "どのリリースにも入れない Issue (issue-practice)"}],
                         "リポジトリに無いラベル no-release は、作るラベルとして示す")
        self.assertFalse([a for a in self.recorded() if a[:2] in (["issue", "create"], ["issue", "edit"], ["label", "create"])],
                         "示すときは書き込まない")

    def test_pull_request_dependency_is_only_in_body(self):
        path = self.write_draft(draft_text(THREE[1]))
        self.github()
        code, out, err = self.cli("issues", "plan", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertNotIn("add-blocked-by", [a["action"] for a in out["items"][0]["actions"]],
                         "依存先が PR なら blocked by を設定しない (本文の節「依存先」だけに書く)")

    def test_github_state_errors(self):
        cases = {
            "閉じた依存先": item("a", "x", blocked="#13"),
            "番号が PR の依存先": item("a", "x", blocked="#7"),
            "無いマイルストーン": item("a", "x", milestone="R99 (無い)"),
            "無いラベル": item("a", "x", labels="無いラベル"),
        }
        for name, section in cases.items():
            with self.subTest(name):
                path = self.write_draft(draft_text(section))
                self.github()
                code, out, _ = self.cli("issues", "plan", path, "--repo", REPO)
                self.assertEqual(code, 3)
                self.assertEqual(out["errors"][0]["line"], 9, "誤りに、計画案の Issue の見出しの行番号を付ける")

    def test_form_error_runs_no_gh(self):
        path = self.write_draft(draft_text("### a: x\n\n- 親 Issue: なし\n"))
        code, out, _ = self.cli("issues", "plan", path, "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])
        self.assertTrue(all(e["line"] for e in out["errors"]))
        self.assertEqual(self.recorded(), [], "計画案の形が違えば gh を実行しない")
        code, out, _ = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertEqual(self.recorded(), [], "実行するときも、形が違えば何も作らない")

    def test_existing_issue_with_other_parent_is_error(self):
        path = self.write_draft(draft_text(THREE[1]))
        self.github(open_issues=[(101, "b")], relations={101: {"parent": {"url": url(300)}}})
        code, out, _ = self.cli("issues", "plan", path, "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertIn("別の親 Issue", out["errors"][0]["message"])

    def test_gh_failure(self):
        path = self.write_draft(draft_text(*THREE))
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        code, out, _ = self.cli("issues", "plan", path, "--repo", REPO)
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "auth")


class IssuesCreateTest(IssuesCliCase):

    def test_creates_and_sets_relations(self):
        path = self.write_draft(draft_text(*THREE))
        self.github(labels=("bug",), extra=[self.create_ok("一つ目", 101), self.create_ok("二つ目", 102),
                                            self.create_ok("三つ目", 103)])
        code, out, err = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["issues"], [{"key": "a", "url": url(101)}, {"key": "b", "url": url(102)},
                                         {"key": "c", "url": url(103)}])
        label_create = [a for a in self.recorded() if a[:2] == ["label", "create"]]
        self.assertEqual(label_create, [["label", "create", "no-release", "-R", REPO, "--color", "cfd3d7", "--description",
                                         "どのリリースにも入れない Issue (issue-practice)"]])
        first = self.recorded_full()
        create_a = next(r for r in first if r["args"][:2] == ["issue", "create"] and "一つ目" in r["args"])
        self.assertIn("--milestone", create_a["args"])
        self.assertTrue(create_a["stdin"].rstrip("\n").endswith(issues.created_from_line(DRAFT_NAME, "a")),
                        "本文の最後の行に created-from の行を書く")
        self.assertNotIn("--parent", create_a["args"], "親と blocked by は Issue を作るコマンドに付けない")
        self.assertEqual(self.edits(), [["issue", "edit", url(101), "--parent", url(239)],
                                        ["issue", "edit", url(101), "--add-blocked-by", url(12)],
                                        ["issue", "edit", url(102), "--parent", url(239)]])

    def test_retry_after_failure_creates_only_the_rest(self):
        path = self.write_draft(draft_text(*THREE))
        failing = {"prefix": ["issue", "create"], "contains": ["三つ目"], "exit": 1, "stderr": "HTTP 502: Bad Gateway\n",
                   "once": True}
        self.github(extra=[self.create_ok("一つ目", 101), self.create_ok("二つ目", 102), failing],
                    labels=("bug", "no-release"))
        code, out, _ = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 4)
        self.assertEqual([d["key"] for d in out["done"] if d["action"] == "create"], ["a", "b"])
        self.assertEqual(len(self.creates()), 3)
        # 2 件が作られた後の GitHub の状態でやり直す
        os.remove(self.args_file)
        self.github(open_issues=[(101, "a"), (102, "b")],
                    relations={101: {"milestone": {"title": "R5 (確認用のリリース)"}, "labels": ["bug"],
                                     "parent": {"url": url(239)}, "blockedBy": [url(12)]},
                               102: {"parent": {"url": url(239)}}},
                    extra=[self.create_ok("三つ目", 103)], labels=("bug", "no-release"))
        code, out, err = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.creates()), 1, "やり直しでは、作り済みの 2 件を作らない")
        self.assertIn("三つ目", self.creates()[0])
        self.assertEqual(self.edits(), [], "作り済みの Issue に足りない設定は無い")
        self.assertEqual([i["url"] for i in out["issues"]], [url(101), url(102), url(103)])

    def test_retry_after_parent_failure_sets_only_parent(self):
        path = self.write_draft(draft_text(THREE[1]))
        self.github(extra=[self.create_ok("二つ目", 102),
                           {"prefix": ["issue", "edit"], "contains": ["--parent"], "exit": 1,
                            "stderr": "GraphQL: Something went wrong\n", "once": True}])
        code, out, _ = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 4)
        os.remove(self.args_file)
        self.github(open_issues=[(102, "b")], relations={102: {}})
        code, out, err = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.creates(), [], "Issue は作らない")
        self.assertEqual(self.edits(), [["issue", "edit", url(102), "--parent", url(239)]], "親 Issue だけを設定する")

    def test_existing_issue_gets_missing_settings(self):
        path = self.write_draft(draft_text(THREE[0]))
        self.github(open_issues=[(101, "a")], relations={101: {"labels": [], "parent": {"url": url(239)}}})
        code, out, err = self.cli("issues", "create", path, "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.edits(), [["issue", "edit", url(101), "--milestone", "R5 (確認用のリリース)"],
                                        ["issue", "edit", url(101), "--add-label", "bug"],
                                        ["issue", "edit", url(101), "--add-blocked-by", url(12)]])

    def test_record_approval_once(self):
        path = self.write_draft(draft_text(THREE[2]))
        approval = f"issue-practice: approval draft={DRAFT_NAME}"
        self.github(extra=[self.create_ok("三つ目", 103),
                           {"prefix": ["api", f"repos/{REPO}/issues/103/comments"], "stdout": [[]], "once": True},
                           {"prefix": ["api", f"repos/{REPO}/issues/103/comments"], "stdout": [[
                               {"id": 1, "html_url": url(103) + "#issuecomment-1", "created_at": "x", "updated_at": "x",
                                "body": approval + "\n\n本文", "user": {"login": LOGIN}}]]}],
                    labels=("no-release",))
        code, out, err = self.cli("issues", "create", path, "--repo", REPO, "--record-approval")
        self.assertEqual(code, 0, err)
        comments = [r for r in self.recorded_full() if r["args"][:2] == ["issue", "comment"]]
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0]["stdin"].startswith(approval + "\n\n"))
        os.remove(self.args_file)
        # 作り済みとして読ませて、もう一度実行する
        self.github(open_issues=[(103, "c")], relations={103: {"labels": ["no-release"]}},
                    extra=[{"prefix": ["api", f"repos/{REPO}/issues/103/comments"], "stdout": [[
                        {"id": 1, "html_url": url(103) + "#issuecomment-1", "created_at": "x", "updated_at": "x",
                         "body": approval + "\n\n本文", "user": {"login": LOGIN}}]]}], labels=("no-release",))
        code, out, err = self.cli("issues", "create", path, "--repo", REPO, "--record-approval")
        self.assertEqual(code, 0, err)
        self.assertFalse([a for a in self.recorded() if a[:2] == ["issue", "comment"]], "approval の記録を二重に書かない")


class SandboxFixtureTest(unittest.TestCase):
    """確認用のリポジトリで取った固定データの形が、モジュールが読む形と合うこと。"""

    def test_issue_create_output(self):
        self.assertEqual(fixture("sandbox-issue-create").strip(), "https://github.com/akm/issue-practice-sandbox/issues/2")

    def test_relations_shape(self):
        data = fixture_json("sandbox-issue-view-relations")
        self.assertEqual(issues.RELATION_FIELDS.split(","), [k for k in ("number", "url", "state", "milestone", "labels",
                                                                          "parent", "blockedBy") if k in data])
        self.assertEqual(data["parent"]["url"], "https://github.com/akm/issue-practice-sandbox/issues/1")
        self.assertEqual([n["url"] for n in data["blockedBy"]["nodes"]], ["https://github.com/akm/issue-practice-sandbox/issues/4"])

    def test_open_issues_shape(self):
        pages = fixture_json("sandbox-issues-open")
        self.assertTrue(all("html_url" in i and "body" in i for page in pages for i in page))


class DocTest(unittest.TestCase):
    """文書 `issue-practice/references/issue-bodies.md` の書式とラベルの表が、モジュールの定数と一致すること。"""

    def setUp(self):
        with open(os.path.join(HERE, "..", "references", "issue-bodies.md"), encoding="utf-8") as f:
            self.doc = f.read()

    def test_fields(self):
        table = self.doc.split("| 項目 | 値 |\n| --- | --- |\n")[1].split("\n\n")[0]
        names = tuple(line.split("|")[1].strip() for line in table.splitlines())
        self.assertEqual(names, issues.FIELDS, "文書の項目の表と issues.FIELDS が一致すること (順序も)")
        self.assertIn(f"`## {issues.SECTION_TITLE}`", self.doc)
        self.assertIn(f"`{issues.BODY_OPEN}`", self.doc)
        self.assertIn(f"`{issues.NONE_VALUE}`", self.doc)

    def test_labels_table(self):
        table = self.doc.split("| ラベル | 色 | 説明 |")[1]
        rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{6})` \| (.+) \|$", table, re.MULTILINE)
        documented = {name: (color, description) for name, color, description in rows}
        expected = dict(issues.LABELS)
        expected["release-target:<名前>"] = (issues.TARGET_LABEL_COLOR, issues.TARGET_LABEL_DESCRIPTION.format(name="<名前>"))
        self.assertEqual(documented, expected)
        self.assertEqual(issues.managed_label("release-target:api"),
                         (issues.TARGET_LABEL_COLOR, "リリース対象 api のリリース計画 Issue とリリース Issue (issue-practice)"))
        self.assertIsNone(issues.managed_label("bug"))


if __name__ == "__main__":
    unittest.main()
