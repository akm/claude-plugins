"""検査 i (参照の向き。モジュール direction) のテスト。YAML の参照と、手書きの Markdown のリンクの両方。"""

import unittest

from doc_structured.direction import check_direction, check_markdown_direction
from doc_structured.documents import load_documents
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


CHILD = "docs/domains/02-loans/design/overdue_notice.md"
CHILD_HEAD = '<a name="d-loans-design-f-overdue_notice"></a>\n\n# 延滞の通知\n\n'
RETURN_DEADLINE = '[節「返却期限」]: ../concept.md#d-loans-concept-h-return_deadline "ドメイン `loans` のファイル `concept.md` の節「返却期限」"\n'


class MarkdownDirectionTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def problems_for(self, files: dict[str, str]) -> list[str]:
        for relative, text in files.items():
            self.write(relative, text)
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [], "検査 h の問題がある")
        index, _ = load_documents(self.project, project)
        return [p.format() for p in check_markdown_direction(index)]

    def test_sample_project_has_no_problems(self):
        self.assertEqual(self.problems_for({}), [])

    def test_link_from_child_file_to_parent_directory_section_fails(self):
        found = self.problems_for({CHILD: CHILD_HEAD + "期限は[節「返却期限」]による。\n\n" + RETURN_DEADLINE})
        self.assertEqual(found, [
            f"{CHILD}:5:4: 検査 i: リンク [節「返却期限」] の参照先 d-loans-concept-h-return_deadline は、"
            "祖先のディレクトリの手書きのファイル docs/domains/02-loans/concept.md にある。"
            "参照される内容を、サブディレクトリの子のファイルに移す"
        ])

    def test_link_from_child_file_to_its_parent_file_fails(self):
        found = self.problems_for({
            CHILD: CHILD_HEAD + "[`design.md`]の続き。\n\n"
            '[`design.md`]: ../design.md#d-loans-design "ドメイン `loans` のファイル `design.md`"\n'
        })
        self.assertEqual(len(found), 1)
        self.assertIn("参照先 d-loans-design は、祖先のディレクトリの手書きのファイル", found[0])

    def test_allowed_links(self):
        found = self.problems_for({
            # 子のファイルから、生成したファイル (ドメインのディレクトリの直下) と、別のサブツリーの子のファイルへ
            CHILD: CHILD_HEAD
            + "[開館日]に[借りた利用者]へ通知する。[`concept/rules.md`]による。\n\n"
            '[開館日]: ../unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"\n'
            '[借りた利用者]: ../models.md#d-loans-m-loan-a-member "ドメイン `loans` のモデル「貸出」の属性「借りた利用者」"\n'
            '[`concept/rules.md`]: ../concept/rules.md#d-loans-concept-f-rules "ドメイン `loans` のファイル `concept/rules.md`"\n',
            "docs/domains/02-loans/concept/rules.md": '<a name="d-loans-concept-f-rules"></a>\n\n# 規則\n',
        })
        # 同じディレクトリ (concept.md から design.md)・子孫 (design.md から子のファイル)・ほかのドメインは、サンプルの中にある
        self.assertEqual(found, [])

    def test_link_without_anchor_is_left_to_check_b(self):
        found = self.problems_for({
            CHILD: CHILD_HEAD + "[節「無い」]\n\n"
            '[節「無い」]: ../concept.md#d-loans-concept-h-missing "ドメイン `loans` のファイル `concept.md` の節「無い」"\n'
        })
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
