"""手書きの Markdown の読み取り (モジュール markdown) のテスト。"""

import unittest

from doc_structured import markdown


def labels(document: markdown.Document) -> list[tuple[str, str, int, int]]:
    return [(r.form, r.label, r.line, r.column) for r in document.references]


class ReferenceTest(unittest.TestCase):
    def test_shortcut_full_and_collapsed(self):
        doc = markdown.parse("貸出は [モデル「貸出」] と [返却][d-loans-m-loan] と [開館日][] を使う。\n")
        self.assertEqual(
            labels(doc),
            [
                ("shortcut", "モデル「貸出」", 1, 5),
                ("full", "d-loans-m-loan", 1, 17),
                ("collapsed", "開館日", 1, 40),
            ],
        )
        self.assertEqual(doc.references[1].text, "返却")
        self.assertEqual((doc.references[1].label_line, doc.references[1].label_column), (1, 21))

    def test_label_spanning_lines(self):
        doc = markdown.parse("前の文 [ドメイン `loans` の\nモデル「貸出」] の後\n")
        self.assertEqual(labels(doc), [("shortcut", "ドメイン `loans` の\nモデル「貸出」", 1, 5)])

    def test_inline_code_hides_brackets(self):
        doc = markdown.parse("`[a]` と ``[b] ` c`` と [`concept.md`]\n")
        self.assertEqual(labels(doc), [("shortcut", "`concept.md`", 1, 23)])

    def test_bracket_inside_inline_code_in_label(self):
        doc = markdown.parse("[`]`][x]\n")
        self.assertEqual(labels(doc), [("full", "x", 1, 1)])

    def test_escaped_bracket_is_not_a_label(self):
        doc = markdown.parse("配列 \\[a, b] と [a, b]\n")
        self.assertEqual(labels(doc), [("shortcut", "a, b", 1, 14)])

    def test_task_list_alert_and_footnote_are_not_labels(self):
        doc = markdown.parse(
            "- [ ] 未完了 [a]\n- [x] 完了\n\n> [!NOTE]\n> 注記 [b]\n\n脚注[^1]\n\n[^1]: 脚注の文\n"
        )
        self.assertEqual([r.label for r in doc.references], ["a", "b"])
        self.assertEqual(doc.definitions, [])

    def test_code_blocks_html_blocks_and_comments_are_not_read(self):
        doc = markdown.parse(
            "```mermaid\nA[a] --> B[b]\n```\n\n    [c]\n\n<!-- [d]\n[e] -->\n\n"
            "<details>\n[f]\n</details>\n\n本文 <!-- [g] --> [h] <span title=\"[i]\">x</span>\n"
        )
        self.assertEqual([r.label for r in doc.references], ["h"])

    def test_images_are_skipped(self):
        doc = markdown.parse("![図](images/a.png) と ![図][fig] と [a]\n")
        self.assertEqual([r.label for r in doc.references], ["a"])
        self.assertEqual(doc.inline_links, [])

    def test_image_labels_inside_link_text_are_kept(self):
        doc = markdown.parse("[![CI][ci-badge]][ci] と [![図][fig]](https://example.com) と [`![x][y]`][z]\n")
        self.assertEqual(doc.image_labels, ["ci-badge", "fig"])
        self.assertEqual([(r.form, r.label) for r in doc.references], [("full", "ci"), ("full", "z")])

    def test_html_and_autolink_inside_link_text_are_not_read_as_images(self):
        for text in ('[<!-- ![a][b] -->x][c]', '[<span title="![a][b]">x</span>][c]', "[x <https://e.com/![a][b]>][c]"):
            with self.subTest(text=text):
                self.assertEqual(markdown.parse(text + "\n").image_labels, [])

    def test_reference_style_image_labels_are_kept(self):
        doc = markdown.parse("![図](a.png) と ![流れ][flow] と ![表][] と ![配置図] と [a]\n")
        self.assertEqual(doc.image_labels, ["flow", "表", "配置図"])
        self.assertEqual([r.label for r in doc.references], ["a"])

    def test_empty_brackets_are_not_labels(self):
        self.assertEqual(markdown.parse("空の [] と [ ]\n").references, [])

    def test_labels_in_list_quote_table_and_heading(self):
        doc = markdown.parse("# 見出し [a]\n\n- 項目 [b]\n\n> 引用 [c]\n\n| 列 |\n|---|\n| [d] |\n")
        self.assertEqual([(r.label, r.line) for r in doc.references], [("a", 1), ("b", 3), ("c", 5), ("d", 9)])


