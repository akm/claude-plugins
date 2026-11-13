#!/usr/bin/env python3
"""本文の範囲と節の読み書き (ファイル `issue-practice/scripts/issue_practice/bodies.py`) のテスト。"""

import hashlib
import os
import unittest

from fakegh_case import FakeGhCase, fixture_json

from issue_practice import bodies  # noqa: E402

BODY_239 = fixture_json("issue-view-239")["body"]
BODY_266 = fixture_json("issue-view-266")["body"]

SAMPLE = """# 題

前の本文

<!-- issue-practice:merge-plan -->

| 順 | 作業 Issue |
| --- | --- |
| 1 | #1 |

<!-- /issue-practice:merge-plan -->

後の本文
"""


class RegionTest(unittest.TestCase):

    def test_reads_region_of_real_body(self):
        r = bodies.find_region(BODY_239, "merge-plan")
        self.assertNotIn("error", r)
        self.assertTrue(r["content"].startswith("- ブランチの構成: 1"))
        self.assertIn("gitGraph", r["content"])
        self.assertTrue(r["content"].endswith("```"), "前後の空行を除くこと")
        r = bodies.find_region(BODY_239, "closing-conditions")
        self.assertIn("### すべての作業 Issue に共通するクローズ条件", r["content"])

    def test_replace_changes_only_inside(self):
        r = bodies.replace_region(SAMPLE, "merge-plan", "新しい表\n")
        self.assertNotIn("error", r)
        new = r["body"]
        before, _, rest = SAMPLE.partition("<!-- issue-practice:merge-plan -->")
        _, _, after = rest.partition("<!-- /issue-practice:merge-plan -->")
        self.assertTrue(new.startswith(before + "<!-- issue-practice:merge-plan -->\n\n新しい表\n\n"))
        self.assertTrue(new.endswith("<!-- /issue-practice:merge-plan -->" + after), "範囲の外を変えないこと")
        self.assertEqual(bodies.find_region(new, "merge-plan")["content"], "新しい表")

    def test_replace_on_real_body_keeps_outside(self):
        new = bodies.replace_region(BODY_239, "merge-plan", "x")["body"]
        start = BODY_239.index("<!-- issue-practice:merge-plan -->")
        end = BODY_239.index("<!-- /issue-practice:merge-plan -->")
        self.assertEqual(new[:start], BODY_239[:start])
        self.assertTrue(new.endswith(BODY_239[end:]))
        self.assertEqual(bodies.find_region(new, "closing-conditions"), bodies.find_region(BODY_239, "closing-conditions"),
                         "ほかの範囲は変えないこと")

    def test_crlf_body_keeps_line_endings_outside(self):
        body = SAMPLE.replace("\n", "\r\n")
        r = bodies.find_region(body, "merge-plan")
        self.assertNotIn("\r", r["content"])
        new = bodies.replace_region(body, "merge-plan", "x")["body"]
        self.assertTrue(new.startswith("# 題\r\n\r\n前の本文\r\n"))
        self.assertTrue(new.endswith("<!-- /issue-practice:merge-plan -->\r\n\r\n後の本文\r\n"))

    def test_errors(self):
        start, end = bodies.start_mark("merge-plan"), bodies.end_mark("merge-plan")
        cases = {
            "マークが無い": "本文だけ\n",
            "閉じていない": f"{start}\nx\n",
            "開始のマークが無い": f"x\n{end}\n",
            "複数": f"{start}\n{end}\n{start}\n{end}\n",
            "より前": f"{end}\nx\n{start}\n",
        }
        for label, body in cases.items():
            with self.subTest(label=label):
                r = bodies.find_region(body, "merge-plan")
                self.assertIn("error", r)
                self.assertIn("error", bodies.replace_region(body, "merge-plan", "y"), "誤りのときは書き換えないこと")
        self.assertIn("知らない範囲", bodies.find_region(SAMPLE, "no-such")["error"])

    def test_marks_in_code_block_are_ignored(self):
        body = ("例:\n\n```markdown\n<!-- issue-practice:merge-plan -->\n例の表\n<!-- /issue-practice:merge-plan -->\n```\n\n"
                + SAMPLE)
        r = bodies.find_region(body, "merge-plan")
        self.assertNotIn("error", r)
        self.assertTrue(r["content"].startswith("| 順 |"))
        self.assertFalse(bodies.has_region_mark("```\n<!-- issue-practice:merge-plan -->\n```\n", "merge-plan"))
        self.assertTrue(bodies.has_region_mark(SAMPLE, "merge-plan"))


