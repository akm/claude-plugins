#!/usr/bin/env python3
"""PR マージ計画の表の解析と、表から gitGraph の図を作ることのテスト (計画の U3・KTD8)。

本文の範囲 merge-plan を読むサブコマンド (merge-plan show・merge-plan set-pr) は、偽の gh (ファイル `issue-practice/tests/fake-gh`) で
確認する。
"""

import os
import re
import unittest

from fakegh_case import HERE, FakeGhCase, fixture_json

from issue_practice import bodies, mergeplan  # noqa: E402

REPO = "o/r"
BODY_239 = fixture_json("issue-view-239")["body"]
HEADER_LINE = "| 順 | 作業 Issue | ブランチ | マージ先 | 先にマージが要る作業 Issue | PR |"
DELIMITER = "| --- | --- | --- | --- | --- | --- |"


def table(*rows):
    return "\n".join([HEADER_LINE, DELIMITER] + [f"| {' | '.join(r)} |" for r in rows])


def plan_text(*rows, settings=("ブランチの構成: 1", "PR をマージする人: 利用者")):
    return "\n".join(f"- {s}" for s in settings) + "\n\n" + table(*rows) + "\n"


THREE_ROWS = (
    ("1", "#12 一覧の絞り込み", "`feat/12-filter`", "main", "なし", ""),
    ("2", "#13 一覧の並べ替え", "`feat/13-sort`", "main", "#12", ""),
    ("3", "#14 文書", "`docs/14-guide`", "main", "なし", ""),
)

MANAGED_ROWS = (
    ("1", "#12 一覧の絞り込み", "`feat/12-filter`", "feat/10-list", "なし", ""),
    ("2", "#13 一覧の並べ替え", "`feat/13-sort`", "feat/10-list", "#12", ""),
)


def managed_settings(config, pr="なし"):
    return (f"ブランチの構成: {config}", "PR をマージする人: 管理セッション", "管理 Issue のブランチ: `feat/10-list`",
            "管理 Issue のブランチのマージ先: main", f"管理 Issue の PR: {pr}")


