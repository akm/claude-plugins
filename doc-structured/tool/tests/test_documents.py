"""手書きの Markdown の発見と、リンクの参照先の一覧 (モジュール documents) のテスト。"""

import shutil
import unittest

from doc_structured.documents import load_documents, section_name
from doc_structured.domains import load_project
from tooltest import ProjectTestCase

CONCEPT = """\
<a name="d-loans-concept"></a>

# 貸出の概念

<a name="d-loans-concept-h-return_deadline"></a>

## 返却期限

本文。
"""

CHILD = """\
<a name="d-loans-design-f-overdue_notice"></a>

# 延滞の通知

<a name="d-loans-design-f-overdue_notice-h-retry"></a>
### 再送 `retry`

本文。
"""


class DocumentsTestCase(ProjectTestCase):
    """サンプルのプロジェクトから手書きのファイルを除いたものを使う (テストごとに手書きのファイルを書く)。"""

    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()
        loans = self.project / "docs/domains/02-loans"
        (loans / "concept.md").unlink()
        (loans / "design.md").unlink()
        shutil.rmtree(loans / "design")

    def load(self):
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        return load_documents(self.project, project)


class FindFilesTest(DocumentsTestCase):
    def test_handwritten_files_and_child_files(self):
        self.write("docs/domains/02-loans/concept.md", CONCEPT)
        self.write("docs/domains/02-loans/design.md", '<a name="d-loans-design"></a>\n\n# 設計\n')
        self.write("docs/domains/02-loans/design/overdue_notice.md", CHILD)
        index, problems = self.load()
        self.assertEqual(problems, [])
        self.assertEqual(
            [(f.path, f.id, f.full_name()) for f in index.files],
            [
                ("docs/domains/02-loans/concept.md", "d-loans-concept", "ドメイン `loans` のファイル `concept.md`"),
                ("docs/domains/02-loans/design.md", "d-loans-design", "ドメイン `loans` のファイル `design.md`"),
                (
                    "docs/domains/02-loans/design/overdue_notice.md",
                    "d-loans-design-f-overdue_notice",
                    "ドメイン `loans` のファイル `design/overdue_notice.md`",
                ),
            ],
        )

    def test_unaccepted_names_and_places(self):
        self.write("docs/domains/02-loans/notes.md", "# メモ\n")
        self.write("docs/domains/02-loans/design/a/b.md", "# b\n")
        self.write("docs/domains/02-loans/design/Overdue.md", "# c\n")
        self.write("docs/domains/02-loans/reservations/notes.md", "# d\n")
        index, problems = self.load()
        self.assertEqual(index.files, [])
        self.assertEqual(
            [(p.check, p.path) for p in problems],
            [
                ("b", "docs/domains/02-loans/notes.md"),
                ("b", "docs/domains/02-loans/design/Overdue.md"),
                ("b", "docs/domains/02-loans/reservations/notes.md"),
                ("b", "docs/domains/02-loans/design/a/b.md"),
            ],
        )
        self.assertIn("concept.md・problem.md・design.md だけ", problems[0].message)
        self.assertIn("snake_case でない", problems[1].message)
        self.assertIn("子のファイルだけ", problems[2].message)
        self.assertIn("1 階層だけ", problems[3].message)

    def test_generated_files_are_not_handwritten(self):
        index, problems = self.load()
        self.assertEqual((index.files, problems), ([], []))


class SampleProjectTest(ProjectTestCase):
    def test_sample_handwritten_files(self):
        self.copy_sample()
        project, _ = load_project(self.project)
        index, problems = load_documents(self.project, project)
        self.assertEqual(problems, [])
        self.assertEqual(
            [f.id for f in index.files],
            ["d-loans-concept", "d-loans-design", "d-loans-design-f-overdue_notice"],
        )


