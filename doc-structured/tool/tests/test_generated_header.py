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

    def test_read_file_header_raises_when_file_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                gh.read_file_header(Path(tmp) / "missing.md")


if __name__ == "__main__":
    unittest.main()
