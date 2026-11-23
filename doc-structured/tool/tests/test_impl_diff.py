"""設計と実装の差分の共通部分 (モジュール impl_diff) のテスト。結果の表の判定と unified diff を、対象を問わない項目で確認する。

スキーマでの確認は tests/test_schema_diff.py。決めた経緯は Issue #207 のコメントの 7・8・12。
"""

import unittest

from doc_structured.impl_diff import Item, Location, judge, unified

LABELS = {"path": "URL パス"}
FALLBACK = Location("config.yaml", 3, 15)
HERE = Location("screen.yaml", 2, 3)


def messages(*items: Item) -> list[str]:
    return [problem.format() for problem in judge(list(items), LABELS, FALLBACK)]


class JudgeTest(unittest.TestCase):
    def test_in_both_without_planned(self):
        self.assertEqual(messages(Item("画面 a", {"path": "/a"}, {"path": "/a"}, location=HERE)), [])

    def test_in_both_with_planned(self):
        self.assertEqual(
            messages(Item("画面 a", {"path": "/a"}, {"path": "/a"}, planned=True, location=HERE)),
            ["screen.yaml:2:3: 検査 j: 画面 a は実装されたので、planned を外す"],
        )

    def test_only_design_with_planned(self):
        self.assertEqual(messages(Item("画面 a", {"path": "/a"}, None, planned=True, location=HERE)), [])

    def test_only_design_without_planned(self):
        self.assertEqual(
            messages(Item("画面 a", {"path": "/a"}, None, location=HERE)),
            ["screen.yaml:2:3: 検査 j: 画面 a が実装に無い。planned: true を付けるか、YAML から消す"],
        )

    def test_only_implementation(self):
        self.assertEqual(
            messages(Item("ルート /b", None, {"path": "/b"})),
            ["config.yaml:3:15: 検査 j: ルート /b が実装にあるが YAML に無い。YAML に足す (または実装を戻す)"],
        )

    def test_compared_value_differs(self):
        self.assertEqual(
            messages(Item("画面 a", {"path": "/a"}, {"path": ""}, location=HERE)),
            ["screen.yaml:2:3: 検査 j: 画面 a の URL パスが違う (設計 /a、実装 無し)。YAML か実装を直す"],
        )

    def test_fix_overrides_instruction(self):
        item = Item("画面 a", {"path": "/a"}, {"path": "/b"}, location=HERE, fixes={"path": "ルートを直す"})
        self.assertEqual(messages(item), ["screen.yaml:2:3: 検査 j: 画面 a の URL パスが違う (設計 /a、実装 /b)。ルートを直す"])

    def test_children_only_when_parent_matches(self):
        child = Item("子 x", {"path": "/x"}, None, location=HERE)
        # 親が実装に無い・planned で実装にある・YAML に無いときは、親だけを報告する
        self.assertEqual(len(messages(Item("親", {}, None, location=HERE, children=[child]))), 1)
        self.assertEqual(len(messages(Item("親", {}, {}, planned=True, location=HERE, children=[child]))), 1)
        self.assertEqual(len(messages(Item("親", None, {}, children=[child]))), 1)
        self.assertEqual(
            messages(Item("親", {}, {}, location=HERE, children=[child])),
            ["screen.yaml:2:3: 検査 j: 子 x が実装に無い。planned: true を付けるか、YAML から消す"],
        )


class UnifiedTest(unittest.TestCase):
    def test_no_difference(self):
        self.assertEqual(unified(["a", "b"], ["a", "b"], "設計", "実装"), "")

    def test_minus_is_design_and_plus_is_implementation(self):
        design = [f"line {i}" for i in range(10)]
        actual = list(design)
        actual[5] = "line 5 changed"
        text = unified(design, actual, "設計 (x)", "実装 (y)")
        lines = text.splitlines()
        self.assertEqual(lines[:2], ["--- 設計 (x)", "+++ 実装 (y)"])
        self.assertIn("-line 5", lines)
        self.assertIn("+line 5 changed", lines)
        # 文脈は前後 3 行
        self.assertIn(" line 2", lines)
        self.assertNotIn(" line 1", lines)
        self.assertIn(" line 8", lines)
        self.assertNotIn(" line 9", lines)


if __name__ == "__main__":
    unittest.main()