class SectionTest(unittest.TestCase):

    def test_reads_section_until_next_same_level_heading(self):
        r = bodies.find_section(BODY_266, "クローズ条件")
        self.assertNotIn("error", r)
        self.assertTrue(r["content"].startswith("### 共通"))
        self.assertIn("確認するポイント:", r["content"])
        body = "## クローズ条件\n\n- [ ] a\n\n### 下\n\n- [ ] b\n\n## 次の節\n\n- [ ] c\n"
        r = bodies.find_section(body, "クローズ条件")
        self.assertIn("- [ ] b", r["content"])
        self.assertNotIn("- [ ] c", r["content"])
        self.assertEqual((r["heading_line"], r["end_line"]), (1, 8))

    def test_section_errors(self):
        self.assertIn("error", bodies.find_section("本文\n", "クローズ条件"))
        self.assertIn("error", bodies.find_section("## クローズ条件\n\n## クローズ条件\n", "クローズ条件"))
        self.assertIn("error", bodies.find_section("```\n## クローズ条件\n```\n", "クローズ条件"), "コードブロックの中の見出しは数えないこと")


class HashTest(unittest.TestCase):

    def test_sha256_of_body_as_is(self):
        self.assertEqual(bodies.body_sha256("あ\n"), hashlib.sha256("あ\n".encode("utf-8")).hexdigest())
        self.assertNotEqual(bodies.body_sha256("a\n"), bodies.body_sha256("a\r\n"), "改行をそろえないこと")
        self.assertEqual(bodies.body_sha256(None), bodies.body_sha256(""))


class BodyCliTest(FakeGhCase):

    def view_entry(self, name="issue-view-239"):
        return {"prefix": ["issue", "view"], "stdout": {"fixture": name}}

    def test_show_whole_body(self):
        self.responses([self.view_entry("issue-view-266")])
        code, out, _ = self.cli("body", "show", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 0)
        self.assertEqual(out["content"], BODY_266)
        self.assertEqual(out["sha256"], bodies.body_sha256(BODY_266))
        self.assertEqual(out["issue"], "akm/claude-plugins#266")
        args = self.recorded()[0]
        self.assertEqual(args[:5], ["issue", "view", "266", "-R", "akm/claude-plugins"])

    def test_show_region(self):
        self.responses([self.view_entry()])
        code, out, _ = self.cli("body", "show", "--issue", "#239", "--repo", "akm/claude-plugins", "--region", "merge-plan")
        self.assertEqual(code, 0)
        self.assertEqual(out["region"]["content"], bodies.find_region(BODY_239, "merge-plan")["content"])
        self.assertEqual(out["sha256"], bodies.body_sha256(BODY_239), "ハッシュ値は本文の全体のもの")

    def test_missing_region_is_exit_3(self):
        self.responses([self.view_entry("issue-view-266")])
        code, out, _ = self.cli("body", "show", "--issue", "akm/claude-plugins#266", "--region", "merge-plan")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])

    def test_ref_without_repo_is_exit_3(self):
        code, out, _ = self.cli("body", "show", "--issue", "#239")
        self.assertEqual(code, 3)
        self.assertEqual(self.recorded(), [], "参照が決まらないときは gh を実行しないこと")

    def test_gh_failure_is_exit_4(self):
        os.environ["FAKE_GH_MODE"] = "network"
        code, out, _ = self.cli("body", "show", "--issue", "akm/claude-plugins#239")
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "network")


if __name__ == "__main__":
    unittest.main()