class LinkAndUrlTest(unittest.TestCase):
    def test_inline_link(self):
        doc = markdown.parse("[概念](concept.md#d-loans-concept \"t\") の後 [a]\n")
        self.assertEqual(doc.inline_links, [markdown.InlineLink("概念", "concept.md#d-loans-concept", 1, 1)])
        self.assertEqual([r.label for r in doc.references], ["a"])

    def test_unclosed_paren_is_a_shortcut(self):
        doc = markdown.parse("[a](b\n")
        self.assertEqual(doc.inline_links, [])
        self.assertEqual([r.label for r in doc.references], ["a"])

    def test_autolink_and_bare_url(self):
        doc = markdown.parse("<https://example.com/a> と https://example.com/b。と (https://example.com/c) と `https://example.com/d`\n")
        self.assertEqual(
            [(u.form, u.url, u.column) for u in doc.urls],
            [("autolink", "https://example.com/a", 1), ("bare", "https://example.com/b", 27), ("bare", "https://example.com/c", 52)],
        )

    def test_bare_url_stops_before_angle_bracket(self):
        doc = markdown.parse("see https://example.com<br> ok\n")
        self.assertEqual([(u.form, u.url) for u in doc.urls], [("bare", "https://example.com")])

    def test_url_in_inline_link_is_not_reported_twice(self):
        doc = markdown.parse("[a](https://example.com)\n")
        self.assertEqual(doc.urls, [])
        self.assertEqual(len(doc.inline_links), 1)

    def test_html_tag_attributes_are_not_urls(self):
        doc = markdown.parse('本文 <a href="https://example.com">x</a>\n')
        self.assertEqual(doc.urls, [])


class DefinitionTest(unittest.TestCase):
    def test_definitions_with_each_quote(self):
        doc = markdown.parse(
            "本文 [a]\n\n"
            '[a]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'
            "[b]: #x 'it\\'s'\n"
            "[c]: <a b.md> (括弧)\n"
            "[d]: https://example.com\n"
        )
        got = [(d.label, d.destination, d.title, d.quote, d.line) for d in doc.definitions]
        self.assertEqual(
            got,
            [
                ("a", "models.md#d-loans-m-loan", "ドメイン `loans` のモデル「貸出」", '"', 3),
                ("b", "#x", "it\\'s", "'", 4),
                ("c", "<a b.md>", "括弧", "(", 5),
                ("d", "https://example.com", None, None, 6),
            ],
        )
        self.assertEqual(doc.definitions[1].title_text, "it's")
        self.assertEqual(doc.body_end, 1)
        self.assertFalse(any(d.in_paragraph for d in doc.definitions))
        # 定義の行の URL は、文中の URL として報告しない
        self.assertEqual(doc.urls, [])

    def test_definition_right_after_paragraph_is_flagged(self):
        doc = markdown.parse("本文 [a]\n[a]: #x \"t\"\n")
        self.assertEqual(len(doc.definitions), 1)
        self.assertTrue(doc.definitions[0].in_paragraph)
        self.assertEqual([r.label for r in doc.references], ["a"])

    def test_definition_in_middle_and_body_end(self):
        doc = markdown.parse("本文\n\n[a]: #x \"t\"\n\n続き\n\n[b]: #y \"u\"\n\n")
        self.assertEqual([d.line for d in doc.definitions], [3, 7])
        self.assertEqual(doc.body_end, 5)

    def test_body_end_without_definitions(self):
        doc = markdown.parse("本文\n\n続き\n")
        self.assertEqual(doc.body_end, 3)

    def test_definition_in_code_block_is_ignored(self):
        doc = markdown.parse("```\n[a]: #x\n```\n")
        self.assertEqual(doc.definitions, [])


class AnchorAndHeadingTest(unittest.TestCase):
    def test_anchors_and_headings(self):
        doc = markdown.parse(
            '<a name="d-loans-concept"></a>\n\n# 貸出の概念\n\n<a name="d-loans-concept-h-due"></a>\n'
            "## 返却期限 `due` ##\n\n下線の見出し\n---\n"
        )
        self.assertEqual(
            doc.anchors,
            [markdown.Anchor("d-loans-concept", 1, 1), markdown.Anchor("d-loans-concept-h-due", 5, 1)],
        )
        self.assertEqual(
            doc.headings,
            [
                markdown.Heading(1, "貸出の概念", 3, True),
                markdown.Heading(2, "返却期限 `due`", 6, True),
                markdown.Heading(2, "下線の見出し", 8, False),
            ],
        )
        self.assertEqual(doc.first_nonblank(), 1)
        self.assertEqual(doc.next_nonblank(1), 3)

    def test_anchor_in_code_block_is_ignored(self):
        doc = markdown.parse('```\n<a name="x"></a>\n```\n')
        self.assertEqual(doc.anchors, [])

    def test_heading_text(self):
        self.assertEqual(markdown.heading_text("## a # b ##"), "a # b")
        self.assertEqual(markdown.heading_text("# C#"), "C#")


class HelperTest(unittest.TestCase):
    def test_normalize_label(self):
        self.assertEqual(markdown.normalize_label("  Foo\n  BAR "), "foo bar")
        self.assertEqual(markdown.normalize_label("モデル「貸出」"), "モデル「貸出」")

    def test_escape_and_unescape_title(self):
        for quote in ('"', "'", "("):
            text = 'a "b" \'c\' (d) \\e'
            escaped = markdown.escape_title(text, quote)
            self.assertEqual(markdown.unescape(escaped), text, quote)

    def test_crlf(self):
        doc = markdown.parse("本文 [a]\r\n\r\n[a]: #x\r\n")
        self.assertEqual(doc.lines, ["本文 [a]", "", "[a]: #x"])
        self.assertEqual(len(doc.definitions), 1)


if __name__ == "__main__":
    unittest.main()
