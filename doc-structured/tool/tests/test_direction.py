"""検査 i のうち、YAML の参照の向き (モジュール direction) のテスト。"""

import unittest

from doc_structured.direction import check_direction
from doc_structured.domains import load_project
from tooltest import ProjectTestCase

ROOT = """\
domain:
  description: 図書の貸出と返却を扱う。
models:
  loan:
    name_ja: 貸出
    definition: 利用者が図書を借りてから返すまでの 1 回の記録。
"""


def model(name: str, target: str | None = None) -> str:
    text = f"models:\n  {name}:\n    name_ja: {name}\n    definition: {name} の定義。\n"
    if target:
        text += f"    attributes:\n      ref:\n        name_ja: 参照\n        definition: 参照先。\n        refers_to: {target}\n"
    return text


class DirectionTest(ProjectTestCase):
    def problems_for(self, files: dict[str, str]) -> list[str]:
        for relative, text in files.items():
            self.write(relative, text)
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [], "検査 h の問題がある")
        return [p.format() for p in check_direction(project)]

    def test_sample_project_has_no_problems(self):
        project, _ = load_project(self.copy_sample())
        self.assertEqual(check_direction(project), [])

    def test_reference_to_ancestor_directory_fails(self):
        found = self.problems_for({
            "docs/domains/01-loans/domain.yaml": ROOT,
            "docs/domains/01-loans/sub/reservation.yaml": model("reservation", "d-loans-m-loan"),
        })
        self.assertEqual(found, [
            "docs/domains/01-loans/sub/reservation.yaml:9:20: 検査 i: refers_to の参照先 d-loans-m-loan は、"
            "祖先のディレクトリの docs/domains/01-loans/domain.yaml にある。"
            "参照される定義 (d-loans-m-loan) を、参照するファイルと同じディレクトリかその下に移す"
        ])

    def test_reference_to_grandparent_directory_fails(self):
        found = self.problems_for({
            "docs/domains/01-loans/domain.yaml": ROOT,
            "docs/domains/01-loans/a/b/deep.yaml": model("deep", "d-loans-m-loan"),
        })
        self.assertEqual(len(found), 1)
        self.assertIn("検査 i:", found[0])

    def test_allowed_directions(self):
        found = self.problems_for({
            # 親から子孫へ
            "docs/domains/01-loans/domain.yaml": ROOT + model("holder", "d-loans-m-child").split("models:\n")[1],
            "docs/domains/01-loans/sub/child.yaml": model("child", "d-loans-m-sibling"),
            # 同じディレクトリ
            "docs/domains/01-loans/sub/sibling.yaml": model("sibling", "d-loans-m-other"),
            # 別のサブツリー
            "docs/domains/01-loans/other/other.yaml": model("other", "d-members-m-member"),
            # ほかのドメイン
            "docs/domains/02-members/domain.yaml": "domain:\n  description: 利用者。\n" + model("member", "d-loans-m-loan"),
        })
        self.assertEqual(found, [])

    def test_self_reference_is_allowed(self):
        found = self.problems_for({
            "docs/domains/01-loans/domain.yaml": ROOT,
            "docs/domains/01-loans/sub/node.yaml": model("node", "d-loans-m-node"),
        })
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