class ParseTest(unittest.TestCase):

    def test_reads_region_of_239(self):
        region = bodies.find_region(BODY_239, mergeplan.REGION)
        plan = mergeplan.parse(region["content"])
        self.assertEqual(plan["errors"], [])
        self.assertEqual((plan["settings"]["config"], plan["settings"]["merger"]), ("1", "利用者"))
        self.assertEqual([r["work"]["number"] for r in plan["rows"]], [266, 267, 268, 269, 270])
        second = plan["rows"][1]
        self.assertEqual((second["branch"], second["base"], [r["number"] for r in second["requires"]], second["pr"]),
                         ("feat/267-new-issue", "main", [266], None))
        self.assertEqual(second["work"]["description"], "Issue を作る (U2)")
        self.assertTrue(any(line.startswith("- 計画:") for line in plan["prefix"]),
                        "設定の表に無い項目 (計画へのリンク) は、読まずに残す")

    def test_pr_cell(self):
        plan = mergeplan.parse(plan_text(("1", "#12", "feat/12-a", "main", "なし", "https://github.com/o/r/pull/15"),
                                         ("2", "#13", "feat/13-b", "main", "なし", "#16")))
        self.assertEqual(plan["errors"], [])
        self.assertEqual([r["pr"] for r in plan["rows"]], ["https://github.com/o/r/pull/15", "#16"])

    def test_errors(self):
        cases = {
            "列が足りない": "- ブランチの構成: 1\n- PR をマージする人: 利用者\n\n| 順 | 作業 Issue | ブランチ | マージ先 | PR |\n"
                       "| --- | --- | --- | --- | --- |\n| 1 | #12 | a | main | |\n",
            "先にマージが要る作業 Issue が表に無い": plan_text(("1", "#12", "a", "main", "#99", "")),
            "先にマージが要る作業 Issue が後の行": plan_text(("1", "#12", "a", "main", "#13", ""), ("2", "#13", "b", "main", "なし", "")),
            "同じブランチ": plan_text(("1", "#12", "a", "main", "なし", ""), ("2", "#13", "a", "main", "なし", "")),
            "同じ作業 Issue": plan_text(("1", "#12", "a", "main", "なし", ""), ("2", "#12", "b", "main", "なし", "")),
            "順が連番ではない": plan_text(("1", "#12", "a", "main", "なし", ""), ("3", "#13", "b", "main", "なし", "")),
            "構成 1 でマージ先がそろわない": plan_text(("1", "#12", "a", "main", "なし", ""), ("2", "#13", "b", "dev", "なし", "")),
            "構成 1 に管理 Issue のブランチ": plan_text(("1", "#12", "a", "main", "なし", ""),
                                               settings=("ブランチの構成: 1", "PR をマージする人: 利用者",
                                                         "管理 Issue のブランチ: feat/10-list")),
            "構成 2 に管理 Issue のブランチが無い": plan_text(("1", "#12", "a", "main", "なし", ""),
                                                  settings=("ブランチの構成: 2", "PR をマージする人: 利用者")),
            "構成 2 でマージ先が管理 Issue のブランチではない": plan_text(("1", "#12", "a", "main", "なし", ""),
                                                           settings=managed_settings("2")),
            "知らない構成": plan_text(("1", "#12", "a", "main", "なし", ""), settings=("ブランチの構成: 4", "PR をマージする人: 利用者")),
            "PR をマージする人の値": plan_text(("1", "#12", "a", "main", "なし", ""), settings=("ブランチの構成: 1", "PR をマージする人: 誰か")),
            "PR をマージする人が無い": plan_text(("1", "#12", "a", "main", "なし", ""), settings=("ブランチの構成: 1",)),
            "列「PR」が PR ではない": plan_text(("1", "#12", "a", "main", "なし", "https://github.com/o/r/issues/3")),
            "キーは計画案だけ": plan_text(("1", "a 一覧", "feat/<番号>-a", "main", "なし", "")),
            "表が無い": "- ブランチの構成: 1\n- PR をマージする人: 利用者\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                plan = mergeplan.parse(text)
                self.assertTrue(plan["errors"], name)

    def test_keys_in_draft(self):
        plan = mergeplan.parse(plan_text(("1", "a 一覧", "`feat/<番号>-a`", "main", "なし", ""),
                                         ("2", "#20 既にある", "feat/20-b", "main", "a", "")), allow_keys=True)
        self.assertEqual(plan["errors"], [])
        self.assertEqual((plan["rows"][0]["work"]["key"], plan["rows"][0]["work"]["number"]), ("a", None))
        self.assertEqual(plan["rows"][1]["requires"], [{"key": "a", "number": None}])
        resolved = mergeplan.resolve(plan, {"a": 31})
        self.assertEqual(resolved["errors"], [])
        self.assertEqual([r["work"]["number"] for r in resolved["rows"]], [31, 20])
        self.assertEqual(resolved["rows"][0]["branch"], "feat/31-a", "ブランチの <番号> を、作った Issue の番号に置き換える")
        self.assertEqual(resolved["rows"][1]["requires"], [{"key": None, "number": 31}])
        unresolved = mergeplan.resolve(plan, {})
        self.assertTrue(unresolved["errors"])


class GraphTest(unittest.TestCase):

    def test_graph_of_239_matches_the_hand_written_one(self):
        region = bodies.find_region(BODY_239, mergeplan.REGION)
        plan = mergeplan.parse(region["content"])
        self.assertEqual(mergeplan.graph(plan), mergeplan.extract_graph(region["content"]))

    def test_config_1_with_dependency(self):
        plan = mergeplan.parse(plan_text(*THREE_ROWS))
        self.assertEqual(mergeplan.graph(plan), "\n".join([
            "gitGraph",
            '  commit id: "main"',
            "  branch feat/12-filter",
            '  commit id: "12"',
            "  checkout main",
            "  branch docs/14-guide",
            '  commit id: "14"',
            "  checkout main",
            "  merge feat/12-filter",
            "  branch feat/13-sort",
            '  commit id: "13"',
            "  checkout main",
            "  merge feat/13-sort",
            "  merge docs/14-guide",
        ]) + "\n", "先にマージが要る作業 Issue が無い行は最初に分かれ、依存する行は依存先のマージの後に分かれる")

    def test_config_2_goes_through_managing_branch(self):
        plan = mergeplan.parse(plan_text(*MANAGED_ROWS, settings=managed_settings("2")))
        self.assertEqual(plan["errors"], [])
        self.assertEqual(mergeplan.graph(plan), "\n".join([
            "gitGraph",
            '  commit id: "main"',
            "  branch feat/10-list",
            '  commit id: "draft PR"',
            "  branch feat/12-filter",
            '  commit id: "12"',
            "  checkout feat/10-list",
            "  merge feat/12-filter",
            "  branch feat/13-sort",
            '  commit id: "13"',
            "  checkout feat/10-list",
            "  merge feat/13-sort",
            "  checkout main",
            "  merge feat/10-list",
        ]) + "\n")

    def test_config_3_has_no_draft_commit(self):
        plan = mergeplan.parse(plan_text(*MANAGED_ROWS, settings=managed_settings("3")))
        self.assertEqual(plan["errors"], [])
        lines = mergeplan.graph(plan).splitlines()
        self.assertNotIn('  commit id: "draft PR"', lines)
        self.assertEqual(lines[2:4], ["  branch feat/10-list", "  branch feat/12-filter"])
        self.assertEqual(lines[-2:], ["  checkout main", "  merge feat/10-list"])

    def test_render_keeps_prefix_and_writes_graph(self):
        plan = mergeplan.parse(BODY_239.split("<!-- issue-practice:merge-plan -->")[1].split("<!-- /issue-practice")[0])
        content = mergeplan.render(plan)
        self.assertIn("- 計画: [docs/plans/", content)
        self.assertIn(HEADER_LINE, content)
        self.assertIn("| 2 | #267 Issue を作る (U2) | `feat/267-new-issue` | main | #266 | |", content)
        self.assertEqual(mergeplan.extract_graph(content), mergeplan.graph(plan))
        self.assertEqual(mergeplan.render(mergeplan.parse(content)), content, "書いた中身を読んで書き直しても変わらない")

    def test_set_pr(self):
        plan = mergeplan.parse(plan_text(*THREE_ROWS))
        changed = mergeplan.set_pr(plan, 13, "https://github.com/o/r/pull/20")
        self.assertEqual((changed["previous"], changed["plan"]["rows"][1]["pr"]), (None, "https://github.com/o/r/pull/20"))
        self.assertIn("error", mergeplan.set_pr(plan, 99, "https://github.com/o/r/pull/20"))
        self.assertIn("error", mergeplan.set_pr(plan, 13, "https://github.com/o/r/issues/20"))


    def test_set_managing_pr(self):
        plan = mergeplan.parse(plan_text(*MANAGED_ROWS, settings=managed_settings("2")))
        changed = mergeplan.set_managing_pr(plan, "https://github.com/o/r/pull/30")
        self.assertEqual(changed["previous"], None)
        self.assertIn("- 管理 Issue の PR: https://github.com/o/r/pull/30", changed["plan"]["prefix"])
        reread = mergeplan.parse(mergeplan.render(changed["plan"]))
        self.assertEqual(reread["settings"]["managing_pr"], "https://github.com/o/r/pull/30")
        no_line = mergeplan.parse(plan_text(*MANAGED_ROWS, settings=managed_settings("3")[:4]))
        self.assertIn("- 管理 Issue の PR: https://github.com/o/r/pull/30",
                      mergeplan.set_managing_pr(no_line, "https://github.com/o/r/pull/30")["plan"]["prefix"],
                      "設定の行が無ければ足す")
        self.assertIn("error", mergeplan.set_managing_pr(mergeplan.parse(plan_text(*THREE_ROWS)), "https://github.com/o/r/pull/30"),
                      "構成 1 には管理 Issue の PR が無い")

def region_body(content, before="## 問題\n\n本文\n\n## PR マージ計画\n\n"):
    return f"{before}{bodies.start_mark(mergeplan.REGION)}\n\n{content}\n\n{bodies.end_mark(mergeplan.REGION)}\n"


class MergePlanCliTest(FakeGhCase):

    def view(self, body, number=10, state="OPEN"):
        return {"prefix": ["issue", "view", str(number), "-R", REPO],
                "stdout": {"number": number, "url": f"https://github.com/{REPO}/issues/{number}", "state": state,
                           "title": "管理 Issue", "body": body, "updatedAt": "2026-11-14T00:00:00Z"}}

    def test_show(self):
        content = mergeplan.render(mergeplan.parse(plan_text(*THREE_ROWS)))
        self.responses([self.view(region_body(content))])
        code, out, err = self.cli("merge-plan", "show", "--issue", f"{REPO}#10")
        self.assertEqual(code, 0, err)
        self.assertTrue(out["graph_matches"])
        self.assertEqual(out["settings"]["config"], "1")
        self.assertEqual([r["work"]["number"] for r in out["rows"]], [12, 13, 14])
        self.assertEqual(out["rows"][0]["work"]["url"], f"https://github.com/{REPO}/issues/12")
        self.assertEqual(out["sha256"], bodies.body_sha256(region_body(content)))

    def test_show_detects_graph_that_differs_from_table(self):
        content = mergeplan.render(mergeplan.parse(plan_text(*THREE_ROWS))).replace('commit id: "14"', 'commit id: "15"')
        self.responses([self.view(region_body(content))])
        code, out, _ = self.cli("merge-plan", "show", "--issue", f"{REPO}#10")
        self.assertEqual(code, 3)
        self.assertFalse(out["graph_matches"])

    def test_show_errors(self):
        self.responses([self.view("## 問題\n\n本文\n")])
        code, out, _ = self.cli("merge-plan", "show", "--issue", f"{REPO}#10")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])
        os.environ["FAKE_GH_MODE"] = "network"
        code, out, _ = self.cli("merge-plan", "show", "--issue", f"{REPO}#10")
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "network")

    def test_show_notice_for_config_2(self):
        content = mergeplan.render(mergeplan.parse(plan_text(*MANAGED_ROWS, settings=managed_settings("2"))))
        self.responses([self.view(region_body(content))])
        code, out, err = self.cli("merge-plan", "show", "--issue", f"{REPO}#10")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["managing_pr_notice"],
                         mergeplan.DRAFT_PR_NOTICE.format(url=f"https://github.com/{REPO}/issues/10"))

    def test_set_pr(self):
        body = region_body(mergeplan.render(mergeplan.parse(plan_text(*THREE_ROWS))))
        self.responses([self.view(body), {"prefix": ["issue", "edit"], "stdout": ""}])
        sha = bodies.body_sha256(body)
        code, out, err = self.cli("merge-plan", "set-pr", "--issue", f"{REPO}#10", "--work", "#13",
                                  "--pr", "https://github.com/o/r/pull/20", "--expect-sha256", sha)
        self.assertEqual(code, 0, err)
        self.assertTrue(out["changed"])
        edits = [r for r in self.recorded_full() if r["args"][:2] == ["issue", "edit"]]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["args"], ["issue", "edit", f"https://github.com/{REPO}/issues/10", "--body-file", "-"])
        written = edits[0]["stdin"]
        self.assertIn("| 2 | #13 一覧の並べ替え | `feat/13-sort` | main | #12 | https://github.com/o/r/pull/20 |", written)
        self.assertTrue(written.startswith("## 問題\n\n本文\n"), "範囲の外は変えない")
        self.assertEqual(out["sha256"], bodies.body_sha256(written))

    def test_set_pr_refuses_changed_body_and_skips_same_url(self):
        body = region_body(mergeplan.render(mergeplan.parse(plan_text(*THREE_ROWS))))
        self.responses([self.view(body), {"prefix": ["issue", "edit"], "stdout": ""}])
        code, out, _ = self.cli("merge-plan", "set-pr", "--issue", f"{REPO}#10", "--work", "#13",
                                "--pr", "https://github.com/o/r/pull/20", "--expect-sha256", "0" * 64)
        self.assertEqual(code, 3)
        self.assertIn("変わった", out["errors"][0])
        self.assertFalse([a for a in self.recorded() if a[:2] == ["issue", "edit"]], "本文が変わっていたら書かない")
        with_pr = region_body(mergeplan.render(mergeplan.set_pr(mergeplan.parse(plan_text(*THREE_ROWS)), 13,
                                                                "https://github.com/o/r/pull/20")["plan"]))
        os.remove(self.args_file)
        self.responses([self.view(with_pr), {"prefix": ["issue", "edit"], "stdout": ""}])
        code, out, err = self.cli("merge-plan", "set-pr", "--issue", f"{REPO}#10", "--work", "13",
                                  "--pr", "https://github.com/o/r/pull/20", "--expect-sha256", bodies.body_sha256(with_pr))
        self.assertEqual(code, 0, err)
        self.assertFalse(out["changed"])
        self.assertFalse([a for a in self.recorded() if a[:2] == ["issue", "edit"]], "同じ URL なら書かない")


    def test_set_managing_pr_cli(self):
        body = region_body(mergeplan.render(mergeplan.parse(plan_text(*MANAGED_ROWS, settings=managed_settings("2")))))
        self.responses([self.view(body), {"prefix": ["issue", "edit"], "stdout": ""}])
        code, out, err = self.cli("merge-plan", "set-pr", "--issue", f"{REPO}#10", "--pr", "https://github.com/o/r/pull/30",
                                  "--expect-sha256", bodies.body_sha256(body))
        self.assertEqual(code, 0, err)
        self.assertEqual((out["work"], out["changed"]), (None, True))
        edits = [r for r in self.recorded_full() if r["args"][:2] == ["issue", "edit"]]
        self.assertIn("- 管理 Issue の PR: https://github.com/o/r/pull/30", edits[0]["stdin"])

