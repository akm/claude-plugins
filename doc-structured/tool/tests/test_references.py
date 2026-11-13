"""手書きの Markdown の参照の読み取り (モジュール references) のテスト。

題材は、サンプルのプロジェクトの貸出のドメインの手書きの concept.md を書き換えたもの。
"""

from doc_structured.documents import load_documents
from doc_structured.domains import load_project
from doc_structured.references import Reference, all_references, file_references
from tooltest import ProjectTestCase

CONCEPT = "docs/domains/02-loans/concept.md"
LOAN = '[モデル「貸出」]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
DESIGN = '[設計]: design.md#d-loans-design "ドメイン `loans` のファイル `design.md`"\n'


class ReferencesTestCase(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def references(self, text: str | None = None, path: str = CONCEPT) -> list[Reference]:
        if text is not None:
            self.write(path, text)
        project, _ = load_project(self.project)
        index, _ = load_documents(self.project, project)
        handwritten = index.file(path)
        assert handwritten is not None
        return file_references(handwritten)


class OwnerTest(ReferencesTestCase):
    def test_owner_follows_heading_levels(self):
        # Issue #198 のコメントの 2 の例: ① 最初の節の前・② アンカー付きの節・③ その中のアンカーの無い小節・
        # ④ アンカーの無い同じ階層の節
        text = (
            '<a name="d-loans-concept"></a>\n'
            "# 概念\n"
            "前置き。[モデル「貸出」]\n"
            "\n"
            '<a name="d-loans-concept-h-return_deadline"></a>\n'
            "## 返却期限\n"
            "文。[モデル「貸出」]\n"
            "\n"
            "### 延滞の扱い\n"
            "文。[モデル「貸出」]\n"
            "\n"
            "## 予約の順番\n"
            "文。[モデル「貸出」]\n"
            "\n" + LOAN
        )
        found = [(r.line, r.owner_id) for r in self.references(text)]
        self.assertEqual(
            found,
            [
                (3, "d-loans-concept"),
                (7, "d-loans-concept-h-return_deadline"),
                (10, "d-loans-concept-h-return_deadline"),
                (13, "d-loans-concept"),
            ],
        )

    def test_nested_anchored_section_is_innermost(self):
        text = (
            '<a name="d-loans-concept"></a>\n'
            "# 概念\n"
            '<a name="d-loans-concept-h-outer"></a>\n'
            "## 外\n"
            '<a name="d-loans-concept-h-inner"></a>\n'
            "### 内\n"
            "文。[モデル「貸出」]\n"
            "## 次\n"
            "文。[モデル「貸出」]\n"
            "\n" + LOAN
        )
        found = [(r.line, r.owner_id) for r in self.references(text)]
        self.assertEqual(found, [(7, "d-loans-concept-h-inner"), (9, "d-loans-concept")])

    def test_anchor_without_section_heading_is_not_a_section(self):
        # 節のアンカーの次が見出しでないものは、節にしない (検査 b が報告する)
        text = (
            '<a name="d-loans-concept"></a>\n'
            "# 概念\n"
            '<a name="d-loans-concept-h-orphan"></a>\n'
            "文。[モデル「貸出」]\n"
            "\n" + LOAN
        )
        self.assertEqual([r.owner_id for r in self.references(text)], ["d-loans-concept"])


class TargetTest(ReferencesTestCase):
    def test_target_is_href_fragment_even_without_anchor(self):
        text = (
            '<a name="d-loans-concept"></a>\n'
            "# 概念\n"
            "[古い名前]と[設計]。\n"
            "\n"
            '[古い名前]: models.md#d-loans-m-old_loan "ドメイン `loans` のモデル「古い貸出」"\n' + DESIGN
        )
        self.assertEqual([r.target_id for r in self.references(text)], ["d-loans-m-old_loan", "d-loans-design"])

    def test_external_and_undefined_labels_are_not_references(self):
        text = (
            '<a name="d-loans-concept"></a>\n'
            "# 概念\n"
            "[外部]と[定義の無いラベル]と[モデル「貸出」]。\n"
            "\n"
            "[外部]: https://example.com/\n" + LOAN
        )
        self.assertEqual([r.target_id for r in self.references(text)], ["d-loans-m-loan"])

    def test_written_form(self):
        text = (
            '<a name="d-loans-concept"></a>\n'
            "# 概念\n"
            "[貸出の記録][モデル「貸出」]と[モデル「貸出」]。\n"
            "\n" + LOAN
        )
        found = [(r.column, r.written) for r in self.references(text)]
        self.assertEqual(found, [(1, "[貸出の記録][モデル「貸出」]"), (18, "[モデル「貸出」]")])

    def test_definition_only_label_is_reported_at_definition_line(self):
        text = '<a name="d-loans-concept"></a>\n# 概念\n本文。\n\n' + LOAN
        found = [(r.line, r.in_body, r.target_id) for r in self.references(text)]
        self.assertEqual(found, [(5, False, "d-loans-m-loan")])


class SampleTest(ReferencesTestCase):
    def test_sample_references(self):
        project, _ = load_project(self.project)
        index, _ = load_documents(self.project, project)
        found = {(r.path, r.line, r.target_id) for r in all_references(index)}
        self.assertIn(("docs/domains/02-loans/design.md", 9, "d-loans-concept-h-return_deadline"), found)
        self.assertIn(("docs/domains/02-loans/design/overdue_notice.md", 9, "d-loans-m-loan-a-member"), found)
        # 生成したファイル (models.md) の参照は読まない
        self.assertFalse([r for r in all_references(index) if r.path.endswith("models.md")])
