#!/usr/bin/env python3
"""節「クローズ条件」のチェックボックスの解析 (ファイル `issue-practice/scripts/issue_practice/checkboxes.py`) のテスト。"""

import os
import unittest

from fakegh_case import FakeGhCase, fixture_json

from issue_practice import checkboxes  # noqa: E402

BODY_239 = fixture_json("issue-view-239")["body"]
BODY_266 = fixture_json("issue-view-266")["body"]

MIXED = """## クローズ条件

期待する状態:

- [ ] 未チェックの項目
- [x] 根拠のある項目 (根拠: https://github.com/o/r/pull/1)
- [X] 根拠の無い項目
- [x] 切り出した項目 (切り出し: https://github.com/o/r/issues/2)
- [x] 根拠が URL ではない項目 (根拠: このコメント)

確認するポイント:

- [ ] 手で確認する項目
    - 確認の方法: 手で確認する
    - 記録先: この Issue のコメント
- [ ] 切り出しのリンクがあるが、チェックが無い項目 (切り出し: https://github.com/o/r/issues/3)

```markdown
- [ ] コードブロックの中の例
```

## 次の節

- [ ] 範囲の外の項目
"""


class ParseTest(unittest.TestCase):

    def test_states(self):
        r = checkboxes.parse(MIXED)
        self.assertEqual(r["source"], "section")
        states = [(item["text"], item["state"]) for item in r["items"]]
        self.assertEqual(states, [
            ("未チェックの項目", "unchecked"),
            ("根拠のある項目", "checked"),
            ("根拠の無い項目", "checked_without_evidence"),
            ("切り出した項目", "carved_out"),
            ("根拠が URL ではない項目 (根拠: このコメント)", "checked_without_evidence"),
            ("手で確認する項目", "unchecked"),
            ("切り出しのリンクがあるが、チェックが無い項目", "unchecked"),
        ])
        self.assertEqual(r["items"][1]["evidence"], "https://github.com/o/r/pull/1")
        self.assertEqual(r["items"][3]["carved_out"], "https://github.com/o/r/issues/2")

    def test_groups_and_details(self):
        items = checkboxes.parse(MIXED)["items"]
        self.assertEqual([i["group"] for i in items], ["expected"] * 5 + ["verification"] * 2)
        self.assertEqual(items[5]["details"], ["- 確認の方法: 手で確認する", "- 記録先: この Issue のコメント"])
        self.assertEqual(items[6]["details"], [])

    def test_summary(self):
        summary = checkboxes.parse(MIXED)["summary"]
        self.assertEqual(summary["counts"], {"unchecked": 3, "checked": 1, "checked_without_evidence": 2, "carved_out": 1})
        self.assertEqual(summary["unsatisfied"], [5, 7, 9, 13, 16])

    def test_working_issue_without_marks(self):
        r = checkboxes.parse(BODY_266)
        self.assertEqual(r["source"], "section")
        self.assertEqual(len(r["items"]), 8)
        self.assertTrue(all(i["state"] == "unchecked" for i in r["items"]))
        self.assertEqual(r["items"][0]["heading"], "共通 (#239 の「すべての作業 Issue に共通するクローズ条件」からコピー)")
        self.assertEqual([i["group"] for i in r["items"]], ["expected"] * 3 + ["expected"] * 3 + ["verification"] * 2)
        self.assertEqual(r["items"][6]["details"][0], "- 確認の方法: 自動テスト (CI)")

    def test_managing_issue_with_marks(self):
        r = checkboxes.parse(BODY_239)
        self.assertEqual(r["source"], "region")
        self.assertEqual(len(r["items"]), 6)
        self.assertEqual(r["items"][0]["heading"], "管理 Issue (#239) 自身のクローズ条件")
        self.assertEqual(r["items"][2]["heading"], "すべての作業 Issue に共通するクローズ条件")
        self.assertEqual(r["items"][1]["group"], "verification")

    def test_heading_groups(self):
        body = "## クローズ条件\n\n### 期待する状態\n\n- [ ] a\n\n### 確認するポイント\n\n- [ ] b\n\n### ほかの見出し\n\n- [ ] c\n"
        self.assertEqual([i["group"] for i in checkboxes.parse(body)["items"]], ["expected", "verification", None])

    def test_broken_marks_are_errors(self):
        body = "## クローズ条件\n\n<!-- issue-practice:closing-conditions -->\n\n- [ ] a\n"
        self.assertIn("error", checkboxes.parse(body), "マークがあるのに閉じていなければ、見出しの節を使わずに誤りを返すこと")

    def test_missing_section(self):
        self.assertIn("error", checkboxes.parse("本文だけ\n"))


class CheckboxesCliTest(FakeGhCase):

    def view(self, body):
        data = fixture_json("issue-view-266")
        data["body"] = body
        self.responses([{"prefix": ["issue", "view"], "stdout": data}])

    def test_unsatisfied_is_exit_3(self):
        self.view(MIXED)
        code, out, _ = self.cli("checkboxes", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 3)
        self.assertEqual(out["summary"]["unsatisfied"], [5, 7, 9, 13, 16])
        self.assertEqual(out["source"], "section")
        self.assertTrue(out["sha256"])

    def test_satisfied_is_exit_0(self):
        self.view("## クローズ条件\n\n- [x] a (根拠: https://github.com/o/r/pull/1)\n- [x] b (切り出し: https://github.com/o/r/issues/2)\n")
        code, out, _ = self.cli("checkboxes", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 0, out)

    def test_no_items_is_exit_3(self):
        self.view("## クローズ条件\n\n決まっていない。\n")
        code, out, _ = self.cli("checkboxes", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])

    def test_missing_section_is_exit_3(self):
        self.view("本文だけ\n")
        code, out, _ = self.cli("checkboxes", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])

    def test_gh_failure_is_exit_4(self):
        os.environ["FAKE_GH_MODE"] = "rate_limited"
        code, out, _ = self.cli("checkboxes", "list", "--issue", "akm/claude-plugins#266")
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "rate_limit")


if __name__ == "__main__":
    unittest.main()
