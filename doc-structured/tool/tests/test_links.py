"""検査 b (モジュール links) のテスト。

項目ごとに、失敗する例と成功する例を確かめる。題材は、サンプルのプロジェクトの貸出のドメインの手書きの concept.md。
"""

from doc_structured.documents import load_documents
from doc_structured.domains import load_project
from doc_structured.links import check_links
from doc_structured.problems import Problem
from tooltest import ProjectTestCase

CONCEPT = "docs/domains/02-loans/concept.md"
HEAD = '<a name="d-loans-concept"></a>\n\n# ドメイン `loans` の概念\n\n'
LOAN_DEFINITION = '[モデル「貸出」]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'


class LinksTestCase(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def found(self, text: str | None = None, path: str = CONCEPT) -> list[Problem]:
        if text is not None:
            self.write(path, text)
        project, yaml_problems = load_project(self.project)
        self.assertEqual(yaml_problems, [])
        index, document_problems = load_documents(self.project, project)
        return [p for p in document_problems + check_links(index) if p.path == path]

    def problems(self, text: str | None = None, path: str = CONCEPT) -> list[tuple[int | None, str]]:
        return [(p.line, p.message) for p in self.found(text, path)]

    def assertPasses(self, text: str, path: str = CONCEPT) -> None:
        self.assertEqual(self.problems(text, path), [])

    def assertReports(self, text: str, fragment: str, line: int | None = None, path: str = CONCEPT) -> None:
        found = self.problems(text, path)
        matched = [p for p in found if fragment in p[1]]
        self.assertTrue(matched, f"{fragment!r} を含む問題が無い: {found}")
        if line is not None:
            self.assertEqual(matched[0][0], line, found)


class SampleTest(LinksTestCase):
    def test_sample_handwritten_files_pass(self):
        for path in (CONCEPT, "docs/domains/02-loans/design.md", "docs/domains/02-loans/design/overdue_notice.md"):
            with self.subTest(path=path):
                self.assertEqual(self.problems(path=path), [])


class FileAnchorTest(LinksTestCase):
    def test_missing_file_anchor(self):
        self.assertReports("# 概念\n", '先頭の行に、ファイルの ID のアンカー <a name="d-loans-concept"></a> が無い', 1)

    def test_wrong_file_anchor(self):
        self.assertReports('<a name="d-loans-design"></a>\n\n# 概念\n', "ファイルの ID d-loans-concept と違う", 1)

    def test_file_anchor_needs_level_one_heading(self):
        self.assertReports('<a name="d-loans-concept"></a>\n\n本文\n', "「#」の見出しが無い", 1)
        self.assertReports('<a name="d-loans-concept"></a>\n## 概念\n', "「#」の見出しが無い", 1)

    def test_blank_lines_before_anchor_and_between_anchor_and_heading_are_accepted(self):
        self.assertPasses('\n<a name="d-loans-concept"></a>\n# 概念\n')
        self.assertPasses('<a name="d-loans-concept"></a>\n\n\n# 概念\n')

    def test_child_file_anchor(self):
        path = "docs/domains/02-loans/design/overdue_notice.md"
        self.assertReports('<a name="d-loans-design-overdue_notice"></a>\n\n# 延滞\n', "ファイルの ID d-loans-design-f-overdue_notice と違う", 1, path)


class SectionAnchorTest(LinksTestCase):
    def test_section_anchor_form(self):
        for name in ("d-loans-concept-due", "d-loans-design-h-due", "d-loans-concept-h-due-h-x", "d-loans-concept-h-Due", "x"):
            with self.subTest(name=name):
                self.assertReports(f'{HEAD}<a name="{name}"></a>\n\n## 期限\n', "d-loans-concept-h-<名前> の形にする", 5)

    def test_section_anchor_needs_heading(self):
        self.assertReports(f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n本文\n', "「##」から「######」の見出しが無い", 5)
        self.assertReports(f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n# 期限\n', "「##」から「######」の見出しが無い", 5)
        self.assertReports(f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n期限\n---\n', "「##」から「######」の見出しが無い", 5)

    def test_section_anchor_with_heading_passes(self):
        self.assertPasses(f'{HEAD}<a name="d-loans-concept-h-due"></a>\n## 期限\n\n<a name="d-loans-concept-h-x"></a>\n\n###### 小さな節\n')

    def test_link_in_anchored_heading(self):
        self.assertReports(
            f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n## [モデル「貸出」]の期限\n\n{LOAN_DEFINITION}',
            "アンカーを付けた見出しにリンクを書かない",
            7,
        )

    def test_link_in_heading_without_anchor_passes(self):
        self.assertPasses(f"{HEAD}## [モデル「貸出」]の期限\n\n{LOAN_DEFINITION}")

    def test_duplicate_anchor(self):
        text = f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n## 期限\n\n<a name="d-loans-concept-h-due"></a>\n\n## 期限 2\n'
        found = self.problems(text)
        self.assertEqual([p[0] for p in found if "同じ ID d-loans-concept-h-due" in p[1]], [5, 9])

    def test_anchor_duplicating_generated_anchor(self):
        self.assertReports(
            f'{HEAD}<a name="d-loans-m-loan"></a>\n\n## 貸出\n', "同じ ID d-loans-m-loan のアンカーが docs/domains/02-loans/models.md:"
        )


class LinkFormTest(LinksTestCase):
    def test_inline_link(self):
        self.assertReports(f"{HEAD}[貸出](models.md#d-loans-m-loan)\n", "[文](URL) の形でリンクを書かない", 5)

    def test_autolink_and_bare_url(self):
        self.assertReports(f"{HEAD}<https://example.com>\n", "<https://example.com> の形でリンクを書かない", 5)
        self.assertReports(f"{HEAD}詳しくは https://example.com を見る\n", "文中に URL https://example.com をそのまま書かない", 5)

    def test_url_in_inline_code_passes(self):
        self.assertPasses(f"{HEAD}`https://example.com` と書く\n")

    def test_external_url_by_reference_passes_without_title(self):
        self.assertPasses(f"{HEAD}[CommonMark の仕様][commonmark] を見る\n\n[commonmark]: https://spec.commonmark.org/\n")

    def test_collapsed_reference(self):
        self.assertReports(f"{HEAD}[モデル「貸出」][]\n\n{LOAN_DEFINITION}", "[モデル「貸出」][] の形で書かない", 5)

    def test_brackets_in_code_and_mermaid_are_not_labels(self):
        self.assertPasses(
            f"{HEAD}`[a, b]` と ``[c]`` と \\[d]\n\n```mermaid\nflowchart LR\n  A[貸出] --> B[返却]\n```\n\n"
            "```python\nx = [1, 2]\n```\n\n    [字下げしたコード]\n\n<!-- [コメント] -->\n\n- [ ] タスク\n\n> [!NOTE]\n> 注記\n\n![図](a.png)\n"
        )

    def test_images_are_not_checked(self):
        self.assertPasses(f"{HEAD}![図](images/loan.png)\n")

    def test_reference_style_image_definitions_are_not_checked(self):
        self.assertPasses(f"{HEAD}図は ![貸出の流れ][flow] のとおり。\n\n[flow]: images/flow.png\n")

    def test_image_inside_link_text_is_not_checked(self):
        self.assertPasses(
            f"{HEAD}[![CI][ci-badge]][ci]\n\n[ci]: https://example.com/ci\n[ci-badge]: https://example.com/badge.svg\n"
        )

    def test_label_used_by_link_and_image_is_checked_as_link(self):
        self.assertReports(
            f"{HEAD}[flow] と ![貸出の流れ][flow]\n\n[flow]: images/flow.png\n", "ID のアンカー (#<ID>) を指していない", 7
        )


class LabelTest(LinksTestCase):
    def test_undefined_label_with_candidates(self):
        self.assertReports(
            f"{HEAD}[貸出] を見る\n", "ラベル 貸出 の定義の行が無い。候補: d-loans-m-loan (ドメイン `loans` のモデル「貸出」)", 5
        )

    def test_undefined_label_without_candidates(self):
        self.assertReports(f"{HEAD}配列 [a, b] を返す\n", "ラベル a, b の定義の行が無い。参照先の候補は無い", 5)

    def test_unused_definition(self):
        self.assertReports(f"{HEAD}本文\n\n{LOAN_DEFINITION}", "ラベル モデル「貸出」 の定義の行が、本文で使われていない", 7)

    def test_label_matching_ignores_case_and_spaces(self):
        self.assertPasses(
            f"{HEAD}[ドメイン  `loans`\nのモデル「貸出」] と [D-Loans-M-Loan]\n\n"
            '[d-loans-m-loan]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
            '[ドメイン `loans` のモデル「貸出」]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
        )

    def test_full_reference(self):
        self.assertPasses(
            f"{HEAD}[モデル「貸出」][d-loans-m-loan] と [借りたもの][d-loans-m-loan]\n\n"
            '[d-loans-m-loan]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
        )

    def test_duplicate_label(self):
        self.assertReports(
            f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}{LOAN_DEFINITION}", "ラベル モデル「貸出」 の定義の行は、7 行目にもある", 8
        )


class DefinitionPlaceTest(LinksTestCase):
    def test_definition_in_middle(self):
        self.assertReports(f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n後の段落\n", "ファイルの末尾のまとまりに書く", 7)

    def test_definition_in_paragraph(self):
        found = self.problems(f"{HEAD}[モデル「貸出」]\n{LOAN_DEFINITION}[開館日]: x.md#y \"z\"\n")
        self.assertEqual([p[0] for p in found if "定義の行として読まれない" in p[1]], [6])

    def test_blank_lines_between_definitions_pass(self):
        self.assertPasses(
            f"{HEAD}[モデル「貸出」] と [未分類の用語「開館日」][開館日]\n\n{LOAN_DEFINITION}\n"
            '[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"\n'
        )


class DefinitionTargetTest(LinksTestCase):
    def test_href_without_fragment(self):
        self.assertReports(f'{HEAD}[貸出]\n\n[貸出]: models.md "t"\n', "ID のアンカー (#<ID>) を指していない", 7)

    def test_href_with_invalid_id(self):
        self.assertReports(f'{HEAD}[貸出]\n\n[貸出]: models.md#loan "t"\n', "href の ID の形が違う", 7)

    def test_href_to_missing_anchor(self):
        self.assertReports(f'{HEAD}[貸出]\n\n[貸出]: models.md#d-loans-m-rental "t"\n', "参照先 d-loans-m-rental のアンカーが無い", 7)

    def test_href_to_wrong_file(self):
        self.assertReports(
            f'{HEAD}[貸出]\n\n[貸出]: terms.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n',
            "正しい href は models.md#d-loans-m-loan",
            7,
        )

    def test_missing_and_stale_title(self):
        self.assertReports(f"{HEAD}[貸出]\n\n[貸出]: models.md#d-loans-m-loan\n", "title が無い", 7)
        self.assertReports(
            f'{HEAD}[貸出]\n\n[貸出]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「借用」"\n',
            "title が、参照先の完全な名前「ドメイン `loans` のモデル「貸出」」と違う",
            7,
        )

    def test_title_quotes(self):
        for line in (
            "[貸出]: models.md#d-loans-m-loan 'ドメイン `loans` のモデル「貸出」'",
            "[貸出]: <models.md#d-loans-m-loan> (ドメイン `loans` のモデル「貸出」)",
        ):
            with self.subTest(line=line):
                self.assertPasses(f"{HEAD}[モデル「貸出」][貸出]\n\n{line}\n")

    def test_section_title_follows_heading(self):
        text = (
            f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n## 返却の "期限"\n\n[節「返却の "期限"」][期限]\n\n'
            '[期限]: #d-loans-concept-h-due "ドメイン `loans` のファイル `concept.md` の節「返却の \\"期限\\"」"\n'
        )
        self.assertPasses(text)
        self.assertReports(text.replace('## 返却の "期限"', "## 返却期限"), "title が、参照先の完全な名前「ドメイン `loans` のファイル `concept.md` の節「返却期限」」と違う")

    def test_link_to_section_in_other_file(self):
        self.assertPasses(
            f"{HEAD}[節「通知する日」]\n\n"
            '[節「通知する日」]: design/overdue_notice.md#d-loans-design-f-overdue_notice-h-timing '
            '"ドメイン `loans` のファイル `design/overdue_notice.md` の節「通知する日」"\n'
        )


class FirstUseTest(LinksTestCase):
    """初出: 各参照先を最初に指す箇所の表示の文が、書ける形のどれかと同じ。"""

    BUSINESS_DAY = (
        '[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"\n'
    )

    def first_use_problems(self, text: str) -> list[Problem]:
        return [p for p in self.found(text) if "を最初に指す箇所" in p.message]

    def test_message_lists_writable_forms(self):
        found = self.first_use_problems(f"{HEAD}休みの日は[開館日]で数えない。\n\n{self.BUSINESS_DAY}")
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].line, found[0].column), (5, 6))
        self.assertEqual(
            found[0].format(),
            "docs/domains/02-loans/concept.md:5:6: 検査 b: 参照先 d-loans-ut-business_day を最初に指す箇所の表示の文「開館日」が、"
            "書ける形のどれとも違う。書ける形:\n"
            "  未分類の用語「開館日」\n"
            "  未分類のアプリケーション用語「開館日」\n"
            "  ドメイン `loans` の未分類の用語「開館日」\n"
            "  ドメイン `loans` の未分類のアプリケーション用語「開館日」",
        )

    def test_writable_forms_pass(self):
        for display in (
            "未分類の用語「開館日」",
            "未分類のアプリケーション用語「開館日」",
            "ドメイン `loans` の未分類の用語「開館日」",
            "ドメイン `loans` の未分類のアプリケーション用語「開館日」",
            "ドメイン `loans`\nの未分類の用語「開館日」",  # 改行と連続する空白は、空白 1 つとして比べる
            "ドメイン  `loans`  の未分類の用語「開館日」",
        ):
            with self.subTest(display=display):
                self.assertPasses(f"{HEAD}[{display}][開館日]\n\n{self.BUSINESS_DAY}")

    def test_other_forms_fail(self):
        for display in (
            "開館日",
            "ドメイン `loans`の未分類の用語「開館日」",  # コードの書式の後の空白が無い
            "ドメイン `Loans` の未分類の用語「開館日」",  # 英字の大文字と小文字が違う
            "用語「開館日」",
        ):
            with self.subTest(display=display):
                self.assertEqual(len(self.first_use_problems(f"{HEAD}[{display}][開館日]\n\n{self.BUSINESS_DAY}")), 1)

    def test_omitting_a_middle_parent_fails(self):
        text = (
            f"{HEAD}[ドメイン `loans` の属性「貸出状態」][貸出状態]\n\n"
            '[貸出状態]: models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"\n'
        )
        found = self.first_use_problems(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0].detail.splitlines(),
            [
                "  属性「貸出状態」",
                "  モデル「貸出」の属性「貸出状態」",
                "  ドメイン `loans` のモデル「貸出」の属性「貸出状態」",
            ],
        )

    def test_shortcut_label_that_is_a_writable_form_passes(self):
        self.assertPasses(f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}")

    def test_only_the_first_use_of_each_target_is_checked(self):
        # 2 つのラベルが同じ参照先を指すとき、参照先を最初に指す箇所だけを検査する
        text = (
            f"{HEAD}[モデル「貸出」]は 1 回の記録。[貸出]と[d-loans-m-loan]は検査しない。\n\n{LOAN_DEFINITION}"
            '[貸出]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
            '[d-loans-m-loan]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
        )
        self.assertPasses(text)
        found = self.first_use_problems(text.replace("[モデル「貸出」]は", "[貸出]は", 1).replace("。[貸出]と", "。[モデル「貸出」]と", 1))
        self.assertEqual([(p.line, p.column) for p in found], [(5, 1)])

    def test_files_sections_and_domains_are_checked(self):
        cases = [
            ("[`design/overdue_notice.md`]", "ファイル `design/overdue_notice.md`",
             '[`design/overdue_notice.md`]: design/overdue_notice.md#d-loans-design-f-overdue_notice '
             '"ドメイン `loans` のファイル `design/overdue_notice.md`"\n'),
            ("[通知する日]", "ファイル `design/overdue_notice.md` の節「通知する日」",
             '[通知する日]: design/overdue_notice.md#d-loans-design-f-overdue_notice-h-timing '
             '"ドメイン `loans` のファイル `design/overdue_notice.md` の節「通知する日」"\n'),
            ("[d-loans]", "ドメイン `loans`", '[d-loans]: README.md#d-loans "ドメイン `loans`"\n'),
        ]
        for link, writable, definition in cases:
            with self.subTest(link=link):
                found = self.first_use_problems(f"{HEAD}{link}\n\n{definition}")
                self.assertEqual(len(found), 1, found)
                self.assertIn(f"  {writable}", found[0].detail.splitlines())
                label = link[1:-1]
                self.assertPasses(f"{HEAD}[{writable}][{label}]\n\n{definition}")

    def test_labels_without_a_target_are_not_counted(self):
        # 外部の URL・定義の行の無いラベル・href の誤り・[ラベル][] は、初出として数えない
        self.assertPasses(f"{HEAD}[CommonMark の仕様][commonmark]\n\n[commonmark]: https://spec.commonmark.org/\n")
        for text in (
            f"{HEAD}[貸出]\n",
            f'{HEAD}[貸出]\n\n[貸出]: models.md#d-loans-m-rental "t"\n',
            f"{HEAD}[モデル「貸出」][]\n\n{LOAN_DEFINITION}",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.first_use_problems(text), [])
        # 参照先を求められないラベルの後の、参照先を求められるリンクが最初の箇所になる
        found = self.first_use_problems(f"{HEAD}[モデル「貸出」][] と [貸出]\n\n" + LOAN_DEFINITION.replace("[モデル「貸出」]", "[貸出]"))
        self.assertEqual([(p.line, p.column) for p in found], [(5, 15)])


class UnacceptedFileTest(LinksTestCase):
    def test_unaccepted_file_is_reported_as_check_b(self):
        self.assertReports("# メモ\n", "concept.md・problem.md・design.md だけ", path="docs/domains/02-loans/notes.md")