class TargetTest(DocumentsTestCase):
    def test_targets_from_yaml_generated_and_handwritten_files(self):
        self.write("docs/domains/02-loans/concept.md", CONCEPT)
        self.write("docs/domains/02-loans/design/overdue_notice.md", CHILD)
        index, _ = self.load()
        targets = index.targets
        self.assertEqual(targets["d-loans"].path, "docs/domains/02-loans/README.md")
        self.assertEqual(targets["d-loans-models"].full_name(), "ドメイン `loans` のファイル `models.md`")
        self.assertEqual(targets["d-loans-m-loan"].path, "docs/domains/02-loans/models.md")
        self.assertEqual(targets["d-loans-m-loan"].full_name(), "ドメイン `loans` のモデル「貸出」")
        self.assertEqual(targets["d-loans-concept"].full_name(), "ドメイン `loans` のファイル `concept.md`")
        self.assertEqual(
            targets["d-loans-concept-h-return_deadline"].full_name(),
            "ドメイン `loans` のファイル `concept.md` の節「返却期限」",
        )
        self.assertEqual(
            targets["d-loans-design-f-overdue_notice-h-retry"].full_name(),
            "ドメイン `loans` のファイル `design/overdue_notice.md` の節「再送 `retry`」",
        )

    def test_href(self):
        self.write("docs/domains/02-loans/concept.md", CONCEPT)
        self.write("docs/domains/02-loans/design/overdue_notice.md", CHILD)
        index, _ = self.load()
        concept = "docs/domains/02-loans/concept.md"
        self.assertEqual(index.targets["d-loans-concept-h-return_deadline"].href(concept), "#d-loans-concept-h-return_deadline")
        self.assertEqual(index.targets["d-loans-m-loan"].href(concept), "models.md#d-loans-m-loan")
        self.assertEqual(index.targets["d-catalog-m-book"].href(concept), "../01-catalog/models.md#d-catalog-m-book")
        self.assertEqual(
            index.targets["d-loans-concept"].href("docs/domains/02-loans/design/overdue_notice.md"),
            "../concept.md#d-loans-concept",
        )

    def test_label_candidates(self):
        self.write("docs/domains/02-loans/concept.md", CONCEPT)
        index, _ = self.load()
        for label in (
            "d-loans-m-loan",
            "貸出",
            "モデル「貸出」",
            "ドメイン `loans` のモデル「貸出」",
            "ドメイン  `loans`\nのモデル「貸出」",  # 連続する空白の違いは無視する
        ):
            with self.subTest(label=label):
                self.assertIn("d-loans-m-loan", [t.id for t in index.candidates(label)])
        self.assertEqual([t.id for t in index.candidates("返却期限")], ["d-loans-concept-h-return_deadline"])
        self.assertEqual([t.id for t in index.candidates("`concept.md`")], ["d-loans-concept"])
        self.assertEqual([t.id for t in index.candidates("ファイル `concept.md` の節「返却期限」")], ["d-loans-concept-h-return_deadline"])
        self.assertEqual([t.id for t in index.candidates("D-LOANS-M-LOAN")], ["d-loans-m-loan"])
        self.assertEqual(index.candidates("無い名前"), [])

    def test_same_name_in_two_domains_gives_two_candidates(self):
        index, _ = self.load()
        ids = [t.id for t in index.candidates("`models.md`")]
        self.assertEqual(ids, ["d-catalog-models", "d-loans-models", "d-members-models"])

    def test_generated_target_path_does_not_follow_duplicate_anchor(self):
        self.write("docs/domains/02-loans/concept.md", CONCEPT + '\n<a name="d-loans-m-loan"></a>\n\n## 貸出\n')
        index, _ = self.load()
        self.assertEqual(index.targets["d-loans-m-loan"].path, "docs/domains/02-loans/models.md")
        self.assertEqual(len(index.anchors["d-loans-m-loan"]), 2)

    def test_invalid_anchors_are_not_targets(self):
        self.write(
            "docs/domains/02-loans/concept.md",
            '# 先頭のアンカーが無い\n\n<a name="d-loans-concept-h-x"></a>\n\n本文 (見出しが続かない)\n\n'
            '<a name="d-loans-design-h-y"></a>\n## ほかのファイルの ID\n',
        )
        index, _ = self.load()
        self.assertNotIn("d-loans-concept", index.targets)
        self.assertNotIn("d-loans-concept-h-x", index.targets)
        self.assertNotIn("d-loans-design-h-y", index.targets)
        self.assertEqual(len(index.anchors["d-loans-concept-h-x"]), 1)


class SectionNameTest(unittest.TestCase):
    def test_section_name(self):
        self.assertEqual(section_name("d-loans-concept", "d-loans-concept-h-due"), "due")
        self.assertIsNone(section_name("d-loans-concept", "d-loans-design-h-due"))
        self.assertIsNone(section_name("d-loans-concept", "d-loans-concept-h-due-h-x"))
        self.assertIsNone(section_name("d-loans-concept", "d-loans-concept-due"))


if __name__ == "__main__":
    unittest.main()