class DocTest(unittest.TestCase):
    """文書 `issue-practice/skills/managing-issue-plan/references/merge-plan.md` の書式が、モジュールの定数と一致すること。"""

    def setUp(self):
        path = os.path.join(HERE, "..", "skills", "managing-issue-plan", "references", "merge-plan.md")
        with open(path, encoding="utf-8") as f:
            self.doc = f.read()

    def test_settings(self):
        table_text = self.doc.split("| 項目 | 値 |\n| --- | --- |\n")[1].split("\n\n")[0]
        names = tuple(line.split("|")[1].strip() for line in table_text.splitlines())
        self.assertEqual(names, mergeplan.SETTINGS)
        self.assertEqual(tuple(re.findall(r"`([^`]+)`", table_text.splitlines()[0].split("|")[2])), mergeplan.CONFIGS)
        self.assertEqual(tuple(re.findall(r"`([^`]+)`", table_text.splitlines()[1].split("|")[2])), mergeplan.MERGERS)

    def test_header_and_marks(self):
        self.assertIn("| " + " | ".join(mergeplan.HEADER) + " |", self.doc)
        self.assertIn(f"`{bodies.start_mark(mergeplan.REGION)}`", self.doc)
        self.assertIn(f"`{mergeplan.DRAFT_COMMIT_ID}`", self.doc)
        self.assertIn(mergeplan.DRAFT_PR_NOTICE.format(url="<管理 Issue の URL>"), self.doc)


if __name__ == "__main__":
    unittest.main()
