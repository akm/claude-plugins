"""生成したファイルの先頭の記述 (モジュール generated_header) のテスト。"""

import tempfile
import unittest
from pathlib import Path

from doc_structured import generated_header as gh

SOURCE = "docs/domains/01-loans/"
COMMAND = "bin/doc-structured generate"


class HeaderTest(unittest.TestCase):
    def test_markdown_line(self):
        self.assertEqual(
            gh.markdown_line(SOURCE),
            "<!-- doc-structured:generated 生成元: docs/domains/01-loans/ コマンド: bin/doc-structured generate "
            "(このファイルを直接編集せず、生成元を直して生成し直す) -->",
        )

    def test_read_from_each_file_kind(self):
        expected = gh.Header(SOURCE, COMMAND)
        cases = {
            "frontmatter の無い Markdown": gh.markdown_line(SOURCE) + "\n# 見出し\n",
            "frontmatter のある Markdown": "---\n" + gh.hash_line(SOURCE) + "\npaths: docs/**\n---\n本文\n",
            "YAML": gh.hash_line(SOURCE) + "\nkey: value\n",
            "シェルスクリプト": "#!/usr/bin/env bash\n" + gh.hash_line(SOURCE) + "\nset -eu\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assertEqual(gh.read_header(text), expected)

    def test_hand_written_files_are_not_generated(self):
        for text in (
            "# 見出し\n本文\n",
            "",
            "<!-- 生成元: docs/ -->\n",
            # 4 行目より後にある記述は判定の対象外
            "a\nb\nc\n" + gh.markdown_line(SOURCE) + "\n",
            # 決まった文字列の後に空白が無いものは別の文字列
            "<!-- doc-structured:generatedX -->\n",
        ):
            with self.subTest(text=text):
                self.assertIsNone(gh.read_header(text))

    def test_marker_without_fields_is_still_generated(self):
        self.assertEqual(gh.read_header("<!-- doc-structured:generated 壊れた行 -->\n"), gh.Header("", ""))

    def test_read_file_header_reads_first_lines_of_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / "models.md"
            generated.write_text(gh.markdown_line(SOURCE) + "\n\n# モデル\n", encoding="utf-8")
            self.assertEqual(gh.read_file_header(generated), gh.Header(SOURCE, COMMAND))
            # 文字列のパスも受け付ける
            self.assertEqual(gh.read_file_header(str(generated)), gh.Header(SOURCE, COMMAND))
            # 先頭の 3 行より後にある記述は判定に使わない
            late = Path(tmp) / "notes.md"
            late.write_text("# メモ\n\n説明\n" + gh.markdown_line(SOURCE) + "\n", encoding="utf-8")
            self.assertIsNone(gh.read_file_header(late))
            # UTF-8 として読めないバイトがあっても、置き換えて判定する
            broken = Path(tmp) / "broken.md"
            broken.write_bytes(gh.markdown_line(SOURCE).encode("utf-8") + b"\n\xff\xfe\n")
            self.assertEqual(gh.read_file_header(broken), gh.Header(SOURCE, COMMAND))

    def test_both_functions_judge_the_same(self):
        # 1 行目が長くても、行の区切りの種類に関わらず、2 つの関数は同じく判定する
        line = gh.hash_line(SOURCE).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            for long_line in (b"a" * 10, b"a" * 10000):
                for separator in (b"\n", b"\r", "\u2028".encode("utf-8")):
                    with self.subTest(length=len(long_line), separator=separator):
                        path.write_bytes(long_line + separator + line + b"\n")
                        self.assertEqual(gh.read_file_header(path), gh.Header(SOURCE, COMMAND))
                        self.assertEqual(gh.read_file(path).header, gh.Header(SOURCE, COMMAND))

    def test_read_file_header_raises_when_file_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                gh.read_file_header(Path(tmp) / "missing.md")

    def test_bom_and_invalid_bytes_are_read_the_same_way_everywhere(self):
        line = gh.markdown_line(SOURCE).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain.md"
            plain.write_bytes(line + b"\n# x\n")
            bom = Path(tmp) / "bom.md"
            bom.write_bytes(b"\xef\xbb\xbf" + line + b"\n# x\n")
            broken = Path(tmp) / "broken.md"
            broken.write_bytes(line + b"\n# x\xff\n")
            bom_only = Path(tmp) / "bom-only.md"
            bom_only.write_bytes(b"\xef\xbb\xbf\n")
            # 先頭の BOM と読めないバイトは、先頭の記述の判定に影響しない (先頭だけ読む関数も、全体を読む関数も同じ)
            for path in (plain, bom, broken):
                with self.subTest(file=path.name):
                    self.assertEqual(gh.read_file_header(path), gh.Header(SOURCE, COMMAND))
                    self.assertEqual(gh.read_file(path).header, gh.Header(SOURCE, COMMAND))
            # 読んだまま正確かは、BOM の除去とバイトの置き換えがあったかで決まる
            self.assertTrue(gh.read_file(plain).exact)
            self.assertFalse(gh.read_file(bom).exact)
            self.assertFalse(gh.read_file(broken).exact)
            self.assertEqual(gh.read_file(bom).text, gh.read_file(plain).text)
            # BOM だけのファイルは空白だけのファイルとして扱う。BOM が 2 つ以上並んでいても同じ
            double_bom = Path(tmp) / "double-bom.md"
            double_bom.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbf\n")
            for path in (bom_only, double_bom):
                with self.subTest(file=path.name):
                    self.assertTrue(gh.read_file(path).is_blank)
                    self.assertIsNone(gh.read_file(path).header)

    def test_line_endings_are_read_as_lf(self):
        # 改行の CRLF と CR は LF として読み、生成し直した内容と比べるときの違いに数えない
        text = gh.markdown_line(SOURCE) + "\n# x\n"
        with tempfile.TemporaryDirectory() as tmp:
            for name, newline in (("crlf.md", b"\r\n"), ("cr.md", b"\r")):
                with self.subTest(file=name):
                    path = Path(tmp) / name
                    path.write_bytes(text.encode("utf-8").replace(b"\n", newline))
                    content = gh.read_file(path)
                    self.assertEqual(content.text, text)
                    self.assertTrue(content.matches(text))
                    self.assertEqual(gh.read_file_header(path), gh.Header(SOURCE, COMMAND))
            # BOM があれば、内容が同じでも生成し直した内容と同じとはしない
            bom = Path(tmp) / "bom.md"
            bom.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
            self.assertFalse(gh.read_file(bom).matches(text))


if __name__ == "__main__":
    unittest.main()
